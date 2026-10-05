"""Streaming around bulbs zigbee2mqtt can't reach.

Run from the repo root: ``python -m pytest hue_ent/tests``

Every frame goes to the zone's proxy, which re-broadcasts it to the other
bulbs. Bulbs on a wall switch are routinely powered off, and when the proxy
was one of them the whole zone stayed dark - even with its other bulbs on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import main as main_mod
from hue_ent.tests.test_zone_runner import make_runner

Z2M = main_mod.Z2M_BASE


def set_topics(bridge, fn):
    return [p for t, p in bridge.published if t == f"{Z2M}/{fn}/set"]


async def arm(runner):
    await runner.arm()
    runner.close()  # stop the ticker; these tests look at the arm itself


@pytest.mark.asyncio
async def test_an_offline_proxy_hands_over_to_the_strongest_online_bulb():
    runner, bridge = make_runner(lights=("L1", "L2", "L3"))
    bridge.nwk["L3"] = 0x9ABC
    bridge.offline = {"L1"}                                   # the configured proxy
    bridge.light_states = {"L2": {"linkquality": 40}, "L3": {"linkquality": 120}}

    await arm(runner)

    assert runner.armed and runner.proxy == "L3"
    assert runner.stats["proxy"] == "L3"
    await runner.disarm()                                     # sends a closing frame
    assert set_topics(bridge, "L1") == []                     # nothing to the dead proxy
    assert runner.zone.proxy == "L1"                          # config untouched


@pytest.mark.asyncio
async def test_offline_bulbs_are_left_out_of_the_arm_and_the_restore():
    runner, bridge = make_runner(lights=("L1", "L2"))
    bridge.offline = {"L2"}
    bridge.light_states = {"L1": {"state": "ON", "brightness": 50},
                           "L2": {"state": "ON", "brightness": 50}}

    await arm(runner)
    assert runner.proxy == "L1"
    await runner.disarm()

    assert set_topics(bridge, "L2") == []
    assert any(json.loads(p).get("brightness") == 50 for p in set_topics(bridge, "L1")
               if p.startswith("{") and "state" in p)


@pytest.mark.asyncio
async def test_a_zone_with_every_bulb_offline_does_not_arm():
    runner, bridge = make_runner(lights=("L1", "L2"))
    bridge.offline = {"L1", "L2"}

    await arm(runner)

    assert not runner.armed
    assert bridge.pause_calls == []                           # Adaptive Lighting left alone
    assert (runner.zone.switch_state_topic, "OFF") in bridge.published


@pytest.mark.asyncio
async def test_a_bulb_back_online_is_used_again_next_session():
    runner, bridge = make_runner(lights=("L1", "L2"))
    bridge.offline = {"L1"}
    await arm(runner)
    assert runner.proxy == "L2"
    await runner.disarm()

    bridge.offline = set()
    await arm(runner)
    assert runner.proxy == "L1" and runner.online == ["L1", "L2"]
    await runner.disarm()


@pytest.mark.parametrize("payload, offline", [
    (b'{"state":"offline"}', True),
    (b"offline", True),
    (b'{"state":"online"}', False),
    (b"online", False),
])
def test_availability_messages_are_read_in_both_formats(tmp_path, payload, offline):
    from hue_ent.app import zonestore
    bridge = main_mod.Bridge({}, zonestore.ZoneStore(str(tmp_path / "z.json")))
    bridge.offline = {"Hall 1"} if not offline else set()

    bridge.handle_message(f"{Z2M}/Hall 1/availability", payload)

    assert ("Hall 1" in bridge.offline) is offline


def test_an_unreadable_availability_message_changes_nothing(tmp_path):
    from hue_ent.app import zonestore
    bridge = main_mod.Bridge({}, zonestore.ZoneStore(str(tmp_path / "z.json")))
    bridge.offline = {"Hall 1"}
    bridge.handle_message(f"{Z2M}/Hall 1/availability", b"[1, 2]")
    bridge.handle_message(f"{Z2M}/Hall 1/availability", b"")
    assert bridge.offline == {"Hall 1"}


# --- the restore is checked ------------------------------------------------

class ProxyKeepsTheClosingFrame:
    """Bulb L1 reports the closing frame's level the first time it's restored."""

    def __init__(self, bridge, fn="L1"):
        self.bridge, self.fn, self.fired = bridge, fn, False
        self.inner = bridge.publish

    async def __call__(self, topic, payload, retain=False):
        await self.inner(topic, payload, retain)
        if topic == f"{Z2M}/{self.fn}/set" and '"brightness"' in payload and not self.fired:
            self.fired = True
            self.bridge.light_states[self.fn] = {"state": "ON", "brightness": 1}


def restores(bridge, fn):
    return [p for p in set_topics(bridge, fn) if '"brightness"' in p]


@pytest.mark.asyncio
async def test_a_restore_that_did_not_take_is_sent_again():
    runner, bridge = make_runner(lights=("L1", "L2"))
    bridge.light_states = {"L1": {"state": "ON", "brightness": 58, "color_temp": 500},
                           "L2": {"state": "ON", "brightness": 90}}
    await arm(runner)
    bridge.publish = ProxyKeepsTheClosingFrame(bridge)

    await runner.disarm()

    assert len(restores(bridge, "L1")) == 2
    assert json.loads(restores(bridge, "L1")[1]) == {
        "state": "ON", "brightness": 58, "color_temp": 500}
    assert len(restores(bridge, "L2")) == 1                   # it reported nothing wrong


@pytest.mark.asyncio
async def test_the_check_runs_before_adaptive_lighting_comes_back():
    """Otherwise Adaptive Lighting's own adjustment would look like a failure."""
    runner, bridge = make_runner(lights=("L1",))
    bridge.light_states = {"L1": {"state": "ON", "brightness": 58}}
    await arm(runner)
    order = []
    inner_publish, inner_pause = bridge.publish, bridge.set_pause_entities

    async def publish(topic, payload, retain=False):
        await inner_publish(topic, payload, retain)
        if '"brightness"' in payload:
            order.append("restore")

    async def pause(zone, paused):
        await inner_pause(zone, paused)
        order.append("pause off" if not paused else "pause on")
        bridge.light_states["L1"] = {"state": "ON", "brightness": 120}   # AL adapts

    bridge.publish, bridge.set_pause_entities = publish, pause
    await runner.disarm()

    assert order == ["restore", "pause off"]


@pytest.mark.parametrize("report, payload, took", [
    ({"state": "ON", "brightness": 57}, {"state": "ON", "brightness": 58}, True),
    ({"state": "ON", "brightness": 1}, {"state": "ON", "brightness": 58}, False),
    ({"state": "ON"}, {"state": "ON", "brightness": 58}, True),
    ({"state": "ON", "brightness": 40}, {"state": "ON"}, True),
    ({"state": "ON", "brightness": 40}, {"state": "OFF"}, False),
    ({}, {"state": "OFF"}, False),
])
def test_what_counts_as_a_restore_that_took(report, payload, took):
    assert main_mod._restore_took(report, payload) is took
