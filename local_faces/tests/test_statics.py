"""Spotting the faces that never move.

Run from the repo root: ``python -m pytest local_faces/tests``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import statics as statics_mod


def vec(*values: float) -> np.ndarray:
    arr = np.array(values, dtype="float32")
    return arr / np.linalg.norm(arr)


POSTER = vec(0, 1, 0)
POSTER_ALT = vec(0.05, 0.99, 0)      # same face, next frame
PASSERBY = vec(1, 0, 0)
BOX = (100, 100, 60, 60)


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    monkeypatch.setattr(statics_mod, "DISMISSED_PATH", str(tmp_path / "dismissed.json"))
    return statics_mod.StaticWatcher(threshold=0.5, model="sface",
                                     min_hits=5, min_span_s=600)


def sit(watcher, seconds: float, hits: int, box=BOX, camera="Hallway",
        embedding=POSTER, start: float = 1_000.0):
    """Observe the same face in the same place `hits` times over `seconds`."""
    step = seconds / max(1, hits - 1)
    for i in range(hits):
        watcher.observe(camera, box, embedding, thumb=b"jpeg", now=start + i * step)


# --- the geometry ---------------------------------------------------------

def test_iou_of_identical_boxes_is_one():
    assert statics_mod._iou(BOX, BOX) == pytest.approx(1.0)


def test_iou_of_disjoint_boxes_is_zero():
    assert statics_mod._iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_a_nudged_box_is_still_the_same_spot():
    assert statics_mod._iou(BOX, (103, 102, 60, 60)) > statics_mod.MIN_IOU


def test_describe_span_reads_like_a_human_wrote_it():
    assert statics_mod.describe_span(45) == "0m"
    assert statics_mod.describe_span(45 * 60) == "45m"
    assert statics_mod.describe_span(3 * 3600 + 12 * 60) == "3h 12m"


# --- suggesting -----------------------------------------------------------

def test_a_face_that_sits_still_long_enough_is_suggested(watcher):
    sit(watcher, seconds=1200, hits=10)

    suggestions = watcher.suggestions()
    assert len(suggestions) == 1
    assert suggestions[0]["camera"] == "Hallway"
    assert suggestions[0]["hits"] == 10
    assert suggestions[0]["span"] == "20m"
    assert suggestions[0]["thumb"]


def test_a_brief_visit_is_not_suggested(watcher):
    sit(watcher, seconds=30, hits=10)          # ten sightings, but only 30s
    assert watcher.suggestions() == []


def test_a_rare_sighting_is_not_suggested(watcher):
    sit(watcher, seconds=1200, hits=3)         # long span, too few hits
    assert watcher.suggestions() == []


def test_a_face_that_moves_is_not_one_candidate(watcher):
    for i in range(10):
        watcher.observe("Hallway", (100 + i * 40, 100, 60, 60), POSTER,
                        now=1000 + i * 120)
    assert watcher.suggestions() == []         # ten separate one-hit candidates


def test_two_pictures_on_one_camera_are_tracked_apart(watcher):
    sit(watcher, seconds=1200, hits=10, box=(10, 10, 50, 50), embedding=POSTER)
    sit(watcher, seconds=1200, hits=10, box=(300, 10, 50, 50), embedding=PASSERBY)
    assert len(watcher.suggestions()) == 2


def test_the_same_picture_on_two_cameras_is_two_candidates(watcher):
    sit(watcher, seconds=1200, hits=10, camera="Hallway")
    sit(watcher, seconds=1200, hits=10, camera="Kitchen")
    assert {s["camera"] for s in watcher.suggestions()} == {"Hallway", "Kitchen"}


def test_a_slightly_different_frame_of_the_same_face_still_counts(watcher):
    for i in range(10):
        emb = POSTER if i % 2 else POSTER_ALT
        watcher.observe("Hallway", (100 + (i % 2), 100, 60, 60), emb, now=1000 + i * 120)
    assert len(watcher.suggestions()) == 1


def test_suggestions_are_ordered_by_how_long_they_have_been_there(watcher):
    sit(watcher, seconds=700, hits=6, box=(10, 10, 50, 50), embedding=POSTER)
    sit(watcher, seconds=3600, hits=6, box=(300, 10, 50, 50), embedding=PASSERBY)
    spans = [s["span_s"] for s in watcher.suggestions()]
    assert spans == sorted(spans, reverse=True)


# --- acting on them -------------------------------------------------------

def test_dismissing_stops_it_being_suggested_again(watcher):
    sit(watcher, seconds=1200, hits=10)
    cid = watcher.suggestions()[0]["id"]

    assert watcher.dismiss(cid)
    assert watcher.suggestions() == []

    sit(watcher, seconds=1200, hits=10, start=100_000)     # it keeps being seen
    assert watcher.suggestions() == []                     # ...and stays quiet


def test_a_dismissal_survives_a_restart(watcher, tmp_path):
    sit(watcher, seconds=1200, hits=10)
    watcher.dismiss(watcher.suggestions()[0]["id"])

    revived = statics_mod.StaticWatcher(threshold=0.5, model="sface",
                                        min_hits=5, min_span_s=600)
    sit(revived, seconds=1200, hits=10)
    assert revived.suggestions() == []

    stored = json.loads(Path(statics_mod.DISMISSED_PATH).read_text())
    assert stored["model"] == "sface"
    assert len(stored["embeddings"]) == 1


def test_dismissals_from_another_model_are_ignored(watcher):
    sit(watcher, seconds=1200, hits=10)
    watcher.dismiss(watcher.suggestions()[0]["id"])

    other = statics_mod.StaticWatcher(threshold=0.5, model="mobilefacenet_w600k",
                                      min_hits=5, min_span_s=600)
    sit(other, seconds=1200, hits=10)
    assert len(other.suggestions()) == 1       # embeddings aren't comparable


def test_dropping_a_candidate_forgets_it_without_dismissing(watcher):
    sit(watcher, seconds=1200, hits=10)
    cid = watcher.suggestions()[0]["id"]

    watcher.drop(cid)
    assert watcher.suggestions() == []

    sit(watcher, seconds=1200, hits=10, start=100_000)
    assert len(watcher.suggestions()) == 1     # not remembered as "a person"


def test_dismissing_something_gone_reports_false(watcher):
    assert not watcher.dismiss("nope")


def test_a_corrupt_dismissal_file_is_survivable(tmp_path, monkeypatch):
    path = tmp_path / "dismissed.json"
    path.write_text("{not json")
    monkeypatch.setattr(statics_mod, "DISMISSED_PATH", str(path))
    assert statics_mod.StaticWatcher(threshold=0.5, model="sface").suggestions() == []


# --- staying bounded ------------------------------------------------------

def test_a_face_not_seen_for_hours_is_forgotten(watcher):
    sit(watcher, seconds=1200, hits=10)
    assert len(watcher.suggestions()) == 1

    # A new face, hours later: the prune on observe drops the stale candidate.
    watcher.observe("Hallway", (10, 10, 20, 20), PASSERBY,
                    now=1_000 + 1200 + statics_mod.FORGET_AFTER_S + 1)
    assert watcher.suggestions() == []


def test_the_candidate_list_stays_bounded(watcher):
    for i in range(statics_mod.MAX_CANDIDATES + 25):
        watcher.observe("Hallway", (i * 100, 0, 20, 20), vec(1, i + 1, 0), now=1_000 + i)
    assert len(watcher._candidates) <= statics_mod.MAX_CANDIDATES
