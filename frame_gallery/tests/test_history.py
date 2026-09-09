"""The no-repeat window and the hidden list.

Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import gallery as gallery_mod
import state as state_mod
from sources.base import Artwork


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", str(tmp_path / "gallery-state.json"))
    return state_mod.History(cap=3)


def reopen(cap: int = 3) -> state_mod.History:
    return state_mod.History(cap=cap)


# --- the no-repeat window -------------------------------------------------

def test_recent_pieces_are_skipped_until_they_fall_out_of_the_window(store):
    for key in ("a:1", "a:2", "a:3"):
        store.add(key)
    assert store.seen("a:1")

    store.add("a:4")                     # cap is 3, so a:1 rolls off
    assert not store.seen("a:1")
    assert store.seen("a:4")


def test_a_zero_cap_disables_the_window(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", str(tmp_path / "s.json"))
    history = state_mod.History(cap=0)
    history.add("a:1")
    assert not history.seen("a:1")


def test_re_showing_a_piece_moves_it_to_the_front(store):
    for key in ("a:1", "a:2", "a:3"):
        store.add(key)
    store.add("a:1")                     # explicit re-show
    store.add("a:4")                     # a:2 is now the oldest
    assert not store.seen("a:2")
    assert store.seen("a:1")


# --- the hidden list ------------------------------------------------------

def test_hiding_a_piece_sticks_across_a_restart(store):
    assert store.hide("artic:42")
    assert store.is_hidden("artic:42")
    assert reopen().is_hidden("artic:42")


def test_hiding_the_same_piece_twice_reports_it_was_already_hidden(store):
    assert store.hide("artic:42")
    assert not store.hide("artic:42")
    assert len(store.hidden) == 1


def test_hiding_nothing_is_refused(store):
    assert not store.hide("")
    assert not store.is_hidden("")


def test_unhide_all_brings_them_back(store):
    store.hide("artic:1")
    store.hide("artic:2")
    assert store.unhide_all() == 2
    assert store.hidden == set()
    assert reopen().hidden == set()
    assert store.unhide_all() == 0        # idempotent


def test_hidden_and_recent_share_one_file_without_clobbering(store):
    store.add("artic:1")
    store.hide("artic:2")
    store.add("artic:3")

    on_disk = json.loads(Path(state_mod.STATE_PATH).read_text())
    assert on_disk["recent"] == ["artic:1", "artic:3"]
    assert on_disk["hidden"] == ["artic:2"]

    revived = reopen()
    assert revived.recent == ["artic:1", "artic:3"]
    assert revived.hidden == {"artic:2"}


def test_a_pre_hidden_state_file_still_loads(tmp_path, monkeypatch):
    """0.6.x wrote {"recent": [...]} with no hidden key at all."""
    path = tmp_path / "gallery-state.json"
    path.write_text(json.dumps({"recent": ["artic:9"]}))
    monkeypatch.setattr(state_mod, "STATE_PATH", str(path))

    history = state_mod.History(cap=3)
    assert history.recent == ["artic:9"]
    assert history.hidden == set()


def test_a_corrupt_state_file_starts_fresh(tmp_path, monkeypatch):
    path = tmp_path / "gallery-state.json"
    path.write_text("{not json")
    monkeypatch.setattr(state_mod, "STATE_PATH", str(path))

    history = state_mod.History(cap=3)
    assert (history.recent, history.hidden) == ([], set())


# --- the picker honours both ----------------------------------------------

class Opts:
    public_domain_only = True
    exclude_keywords = ()
    query = ""


class FakeSource:
    name = "fake"

    def __init__(self, works):
        self.works = works

    def candidates(self, opts, count=100):
        return list(self.works)


def art(n: int) -> Artwork:
    return Artwork(source="fake", id=str(n), title=f"Piece {n}", artist="Someone",
                   image_url=f"https://example.invalid/{n}.jpg")


def test_pick_skips_hidden_pieces(store, monkeypatch):
    monkeypatch.setattr(gallery_mod, "download", lambda url: b"jpeg-bytes")
    works = [art(1), art(2)]
    store.hide("fake:1")

    for _ in range(6):                   # the picker shuffles; never pick the hidden one
        chosen, data = gallery_mod.pick(Opts(), store, [FakeSource(works)])
        assert (chosen.key, data) == ("fake:2", b"jpeg-bytes")


def test_pick_gives_up_when_everything_is_hidden(store, monkeypatch):
    monkeypatch.setattr(gallery_mod, "download", lambda url: b"jpeg-bytes")
    store.hide("fake:1")

    chosen, data = gallery_mod.pick(Opts(), store, [FakeSource([art(1)])], tries=1)
    assert (chosen, data) == (None, None)


def test_pick_skips_recently_shown_pieces_too(store, monkeypatch):
    monkeypatch.setattr(gallery_mod, "download", lambda url: b"jpeg-bytes")
    store.add("fake:1")

    chosen, _ = gallery_mod.pick(Opts(), store, [FakeSource([art(1), art(2)])])
    assert chosen.key == "fake:2"
