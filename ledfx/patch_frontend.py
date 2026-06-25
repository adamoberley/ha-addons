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
5. Match Home Assistant's theme - retune LedFX's DarkBlue/LightBlue themes to
   HA's exact dark/light palette and inject a script that mirrors HA's light/dark
   mode (read from the same-origin ingress parent) onto them.

We also de-brand the page title and set the backend host + theme in localStorage
on every load (see patch_index). Idempotent.
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

# (5) Match the Home Assistant theme. LedFX already defaults to its "DarkBlue"
# theme under HA (it keys off the `hassTokens` localStorage HA leaves at the same
# origin), so retune DarkBlue to HA's exact default *dark* palette and LightBlue
# to HA's *light* palette. The index.html script (patch_index) then follows HA's
# light/dark mode and picks between the two. Anchors are the unique minified MUI
# theme objects; each is expected exactly once across the bundle (checked below).
# Colors below are HA's defaults: --primary-color #03a9f4 on #111111 / #1c1c1c.
THEME_EDITS = (
    # DarkBlue accent: LedFX cyan (#0dbedc) -> HA blue
    (
        'primary:{main:"#0dbedc"},secondary:{main:"#0dbedc"}',
        'primary:{main:"#03a9f4"},secondary:{main:"#03a9f4"}',
    ),
    # DarkBlue surfaces -> HA dark background (#111111) + card (#1c1c1c)
    (
        'background:{default:"#000",paper:"#1c1c1e"}',
        'background:{default:"#111111",paper:"#1c1c1c"}',
    ),
    # DarkBlue body text -> HA dark primary text (#e1e1e1)
    ('text:{primary:"#f9f9fb"}', 'text:{primary:"#e1e1e1"}'),
    # LightBlue surfaces -> HA light background (#fafafa) + card (#fff)
    (
        'primary:{main:"#03a9f4"},secondary:{main:"#03a9f4"},'
        'accent:{main:"#0288d1"},background:{default:"#fdfdfd",paper:"#eee"}',
        'primary:{main:"#03a9f4"},secondary:{main:"#03a9f4"},'
        'accent:{main:"#0288d1"},background:{default:"#fafafa",paper:"#ffffff"}',
    ),
)


def _replace(src: str, old: str, new: str, label: str, expect=None) -> tuple[str, int]:
    n = src.count(old)
    if expect is not None and n != expect:
        print(f"[patch] WARNING: {label}: expected {expect} hit(s), found {n} - frontend may have changed")
    return src.replace(old, new), n


def patch_js() -> None:
    theme_totals = {old: 0 for old, _ in THEME_EDITS}
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
        theme_hits = 0
        for old, new in THEME_EDITS:
            src, n = _replace(src, old, new, f"theme {old[:28]!r}")
            theme_totals[old] += n
            theme_hits += n

        if src != original:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(src)
            name = os.path.basename(path)
            print(f"[patch] {name}: host={host_hits} basename={base_hits} "
                  f"intro={intro_hits} blade-text={blade_hits} theme={theme_hits}")

    # Each theme anchor should match exactly once across the whole bundle.
    for old, total in theme_totals.items():
        if total != 1:
            print(f"[patch] WARNING: theme anchor {old[:40]!r} matched {total}x "
                  f"(expected 1) - frontend theme may have changed")


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

    # The frontend's API base is `localStorage['ledfx-host'] || <live origin>`,
    # and the HA ingress token rotates each session. REMOVING the saved host on
    # every load fought the app's own "host unusable -> set ledfx-host + reload"
    # recovery effect and caused an infinite reload loop. Instead, SET the saved
    # host (and the single-entry Known-Hosts list) to the current origin on every
    # load: always present and correct (handles token rotation), so that recovery
    # effect never fires. Trailing slash is stripped so the WS URL
    # (host + "/api/websocket") doesn't get a double slash.
    cleaner = (
        "<script>try{"
        "var b=window.location.href.split('#')[0].replace(/\\/+$/,'');"
        "localStorage.setItem('ledfx-host',b);"
        "localStorage.setItem('ledfx-hosts',JSON.stringify([b]));"
        "}catch(e){}</script>"
    )
    # Follow the Home Assistant theme. Under HA ingress this page is an iframe
    # served from HA's own origin, so we can read HA's theme CSS variables from
    # the parent document and mirror its light/dark mode onto LedFX's blue themes
    # (retuned to HA's exact palette in patch_js): DarkBlue / LightBlue. We only
    # switch when HA's mode differs from the stored theme's mode, so a user's
    # in-mode pick in Settings is respected; when the parent isn't readable (LAN,
    # not in an iframe) we just default to DarkBlue if nothing is set. Runs before
    # the app bundle, which reads `ledfx-theme` at startup.
    themer = (
        "<script>try{"
        "var H=null;try{if(window.parent&&window.parent!==window){"
        "var s=getComputedStyle(window.parent.document.documentElement),"
        "c=(s.getPropertyValue('--primary-background-color')||"
        "s.getPropertyValue('--card-background-color')||'').trim(),"
        "h=c.match(/^#?([0-9a-f]{6})$/i),"
        "g=c.match(/(\\d+)[,\\s]+(\\d+)[,\\s]+(\\d+)/),r,gr,bl;"
        "if(h){r=parseInt(h[1].slice(0,2),16);gr=parseInt(h[1].slice(2,4),16);"
        "bl=parseInt(h[1].slice(4,6),16);}"
        "else if(g){r=+g[1];gr=+g[2];bl=+g[3];}"
        "if(r!=null){H=(299*r+587*gr+114*bl)/1000<128;}"
        "}}catch(e){}"
        "var D={DarkRed:1,DarkOrange:1,DarkGreen:1,DarkBlue:1,DarkGrey:1,"
        "DarkPink:1,DarkBw:1,DarkMode:1,Darkmode:1},"
        "cur=localStorage.getItem('ledfx-theme');"
        "if(H===null){if(!cur)localStorage.setItem('ledfx-theme','DarkBlue');}"
        "else{var w=H?'DarkBlue':'LightBlue';"
        "if(!cur||(!!D[cur])!==H)localStorage.setItem('ledfx-theme',w);}"
        "}catch(e){}</script>"
    )
    # Declutter the Home dashboard: hide the two 8-gauge stat rows (.hideTablet)
    # and the external-links FAB row (GitHub/Docs/Discord, anchored on the github
    # Fab). Verified live against the running build. We only hide whole sections by
    # className, which is the reliable CSS lever here (color theming is handled by
    # the HA-theme follower above + the retuned MUI themes, not by CSS overrides).
    declutter = (
        "<style>"
        ".Content .hideTablet{display:none!important}"
        '.Content .MuiStack-root:has(> .MuiFab-root[aria-label="github"]){display:none!important}'
        "</style>"
    )

    if cleaner not in html:
        html = html.replace("<head>", "<head>" + cleaner, 1)
    if themer not in html:
        html = html.replace("<head>", "<head>" + themer, 1)
    if declutter not in html:
        html = html.replace("<head>", "<head>" + declutter, 1)

    if html != original:
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(html)
        print("[patch] index.html: de-branded title + stale-host cleaner + "
              "HA-theme follower + declutter style injected")


if __name__ == "__main__":
    patch_js()
    patch_assets()
    patch_index()
