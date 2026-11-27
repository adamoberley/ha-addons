"""Picking the next piece when the source misbehaves.

The two dead ends that took the gallery off the air in November 2026: a
damaged image on reframed.gallery's CDN (a 4K original cut off 27 bytes short
of its end marker) and a collection smaller than the no-repeat window. No
network is touched.

Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import gallery as gallery_mod
import state as state_mod
from sources.base import Artwork

GOOD, BAD = b"good-image", b"damaged-image"


def art(n: int) -> Artwork:
    return Artwork(source="t", id=str(n), title=f"Piece {n}", artist="A",
                   image_url=f"https://img/{n}.jpg")


class FakeSource:
    name = "t"

    def __init__(self, arts):
        self.arts = arts

    def candidates(self, opts, count=100):
        return list(self.arts)


OPTS = SimpleNamespace(public_domain_only=True, exclude_keywords=())


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", str(tmp_path / "gallery-state.json"))
    return state_mod.History(cap=100)


@pytest.fixture
def images(monkeypatch):
    """url -> bytes the fake CDN serves; BAD doesn't decode. Counts downloads."""
    served: dict[str, bytes] = {}
    calls: list[str] = []

    def download(url):
        calls.append(url)
        return served.get(url)

    monkeypatch.setattr(gallery_mod, "download", download)
    monkeypatch.setattr(gallery_mod, "_decodes", lambda data: data == GOOD)
    monkeypatch.setattr(gallery_mod, "_broken", set())
    return SimpleNamespace(served=served, calls=calls)


def test_a_damaged_image_is_skipped_for_a_good_one(history, images):
    images.served.update({"https://img/1.jpg": BAD, "https://img/2.jpg": GOOD})
    chosen, data = gallery_mod.pick(OPTS, history, [FakeSource([art(1), art(2)])])
    assert chosen.key == "t:2" and data == GOOD


def test_a_damaged_image_is_not_downloaded_again(history, images):
    images.served["https://img/1.jpg"] = BAD
    src = FakeSource([art(1)])
    assert gallery_mod.pick(OPTS, history, [src]) == (None, None)
    assert images.calls == ["https://img/1.jpg"]       # once, not once per try
    gallery_mod.pick(OPTS, history, [src])
    assert images.calls == ["https://img/1.jpg"]       # nor on the next cycle


def test_an_exhausted_collection_repeats_the_longest_ago_piece(history, images):
    for n in (1, 2, 3):
        images.served[f"https://img/{n}.jpg"] = GOOD
    for key in ("t:2", "t:1", "t:3"):                  # t:2 shown longest ago
        history.add(key)
    chosen, _ = gallery_mod.pick(OPTS, history, [FakeSource([art(1), art(2), art(3)])])
    assert chosen.key == "t:2"


def test_the_stuck_case_from_the_logs(history, images):
    """Every other piece already shown, and the one left is damaged: the old
    picker failed every cycle on it. Now it repeats the longest-ago piece."""
    images.served.update({"https://img/1.jpg": GOOD, "https://img/2.jpg": GOOD,
                          "https://img/3.jpg": BAD})
    history.add("t:1")
    history.add("t:2")
    chosen, data = gallery_mod.pick(OPTS, history,
                                    [FakeSource([art(1), art(2), art(3)])])
    assert chosen.key == "t:1" and data == GOOD


def test_unseen_pieces_still_win_over_repeats(history, images):
    images.served.update({"https://img/1.jpg": GOOD, "https://img/2.jpg": GOOD})
    history.add("t:1")
    chosen, _ = gallery_mod.pick(OPTS, history, [FakeSource([art(1), art(2)])])
    assert chosen.key == "t:2"


def test_hidden_pieces_are_never_the_fallback(history, images):
    images.served["https://img/1.jpg"] = GOOD
    history.add("t:1")
    history.hide("t:1")
    assert gallery_mod.pick(OPTS, history, [FakeSource([art(1)])]) == (None, None)


def test_a_truncated_jpeg_does_not_decode():
    pil = pytest.importorskip("PIL.Image")
    import imaging

    buf = BytesIO()
    pil.new("RGB", (64, 64), (200, 120, 40)).save(buf, format="JPEG")
    whole = buf.getvalue()
    assert imaging.decodes(whole)
    assert not imaging.decodes(whole[:-27])            # cut short, like the CDN file
    assert not imaging.decodes(b"<html>not an image</html>")
