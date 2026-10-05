"""Which entity a zone pauses while it streams - and keeping that right later.

Run from the repo root: ``python -m pytest hue_ent/tests``

Two ways this went wrong on a real install:
- Adaptive Lighting was recognised by entity id alone, so a renamed master
  (``switch.hallway_night_light_adaptive_lighting_hallway_night_light``) was
  missed, while its renamed sub-switches slipped past the sub-switch filter;
- the panel saves every field, so one save froze the detected switch - and
  once that switch was renamed the zone kept "pausing" an entity that no
  longer existed, leaving Adaptive Lighting fighting the stream.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import registry, zonestore

HALL_IEEE = "0x001788010d94e5dd"
AREAS = [{"area_id": "hallway", "name": "Hallway"},
         {"area_id": "living_room", "name": "Living Room"}]
HALL_DEVICE = {"id": "d1", "identifiers": [["mqtt", f"zigbee2mqtt_{HALL_IEEE}"]],
               "area_id": "hallway"}
AL_DEVICE = {"id": "al", "identifiers": [["adaptive_lighting", "x"]], "area_id": "hallway"}


def al_entity(entity_id, unique_id, **extra):
    return {"entity_id": entity_id, "platform": "adaptive_lighting",
            "unique_id": unique_id, "device_id": "al", **extra}


def hall_rooms(entities):
    area_map = registry.build_area_map(AREAS, [HALL_DEVICE, AL_DEVICE], entities)
    rooms = registry.synthesize_rooms({"Hall 1": {"ieee": HALL_IEEE, "color": True}}, area_map)
    return area_map, rooms


# --- detection -------------------------------------------------------------

def test_a_renamed_master_switch_is_found_by_its_unique_id():
    """The real Hallway: the master and its sub-switches all renamed."""
    _, rooms = hall_rooms([
        al_entity("switch.adaptive_lighting_hallway_night_light_adaptive_lighting_"
                  "adapt_brightness_hallway_night_light", "Hallway Night Light_adapt_brightness"),
        al_entity("switch.adaptive_lighting_hallway_night_light_adaptive_lighting_"
                  "sleep_mode_hallway_night_light", "Hallway Night Light_sleep_mode"),
        al_entity("switch.hallway_night_light_adaptive_lighting_hallway_night_light",
                  "Hallway Night Light"),
    ])
    assert rooms[0]["pause_entities"] == [
        "switch.hallway_night_light_adaptive_lighting_hallway_night_light"]


def test_sub_switches_are_never_picked_whatever_their_name():
    _, rooms = hall_rooms([
        al_entity("switch.adaptive_lighting_hallway_x", "Hallway_adapt_color"),
        al_entity("switch.adaptive_lighting_hallway", "Hallway_sleep_mode"),
    ])
    assert rooms[0]["pause_entities"] == []


def test_a_disabled_master_is_skipped():
    _, rooms = hall_rooms([
        al_entity("switch.adaptive_lighting_hallway", "Hallway", disabled_by="user"),
    ])
    assert rooms[0]["pause_entities"] == []


def test_a_switch_from_another_integration_is_not_adaptive_lighting():
    _, rooms = hall_rooms([
        {"entity_id": "switch.adaptive_lighting_hallway", "platform": "template",
         "unique_id": "x", "area_id": "hallway"},
    ])
    assert rooms[0]["pause_entities"] == []


def test_a_config_named_after_a_room_wins_that_room():
    """An AL config whose device sits elsewhere still pauses the room it names."""
    area_map, _ = hall_rooms([
        al_entity("switch.al_lounge", "Living Room", device_id="elsewhere", area_id="hallway"),
    ])
    assert area_map.al_switches["living_room"] == "switch.al_lounge"


def test_enabled_entity_ids_are_collected():
    area_map, _ = hall_rooms([
        al_entity("switch.a", "A"),
        al_entity("switch.b", "B", disabled_by="integration"),
        {"entity_id": "light.no_area"},
    ])
    assert {"switch.a", "light.no_area"} <= area_map.entity_ids
    assert "switch.b" not in area_map.entity_ids


# --- saved overrides ---------------------------------------------------------

ROOM = {"name": "Hallway", "lights": ["Hall 1"], "pause_entities": ["switch.al_hallway"]}


def store(tmp_path):
    return zonestore.ZoneStore(str(tmp_path / "zones.json"))


def pause_of(s, known=None, room=ROOM):
    configs, _ = s.assemble([room], [], True, known_entities=known)
    return configs[0]["pause_entities"]


def test_saving_the_detected_switch_does_not_freeze_it(tmp_path):
    s = store(tmp_path)
    s.set_override("hallway", {"fps": 15, "pause_entities": ["switch.al_hallway"]},
                   auto_pause=["switch.al_hallway"])
    assert "pause_entities" not in s.overrides["hallway"]
    renamed = dict(ROOM, pause_entities=["switch.al_hallway_renamed"])
    assert pause_of(s, room=renamed) == ["switch.al_hallway_renamed"]


def test_a_real_edit_is_kept(tmp_path):
    s = store(tmp_path)
    s.set_override("hallway", {"pause_entities": ["switch.custom"]},
                   auto_pause=["switch.al_hallway"])
    assert pause_of(s, known={"switch.custom", "switch.al_hallway"}) == ["switch.custom"]


def test_a_saved_entity_that_no_longer_exists_falls_back_to_detection(tmp_path):
    """The Hallway as found: an old saved id that HA no longer has."""
    s = store(tmp_path)
    s.overrides["hallway"] = {"pause_entities": ["switch.adaptive_lighting_hallway"]}
    assert pause_of(s, known={"switch.al_hallway"}) == ["switch.al_hallway"]


def test_only_the_missing_saved_entities_are_dropped(tmp_path):
    s = store(tmp_path)
    s.overrides["hallway"] = {"pause_entities": ["switch.gone", "switch.custom"]}
    assert pause_of(s, known={"switch.custom"}) == ["switch.custom"]


def test_saved_entities_are_trusted_while_ha_has_not_been_read(tmp_path):
    s = store(tmp_path)
    s.overrides["hallway"] = {"pause_entities": ["switch.whatever"]}
    assert pause_of(s, known=None) == ["switch.whatever"]


def test_clearing_pause_entities_on_purpose_is_respected(tmp_path):
    s = store(tmp_path)
    s.set_override("hallway", {"pause_entities": []}, auto_pause=["switch.al_hallway"])
    assert pause_of(s, known={"switch.al_hallway"}) == []
