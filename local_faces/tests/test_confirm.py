"""Confirming a recognition across frames before reporting it (0.10).

Run from the repo root: ``python -m pytest local_faces/tests``
"""

from __future__ import annotations

import json

import engine as engine_mod
import numpy as np
import options as options_mod
import pytest
from confirm import FrameConfirmer
from helpers import face_at, make_app, vec

ALEX = vec(1, 0, 0)
ALEX_ALT = vec(0.98, 0.2, 0)
STRANGER = vec(0, 0, 1)


# --- the voting rule itself --------------------------------------------------

def test_one_frame_is_not_enough():
    c = FrameConfirmer(2)
    assert c.observe("door", [("Alex", 0.6, 100)]) == {"Alex": (False, 0.6)}


def test_two_consecutive_frames_confirm():
    c = FrameConfirmer(2)
    c.observe("door", [("Alex", 0.6, 100)])
    sure, _ = c.observe("door", [("Alex", 0.5, 100)])["Alex"]
    assert sure


def test_two_of_the_last_three_frames_confirm():
    c = FrameConfirmer(2)
    c.observe("door", [("Alex", 0.6, 100)])
    c.observe("door", [])                                  # looked away for a frame
    assert c.observe("door", [("Alex", 0.6, 100)])["Alex"][0]


def test_frames_too_far_apart_do_not_confirm():
    c = FrameConfirmer(2)
    c.observe("door", [("Alex", 0.6, 100)])
    c.observe("door", [])
    c.observe("door", [])
    assert not c.observe("door", [("Alex", 0.6, 100)])["Alex"][0]


def test_the_score_is_weighted_toward_bigger_faces():
    c = FrameConfirmer(2)
    c.observe("door", [("Alex", 0.40, 50)])                 # small, distant
    _, score = c.observe("door", [("Alex", 0.70, 150)])["Alex"]   # big, close
    assert score == pytest.approx((0.40 * 50 + 0.70 * 150) / 200)


def test_cameras_are_counted_separately():
    c = FrameConfirmer(2)
    c.observe("door", [("Alex", 0.6, 100)])
    assert not c.observe("yard", [("Alex", 0.6, 100)])["Alex"][0]


def test_reset_forgets_a_camera():
    c = FrameConfirmer(2)
    c.observe("door", [("Alex", 0.6, 100)])
    c.reset("door")
    assert not c.observe("door", [("Alex", 0.6, 100)])["Alex"][0]


def test_one_frame_setting_confirms_immediately():
    assert FrameConfirmer(1).observe("door", [("Alex", 0.6, 100)])["Alex"][0]


# --- in the pipeline ------------------------------------------------------------

def test_a_single_frame_match_reports_nothing(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)], confirm_frames=2)

    app.tick()

    assert log.recent() == [] and app.events.sent == []
    assert app.mqtt.person_state("alex")[0] is False
    assert app._status["arcade"]["state"] == "idle"
    assert app.preview_jpeg("arcade") is not None           # still drawn, as "checking"


def test_the_second_agreeing_frame_reports_with_the_averaged_score(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)], confirm_frames=2)
    app.tick()
    app.engine.faces = [face_at(ALEX_ALT)]

    app.tick()

    (event,) = app.events.sent
    expected = (float(ALEX @ ALEX) + float(ALEX @ ALEX_ALT)) / 2
    assert event["name"] == "Alex" and event["score"] == pytest.approx(expected, abs=1e-3)
    assert [e["name"] for e in log.recent()] == ["Alex"]
    assert app.mqtt.person_state("alex")[0] is True
    assert app._status["arcade"]["state"] == "known"


def test_a_one_frame_stranger_between_known_frames_is_never_reported(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX)], confirm_frames=2)
    app.tick()
    app.engine.faces = [face_at(STRANGER)]                  # one bad frame
    app.tick()
    app.engine.faces = [face_at(ALEX)]
    app.tick()

    assert [e["name"] for e in app.events.sent] == ["Alex"]  # no "unknown"
    assert all(not e["unknown"] for e in log.recent())


def test_unknown_faces_need_confirming_too(db, log):
    app, _ = make_app(db, log, [face_at(STRANGER)], confirm_frames=2)
    app.tick()
    assert app.events.sent == []
    app.tick()
    assert app.events.sent[0]["known"] is False


def test_a_camera_going_idle_starts_its_count_over(db, log):
    db.add("Alex", ALEX, b"")
    person = "binary_sensor.door_person"
    app, _ = make_app(db, log, [face_at(ALEX)], triggers={"arcade": (person,)},
                      confirm_frames=2, trigger_hold_seconds=0)
    app.triggers.set_state(person, "on")
    app.tick()                                               # frame 1 of 2
    app.triggers.set_state(person, "off")
    app.tick()                                               # idle: history dropped
    app.triggers.set_state(person, "on")
    app.tick()                                               # frame 1 of 2 again

    assert app.events.sent == []


def test_ignored_faces_are_not_counted(db, log):
    db.add("Poster", STRANGER, b"", ignored=True)
    app, _ = make_app(db, log, [face_at(STRANGER)], confirm_frames=2)
    app.tick()
    app.tick()
    assert app.events.sent == [] and log.recent() == []


# --- drawing and options ----------------------------------------------------------

def test_pending_faces_are_drawn_without_error():
    frame = np.zeros((120, 160, 3), dtype="uint8")
    out = engine_mod.FaceEngine.annotate(frame, [
        (face_at(ALEX), "Alex", 0.6, False, True),           # checking
        (face_at(ALEX, x=60), "Alex", 0.6, False),           # old 4-tuple still fine
    ])
    assert out.shape == frame.shape and out.any()


def test_the_default_is_two_frames(monkeypatch, tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({}))
    monkeypatch.setattr(options_mod, "OPTIONS_PATH", str(path))
    assert options_mod.load().confirm_frames == 2
    path.write_text(json.dumps({"confirm_frames": 0}))
    assert options_mod.load().confirm_frames == 1            # never below one

