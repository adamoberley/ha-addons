#!/usr/bin/env python3
"""Make the bundled LedFX web UI work under Home Assistant ingress.

Two fixes are applied to the (minified) frontend, both required for it to run
behind the HA ingress proxy *and* on the LAN:

1. Backend host. The stock frontend resolves its backend as:

       host = isStandaloneApp() ? "http://localhost:8888"
                                : window.location.href.split("#")[0]

   Behind ingress (and on first load) it can take the ``localhost:8888`` branch,
   so every API call and the data WebSocket target the *browser's* machine.
   We rewrite that hard-coded fallback to the page's own origin.

2. Router basename. This is the HASS-optimised build (``PUBLIC_URL="."``), which
   gives the relative asset paths ingress needs — but it also sets the React
   Router to ``basename:"."``, which the router normalises to ``"/."``. No real
   URL starts with ``/.``, so the router "won't render anything" → a blank page
   (confirmed via the browser console). HA ingress serves the app so the router's
   in-app location is ``/`` (and on the LAN it's also ``/``), so we set the
   basename to a plain ``/`` — which matches in both cases. (A dynamic
   ``document.baseURI`` basename does NOT work: under ingress baseURI is the full
   ``/api/hassio_ingress/<token>/`` path, but the router's location is just ``/``,
   so they don't match.)

We also de-brand the page title and clear any stale cached ``localhost`` host
(left in localStorage by the old add-on at the same Nabu Casa origin), so the
frontend falls back to our same-origin default instead of ``localhost:8888``.
Idempotent: safe to run more than once.
"""
from __future__ import annotations

import glob
import os

import ledfx_frontend

ROOT = os.path.dirname(ledfx_frontend.__file__)

# A JS expression yielding the current origin+path (hash stripped) - what the
# non-standalone branch already uses.
ORIGIN_EXPR = '(window.location.href.split("#")[0])'
HOST_FALLBACKS = ('"http://localhost:8888"', '"https://ledfx.local:8889"')

# React Router basename: "." normalises to "/." and matches nothing -> blank page.
# Under HA ingress the in-app router location is "/" (not the ingress path), and
# on the LAN it's "/" too, so a plain "/" basename matches in both cases.
BASENAME_BUG = 'basename:"."'
BASENAME_FIX = 'basename:"/"'


def patch_js() -> None:
    host_total = base_total = 0
    for path in glob.glob(os.path.join(ROOT, "static", "js", "*.js")):
        with open(path, encoding="utf-8") as handle:
            src = original = handle.read()

        host_hits = sum(src.count(token) for token in HOST_FALLBACKS)
        for token in HOST_FALLBACKS:
            src = src.replace(token, ORIGIN_EXPR)

        base_hits = src.count(BASENAME_BUG)
        src = src.replace(BASENAME_BUG, BASENAME_FIX)

        if src != original:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(src)
            host_total += host_hits
            base_total += base_hits
            print(
                f"[patch] {os.path.basename(path)}: "
                f"{host_hits} host fallback(s), {base_hits} router-basename fix(es)"
            )

    if not host_total:
        print("[patch] WARNING: no localhost host fallbacks found - frontend may have changed")
    if not base_total:
        print("[patch] WARNING: no 'basename:\".\"' found - the blank-page fix did NOT apply")


def patch_index() -> None:
    index = os.path.join(ROOT, "index.html")
    with open(index, encoding="utf-8") as handle:
        html = original = handle.read()

    html = html.replace("LedFx Client - by Blade", "LedFX for Home Assistant")

    cleaner = (
        "<script>try{['ledfx-host','ledfx-frontend'].forEach(function(k){"
        "var v=localStorage.getItem(k);"
        "if(v&&(v.indexOf('localhost')>-1||v.indexOf('127.0.0.1')>-1))"
        "localStorage.removeItem(k);});}catch(e){}</script>"
    )
    if cleaner not in html:
        html = html.replace("<head>", "<head>" + cleaner, 1)

    if html != original:
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(html)
        print("[patch] index.html: de-branded title + stale-host cleaner injected")


if __name__ == "__main__":
    patch_js()
    patch_index()
