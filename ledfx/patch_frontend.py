#!/usr/bin/env python3
"""Make the bundled LedFX web UI work under Home Assistant ingress.

The stock frontend resolves its backend like this (minified):

    host = isStandaloneApp() ? "http://localhost:8888"
                             : window.location.href.split("#")[0]

Behind the HA ingress proxy (and on first load before a host is cached) it can
take the ``localhost:8888`` branch, so every API call and the data WebSocket
target the *browser's* machine instead of the add-on - hence "no core found",
dead graphs, and failed edits. It also caches the chosen host in
``localStorage["ledfx-frontend"]``, so a bad value sticks.

We rewrite that hard-coded fallback to use the page's own origin. The WebSocket
URL is already derived from ``window.location``, so this single change makes the
exact same build work both under ingress (``wss://…/<token>/api/websocket``) and
directly on the LAN. We also de-brand the page title and clear any stale cached
``localhost`` host on load.

Idempotent: safe to run more than once.
"""
from __future__ import annotations

import glob
import os

import ledfx_frontend

ROOT = os.path.dirname(ledfx_frontend.__file__)
# A JS expression that yields the current origin+path with the hash stripped -
# exactly what the non-standalone branch already uses.
ORIGIN_EXPR = '(window.location.href.split("#")[0])'
FALLBACKS = ('"http://localhost:8888"', '"https://ledfx.local:8889"')


def patch_js() -> None:
    total = 0
    for path in glob.glob(os.path.join(ROOT, "static", "js", "*.js")):
        with open(path, encoding="utf-8") as handle:
            src = handle.read()
        hits = sum(src.count(token) for token in FALLBACKS)
        if not hits:
            continue
        for token in FALLBACKS:
            src = src.replace(token, ORIGIN_EXPR)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(src)
        total += hits
        print(f"[patch] {os.path.basename(path)}: rewrote {hits} backend-host fallback(s)")
    if not total:
        print("[patch] WARNING: no localhost fallbacks found - frontend layout may have changed")


def patch_index() -> None:
    index = os.path.join(ROOT, "index.html")
    with open(index, encoding="utf-8") as handle:
        html = html_orig = handle.read()

    html = html.replace("LedFx Client - by Blade", "LedFX for Home Assistant")

    cleaner = (
        "<script>try{var k='ledfx-frontend',v=localStorage.getItem(k);"
        "if(v&&v.indexOf('localhost:8888')>-1)localStorage.removeItem(k);}catch(e){}</script>"
    )
    if cleaner not in html:
        html = html.replace("<head>", "<head>" + cleaner, 1)

    if html != html_orig:
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(html)
        print("[patch] index.html: de-branded title + stale-host cleaner injected")


if __name__ == "__main__":
    patch_js()
    patch_index()
