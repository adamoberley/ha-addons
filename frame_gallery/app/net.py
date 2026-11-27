"""HTTP for the art sources: one User-Agent, one polite retry policy.

reframed.gallery and the Art Institute both sit behind Cloudflare, which
answers a burst with 403/429. Every request backs off briefly and tries again;
anything still failing after that is logged and returned as None, so a source
outage costs a cycle, never the app.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("frame-gallery.net")

USER_AGENT = "ha-addons/0.8 (+https://github.com/adamoberley/ha-addons) frame-gallery"
_RATE_LIMITED = (403, 429)


def get(url: str, *, params: dict | None = None, headers: dict | None = None,
        timeout: float = 20, attempts: int = 3) -> requests.Response | None:
    """GET `url`, backing off on rate limits and network errors. None if it
    never succeeds."""
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(1, attempts + 1):
        last = attempt == attempts
        try:
            r = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if r.status_code in _RATE_LIMITED and not last:
                time.sleep(2 * attempt)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if not last:
                time.sleep(2)
                continue
            log.warning("request failed (%s): %s", url, exc)
    return None
