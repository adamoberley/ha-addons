"""Room discovery from the Home Assistant registries.

Run from the repo root: ``python -m pytest hue_ent/tests``

The regression these guard against is github issue #12: one device registry
entry whose ``identifiers`` weren't the documented list-of-pairs aborted the
whole discovery pass ("too many values to unpack (expected 2)"), so a correctly
configured Hue setup ended up with no zones at all.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import registry

LIVING_IEEE = "0x001788010d94e5db"
KITCHEN_IEEE = "0x001788010d94e5dc"
HALL_IEEE = "0x001788010d94e5dd"


def light(ieee: str, color: bool = True) -> dict:
    return {"ieee": ieee, "color": color}


def device(device_id: str, identifiers, area_id: str | None = None, **extra) -> dict:
    return {"id": device_id, "identifiers": identifiers, "area_id": area_id, **extra}


AREAS = [
    {"area_id": "living_room", "name": "Living Room"},
    {"area_id": "kitchen", "name": "Kitchen"},
]


def discover(devices, entities=(), areas=AREAS, lights=None):
    area_map = registry.build_area_map(list(areas), list(devices), list(entities))
    z2m = lights if lights is not None else {"Living 1": light(LIVING_IEEE)}
    return area_map, registry.synthesize_rooms(z2m, area_map)


# --- the documented shape still works ------------------------------------

def test_pairs_shape_maps_lights_to_areas():
    _, rooms = discover(
        [device("d1", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room")],
    )
    assert rooms == [{"name": "Living Room", "lights": ["Living 1"],
                      "skipped": [], "pause_entities": []}]


def test_zigbee_connection_is_also_read():
    _, rooms = discover(
        [device("d1", [], "living_room", connections=[["zigbee", LIVING_IEEE]])],
    )
    assert [r["name"] for r in rooms] == ["Living Room"]


# --- issue #12: malformed neighbours must not sink the pass ---------------

@pytest.mark.parametrize("bad_identifiers", [
    ["mqtt", "zigbee2mqtt_0xdeadbeefdeadbeef"],          # flat list of strings
    [["hue", "abc", "extra"]],                            # three-element entry
    [["single"]],                                         # one-element entry
    {"mqtt": "zigbee2mqtt_0xdeadbeefdeadbeef"},           # a dict
    "zigbee2mqtt_0xdeadbeefdeadbeef",                     # a bare string
    None,                                                 # absent
    [None, 42, ["mqtt", "x"]],                            # mixed junk
])
def test_malformed_device_entry_does_not_break_discovery(bad_identifiers):
    """A neighbouring integration's odd registry row is skipped, not fatal."""
    _, rooms = discover([
        device("bad", bad_identifiers, "kitchen"),
        device("good", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room"),
    ])
    assert [r["name"] for r in rooms] == ["Living Room"]


def test_non_dict_device_rows_are_counted_and_skipped():
    area_map, rooms = discover([
        "not-a-device",
        device("good", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room"),
    ])
    assert area_map.unreadable == ["'not-a-device'"]
    assert [r["name"] for r in rooms] == ["Living Room"]


def test_ieee_recovered_from_an_unexpected_position():
    """The address is found by pattern, not by tuple position."""
    _, rooms = discover([
        device("d1", [["mqtt", "z2m", f"device_{LIVING_IEEE}_light"]], "living_room"),
    ])
    assert [r["name"] for r in rooms] == ["Living Room"]


# --- area assignment on the entity, not the device -----------------------

def test_entity_area_matches_a_light_with_no_device_area():
    _, rooms = discover(
        devices=[device("d1", [["mqtt", f"zigbee2mqtt_{KITCHEN_IEEE}"]], None)],
        entities=[{"entity_id": "light.kitchen_1", "device_id": "d1", "area_id": "kitchen"}],
        lights={"Kitchen 1": light(KITCHEN_IEEE)},
    )
    assert [r["name"] for r in rooms] == ["Kitchen"]


def test_entity_area_overrides_the_device_area():
    _, rooms = discover(
        devices=[device("d1", [["mqtt", f"zigbee2mqtt_{KITCHEN_IEEE}"]], "living_room")],
        entities=[{"entity_id": "light.kitchen_1", "device_id": "d1", "area_id": "kitchen"}],
        lights={"Kitchen 1": light(KITCHEN_IEEE)},
    )
    assert [r["name"] for r in rooms] == ["Kitchen"]


def test_friendly_name_falls_back_to_the_entity_id():
    """No Zigbee address on the HA device at all: match z2m's entity naming."""
    _, rooms = discover(
        devices=[device("d1", [["mqtt", "some_opaque_id"]], "kitchen")],
        entities=[{"entity_id": "light.kitchen_1", "device_id": "d1"}],
        lights={"Kitchen 1": light("0xffffffffffffffff")},
    )
    assert [r["name"] for r in rooms] == ["Kitchen"]


# --- zone shaping ---------------------------------------------------------

def test_non_color_lights_are_listed_as_skipped():
    _, rooms = discover(
        devices=[
            device("d1", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room"),
            device("d2", [["mqtt", f"zigbee2mqtt_{KITCHEN_IEEE}"]], "living_room"),
        ],
        lights={"Living 1": light(LIVING_IEEE), "Living White": light(KITCHEN_IEEE, color=False)},
    )
    assert rooms[0]["lights"] == ["Living 1"]
    assert rooms[0]["skipped"] == ["Living White (no color)"]


def test_a_room_with_only_white_bulbs_is_dropped():
    _, rooms = discover(
        devices=[device("d1", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room")],
        lights={"Living White": light(LIVING_IEEE, color=False)},
    )
    assert rooms == []


def test_zone_is_capped_at_ten_lights():
    devices, lights = [], {}
    for i in range(12):
        ieee = f"0x00178801000000{i:02d}"
        devices.append(device(f"d{i}", [["mqtt", f"zigbee2mqtt_{ieee}"]], "living_room"))
        lights[f"Living {i:02d}"] = light(ieee)
    _, rooms = discover(devices, lights=lights)
    assert len(rooms[0]["lights"]) == registry.MAX_ZONE_LIGHTS
    assert rooms[0]["skipped"] == ["Living 10 (zone full)", "Living 11 (zone full)"]


# --- Adaptive Lighting master switch -------------------------------------

def test_adaptive_lighting_master_is_matched_by_name():
    _, rooms = discover(
        devices=[device("d1", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room")],
        entities=[
            {"entity_id": "switch.adaptive_lighting_living_room", "area_id": "living_room"},
            {"entity_id": "switch.adaptive_lighting_sleep_mode_living_room",
             "area_id": "living_room"},
        ],
    )
    assert rooms[0]["pause_entities"] == ["switch.adaptive_lighting_living_room"]


def test_adaptive_lighting_sub_switches_are_never_used():
    _, rooms = discover(
        devices=[device("d1", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room")],
        entities=[
            {"entity_id": "switch.adaptive_lighting_adapt_brightness_living_room",
             "area_id": "living_room"},
            {"entity_id": "switch.adaptive_lighting_adapt_color_living_room",
             "area_id": "living_room"},
        ],
    )
    assert rooms[0]["pause_entities"] == []


# --- discovery result / diagnostics --------------------------------------

def test_summary_explains_lights_with_no_area():
    area_map = registry.build_area_map(AREAS, [], [])
    assert registry.synthesize_rooms({"Living 1": light(LIVING_IEEE)}, area_map) == []
    result = registry.Discovery(ok=True, areas=2, lights=3, matched=0)
    assert "None of the 3 Philips light(s)" in result.summary


def test_summary_reports_a_failure():
    assert "could not be read: RuntimeError: nope" in registry.Discovery(
        error="RuntimeError: nope").summary


def test_fresh_result_does_not_claim_a_failure():
    assert registry.Discovery().summary == "Home Assistant rooms have not been read yet."


@pytest.mark.asyncio
async def test_discover_rooms_from_a_fixture(tmp_path, monkeypatch):
    """The HA_REGISTRY_FIXTURE dev hook drives the whole pass end to end."""
    fixture = tmp_path / "registry.json"
    fixture.write_text(json.dumps({
        "areas": AREAS,
        "devices": [
            device("d1", [["mqtt", f"zigbee2mqtt_{LIVING_IEEE}"]], "living_room"),
            device("d2", ["mqtt", f"zigbee2mqtt_{KITCHEN_IEEE}"], "kitchen"),  # malformed
            device("d3", [["mqtt", f"zigbee2mqtt_{HALL_IEEE}"]], None),        # no area
        ],
        "entities": [{"entity_id": "light.kitchen_1", "device_id": "d2", "area_id": "kitchen"}],
    }))
    monkeypatch.setenv("HA_REGISTRY_FIXTURE", str(fixture))

    result = await registry.discover_rooms({
        "Living 1": light(LIVING_IEEE),
        "Kitchen 1": light(KITCHEN_IEEE),
        "Hall 1": light(HALL_IEEE),
    })

    assert result.ok
    assert [r["name"] for r in result.rooms] == ["Kitchen", "Living Room"]
    assert (result.matched, result.lights, result.areas) == (2, 3, 2)
    assert "2 of 3" in result.summary


@pytest.mark.asyncio
async def test_discover_rooms_reports_a_transport_failure(monkeypatch):
    monkeypatch.delenv("HA_REGISTRY_FIXTURE", raising=False)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)

    result = await registry.discover_rooms({"Living 1": light(LIVING_IEEE)}, retries=1)

    assert not result.ok
    assert "SUPERVISOR_TOKEN" in result.error
    assert result.rooms == []
