"""Choose the next artwork: gather candidates, filter, download, check.

Filters applied to every candidate:
  - public-domain only (if enabled)
  - family-safe keyword blocklist (matched against the work's tags)
  - not hidden by hand (the panel's "Never show this" button)
  - not shown recently (the no-repeat history)
The first survivor whose image downloads AND decodes wins; if a batch yields
nothing usable we ask the source again (a fresh random batch) a few times.

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

import net
from imaging import decodes
from sources.base import ArtSource, Artwork
from state import History

log = logging.getLogger("frame-gallery.gallery")

# Keys whose image downloaded but wouldn't decode. In memory only: if the
# source repairs the file, a restart gives it another chance.
_broken: set[str] = set()


def download(url: str) -> bytes | None:
    """Image bytes, or None if they won't come."""
    r = net.get(url, timeout=30, attempts=2)
    return (r.content or None) if r is not None else None


def fetch_image(art: Artwork) -> bytes | None:
    """Download `art`'s image and make sure it's a whole picture. None if the
    download failed or the file is damaged (which is then remembered)."""
    if art.key in _broken:
        return None
    data = download(art.image_url)
    if not data:
        return None
    if not decodes(data):
        _broken.add(art.key)
        log.warning("'%s' by %s: the source's image file is damaged - skipping it (%s)",
                    art.title, art.artist, art.image_url)
        return None
    return data


def _excluded(art: Artwork, opts, history: History) -> bool:
    return ((opts.public_domain_only and not art.public_domain)
            or any(k in art.tags for k in opts.exclude_keywords)
            or history.is_hidden(art.key)
            or art.key in _broken)


def _first_usable(arts):
    for art in arts:
        data = fetch_image(art)
        if data:
            return art, data
    return None, None


def pick(opts, history: History, source: ArtSource, tries: int = 3):
    """Return (Artwork, image_bytes_from_source) or (None, None)."""
    repeats: dict[str, Artwork] = {}     # passed the filters but shown recently
    for attempt in range(1, tries + 1):
        try:
            batch = source.candidates(opts, count=100)
        except Exception as exc:
            log.warning("source %s failed: %s", source.name, exc)
            batch = []
        fresh = []
        for art in batch:
            if _excluded(art, opts, history):
                continue
            if history.seen(art.key):
                repeats[art.key] = art
            else:
                fresh.append(art)
        random.shuffle(fresh)
        art, data = _first_usable(fresh)
        if art:
            return art, data
        log.info("no usable candidate yet (attempt %d/%d)", attempt, tries)

    # Everything left has been shown within the no-repeat window - the
    # collection is smaller than the window. Reuse the longest-ago piece.
    art, data = _first_usable(history.oldest_first(list(repeats.values())))
    if art:
        log.info("every piece in this collection has been shown recently - "
                 "repeating the one shown longest ago")
    return art, data
