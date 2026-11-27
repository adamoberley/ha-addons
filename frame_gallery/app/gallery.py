"""Choose the next artwork: gather candidates, filter, dedupe, download.

Filters applied to every candidate:
  - public-domain only (if enabled)
  - family-safe keyword blocklist (title/artist/department/classification/terms)
  - not hidden by hand (the panel's "Never show this" button)
  - not shown recently (the no-repeat history)
The first survivor whose image downloads AND decodes wins; if a batch yields
nothing usable we re-roll (a fresh random page) a few times.

Two ways a pick used to dead-end, both handled here:
  - A damaged image (the source serves a truncated file with a 200). It's
    skipped and remembered for the rest of the run, so it isn't downloaded again
    every cycle.
  - A collection smaller than the no-repeat window (Christmas has ~30 pieces,
    the window defaults to 2000). Once every piece has been shown, the one shown
    longest ago goes up again rather than nothing at all.
"""
from __future__ import annotations

import logging
import random
import time

import requests

log = logging.getLogger("frame-gallery.gallery")

_UA = {"User-Agent": "ha-addons/0.1 (+https://github.com/adamoberley/ha-addons)"}

# Keys whose image downloaded but wouldn't decode. In memory only: if the
# source repairs the file, a restart gives it another chance.
_broken: set[str] = set()


def _blocked(art, keywords) -> bool:
    return any(k in art.tags for k in keywords)


def download(url: str) -> bytes | None:
    """Fetch image bytes, retrying once past a rate-limit. None if it won't come."""
    for attempt in range(2):
        try:
            r = requests.get(url, headers=_UA, timeout=30)
            if r.status_code in (403, 429) and attempt < 1:
                time.sleep(2)
                continue
            r.raise_for_status()
            return r.content or None
        except requests.RequestException as exc:
            if attempt < 1:
                time.sleep(2)
                continue
            log.warning("image download failed (%s): %s", url, exc)
    return None


def _decodes(data: bytes) -> bool:
    from imaging import decodes  # Pillow loads only when an image is checked
    return decodes(data)


def fetch_image(art) -> bytes | None:
    """Download `art`'s image and make sure it's a whole picture. None if the
    download failed or the file is damaged (which is then remembered)."""
    if art.key in _broken:
        return None
    data = download(art.image_url)
    if not data:
        return None
    if not _decodes(data):
        _broken.add(art.key)
        log.warning("'%s' by %s: the source's image file is damaged - skipping it (%s)",
                    art.title, art.artist, art.image_url)
        return None
    return data


def _first_usable(arts):
    for art in arts:
        data = fetch_image(art)
        if data:
            return art, data
    return None, None


def pick(opts, history, sources, tries: int = 3):
    """Return (Artwork, image_bytes_from_source) or (None, None)."""
    srcs = list(sources)
    random.shuffle(srcs)
    repeats: dict[str, object] = {}     # filtered-in but shown recently, by key
    for attempt in range(1, tries + 1):
        for src in srcs:
            try:
                pool = src.candidates(opts, count=100)
            except Exception as exc:
                log.warning("source %s failed: %s", src.name, exc)
                continue
            fresh = []
            for a in pool:
                if ((opts.public_domain_only and not a.public_domain)
                        or _blocked(a, opts.exclude_keywords)
                        or history.is_hidden(a.key) or a.key in _broken):
                    continue
                if history.seen(a.key):
                    repeats[a.key] = a
                else:
                    fresh.append(a)
            random.shuffle(fresh)
            art, data = _first_usable(fresh)
            if art:
                return art, data
        log.info("no usable candidate yet (attempt %d/%d)", attempt, tries)

    # Everything left has been shown within the no-repeat window - the
    # collection is smaller than the window. Reuse the longest-ago piece.
    if repeats:
        art, data = _first_usable(history.oldest_first(list(repeats.values())))
        if art:
            log.info("every piece in this collection has been shown recently - "
                     "repeating the one shown longest ago")
            return art, data
    return None, None
