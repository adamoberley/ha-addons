"""reframed.gallery source - curated public-domain art crafted for the Frame.

reframed.gallery has no API, but publishes a sitemap of ~1,100 artwork pages
(/{artist}/{title}); each page server-renders a Cloudflare image. We cache the
sitemap, then resolve a few random pieces per cycle to their image URL, growing
an in-memory catalogue (so steady-state is ~one image download per interval).

Their largest public Cloudflare variant is "preview" (1400x787, already cropped
~16:9 for the Frame); imaging.py scales it to the panel. The art is public
domain (sourced from Wikimedia Commons) and free for personal use per the
gallery's FAQ - so we identify ourselves, fetch gently, and credit them on screen.
"""
from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import urlparse

import requests

from sources.base import ArtSource, Artwork

log = logging.getLogger("frame-gallery.reframed")

SITEMAP = "https://www.reframed.gallery/sitemap.xml"
CDN_HASH = "ypD62Q2Ttpsm-db9mriXAg"
VARIANT = "preview"               # largest public Cloudflare variant (1400x787)
SITEMAP_TTL = 24 * 3600           # re-read the sitemap at most once a day
RESOLVE_PER_CYCLE = 8             # new artwork pages to resolve per candidates() call
RESOLVE_DELAY = 2.0               # seconds between page fetches (under Cloudflare's bot limit)
# 2-segment sitemap paths that are category listings, not individual artworks.
NONART = frozenset({"collections", "verticals", "colors"})
HEADERS = {
    "User-Agent": "ha-addons/0.1 (+https://github.com/adamoberley/ha-addons) frame-gallery",
}

# The hero image's id (8-4-4-4-12 hex), read from its blur/preview variant. The
# blur/preview pair is the hero; related works lower on the page use /thumbnail.
_IMG_RE = re.compile(
    r"imagedelivery\.net/" + re.escape(CDN_HASH)
    + r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(?:blur|preview)"
)
_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)


def _deslug(seg: str) -> str:
    return seg.replace("-", " ").strip().title() or "Unknown"


class ReframedSource(ArtSource):
    name = "reframed"

    def __init__(self) -> None:
        self._urls: list[str] = []                 # artwork page URLs (sitemap cache)
        self._urls_ts: float = 0.0
        self._resolved: dict[str, Artwork] = {}    # page URL -> Artwork (grows over time)

    def _get(self, url: str) -> requests.Response | None:
        """GET with a short backoff on 403/429. Returns the response, or None."""
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

    def _load_sitemap(self) -> None:
        if self._urls and (time.time() - self._urls_ts) < SITEMAP_TTL:
            return
        r = self._get(SITEMAP)
        if r is None:
            return
        # Artwork pages are /{artist}/{title} (one slash). Single-segment static
        # pages (/recent, /faq, ...) and the /collections|/verticals|/colors
        # listing pages are not individual works, so drop them.
        urls = []
        for loc in _LOC_RE.findall(r.text):
            path = urlparse(loc).path.strip("/")
            if path.count("/") == 1 and path.split("/", 1)[0] not in NONART:
                urls.append(loc)
        if urls:
            self._urls, self._urls_ts = urls, time.time()
            log.info("reframed sitemap: %d artworks", len(urls))

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
        art = Artwork(
            source=self.name,
            id=image_id,
            title=title,
            artist=artist,
            image_url=f"https://imagedelivery.net/{CDN_HASH}/{image_id}/{VARIANT}",
            public_domain=True,
            tags=f"{artist} {title}".lower(),
            credit="reframed.gallery",
        )
        self._resolved[page_url] = art
        return art

    def candidates(self, opts, count: int = 100) -> list[Artwork]:
        self._load_sitemap()
        if not self._urls:
            return []

        pool = self._urls
        if opts.query:
            terms = opts.query.lower().split()
            matched = [u for u in pool
                       if all(t in urlparse(u).path.lower() for t in terms)]
            pool = matched or pool   # a query that matches nothing falls back to all

        # Resolve a few not-yet-seen pages to grow the catalogue, then return a
        # shuffled sample of everything resolved so far (the picker filters/downloads).
        unresolved = [u for u in pool if u not in self._resolved]
        random.shuffle(unresolved)
        for n, page_url in enumerate(unresolved[:RESOLVE_PER_CYCLE]):
            if n:
                time.sleep(RESOLVE_DELAY)   # space out fetches to stay polite
            self._resolve(page_url)

        ready = [self._resolved[u] for u in pool if u in self._resolved]
        random.shuffle(ready)
        return ready[:count]
