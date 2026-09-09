"""The streaming ticker: when a zone gives up, and what it sends while it doesn't.

Run from the repo root: ``python -m pytest hue_ent/tests``

The regression here: idleness used to be measured from the last DDP frame only,
so a zone armed with nothing streaming (the HA switch, the panel's test button,
a LedFX that never starts) never timed out - it sat armed forever with its
switch on and its pause entities, typically Adaptive Lighting, left off.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import main as main_mod


class FakeBridge:
    """Just enough Bridge for a runner: publishes, addresses, pause calls."""

    def __init__(self):
        self.published: list[tuple[str, str]] = []
        self.nwk = {"L1": 0x1234, "L2": 0x5678}
        self.light_states: dict[str, dict] = {}
        self.pause_calls: list[bool] = []
        self.stopping = False

    async def publish(self, topic: str, payload: str, retain: bool = False) -> None:
        self.published.append((topic, payload))

    async def set_pause_entities(self, zone, paused: bool) -> None:
        self.pause_calls.append(paused)

    def schedule_arm(self, slug: str, reason: str) -> None:  # pragma: no cover
        pass


def make_runner(idle_timeout_s: float = 0.15, lights=("L1", "L2")):
    zone = main_mod.Zone({
        "name": "Living Room",
        "lights": list(lights),
        "ddp_port": 4048,
        "fps": 25,
        "idle_timeout_s": idle_timeout_s,
        "pause_entities": ["switch.adaptive_lighting_living_room"],
    })
    bridge = FakeBridge()
    return main_mod.ZoneRunner(zone, bridge), bridge


class FakeDdp:
    """Stands in for the DDP listener: one latest frame and a receive stamp."""

    def __init__(self, latest=None, last_rx: float = 0.0, rx_fps: float = 0.0):
        self.latest = latest
        self.last_rx = last_rx
        self.frames_rx = 0 if latest is None else 1
        self.rx_fps = rx_fps


async def run_ticker(runner, bridge, timeout: float = 3.0) -> None:
    """Run the ticker to completion, failing loudly if it never gives up.

    The ticker fires disarm() as a task, and disarming deliberately paces its
    Zigbee writes, so wait for the restore to land rather than a fixed sleep.
    """
    await asyncio.wait_for(runner._run_ticker(), timeout=timeout)
    deadline = time.monotonic() + timeout
    while not bridge.pause_calls and time.monotonic() < deadline:
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_a_zone_armed_with_no_stream_gives_up_and_restores():
    """The bug: this used to spin forever, holding Adaptive Lighting off."""
    runner, bridge = make_runner(idle_timeout_s=0.15)
    runner.armed = True
    runner._armed_at = time.monotonic()
    runner.ddp = None                      # nothing ever bound / nothing streaming

    await run_ticker(runner, bridge)

    assert not runner.armed
    assert bridge.pause_calls == [False]   # pause entities turned back on
    assert (runner.zone.switch_state_topic, "OFF") in bridge.published


@pytest.mark.asyncio
async def test_a_listener_that_never_received_a_frame_also_times_out():
    runner, bridge = make_runner(idle_timeout_s=0.15)
    runner.armed = True
    runner._armed_at = time.monotonic()
    runner.ddp = FakeDdp(latest=None, last_rx=0.0)

    await run_ticker(runner, bridge)

    assert not runner.armed


@pytest.mark.asyncio
async def test_a_stream_that_stops_times_out_from_its_last_frame():
    runner, bridge = make_runner(idle_timeout_s=0.15)
    runner.armed = True
    runner._armed_at = time.monotonic() - 60      # armed long ago, but streaming
    runner.ddp = FakeDdp(latest=[(255, 0, 0), (0, 255, 0)], last_rx=time.monotonic())

    await run_ticker(runner, bridge)

    assert not runner.armed
    # It streamed before giving up: a frame went to the proxy bulb.
    frame_topics = [t for t, _ in bridge.published if t.endswith("/L1/set")]
    assert frame_topics, "expected at least one streamed frame to the proxy"


@pytest.mark.asyncio
async def test_a_live_stream_keeps_streaming_and_does_not_disarm():
    runner, bridge = make_runner(idle_timeout_s=5.0)
    runner.armed = True
    runner._armed_at = time.monotonic()
    ddp = FakeDdp(latest=[(255, 0, 0), (0, 0, 255)], last_rx=time.monotonic())
    runner.ddp = ddp

    ticker = asyncio.ensure_future(runner._run_ticker())
    for _ in range(6):                            # keep the stream "live"
        await asyncio.sleep(0.02)
        ddp.last_rx = time.monotonic()
        ddp.latest = [(ddp.frames_rx % 256, 0, 0), (0, 0, 255)]
        ddp.frames_rx += 1
    ticker.cancel()
    await asyncio.gather(ticker, return_exceptions=True)

    assert runner.armed                           # never gave up on a live stream
    payloads = [json.loads(p) for t, p in bridge.published if t.endswith("/L1/set")]
    assert payloads, "expected streamed frames"
    assert all("zclcommand" in p for p in payloads)


@pytest.mark.asyncio
async def test_an_unchanged_frame_is_resent_only_as_a_keepalive():
    """Bulbs fall out of entertainment mode after a few silent seconds, so a
    static frame still has to be re-sent - but not at full frame rate."""
    runner, bridge = make_runner(idle_timeout_s=5.0)
    runner.armed = True
    runner._armed_at = time.monotonic()
    ddp = FakeDdp(latest=[(10, 20, 30), (40, 50, 60)], last_rx=time.monotonic())
    runner.ddp = ddp

    ticker = asyncio.ensure_future(runner._run_ticker())
    for _ in range(10):                           # ~0.2s of an unchanging frame
        await asyncio.sleep(0.02)
        ddp.last_rx = time.monotonic()
    ticker.cancel()
    await asyncio.gather(ticker, return_exceptions=True)

    sends = [1 for t, _ in bridge.published if t.endswith("/L1/set")]
    assert len(sends) == 1, f"a static frame should send once, not {len(sends)} times"
