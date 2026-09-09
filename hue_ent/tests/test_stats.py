"""What the panel reports: stream rates, and each bulb's signal.

Run from the repo root: ``python -m pytest hue_ent/tests``
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import main as main_mod
from hue_ent.app import registry as registry_mod
from hue_ent.app import web as web_mod
from hue_ent.tests.test_zone_runner import FakeBridge, FakeDdp, make_runner

DDP_HEADER = b"\x41\x00\x00\x00" + b"\x00" * 6      # 10 bytes, contents ignored


def ddp_frame(pixels) -> bytes:
    body = bytes(v for px in pixels for v in px)
    return DDP_HEADER + body


# --- the rate helper ------------------------------------------------------

def test_rate_needs_two_samples():
    assert main_mod._rate([]) == 0.0
    assert main_mod._rate([time.monotonic()]) == 0.0


def test_rate_is_frames_per_second_over_the_window():
    now = time.monotonic()
    stamps = [now - 1.0 + i * 0.04 for i in range(26)]     # 25 gaps in 1s
    assert main_mod._rate(stamps) == pytest.approx(25.0, abs=0.6)


def test_a_stale_window_reports_zero():
    old = time.monotonic() - 30
    assert main_mod._rate([old, old + 0.04]) == 0.0


# --- the DDP listener -----------------------------------------------------

def test_the_listener_counts_frames_and_reports_a_rate():
    seen = []
    proto = main_mod.DdpProtocol(2, lambda: seen.append(1))

    for _ in range(10):
        proto.datagram_received(ddp_frame([(1, 2, 3), (4, 5, 6)]), ("127.0.0.1", 4048))
        time.sleep(0.01)

    assert proto.frames_rx == 10
    assert len(seen) == 10
    assert proto.latest == [(1, 2, 3), (4, 5, 6)]
    assert proto.rx_fps > 0


def test_a_short_datagram_is_ignored_entirely():
    proto = main_mod.DdpProtocol(4, lambda: None)
    proto.datagram_received(DDP_HEADER + b"\x01\x02\x03", ("127.0.0.1", 4048))
    assert (proto.frames_rx, proto.latest, proto.rx_fps) == (0, None, 0.0)


# --- per-zone stats -------------------------------------------------------

def test_stats_say_nothing_has_arrived_yet():
    runner, _ = make_runner()
    stats = runner.stats

    assert stats["armed"] is False
    assert stats["frames_rx"] == 0
    assert stats["last_rx_age_s"] is None      # never, not "a long time ago"
    assert (stats["rx_fps"], stats["tx_fps"], stats["sends"]) == (0.0, 0.0, 0)


def test_stats_report_the_age_of_a_stream_that_stopped():
    runner, _ = make_runner()
    runner.ddp = FakeDdp(latest=[(1, 1, 1)], last_rx=time.monotonic() - 12)
    runner.ddp.frames_rx = 400

    stats = runner.stats
    assert stats["last_rx_age_s"] == pytest.approx(12, abs=1)
    assert stats["frames_rx"] == 400


@pytest.mark.asyncio
async def test_sending_frames_counts_them_and_reports_an_outgoing_rate():
    runner, bridge = make_runner(idle_timeout_s=5.0)
    runner.armed = True
    runner._armed_at = time.monotonic()
    ddp = FakeDdp(latest=[(255, 0, 0), (0, 0, 255)], last_rx=time.monotonic())
    runner.ddp = ddp

    ticker = asyncio.ensure_future(runner._run_ticker())
    for i in range(8):
        await asyncio.sleep(0.02)
        ddp.last_rx = time.monotonic()
        ddp.latest = [(i * 8 % 256, 0, 0), (0, 0, 255)]     # a changing frame
    ticker.cancel()
    await asyncio.gather(ticker, return_exceptions=True)

    stats = runner.stats
    assert stats["sends"] >= 3
    assert stats["tx_fps"] > 0
    assert stats["armed_for_s"] is not None
    assert stats["sends"] == len([1 for t, _ in bridge.published if t.endswith("/L1/set")])


# --- link quality and the proxy hint --------------------------------------

class ViewBridge(FakeBridge):
    """A bridge with room views, as web._state() expects."""

    def __init__(self, lights, states, armed=False):
        super().__init__()
        self.light_states = dict(states)
        self.options = {"auto_zones": True, "ledfx_url": "http://127.0.0.1:8888"}
        self.discovery = registry_mod.Discovery(
            rooms=[], ok=True, areas=2, lights=len(lights), matched=len(lights))
        self.devices_seen = type("E", (), {"is_set": lambda self: True})()
        self.zones = {}
        self.runners = {}
        self.room_views = [{
            "slug": "living_room", "source": "auto", "enabled": True,
            "available_lights": list(lights), "skipped": [],
            "config": {"name": "Living Room", "lights": list(lights), "ddp_port": 4048},
        }]


def test_state_reports_each_bulbs_link_quality():
    bridge = ViewBridge(["L1", "L2"],
                        {"L1": {"linkquality": 84}, "L2": {"linkquality": 41}})

    room = web_mod._state(bridge)["rooms"][0]

    assert room["link_quality"] == {"L1": 84, "L2": 41}
    assert room["strongest_light"] == "L1"


def test_bulbs_with_no_report_are_simply_absent():
    bridge = ViewBridge(["L1", "L2"], {"L1": {"state": "ON"}})

    room = web_mod._state(bridge)["rooms"][0]

    assert room["link_quality"] == {}
    assert room["strongest_light"] is None


def test_a_nonsense_link_quality_is_ignored():
    bridge = ViewBridge(["L1", "L2"],
                        {"L1": {"linkquality": None}, "L2": {"linkquality": "good"}})
    assert web_mod._state(bridge)["rooms"][0]["link_quality"] == {}


def test_state_carries_no_stats_for_a_zone_that_is_not_running():
    bridge = ViewBridge(["L1"], {})
    assert web_mod._state(bridge)["rooms"][0]["stats"] is None


def test_state_carries_the_runners_stats_when_it_is_running():
    bridge = ViewBridge(["L1", "L2"], {"L1": {"linkquality": 70}})
    runner, _ = make_runner()
    runner.ddp = FakeDdp(latest=[(1, 1, 1)], last_rx=time.monotonic())
    runner.ddp.frames_rx = 12
    bridge.runners["living_room"] = runner

    room = web_mod._state(bridge)["rooms"][0]

    assert room["stats"]["frames_rx"] == 12
    assert room["stats"]["armed"] is False
