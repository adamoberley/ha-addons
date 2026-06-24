"""reframed.gallery source - curated public-domain art crafted for the Frame.

reframed.gallery has no API, but publishes a sitemap (~2,300 artwork pages) and
collection pages (/collections/<slug>). We pick a pool of artwork pages - the
whole catalogue, a chosen collection, or the season's collection - then resolve a
few random ones per cycle to their Cloudflare image, growing an in-memory
catalogue (steady-state ~one image fetch per change). Each artwork page also
lists its genre + collection memberships, which we fold into the work's tags so
the family-safe keyword filter has subject/theme to match, not just the title.

Largest public Cloudflare variant is "preview" (1400x787, ~16:9). Art is public
domain (Wikimedia-sourced), free for personal use per the gallery's FAQ - so we
identify ourselves, fetch gently, and credit reframed.gallery on screen.
"""
from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

from sources.base import ArtSource, Artwork

log = logging.getLogger("frame-gallery.reframed")

SITEMAP = "https://www.reframed.gallery/sitemap.xml"
COLLECTION = "https://www.reframed.gallery/collections/{}"
BASE = "https://www.reframed.gallery"
CDN_HASH = "ypD62Q2Ttpsm-db9mriXAg"
VARIANT = "preview"               # largest public Cloudflare variant (1400x787)
POOL_TTL = 24 * 3600              # re-read sitemap/collection at most once a day
RESOLVE_PER_CYCLE = 8             # new artwork pages resolved per candidates() call
RESOLVE_DELAY = 2.0               # seconds between fetches (under Cloudflare's bot limit)
# Path first-segments that are navigation/category pages, not individual artworks.
NONART = frozenset({"collections", "verticals", "colors", "cartographers",
                    "wheres-wally", "page", "artists", "recent", "chrome-extension",
                    "faq", "contact", "about", "_next"})
HEADERS = {
    "User-Agent": "ha-addons/0.1 (+https://github.com/adamoberley/ha-addons) frame-gallery",
}

_IMG_RE = re.compile(
    r"imagedelivery\.net/" + re.escape(CDN_HASH)
    + r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(?:blur|preview)"
)
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_LINK_RE = re.compile(r'href="(/[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*)"')
_COLL_RE = re.compile(r"/collections/([a-z0-9-]+)")

def _deslug(seg: str) -> str:
    return seg.replace("-", " ").strip().title() or "Unknown"


def _seasonal_slug(now: datetime, hemisphere: str) -> str:
    """Current season's reframed collection. December -> Christmas (the holiday, both
    hemispheres); otherwise map by season, shifting 6 months south of the equator."""
    month = now.month
    if month == 12:
        return "christmas"
    m = month
    if str(hemisphere).lower().startswith("s"):
        m = (month + 5) % 12 + 1   # +6 months for the Southern hemisphere
    if m in (1, 2, 12):
        return "winter"
    if m in (3, 4, 5):
        return "spring-blossoms"
    if m in (6, 7, 8):
        return "here-comes-the-sun"
    return "fall"   # 9, 10, 11


class ReframedSource(ArtSource):
    name = "reframed"

    def __init__(self) -> None:
        self.override: str | None = None        # live collection switch (HA select)
        self._pools: dict[str, list[str]] = {}   # pool key -> artwork page URLs
        self._pool_ts: dict[str, float] = {}
        self._resolved: dict[str, Artwork] = {}  # page URL -> Artwork

    def active_collection(self, opts) -> str:
        """Effective collection slug: live override beats the option; '' / 'all' = whole catalogue."""
        choice = (self.override or getattr(opts, "collection", "") or "").strip().lower()
        if choice in ("", "all"):
            return ""
        if choice == "seasonal":
            return _seasonal_slug(datetime.now(), getattr(opts, "hemisphere", "north"))
        return choice

    def _get(self, url: str) -> requests.Response | None:
        for attempt in range(3):
            try:
                r = requests.get(url, headers=HEADERS, timeout=20)
                if r.status_code in (403, 429) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(2)
                    continue
                log.warning("reframed request failed (%s): %s", url, exc)
        return None

    def _artwork_paths(self, html: str) -> list[str]:
        """Unique /artist/title links on a collection page, in document order, minus nav."""
        seen, out = set(), []
        for path in _LINK_RE.findall(html):
            if path.strip("/").split("/", 1)[0] in NONART or path in seen:
                continue
            seen.add(path)
            out.append(BASE + path)
        return out

    def _load_pool(self, key: str) -> list[str]:
        if self._pools.get(key) and (time.time() - self._pool_ts.get(key, 0)) < POOL_TTL:
            return self._pools[key]
        if key == "__all__":
            r = self._get(SITEMAP)
            urls = []
            if r is not None:
                for loc in _LOC_RE.findall(r.text):
                    p = urlparse(loc).path.strip("/")
                    if p.count("/") == 1 and p.split("/", 1)[0] not in NONART:
                        urls.append(loc)
        else:
            r = self._get(COLLECTION.format(key))
            urls = self._artwork_paths(r.text) if r is not None else []
        if urls:
            self._pools[key] = urls
            self._pool_ts[key] = time.time()
            log.info("reframed pool '%s': %d artworks", key, len(urls))
        return self._pools.get(key, [])

    def _resolve(self, page_url: str) -> Artwork | None:
        if page_url in self._resolved:
            return self._resolved[page_url]
        r = self._get(page_url)
        if r is None:
            return None
        m = _IMG_RE.search(r.text)
        if not m:
            log.debug("no image found on %s", page_url)
            return None
        image_id = m.group(1)
        segs = urlparse(page_url).path.strip("/").split("/")
        artist = _deslug(segs[0])
        title = _deslug(segs[1]) if len(segs) > 1 else "Untitled"
        # Fold collection memberships into tags so exclude_keywords matches subject/theme.
        memberships = {s for s in _COLL_RE.findall(r.text) if s != "all"}
        tags = " ".join([artist, title, *(_deslug(s) for s in memberships)]).lower()
        art = Artwork(
            source=self.name,
            id=image_id,
            title=title,
            artist=artist,
            image_url=f"https://imagedelivery.net/{CDN_HASH}/{image_id}/{VARIANT}",
            public_domain=True,
            tags=tags,
            credit="reframed.gallery",
        )
        self._resolved[page_url] = art
        return art

    def candidates(self, opts, count: int = 100) -> list[Artwork]:
        key = self.active_collection(opts) or "__all__"
        pool = self._load_pool(key)
        if not pool and key != "__all__":
            log.warning("collection '%s' empty - falling back to the whole catalogue", key)
            pool = self._load_pool("__all__")
        if not pool:
            return []

        if opts.query:
            terms = opts.query.lower().split()
            matched = [u for u in pool if all(t in urlparse(u).path.lower() for t in terms)]
            pool = matched or pool   # a query that matches nothing falls back to the pool

        unresolved = [u for u in pool if u not in self._resolved]
        random.shuffle(unresolved)
        for n, page_url in enumerate(unresolved[:RESOLVE_PER_CYCLE]):
            if n:
                time.sleep(RESOLVE_DELAY)   # space out fetches to stay polite
            self._resolve(page_url)

        ready = [self._resolved[u] for u in pool if u in self._resolved]
        random.shuffle(ready)
        return ready[:count]
