"""Choose the next artwork: gather candidates, filter, dedupe, download.

Filters applied to every candidate:
  - public-domain only (if enabled)
  - family-safe keyword blocklist (title/artist/department/classification/terms)
  - not shown recently (the no-repeat history)
The first survivor whose image actually downloads wins; if a batch yields
nothing usable we re-roll (a fresh random page) a few times.
"""
from __future__ import annotations

import logging
import random
import time

import requests

log = logging.getLogger("frame-gallery.gallery")

_UA = {"User-Agent": "ha-addons/0.1 (+https://github.com/adamoberley/ha-addons)"}


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


def pick(opts, history, sources, tries: int = 3):
    """Return (Artwork, jpeg_bytes_from_source) or (None, None)."""
    srcs = list(sources)
    random.shuffle(srcs)
    for attempt in range(1, tries + 1):
        for src in srcs:
            try:
                pool = src.candidates(opts, count=100)
            except Exception as exc:
                log.warning("source %s failed: %s", src.name, exc)
                continue
            cands = [a for a in pool
                     if (not opts.public_domain_only or a.public_domain)
                     and not _blocked(a, opts.exclude_keywords)
                     and not history.seen(a.key)]
            random.shuffle(cands)
            for art in cands:
                data = download(art.image_url)
                if data:
                    return art, data
        log.info("no usable candidate yet (attempt %d/%d)", attempt, tries)
    return None, None
