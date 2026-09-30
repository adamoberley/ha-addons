"""Home Assistant cameras, trigger-gated recognition, and the recognized event (0.8).

Run from the repo root: ``python -m pytest local_faces/tests``
"""

from __future__ import annotations

import json
import time

import camera as camera_mod
import cv2
import hass as hass_mod
import numpy as np
import options as options_mod
from helpers import face_at, make_app, vec

ALEX = vec(1, 0, 0)
STRANGER = vec(0, 0, 1)
PERSON = "binary_sensor.front_porch_person"
MOTION = "binary_sensor.front_porch_motion"


# --- options ----------------------------------------------------------------

def _load(monkeypatch, tmp_path, raw: dict):
    path = tmp_path / "options.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(options_mod, "OPTIONS_PATH", str(path))
    return options_mod.load()


def test_a_camera_can_be_just_an_ha_entity_with_triggers(monkeypatch, tmp_path):
    opts = _load(monkeypatch, tmp_path, {"cameras": [{
        "name": "Front Porch", "camera_entity": "camera.front_porch_clear",
        "trigger_entities": f"{PERSON}, {MOTION}\n{PERSON}",
    }]})
    (cam,) = opts.cameras
    assert cam.camera_entity == "camera.front_porch_clear"
    assert cam.source_kind == "ha"
    assert cam.triggers == (PERSON, MOTION)            # split, de-duplicated, ordered
    assert opts.active_interval == 0.5 and opts.trigger_hold_seconds == 10
    assert opts.fire_events is True


def test_existing_rtsp_configs_are_unchanged(monkeypatch, tmp_path):
    opts = _load(monkeypatch, tmp_path, {
        "cameras": [{"name": "Door", "stream_url": "rtsp://cam/1", "camera_mode": "stream"},
                    {"name": "Nothing configured"}],
    })
    (cam,) = opts.cameras                                # the empty entry is skipped
    assert (cam.stream_url, cam.source_kind, cam.triggers) == ("rtsp://cam/1", "stream", ())


def test_the_legacy_single_url_still_works(monkeypatch, tmp_path):
    opts = _load(monkeypatch, tmp_path, {"stream_url": "rtsp://cam/1"})
    assert [c.slug for c in opts.cameras] == ["camera"]
    assert opts.cameras[0].triggers == ()


# --- gating -----------------------------------------------------------------

def test_a_gated_camera_is_not_analyzed_while_its_triggers_are_off(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)], triggers={"arcade": (PERSON,)})
    app.triggers.set_state(PERSON, "off")

    app.tick()

    assert app.preview_jpeg("arcade") is None             # no frame was even looked at
    assert log.recent() == []
    assert app.sources["arcade"].active is False          # the source is paused
    assert app._status["arcade"]["watching"] is False


def test_it_starts_looking_the_moment_a_trigger_turns_on(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)], triggers={"arcade": (PERSON,)})
    app.triggers.set_state(PERSON, "off")
    app.tick()
    app.wake.clear()

    app.triggers.set_state(PERSON, "on")

    assert app.wake.is_set()                               # main loop wakes immediately
    app.tick()
    assert app.sources["arcade"].active is True
    assert [e["name"] for e in log.recent()] == ["Alex"]


def test_it_keeps_looking_for_the_hold_time_after_the_trigger_drops(db, log, monkeypatch):
    app, _ = make_app(db, log, [], triggers={"arcade": (PERSON,)}, trigger_hold_seconds=10)
    app.triggers.set_state(PERSON, "on")
    app.triggers.set_state(PERSON, "off")
    cam = app.cameras[0]

    assert app.camera_active(cam)                          # just dropped: still holding
    later = time.time() + 11
    monkeypatch.setattr("main.time.time", lambda: later)
    assert not app.camera_active(cam)                      # hold expired


def test_the_hold_counts_from_when_the_trigger_turned_off(db, log, monkeypatch):
    """A sensor that stays on longer than the hold must still get the hold after.

    Found running against a live HA: the hold was measured from when the trigger
    turned *on*, so after 6 s of "person detected" a 3 s hold had already expired
    the moment the sensor dropped.
    """
    clock = [1000.0]
    monkeypatch.setattr("hass.time.time", lambda: clock[0])
    monkeypatch.setattr("main.time.time", lambda: clock[0])
    app, _ = make_app(db, log, [], triggers={"arcade": (PERSON,)}, trigger_hold_seconds=3)
    cam = app.cameras[0]
    app.triggers.set_state(PERSON, "on")
    clock[0] += 6                                          # someone at the door for 6 s
    app.triggers.set_state(PERSON, "off")

    clock[0] += 2
    assert app.camera_active(cam)                          # 2 s into a 3 s hold
    clock[0] += 2
    assert not app.camera_active(cam)


def test_any_one_of_several_triggers_is_enough(db, log):
    app, _ = make_app(db, log, [], triggers={"arcade": (PERSON, MOTION)})
    app.triggers.set_state(PERSON, "off")
    app.triggers.set_state(MOTION, "on")
    assert app.camera_active(app.cameras[0])


def test_ungated_cameras_keep_running_alongside_gated_ones(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)], cameras=("door", "yard"),
                      triggers={"door": (PERSON,)})
    app.triggers.set_state(PERSON, "off")

    app.tick()
    app.tick()

    assert app.preview_jpeg("yard") is not None
    assert app.preview_jpeg("door") is None
    assert {e["camera"] for e in log.recent()} == {"Yard"}


def test_when_ha_cannot_be_reached_a_gated_camera_keeps_recognizing(db, log):
    """Fail open: an unknown trigger state must not blind the camera."""
    app, _ = make_app(db, log, [], triggers={"arcade": (PERSON,)})
    app.triggers.connected = False
    assert app.camera_active(app.cameras[0])


def test_the_loop_runs_faster_only_while_a_triggered_camera_is_active(db, log):
    app, _ = make_app(db, log, [], cameras=("door", "yard"), triggers={"door": (PERSON,)},
                      detect_interval=2.0, active_interval=0.5)
    app.triggers.set_state(PERSON, "off")
    assert app.next_wait() == 2.0
    app.triggers.set_state(PERSON, "on")
    assert app.next_wait() == 0.5


# --- the local_faces_recognized event --------------------------------------

def test_a_recognition_fires_an_ha_event(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)])
    app.cameras[0].camera_entity = "camera.front_porch_clear"

    app.tick()

    (event,) = app.events.sent
    assert event["name"] == "Alex" and event["known"] is True
    assert event["camera"] == "Arcade" and event["camera_entity"] == "camera.front_porch_clear"
    assert 0 < event["score"] <= 1


def test_an_unknown_face_fires_an_event_with_no_name(db, log):
    app, _ = make_app(db, log, [face_at(STRANGER)])
    app.tick()
    (event,) = app.events.sent
    assert event["name"] is None and event["known"] is False


def test_ignored_faces_fire_no_event(db, log):
    db.add("Poster", STRANGER, b"", ignored=True)
    app, _ = make_app(db, log, [face_at(STRANGER)])
    app.tick()
    assert app.events.sent == []


def test_the_event_sender_posts_to_core(monkeypatch):
    fired = []

    class Client:
        available = True

        def fire_event(self, event_type, data):
            fired.append((event_type, data))

    sender = hass_mod.EventSender(Client())
    sender.send({"name": "Alex"})
    sender._queue.join()
    assert fired == [("local_faces_recognized", {"name": "Alex"})]


# --- trigger websocket messages (shapes captured from a live HA) ------------

def test_the_watcher_reads_current_states_and_trigger_events():
    watcher = hass_mod.TriggerWatcher([PERSON], token="t")
    watcher.connected = True
    watcher.handle_message({"id": 2, "type": "result", "success": True, "result": [
        {"entity_id": PERSON, "state": "off"}, {"entity_id": "light.x", "state": "on"}]})
    assert watcher.is_on(PERSON) is False

    watcher.handle_message({"id": 1, "type": "event", "event": {"variables": {"trigger": {
        "platform": "state", "entity_id": PERSON,
        "from_state": {"entity_id": PERSON, "state": "off"},
        "to_state": {"entity_id": PERSON, "state": "on"}}}}})
    assert watcher.is_on(PERSON) is True
    assert watcher.last_on(PERSON) > 0


def test_unavailable_and_unknown_trigger_states_count_as_off():
    watcher = hass_mod.TriggerWatcher([PERSON], token="t")
    watcher.connected = True
    for state in ("unavailable", "unknown", "", None):
        watcher.set_state(PERSON, state)
        assert watcher.is_on(PERSON) is False


# --- the Home Assistant camera source ---------------------------------------

class _Stills:
    """A stand-in HaClient serving one JPEG and counting the fetches."""

    available = True

    def __init__(self):
        _, buf = cv2.imencode(".jpg", np.full((48, 64, 3), 128, dtype="uint8"))
        self.jpeg = buf.tobytes()
        self.calls = 0

    def camera_image(self, _entity):
        self.calls += 1
        return self.jpeg


def test_the_ha_source_decodes_the_entitys_still():
    client = _Stills()
    src = camera_mod.HaCameraSource(client, "camera.front_porch_clear", poll=0.5)
    assert src.fetch_once()
    frame = src.latest()
    assert frame is not None and frame.shape == (48, 64, 3)


def test_a_paused_ha_source_hands_out_no_stale_frame():
    src = camera_mod.HaCameraSource(_Stills(), "camera.front_porch_clear", poll=0.5)
    src.fetch_once()
    src.set_active(False)
    assert src.latest() is None


def test_a_paused_ha_source_stops_fetching():
    client = _Stills()
    src = camera_mod.HaCameraSource(client, "camera.front_porch_clear", poll=0.2)
    src.set_active(False)
    src.start()
    time.sleep(0.5)
    idle_calls = client.calls
    src.set_active(True)
    time.sleep(0.5)
    src.stop()
    assert idle_calls == 0
    assert client.calls >= 2


def test_a_failed_snapshot_is_not_a_frame():
    class Offline(_Stills):
        def camera_image(self, _entity):
            return None

    src = camera_mod.HaCameraSource(Offline(), "camera.front_porch_clear", poll=0.5)
    assert not src.fetch_once()
    assert src.latest() is None


def test_a_paused_stream_is_released_after_the_idle_grace(monkeypatch):
    src = camera_mod.CameraSource("rtsp://cam/1", "stream", 1.0)
    clock = [1000.0]
    monkeypatch.setattr(camera_mod.time, "monotonic", lambda: clock[0])
    src.set_active(False)
    assert not src._idle_too_long()
    clock[0] += camera_mod.STREAM_IDLE_RELEASE + 1
    assert src._idle_too_long()
    src.set_active(True)
    assert not src._idle_too_long()
