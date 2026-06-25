#!/usr/bin/env python3
"""Patch the bundled LedFX web UI for a clean, native Home Assistant experience.

All edits are applied to the prebuilt (minified) HASS frontend at build time.
Each replacement is guarded by a hit count and warns if a token isn't found, so
a future frontend bump that moves an anchor fails loud instead of silent.

Fixes:
1. Backend host - rewrite the hard-coded `http://localhost:8888` fallback to the
   page's own origin, so the UI talks to the right backend under ingress + LAN.
2. Router basename - `basename:"."` normalises to `"/."` and matches nothing
   (blank page). Set it to `/`, which matches the router's `/` location under
   both ingress and the LAN root.
3. Skip onboarding - flip the persisted store default `intro:!0` (true) -> `!1`
   (false) so the "Setup Assistant" wizard never shows. Devices auto-scan on
   startup instead (scan_on_startup, set in run.sh); re-scan lives in Settings.
   Anchored to `intro:!0,setIntro:` (unique) so the unrelated `intro:!0` icon
   prop is left alone.
4. De-Blade - blank the `blademod*.svg` asset (the "BLADE MOD" sidebar badge is
   a vector asset, not inlined JS) and rename the "Blade Scene" onboarding text.

We also de-brand the page title and clear any stale `localhost` backend host
cached in localStorage by the old app at the same origin. Idempotent.
"""
from __future__ import annotations

import glob
import os

import ledfx_frontend

ROOT = os.path.dirname(ledfx_frontend.__file__)

# (1) backend host -> current origin (hash stripped)
ORIGIN_EXPR = '(window.location.href.split("#")[0])'
HOST_FALLBACKS = ('"http://localhost:8888"', '"https://ledfx.local:8889"')

# (2) router basename "." -> "/"
BASENAME_BUG = 'basename:"."'
BASENAME_FIX = 'basename:"/"'

# (3) wizard store default intro:true -> false (anchored so the icon prop is safe)
INTRO_BUG = "intro:!0,setIntro:"
INTRO_FIX = "intro:!1,setIntro:"

# (4) de-Blade onboarding text (longest first so substrings aren't half-replaced)
BLADE_STRINGS = (
    ("Skip Blade Scene", "Skip"),
    ("Add Blade Scene", "Add Demo Scene"),
    ("Blade Scene", "Demo Scene"),
)

# (4) the "BLADE MOD" sidebar badge is this vector asset; blank it out
BLANK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'


def _replace(src: str, old: str, new: str, label: str, expect=None) -> tuple[str, int]:
    n = src.count(old)
    if expect is not None and n != expect:
        print(f"[patch] WARNING: {label}: expected {expect} hit(s), found {n} - frontend may have changed")
    return src.replace(old, new), n


def patch_js() -> None:
    for path in glob.glob(os.path.join(ROOT, "static", "js", "*.js")):
        with open(path, encoding="utf-8") as handle:
            src = original = handle.read()

        host_hits = sum(src.count(t) for t in HOST_FALLBACKS)
        for token in HOST_FALLBACKS:
            src = src.replace(token, ORIGIN_EXPR)

        src, base_hits = _replace(src, BASENAME_BUG, BASENAME_FIX, "basename")
        src, intro_hits = _replace(src, INTRO_BUG, INTRO_FIX, "intro/wizard")
        blade_hits = 0
        for old, new in BLADE_STRINGS:
            src, n = _replace(src, old, new, f"blade-text {old!r}")
            blade_hits += n

        if src != original:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(src)
            name = os.path.basename(path)
            print(f"[patch] {name}: host={host_hits} basename={base_hits} "
                  f"intro={intro_hits} blade-text={blade_hits}")


def patch_assets() -> None:
    found = False
    for path in glob.glob(os.path.join(ROOT, "static", "media", "*blademod*.svg")):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(BLANK_SVG)
        found = True
        print(f"[patch] blanked Blade badge asset: {os.path.basename(path)}")
    if not found:
        print("[patch] note: no blademod*.svg found (sidebar badge may have moved)")


def patch_index() -> None:
    index = os.path.join(ROOT, "index.html")
    with open(index, encoding="utf-8") as handle:
        html = original = handle.read()

    html = html.replace("LedFx Client - by Blade", "LedFX for Home Assistant")

    # The frontend's API base is `localStorage['ledfx-host'] || <live origin>`.
    # The HA ingress token rotates each session, so any saved host (a stale
    # token URL, the bare nabu.casa origin, localhost, the LAN IP) goes 404. Clear
    # the saved host + the Known-Hosts list every load so it always falls back to
    # the live origin. Also drop a localhost value cached in the main store.
    cleaner = (
        "<script>try{"
        "localStorage.removeItem('ledfx-host');"
        "localStorage.removeItem('ledfx-hosts');"
        "var v=localStorage.getItem('ledfx-frontend');"
        "if(v&&(v.indexOf('localhost')>-1||v.indexOf('127.0.0.1')>-1))"
        "localStorage.removeItem('ledfx-frontend');"
        "}catch(e){}</script>"
    )
    if cleaner not in html:
        html = html.replace("<head>", "<head>" + cleaner, 1)

    if html != original:
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(html)
        print("[patch] index.html: de-branded title + stale-host cleaner injected")


if __name__ == "__main__":
    patch_js()
    patch_assets()
    patch_index()
