"""Per-person presence entities, and the suggestions that feed the ignore list.

Run from the repo root: ``python -m pytest local_faces/tests``
"""

from __future__ import annotations

import time

import statics as statics_mod
from helpers import FakeEngine, face_at, make_app, vec
from mqtt_pub import person_slugs

ALEX = vec(1, 0, 0)
ALEX_ALT = vec(0.98, 0.2, 0)
SAM = vec(0, 1, 0)
STRANGER = vec(0, 0, 1)


# --- entity naming --------------------------------------------------------

def test_person_slugs_are_stable_and_readable():
    assert person_slugs(["Alex", "Sam O'Neill"]) == {"Alex": "alex", "Sam O'Neill": "sam_o_neill"}


def test_person_slugs_do_not_collide():
    slugs = person_slugs(["Alex B", "Alex-B", "Alex.B"])
    assert sorted(slugs.values()) == ["alex_b", "alex_b_2", "alex_b_3"]
    assert person_slugs(["Alex-B", "Alex.B", "Alex B"]) == slugs   # order-independent


def test_person_slugs_never_produce_an_empty_id():
    assert person_slugs(["!!!"]) == {"!!!": "person"}


# --- presence -------------------------------------------------------------

def test_a_recognized_person_turns_their_sensor_on(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)])

    app.tick()

    present, attrs = app.mqtt.person_state("alex")
    assert present is True
    assert attrs["camera"] == "Arcade"
    assert attrs["last_seen"] and attrs["score"] > 0.9


def test_presence_turns_off_after_the_timeout(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)], presence_timeout_seconds=60)
    app.tick()
    assert app.mqtt.person_state("alex")[0] is True

    app._seen["Alex"]["ts"] = time.time() - 61     # last seen just over a minute ago
    app.engine = FakeEngine([])
    app.tick()

    present, attrs = app.mqtt.person_state("alex")
    assert present is False
    assert attrs["last_seen"]                      # the timestamp is kept


def test_presence_survives_a_gap_shorter_than_the_timeout(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)], presence_timeout_seconds=300)
    app.tick()
    app.engine = FakeEngine([])                    # steps out of frame

    for _ in range(5):
        app.tick()

    assert app.mqtt.person_state("alex")[0] is True


def test_presence_expires_even_with_no_cameras_configured(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [], cameras=(), presence_timeout_seconds=30)
    app._seen["Alex"] = {"ts": time.time() - 31, "camera": "Arcade",
                         "score": 0.9, "present": True}

    app.tick()

    assert app.mqtt.person_state("alex")[0] is False


def test_only_the_recognized_person_is_marked_present(db, log):
    db.add("Alex", ALEX, b"")
    db.add("Sam", SAM, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)])

    app.tick()

    assert app.mqtt.person_state("alex")[0] is True
    assert app.mqtt.person_state("sam")[0] is False      # announced, never seen


def test_an_ignored_face_never_marks_anyone_present(db, log):
    db.add("Poster", SAM, b"", ignored=True)
    app, _ = make_app(db, log, [face_at(SAM)])

    app.tick()

    assert app.mqtt.person_state("poster") is None       # not a person entity at all
    assert app._seen == {}


def test_enrolling_someone_creates_their_entity_without_a_restart(db, log):
    app, _ = make_app(db, log, [face_at(STRANGER)])
    assert app.mqtt.people == {}

    app.tick()                                     # logged as unknown
    sighting = log.recent()[0]
    assert app.name_sighting(sighting["id"], "Sam")["ok"]

    assert app.mqtt.people == {"Sam": "sam"}


def test_removing_someone_deletes_their_entity(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)])
    app.tick()

    assert app.delete_person("Alex")["ok"]

    assert "alex" in app.mqtt.cleared
    assert app.mqtt.people == {}
    assert "Alex" not in app._seen


def test_person_sensors_can_be_switched_off(db, log):
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)], person_sensors=False)

    app.tick()

    assert app.mqtt.person_states == []
    assert app.mqtt.published                      # the camera sensor still publishes


def test_the_dashboard_shows_when_each_person_was_last_seen(db, log):
    db.add("Alex", ALEX, b"")
    db.add("Sam", SAM, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)])
    app.tick()

    view = {p["name"]: p for p in app.people_view()}
    assert view["Alex"]["present"] is True
    assert view["Alex"]["last_camera"] == "Arcade"
    assert view["Alex"]["last_seen"] > 0
    assert view["Sam"]["present"] is False and view["Sam"]["last_seen"] is None


def test_status_counts_people_ignored_faces_and_suggestions(db, log):
    db.add("Alex", ALEX, b"")
    db.add("Poster", SAM, b"", ignored=True)
    app, _ = make_app(db, log, [])

    status = app.public_status()

    assert (status["people"], status["ignored"], status["suggestions"]) == (1, 1, 0)


# --- suggestions, end to end through the App ------------------------------

def watcher(min_hits=3, min_span_s=60):
    return statics_mod.StaticWatcher(threshold=0.5, model="sface",
                                     min_hits=min_hits, min_span_s=min_span_s)


def test_an_unknown_face_that_sits_still_becomes_a_suggestion(db, log, dismissals):
    app, _ = make_app(db, log, [face_at(STRANGER)], statics=watcher())

    for _ in range(4):                             # four ticks, same spot
        app._cooldown.clear()
        app.tick()
    # The watcher needs a span, not just hits: age the candidate.
    cand = next(iter(app.statics._candidates.values()))
    cand.first_ts -= 3600

    suggestions = app.suggestions()
    assert len(suggestions) == 1
    assert suggestions[0]["camera"] == "Arcade"
    assert app.public_status()["suggestions"] == 1


def test_accepting_a_suggestion_ignores_the_face_and_clears_the_log(db, log, dismissals):
    app, _ = make_app(db, log, [face_at(STRANGER)], statics=watcher())
    for _ in range(4):
        app._cooldown.clear()
        app.tick()
    next(iter(app.statics._candidates.values())).first_ts -= 3600
    suggestion = app.suggestions()[0]

    result = app.ignore_suggestion(suggestion["id"], "Hallway poster")

    assert result["ok"]
    assert [f["name"] for f in db.ignored_faces()] == ["Hallway poster"]
    assert log.recent() == []                      # its past sightings went too
    assert app.suggestions() == []

    app._cooldown.clear()
    app.tick()
    assert log.recent() == []                      # and it stays out


def test_dismissing_a_suggestion_keeps_the_face_and_stops_asking(db, log, dismissals):
    app, _ = make_app(db, log, [face_at(STRANGER)], statics=watcher())
    for _ in range(4):
        app._cooldown.clear()
        app.tick()
    next(iter(app.statics._candidates.values())).first_ts -= 3600
    suggestion = app.suggestions()[0]

    result = app.dismiss_suggestion(suggestion["id"])

    assert result["ok"]
    assert db.ignored_faces() == []
    assert app.suggestions() == []
    assert dismissals.exists()


def test_acting_on_a_stale_suggestion_says_so(db, log, dismissals):
    app, _ = make_app(db, log, [], statics=watcher())
    assert not app.ignore_suggestion("gone")["ok"]
    assert not app.dismiss_suggestion("gone")["ok"]


def test_a_known_face_is_never_offered_as_a_suggestion(db, log, dismissals):
    """A framed photo of an enrolled person can't be ignored safely."""
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)], statics=watcher())

    for _ in range(6):
        app._cooldown.clear()
        app.tick()

    assert app.statics._candidates == {}
    assert app.suggestions() == []


def test_ignoring_a_face_that_matches_an_enrolled_person_is_refused(db, log, dismissals):
    """The same hazard by hand: it would shadow the real person."""
    db.add("Alex", ALEX, b"")
    app, _ = make_app(db, log, [face_at(ALEX_ALT)])
    app.tick()
    sighting = log.recent()[0]

    result = app.ignore_sighting(sighting["id"], "Photo of Alex")

    assert not result["ok"]
    assert "matches Alex" in result["message"]
    assert db.ignored_faces() == []
