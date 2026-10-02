"""Which zone streams: arming, switching rooms, and live rebuilds.

Run from the repo root: ``python -m pytest hue_ent/tests``

Regressions from #30:
- a freshly armed zone disarmed on its first tick ("no DDP for 183s") because
  idleness was measured from a frame left over from an earlier session;
- LedFX feeds every zone with an effect at once, and each stream could preempt
  the active zone, so zones knocked each other off - and two overlapping arms
  could leave both streaming;
- a retained "ON" on a switch's command topic re-armed the zone on every
  re-subscribe, and every rebuild re-subscribed (and re-provisioned LedFX).
"""

from __future__ import annotations

import asyncio
import socket
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import main as main_mod
from hue_ent.app import zonestore
from hue_ent.tests.test_zone_runner import FakeDdp, make_runner


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("0.0.0.0", 0))
        return sock.getsockname()[1]


def make_bridge(tmp_path, zones, ledfx_url=""):
    options = {"auto_zones": False, "zones": zones, "ledfx_url": ledfx_url}
    return main_mod.Bridge(options, zonestore.ZoneStore(str(tmp_path / "zones.json")))


def zone_cfg(name, lights, **extra):
    return {"name": name, "lights": list(lights), "ddp_port": free_port(), **extra}


def fake_arming(bridge, arm_s=0.05):
    """Swap the Zigbee arm/disarm rituals for quick stand-ins."""
    log: list[str] = []
    for slug, runner in bridge.runners.items():
        async def arm(runner=runner, slug=slug):
            await asyncio.sleep(arm_s)            # the ritual takes a while
            runner.armed = True
            log.append(f"arm {slug}")

        async def disarm(runner=runner, slug=slug):
            if runner.armed:
                runner.armed = False
                log.append(f"disarm {slug}")

        runner.arm = arm
        runner.disarm = disarm
    return log


async def settle(bridge, timeout=2.0):
    deadline = time.monotonic() + timeout
    while (bridge._pending_arms or bridge._arming) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


async def two_zone_bridge(tmp_path, **kw):
    bridge = make_bridge(tmp_path, [
        zone_cfg("Kitchen", ["K1", "K2"]), zone_cfg("Lounge", ["L1"]),
    ], **kw)
    bridge.nwk = {"K1": 1, "K2": 2, "L1": 3}
    await bridge.rebuild_zones()
    return bridge


def close(bridge):
    for runner in bridge.runners.values():
        runner.close()


# --- the idle timer -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_frame_from_before_the_arm_does_not_count_as_idle_time():
    """The bug: armed 2 s ago, disarmed for 'no DDP for 183s'."""
    runner, _bridge = make_runner(idle_timeout_s=0.3)
    runner.armed = True
    runner._armed_at = time.monotonic()
    runner.ddp = FakeDdp(latest=[(1, 2, 3), (4, 5, 6)], last_rx=time.monotonic() - 183)

    ticker = asyncio.ensure_future(runner._run_ticker())
    await asyncio.sleep(0.15)                     # a few ticks, under the timeout
    assert runner.armed, "a fresh arm must get its full idle timeout"

    await asyncio.wait_for(ticker, timeout=2.0)   # ...and it still gives up after
    assert not runner.armed


# --- one zone at a time --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stream_does_not_take_over_from_the_active_zone(tmp_path):
    bridge = await two_zone_bridge(tmp_path)
    log = fake_arming(bridge)
    try:
        bridge.schedule_arm("kitchen", reason="switch")
        await settle(bridge)
        bridge.schedule_arm("lounge", reason="ddp")
        await settle(bridge)

        assert bridge.runners["kitchen"].armed
        assert not bridge.runners["lounge"].armed
        assert log == ["arm kitchen"]
    finally:
        close(bridge)


@pytest.mark.asyncio
async def test_a_stream_arriving_mid_arm_does_not_arm_a_second_zone(tmp_path):
    """Both zones used to end up armed: each saw the other as not armed yet."""
    bridge = await two_zone_bridge(tmp_path)
    log = fake_arming(bridge, arm_s=0.2)
    try:
        bridge.schedule_arm("kitchen", reason="switch")
        await asyncio.sleep(0.05)                 # kitchen is mid-ritual
        bridge.runners["lounge"].on_ddp_activity()
        await settle(bridge)

        armed = [s for s, r in bridge.runners.items() if r.armed]
        assert armed == ["kitchen"]
        assert log == ["arm kitchen"]
    finally:
        close(bridge)


@pytest.mark.asyncio
async def test_switching_rooms_keeps_the_old_room_off(tmp_path):
    """Explicitly picking a room stops the other, and the other's still-running
    LedFX stream doesn't grab the bulbs back."""
    bridge = await two_zone_bridge(tmp_path)
    log = fake_arming(bridge)
    try:
        bridge.runners["lounge"].on_ddp_activity()  # lounge's stream arms it
        await settle(bridge)
        bridge.schedule_arm("kitchen", reason="switch")
        await settle(bridge)
        assert log == ["arm lounge", "disarm lounge", "arm kitchen"]

        await bridge.runners["kitchen"].disarm()  # kitchen times out...
        bridge.runners["lounge"].on_ddp_activity()  # ...lounge still streaming
        await settle(bridge)

        assert not bridge.runners["lounge"].armed
    finally:
        close(bridge)


@pytest.mark.asyncio
async def test_a_lone_stream_still_auto_arms(tmp_path):
    bridge = await two_zone_bridge(tmp_path)
    log = fake_arming(bridge)
    try:
        bridge.runners["lounge"].on_ddp_activity()
        await settle(bridge)
        assert log == ["arm lounge"]
    finally:
        close(bridge)


# --- MQTT commands --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retained_command_is_ignored_and_cleared(tmp_path):
    bridge = await two_zone_bridge(tmp_path)
    log = fake_arming(bridge)
    published = []

    async def publish(topic, payload, retain=False):
        published.append((topic, payload, retain))

    bridge.publish = publish
    try:
        topic = bridge.zones["kitchen"].switch_command_topic
        bridge.handle_message(topic, b"ON", retain=True)
        await asyncio.sleep(0.02)
        await settle(bridge)

        assert log == []
        assert (topic, "", True) in published

        # The broker forwards the clear as an empty live message: not an "off".
        bridge.handle_message(topic, b"", retain=False)
        assert not bridge.runners["kitchen"]._suppress_auto

        bridge.handle_message(topic, b"ON", retain=False)
        await asyncio.sleep(0.02)
        await settle(bridge)
        assert log == ["arm kitchen"]
    finally:
        close(bridge)


# --- live rebuilds --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rebuild_leaves_unchanged_zones_streaming(tmp_path):
    bridge = await two_zone_bridge(tmp_path)
    fake_arming(bridge)
    try:
        bridge.schedule_arm("kitchen", reason="switch")
        await settle(bridge)
        kitchen = bridge.runners["kitchen"]
        lounge = bridge.runners["lounge"]

        bridge.options["zones"][1]["fps"] = 10    # edit the *other* zone
        await bridge.rebuild_zones()

        assert bridge.runners["kitchen"] is kitchen
        assert kitchen.armed, "saving one room mustn't interrupt another"
        assert kitchen.ddp_transport is not None
        assert bridge.runners["lounge"] is not lounge
        assert bridge.zones["lounge"].fps == 10
        assert bridge.runners["lounge"].ddp_transport is not None
    finally:
        close(bridge)


@pytest.mark.asyncio
async def test_ledfx_is_only_reprovisioned_when_its_devices_would_change(
        tmp_path, monkeypatch):
    kicks = []

    async def provision_forever(base_url, target_ip, zones):
        kicks.append(sorted(z.name for z in zones))

    monkeypatch.setattr(main_mod.ledfx, "provision_forever", provision_forever)
    bridge = await two_zone_bridge(tmp_path, ledfx_url="http://ledfx")
    try:
        await asyncio.sleep(0)
        assert len(kicks) == 1

        await bridge.rebuild_zones()                          # nothing changed
        bridge.options["zones"][0]["brightness_scale"] = 0.5  # LedFX doesn't care
        await bridge.rebuild_zones()
        await asyncio.sleep(0)
        assert len(kicks) == 1

        bridge.options["zones"][0]["fps"] = 10                # LedFX does
        await bridge.rebuild_zones()
        await asyncio.sleep(0)
        assert len(kicks) == 2

        await bridge.rebuild_zones(force_provision=True)      # "Rescan rooms"
        await asyncio.sleep(0)
        assert len(kicks) == 3
    finally:
        close(bridge)
