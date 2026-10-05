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
