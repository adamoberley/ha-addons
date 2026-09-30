"""The face library (0.9): per-sample records, the quality gate, outliers (#24).

Run from the repo root: ``python -m pytest local_faces/tests``
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import cv2
import facedb as facedb_mod
import main as main_mod
import numpy as np
import pytest
import quality as quality_mod
from helpers import face_at, make_app, vec

ALEX = vec(1, 0, 0)
ALEX_2 = vec(0.97, 0.2, 0)
ALEX_3 = vec(0.95, 0, 0.25)
SAM = vec(0, 1, 0)
ISO_WITH_OFFSET = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")


def jpeg(value: int = 128) -> bytes:
    _, buf = cv2.imencode(".jpg", np.full((112, 112, 3), value, dtype="uint8"))
    return buf.tobytes()


def reload_db(db):
    return facedb_mod.FaceDB(db.threshold, db.model_id)


# --- per-sample records -----------------------------------------------------

def test_each_sample_keeps_its_own_thumbnail_date_and_quality(db):
    db.add("Alex", ALEX, jpeg(10), quality=0.61)
    db.add("Alex", ALEX_2, jpeg(20), quality=0.33)

    first, second = db.samples("Alex")
    assert first["id"] != second["id"]
    assert base64.b64decode(first["thumb"]) == jpeg(10)
    assert (first["quality"], second["quality"]) == (0.61, 0.33)
    assert first["added"] and second["added"] >= first["added"]


def test_the_file_stays_readable_by_older_versions(db):
    db.add("Alex", ALEX, jpeg(), quality=0.5)
    saved = json.loads(Path(facedb_mod.DB_PATH).read_text())
    person = saved["models"]["sface"]["people"]["Alex"]
    assert len(person["embeddings"]) == 1                 # the pre-0.9 field, untouched
    assert len(person["samples"]) == 1                    # the new one sits beside it


def test_samples_from_before_0_9_load_with_ids_and_no_preview(tmp_path, monkeypatch):
    path = tmp_path / "faces.json"
    path.write_text(json.dumps({"version": 2, "models": {"sface": {"people": {
        "Alex": {"embeddings": [ALEX.tolist(), ALEX_2.tolist()], "thumb": ""}}}}}))
    monkeypatch.setattr(facedb_mod, "DB_PATH", str(path))

    db = facedb_mod.FaceDB(0.5, "sface")

    samples = db.samples("Alex")
    assert len(samples) == 2 and len({s["id"] for s in samples}) == 2
    assert all(s["thumb"] == "" and s["quality"] is None for s in samples)
    assert db.match(ALEX)[0] == "Alex"                     # recognition unaffected


def test_records_survive_a_restart(db):
    db.add("Alex", ALEX, jpeg(), quality=0.5)
    sid = db.samples("Alex")[0]["id"]
    assert reload_db(db).samples("Alex")[0]["id"] == sid


# --- removing and moving one sample -----------------------------------------

def test_removing_one_sample_keeps_the_rest(db):
    db.add("Alex", ALEX, jpeg(10))
    db.add("Alex", SAM, jpeg(20))                          # a stranger saved as Alex
    bad = db.samples("Alex")[1]["id"]

    assert db.delete_sample("Alex", bad) == 1

    np.testing.assert_allclose(db.embeddings_for("Alex"), [ALEX], atol=1e-6)
    assert db.match(SAM)[0] is None                        # no longer matches as Alex
    assert len(reload_db(db).samples("Alex")) == 1


def test_removing_the_last_sample_removes_the_person(db):
    db.add("Alex", ALEX, jpeg())
    assert db.delete_sample("Alex", db.samples("Alex")[0]["id"]) == 0
    assert db.kind("Alex") is None


def test_removing_an_unknown_sample_says_so(db):
    db.add("Alex", ALEX, jpeg())
    assert db.delete_sample("Alex", "nope") is None
    assert db.delete_sample("Nobody", "nope") is None


def test_moving_a_sample_to_the_right_person(db):
    db.add("Alex", ALEX, jpeg(10))
    db.add("Alex", SAM, jpeg(20))
    db.add("Sam", vec(0.1, 1, 0), jpeg(30))
    sid = db.samples("Alex")[1]["id"]

    ok, _ = db.move_sample("Alex", sid, "Sam")

    assert ok
    assert len(db.samples("Alex")) == 1 and len(db.samples("Sam")) == 2
    assert sid in {s["id"] for s in db.samples("Sam")}      # record travels with it
    assert db.match(SAM)[0] == "Sam"


def test_moving_to_a_new_name_creates_that_person(db):
    db.add("Alex", ALEX, jpeg())
    db.add("Alex", SAM, jpeg())
    ok, _ = db.move_sample("Alex", db.samples("Alex")[1]["id"], "Sam")
    assert ok and db.kind("Sam") == "person"


def test_a_sample_cannot_be_moved_into_the_ignore_list(db):
    db.add("Alex", ALEX, jpeg())
    db.add("Poster", SAM, jpeg(), ignored=True)
    ok, message = db.move_sample("Alex", db.samples("Alex")[0]["id"], "Poster")
    assert not ok and "ignored" in message
    assert len(db.samples("Alex")) == 1


def test_the_cover_picture_falls_back_when_its_sample_is_removed(db):
    db.add("Alex", ALEX, jpeg(10))
    db.add("Alex", ALEX_2, jpeg(200))                      # newest = cover
    db.delete_sample("Alex", db.samples("Alex")[1]["id"])
    (person,) = db.people()
    assert base64.b64decode(person["thumb"]) == jpeg(10)


# --- outliers -----------------------------------------------------------------

def test_a_sample_that_does_not_match_the_others_is_flagged(db):
    for v in (ALEX, ALEX_2, ALEX_3):
        db.add("Alex", v, jpeg())
    db.add("Alex", SAM, jpeg())                             # the bad one

    flags = [s["outlier"] for s in db.samples("Alex")]

    assert flags == [False, False, False, True]


def test_outliers_need_at_least_three_samples_to_judge(db):
    db.add("Alex", ALEX, jpeg())
    db.add("Alex", SAM, jpeg())
    assert [s["outlier"] for s in db.samples("Alex")] == [False, False]
    assert all(s["similarity"] is None for s in db.samples("Alex"))


# --- the quality gate at enrollment ----------------------------------------

def _stage(app, score):
    app.quality.score = score
    staged = app._stage(np.zeros((120, 160, 3), dtype="uint8"))
    assert staged["ok"]
    return staged


def test_a_poor_capture_is_refused_until_you_insist(db, log):
    app, _ = make_app(db, log, [face_at(ALEX)])
    staged = _stage(app, 0.12)
    assert staged["quality_label"] == "poor"

    refused = app.commit_enrollment(staged["token"], "Alex")
    assert not refused["ok"] and refused["needs_confirm"]
    assert db.kind("Alex") is None

    saved = app.commit_enrollment(staged["token"], "Alex", force=True)   # same capture
    assert saved["ok"]
    assert db.samples("Alex")[0]["quality"] == 0.12


def test_fair_and_good_captures_save_normally(db, log):
    app, _ = make_app(db, log, [face_at(ALEX)])
    for score in (0.3, 0.6):
        assert app.commit_enrollment(_stage(app, score)["token"], "Alex")["ok"]
    assert [s["quality"] for s in db.samples("Alex")] == [0.3, 0.6]


def test_without_the_quality_model_nothing_is_refused(db, log):
    app, _ = make_app(db, log, [face_at(ALEX)])
    assert app.commit_enrollment(_stage(app, None)["token"], "Alex")["ok"]


def test_naming_a_poor_sighting_is_refused_until_you_insist(db, log):
    app, _ = make_app(db, log, [face_at(SAM)])
    app.tick()
    sighting = log.recent()[0]
    app.quality.score = 0.1

    assert app.name_sighting(sighting["id"], "Sam")["needs_confirm"]
    assert app.name_sighting(sighting["id"], "Sam", force=True)["ok"]


# --- the app's library actions ------------------------------------------------

def test_removing_a_persons_last_sample_takes_them_out_of_ha(db, log):
    db.add("Alex", ALEX, jpeg())
    app, _ = make_app(db, log)
    sid = app.person_samples("Alex")["samples"][0]["id"]

    result = app.delete_sample("Alex", sid)

    assert result["ok"] and result["left"] == 0
    assert "alex" in app.mqtt.cleared
    assert app.mqtt.people == {}


def test_moving_a_sample_to_someone_new_gives_them_an_entity(db, log):
    db.add("Alex", ALEX, jpeg())
    db.add("Alex", SAM, jpeg())
    app, _ = make_app(db, log)
    sid = app.person_samples("Alex")["samples"][1]["id"]

    assert app.move_sample("Alex", sid, "Sam")["ok"]

    assert app.mqtt.people == {"Alex": "alex", "Sam": "sam"}


def test_the_people_list_counts_samples_that_look_off(db, log):
    for v in (ALEX, ALEX_2, ALEX_3):
        db.add("Alex", v, jpeg(), quality=0.6)
    db.add("Alex", SAM, jpeg(), quality=0.6)                # outlier
    db.add("Alex", ALEX, jpeg(), quality=0.1)               # blurry
    app, _ = make_app(db, log)
    (alex,) = app.people_view()
    assert alex["flagged"] == 2


def test_sample_listing_labels_quality(db, log):
    db.add("Alex", ALEX, jpeg(), quality=0.1)
    app, _ = make_app(db, log)
    assert app.person_samples("Alex")["samples"][0]["quality_label"] == "poor"
    assert not app.person_samples("Nobody")["ok"]


# --- timestamps and names HA can use directly -------------------------------

def test_presence_attributes_carry_the_plain_name_and_a_utc_offset(db, log):
    db.add("Alex Smith", ALEX, jpeg())
    app, _ = make_app(db, log, [face_at(ALEX)])
    app.tick()
    _present, attrs = app.mqtt.person_state("alex_smith")
    assert attrs["person"] == "Alex Smith"
    assert ISO_WITH_OFFSET.match(attrs["last_seen"]), attrs["last_seen"]


def test_event_and_sensor_timestamps_carry_a_utc_offset(db, log):
    db.add("Alex", ALEX, jpeg())
    app, _ = make_app(db, log, [face_at(ALEX)])
    app.tick()
    assert ISO_WITH_OFFSET.match(app.events.sent[0]["timestamp"])
    assert ISO_WITH_OFFSET.match(app.mqtt.published[0][2]["timestamp"])


def test_iso_helper_round_trips():
    import datetime
    stamp = main_mod._iso(1_790_797_500)
    assert datetime.datetime.fromisoformat(stamp).timestamp() == 1_790_797_500


# --- the quality model itself ---------------------------------------------------

def test_quality_labels():
    assert quality_mod.label(None) is None
    assert quality_mod.label(0.1) == "poor"
    assert quality_mod.label(0.3) == "fair"
    assert quality_mod.label(0.6) == "good"


def test_the_scorer_without_a_model_scores_nothing():
    scorer = quality_mod.QualityScorer(None)
    assert not scorer.available and scorer.score_thumb(jpeg()) is None


MODEL = os.environ.get("LF_QUALITY_MODEL", "/tmp/claude-501/lf-models/ediffiqa_tiny_jun2024.onnx")


@pytest.mark.skipif(not os.path.exists(MODEL), reason="quality model not downloaded")
def test_the_real_model_scores_a_blank_crop_as_useless():
    scorer = quality_mod.QualityScorer(MODEL)
    score = scorer.score_thumb(jpeg())
    assert score is not None and quality_mod.label(score) == "poor"
