# ruff: noqa: E501  (the page fixture is verbatim markup)
"""Reading a reframed.gallery artwork page into an Artwork.

The page markup below is trimmed from the live site (October 2026): a schema.org
VisualArtwork block, plus Next.js page data (JSON inside a JS string) that
carries each original's Cloudflare image id. No network is touched.

Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from sources import reframed as reframed_mod

ORIGINAL = ("https://cdn.reframed.gallery/originals/"
            "George%20Inness%20-%20Autumn%20Meadows%20-%20reframed.jpg")

PAGE = """<html><head>
<meta property="og:image" content="https://cdn.reframed.gallery/cdn-cgi/image/width=700,quality=80,format=auto/originals/George%20Inness%20-%20Autumn%20Meadows%20-%20reframed.jpg"/>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"VisualArtwork",
"name":"Autumn Meadows","artist":{"@type":"Person","name":"George Inness"},
"image":"https://cdn.reframed.gallery/cdn-cgi/image/width=1400,quality=85,format=auto/originals/George%20Inness%20-%20Autumn%20Meadows%20-%20reframed.jpg",
"contentUrl":"__ORIGINAL__",
"description":"Golden light spreads across this autumn evening."}</script>
</head><body>
<a href="/collections/fall">Fall</a><a href="/collections/golden-hour">Golden Hour</a>
<script>self.__next_f.push([1,"27:[\\"$\\",\\"$L24\\",\\"abf0\\",{\\"id\\":\\"abf0\\",\\"r2Key\\":\\"originals/Walter Moras - Autumnal Woodland - reframed.jpg\\",\\"cfImageId\\":\\"7e931dc2-8142-4111-2367-7e3a116edd00\\",\\"href\\":\\"/walter-moras/autumnal-woodland\\"}]\\n"])</script>
<script>self.__next_f.push([1,"{\\"r2Key\\":\\"originals/George Inness - Autumn Meadows - reframed.jpg\\",\\"cfImageId\\":\\"d99212ba-b039-432d-7d7d-9f7ba31e7900\\",\\"title\\":\\"Autumn Meadows\\"}"])</script>
</body></html>""".replace("__ORIGINAL__", ORIGINAL)


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture
def src(monkeypatch):
    s = reframed_mod.ReframedSource()
    pages = {"https://www.reframed.gallery/george-inness/autumn-meadows": PAGE}
    monkeypatch.setattr(s, "_get", lambda url: _Resp(pages[url]) if url in pages else None)
    return s


def test_a_page_resolves_to_its_full_resolution_original(src):
    art = src.artwork_from_url("reframed.gallery/george-inness/autumn-meadows")
    assert art is not None
    assert art.image_url == ORIGINAL
    assert art.title == "Autumn Meadows"
    assert art.artist == "George Inness"
    assert art.description.startswith("Golden light")


def test_the_id_is_this_works_cloudflare_id_not_a_related_pieces(src):
    # Earlier versions keyed history on this id; keeping it keeps the no-repeat
    # window and the hidden list meaningful across the upgrade.
    art = src.artwork_from_url("/george-inness/autumn-meadows")
    assert art.key == "reframed:d99212ba-b039-432d-7d7d-9f7ba31e7900"


def test_collection_memberships_feed_the_keyword_filter(src):
    art = src.artwork_from_url("/george-inness/autumn-meadows")
    assert "golden hour" in art.tags and "fall" in art.tags


def test_without_a_cloudflare_id_the_file_name_is_the_id(monkeypatch):
    s = reframed_mod.ReframedSource()
    page = PAGE.replace("d99212ba-b039-432d-7d7d-9f7ba31e7900", "")
    monkeypatch.setattr(s, "_get", lambda url: _Resp(page))
    art = s.artwork_from_url("/george-inness/autumn-meadows")
    assert art.id == "George Inness - Autumn Meadows - reframed.jpg"


def test_a_page_without_artwork_data_resolves_to_nothing(monkeypatch):
    s = reframed_mod.ReframedSource()
    monkeypatch.setattr(s, "_get", lambda url: _Resp("<html>Just a moment...</html>"))
    assert s.artwork_from_url("/george-inness/autumn-meadows") is None
