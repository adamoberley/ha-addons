"""The ignore list: faces that are matched and then deliberately dropped.

Run from the repo root: ``python -m pytest local_faces/tests``

Covers github issue #13 - the faces printed on an arcade cabinet are real faces
and the detector is right to find them, so they need to be recognized and then
skipped, not detected less.
"""

from __future__ import annotations

from pathlib import Path

import facedb as facedb_mod
import numpy as np
from helpers import FakeEngine, face_at, make_app, vec

ALEX = vec(1, 0, 0)
ALEX_ALT = vec(0.98, 0.2, 0)      # same person, another angle
CABINET = vec(0, 1, 0)            # a face painted on the arcade machine
CABINET_ALT = vec(0.05, 0.99, 0)
POSTER = vec(0, 0, 1)             # a different not-a-person face


# --- the face db ----------------------------------------------------------

def test_ignored_entry_matches_but_is_flagged(db):
    db.add("Alex", ALEX, b"")
    db.add("Arcade cabinet", CABINET, b"", ignored=True)

    name, score = db.match(CABINET_ALT)
    assert name == "Arcade cabinet"
    assert score > 0.9
    assert db.is_ignored(name)

    name, _ = db.match(ALEX_ALT)
    assert name == "Alex"
    assert not db.is_ignored(name)


def test_ignored_faces_are_kept_out_of_the_people_list(db):
    db.add("Alex", ALEX, b"")
    db.add("Arcade cabinet", CABINET, b"", ignored=True)

    assert [p["name"] for p in db.people()] == ["Alex"]
    assert [f["name"] for f in db.ignored_faces()] == ["Arcade cabinet"]
    assert db.kind("Alex") == "person"
    assert db.kind("Arcade cabinet") == "ignored"
    assert db.kind("Nobody") is None


def test_the_category_holds_several_patterns(db):
    """"This category can hold more than one pattern inside" (issue #13)."""
    db.add("Arcade cabinet", CABINET, b"", ignored=True)
    db.add("Arcade cabinet", CABINET_ALT, b"", ignored=True)   # second sample
    db.add("Hallway poster", POSTER, b"", ignored=True)        # second entry

    faces = {f["name"]: f["samples"] for f in db.ignored_faces()}
    assert faces == {"Arcade cabinet": 2, "Hallway poster": 1}
    assert db.is_ignored(db.match(POSTER)[0])


def test_an_existing_name_keeps_its_bucket(db):
    db.add("Alex", ALEX, b"")
    db.add("Alex", ALEX_ALT, b"", ignored=True)  # would silently ignore a person
    assert db.kind("Alex") == "person"
    assert not db.is_ignored("Alex")


def test_ignored_state_survives_a_reload(db, tmp_path, monkeypatch):
    db.add("Alex", ALEX, b"")
    db.add("Arcade cabinet", CABINET, b"", ignored=True)

    monkeypatch.setattr(facedb_mod, "DB_PATH", db_path := facedb_mod.DB_PATH)
    reloaded = facedb_mod.FaceDB(threshold=0.5, model_id="sface")
    assert Path(db_path).exists()
    assert [f["name"] for f in reloaded.ignored_faces()] == ["Arcade cabinet"]
    assert [p["name"] for p in reloaded.people()] == ["Alex"]


def test_unignoring_removes_the_entry(db):
    db.add("Arcade cabinet", CABINET, b"", ignored=True)
    assert db.delete("Arcade cabinet")
    assert db.ignored_faces() == []
    assert db.match(CABINET)[0] is None


def test_a_v1_database_still_loads(tmp_path, monkeypatch):
    """The pre-namespace layout has no ignored flag anywhere."""
    path = tmp_path / "faces.json"
    path.write_text('{"people": {"Alex": {"embeddings": [[1.0, 0.0, 0.0]], "thumb": ""}}}')
    monkeypatch.setattr(facedb_mod, "DB_PATH", str(path))

    db = facedb_mod.FaceDB(threshold=0.5, model_id="sface")
    assert [p["name"] for p in db.people()] == ["Alex"]
    assert db.ignored_faces() == []


# --- clearing the sightings the face already left -------------------------

def test_purge_matching_clears_past_sightings_of_that_face(log):
    log.add("Unknown", 0.2, True, b"", CABINET, "sface", camera="Arcade")
    log.add("Unknown", 0.2, True, b"", CABINET_ALT, "sface", camera="Arcade")
    log.add("Alex", 0.9, False, b"", ALEX, "sface", camera="Door")

    dropped = log.purge_matching(np.vstack([CABINET]), threshold=0.5, model="sface")

    assert dropped == 2
    assert [e["name"] for e in log.recent()] == ["Alex"]


def test_purge_matching_ignores_other_models(log):
    log.add("Unknown", 0.2, True, b"", CABINET, "mobilefacenet_w600k", camera="Arcade")
    assert log.purge_matching(np.vstack([CABINET]), threshold=0.5, model="sface") == 0
    assert len(log.recent()) == 1


def test_purge_matching_ignores_other_dimensions(log):
    log.add("Unknown", 0.2, True, b"", vec(1, 0), "sface", camera="Arcade")
    assert log.purge_matching(np.vstack([CABINET]), threshold=0.5, model="sface") == 0


# --- the pipeline: nothing about an ignored face escapes -------------------

def test_an_ignored_face_produces_no_sighting_sensor_or_notification(db, log):
    db.add("Arcade cabinet", CABINET, b"", ignored=True)
    app, _ = make_app(db, log, [face_at(CABINET_ALT)])

    app.tick()

    assert log.recent() == []                        # the reported symptom
    assert app.notifier.sent == []
    assert app.mqtt.published == [("arcade", "none", app.mqtt.published[0][2])]
    status = app.public_status()["cameras"][0]
    assert (status["state"], status["faces"], status["ignored"]) == ("idle", 0, 1)


def test_a_real_person_is_unaffected_by_a_nearby_ignored_face(db, log):
    db.add("Alex", ALEX, b"")
    db.add("Arcade cabinet", CABINET, b"", ignored=True)
    app, _ = make_app(db, log, [face_at(CABINET_ALT, x=10), face_at(ALEX_ALT, x=80)])

    app.tick()

    assert [e["name"] for e in log.recent()] == ["Alex"]
    assert app.notifier.sent == ["Alex recognized at Arcade (98%)"]
    slug, state, attrs = app.mqtt.published[0]
    assert (slug, state) == ("arcade", "Alex")
    assert (attrs["faces"], attrs["ignored_faces"]) == (1, 1)
    status = app.public_status()["cameras"][0]
    assert (status["state"], status["faces"], status["ignored"]) == ("known", 1, 1)


def test_an_unknown_face_still_reports_unknown(db, log):
    db.add("Arcade cabinet", CABINET, b"", ignored=True)
    app, _ = make_app(db, log, [face_at(CABINET, x=10), face_at(POSTER, x=80)])

    app.tick()

    assert [e["unknown"] for e in log.recent()] == [True]
    assert app.notifier.sent == ["Unknown person at Arcade"]
    assert app.mqtt.published[0][1] == "unknown"


def test_ignoring_a_sighting_also_clears_the_log(db, log):
    """The end-to-end move from the dashboard: Ignore on a logged sighting."""
    app, _ = make_app(db, log, [face_at(CABINET)])
    app.tick()                                    # logs it as unknown
    sighting = log.recent()[0]

    result = app.ignore_sighting(sighting["id"], "Arcade cabinet")

    assert result["ok"]
    assert "Ignoring Arcade cabinet" in result["message"]
    assert log.recent() == []                     # its past sightings are gone
    assert [f["name"] for f in db.ignored_faces()] == ["Arcade cabinet"]

    app._cooldown.clear()
    app.tick()                                    # and it stays out from now on
    assert log.recent() == []


def test_ignoring_without_a_label_names_it_for_you(db, log):
    app, _ = make_app(db, log, [face_at(CABINET)])
    app.tick()
    first = log.recent()[0]
    assert app.ignore_sighting(first["id"], "")["name"] == "Ignored face"

    app._cooldown.clear()
    app.engine = FakeEngine([face_at(POSTER)])
    app.tick()
    second = log.recent()[0]
    assert app.ignore_sighting(second["id"], "")["name"] == "Ignored face 2"


def test_ignoring_refuses_to_shadow_an_enrolled_person(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(CABINET)])
    app.tick()
    sighting = log.recent()[0]

    result = app.ignore_sighting(sighting["id"], "Alex")

    assert not result["ok"]
    assert "enrolled person" in result["message"]
    assert db.kind("Alex") == "person"


def test_ignoring_a_capture_uses_the_staged_face(db, log):
    app, _ = make_app(db, log, [face_at(CABINET)])
    staged = app.stage_from_frame("arcade")
    assert staged["ok"]

    result = app.ignore_capture(staged["token"], "Arcade cabinet")

    assert result["ok"]
    assert [f["name"] for f in db.ignored_faces()] == ["Arcade cabinet"]
    assert not app.ignore_capture(staged["token"], "x")["ok"]   # token is single-use


def test_unignore_reports_an_unknown_name(db, log):
    app, _ = make_app(db, log, [])
    assert not app.unignore("Nothing")["ok"]
    db.add("Arcade cabinet", CABINET, b"", ignored=True)
    assert app.unignore("Arcade cabinet")["ok"]
    assert db.ignored_faces() == []
