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
6. Match HA's font - define a real "Roboto" family from the bundled TTFs and
   switch the app's Nunito font stacks to Roboto (HA uses Roboto).
7. Flat header - reskin the MUI AppBar to look like HA's header (surface color,
   no shadow, 1px divider, 56px) instead of a solid blue bar. Driven by HA's live
   theme vars, bridged from the ingress parent onto our :root as --ha-*.

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

# (6) Match HA's font. HA's UI is Roboto; LedFX is Nunito. The bundle ships
# Roboto TTFs but only under per-weight family names (Roboto-Regular/Bold/Black),
# so MUI's request for plain "Roboto" falls back to a system sans. Define a real
# "Roboto" family from those TTFs (appended to fonts.css, which already loads
# ./fonts/* successfully) and switch the app's font stacks to lead with Roboto.
# The browser maps intermediate weights (300/500) to the nearest defined face.
# HA's stack is "Roboto, Noto, sans-serif"; Noto/Helvetica/Arial are graceful
# no-ops if absent and cover non-Latin glyphs. The bundled Roboto faces win.
FONT_JS = (
    'fontFamily:\'"Nunito", "Roboto", "Helvetica", "Arial", sans-serif\'',
    'fontFamily:\'"Roboto", "Noto", "Helvetica", "Arial", sans-serif\'',
)
FONT_CSS = (
    "font-family:Nunito,Roboto,Helvetica,sans-serif",
    "font-family:Roboto,Noto,Helvetica,Arial,sans-serif",
)
# 500 (medium) has no bundled file -> map to Regular so HA's medium-weight text
# (h2, buttons, sub-headers) isn't faux-bolded up to the 700 Bold face.
ROBOTO_FACE = (
    "\n/* HA-match: a real Roboto family from the bundled per-weight TTFs */\n"
    "@font-face{font-family:'Roboto';font-style:normal;font-weight:400;"
    "src:url('./fonts/Roboto-Regular.ttf') format('truetype')}\n"
    "@font-face{font-family:'Roboto';font-style:normal;font-weight:500;"
    "src:url('./fonts/Roboto-Regular.ttf') format('truetype')}\n"
    "@font-face{font-family:'Roboto';font-style:normal;font-weight:700;"
    "src:url('./fonts/Roboto-Bold.ttf') format('truetype')}\n"
    "@font-face{font-family:'Roboto';font-style:normal;font-weight:900;"
    "src:url('./fonts/Roboto-Black.ttf') format('truetype')}\n"
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
        src, font_hits = _replace(src, FONT_JS[0], FONT_JS[1], "font (js)")

        if src != original:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(src)
            name = os.path.basename(path)
            print(f"[patch] {name}: host={host_hits} basename={base_hits} "
                  f"intro={intro_hits} blade-text={blade_hits} "
                  f"theme={theme_hits} font={font_hits}")

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


def patch_styles() -> None:
    """Point the app's base CSS font stack at Roboto and define the family."""
    css_hits = 0
    for path in glob.glob(os.path.join(ROOT, "static", "css", "*.css")):
        with open(path, encoding="utf-8") as handle:
            src = original = handle.read()
        src, n = _replace(src, FONT_CSS[0], FONT_CSS[1], "font (css)")
        css_hits += n
        if src != original:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(src)
            print(f"[patch] {os.path.basename(path)}: font={n}")
    if css_hits != 1:
        print(f"[patch] WARNING: css font anchor matched {css_hits}x (expected 1)")

    # Define a real "Roboto" family from the bundled TTFs (idempotent append).
    fonts_css = os.path.join(ROOT, "fonts.css")
    if os.path.exists(fonts_css):
        with open(fonts_css, encoding="utf-8") as handle:
            css = handle.read()
        if "font-family:'Roboto';font-style:normal;font-weight:400" not in css:
            with open(fonts_css, "a", encoding="utf-8") as handle:
                handle.write(ROBOTO_FACE)
            print("[patch] fonts.css: appended Roboto family (400/500/700/900)")
    else:
        print("[patch] note: fonts.css not found (Roboto family not defined)")


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
    # Bridge HA's live theme vars onto our :root as --ha-*. Same-origin under
    # ingress lets us read the parent's computed custom properties; we resolve
    # each through HA's fallback chain, else a dark/light literal (defaulting to
    # dark, matching the LAN theme default). A MutationObserver re-runs it when HA
    # swaps theme (HA mutates style/class on its <html>). The header CSS below
    # consumes these. dark is inferred from the header/surface bg luminance.
    bridge = (
        "<script>(function(){function ro(){var P=null;try{"
        "if(window.parent&&window.parent!==window)"
        "P=getComputedStyle(window.parent.document.documentElement);}catch(e){}"
        "var d=document.documentElement,dark=true,"
        "bg=P&&(P.getPropertyValue('--app-header-background-color')||"
        "P.getPropertyValue('--sidebar-background-color')||"
        "P.getPropertyValue('--card-background-color')||'').trim(),"
        "m=bg&&bg.match(/^#?([0-9a-f]{6})$/i);"
        "if(m){var r=parseInt(m[1].slice(0,2),16),g=parseInt(m[1].slice(2,4),16),"
        "b=parseInt(m[1].slice(4,6),16);dark=(299*r+587*g+114*b)/1000<128;}"
        "function set(n,vs,ll,ld){var v='';if(P){for(var i=0;i<vs.length&&!v;i++)"
        "v=(P.getPropertyValue(vs[i])||'').trim();}"
        "d.style.setProperty(n,v||(dark?ld:ll));}"
        "set('--ha-header-bg',['--app-header-background-color',"
        "'--sidebar-background-color','--card-background-color'],"
        "'#ffffff','#1c1c1c');"
        "set('--ha-header-fg',['--app-header-text-color','--sidebar-text-color',"
        "'--primary-text-color'],'#212121','#e1e1e1');"
        "set('--ha-header-border',['--app-header-border-bottom'],"
        "'1px solid rgba(0,0,0,0.12)','1px solid rgba(255,255,255,0.12)');"
        "set('--ha-header-height',['--header-height'],'56px','56px');"
        "set('--ha-text-secondary',['--secondary-text-color'],"
        "'#5e5e5e','#9b9b9b');}"
        "ro();try{if(window.parent&&window.parent!==window)"
        "new MutationObserver(ro).observe("
        "window.parent.document.documentElement,"
        "{attributes:true,attributeFilter:['style','class']});}catch(e){}"
        "})();</script>"
    )
    # Reskin the MUI AppBar as HA's flat header instead of a solid primary-color
    # bar: surface background (not blue), no shadow at rest, a 1px bottom divider,
    # HA's 56px height, and header-fg text/icons. background-image:none kills MUI
    # v7's dark elevation overlay. Stable global Mui* classes + !important win
    # over emotion's runtime styles regardless of injection order.
    header_css = (
        "<style>"
        ".MuiAppBar-root,.MuiAppBar-root.MuiAppBar-colorPrimary,"
        ".MuiAppBar-colorPrimary{"
        "background-color:var(--ha-header-bg,#1c1c1c)!important;"
        "background-image:none!important;"
        "color:var(--ha-header-fg,#e1e1e1)!important;"
        "box-shadow:none!important;"
        "border-bottom:var(--ha-header-border,1px solid rgba(255,255,255,0.12))"
        "!important}"
        ".MuiAppBar-root .MuiToolbar-root{"
        "color:var(--ha-header-fg,#e1e1e1)!important;"
        "min-height:var(--ha-header-height,56px)!important}"
        ".MuiAppBar-root .MuiToolbar-root .MuiTypography-root,"
        ".MuiAppBar-root .MuiToolbar-root .MuiIconButton-root,"
        ".MuiAppBar-root .MuiToolbar-root .MuiSvgIcon-root{"
        "color:var(--ha-header-fg,#e1e1e1)!important}"
        # Left-nav drawer header: same flat HA surface as the app bar, not a
        # solid blue block. jss* classes are build-unstable, so target the header
        # structurally (first Box child of the drawer paper) and null any blue
        # child backgrounds (e.g. the de-Blade'd "BLADE MOD" badge box). The
        # white FX logo stays visible on the dark surface.
        ".MuiDrawer-paper>.MuiBox-root:first-child{"
        "background-color:var(--ha-header-bg,#1c1c1c)!important;"
        "color:var(--ha-header-fg,#e1e1e1)!important;"
        "border-bottom:var(--ha-header-border,1px solid rgba(255,255,255,0.12))"
        "!important}"
        ".MuiDrawer-paper>.MuiBox-root:first-child *{"
        "background-color:transparent!important}"
        # Hide the QR-connect shortcut next to the page title for a cleaner
        # header (shares the toolbar with the title; aria-label is stable).
        ".MuiAppBar-root .MuiIconButton-root"
        '[aria-label="Show QR Connect Hosts"]{display:none!important}'
        # Read-only / disabled form fields default to 50% opacity and are hard to
        # read; use HA's secondary-text color instead (theme-aware via bridge).
        ".MuiInputBase-input.Mui-disabled,.MuiInputBase-input:disabled{"
        "-webkit-text-fill-color:var(--ha-text-secondary,#9b9b9b)!important;"
        "color:var(--ha-text-secondary,#9b9b9b)!important}"
        # Mobile: the left nav uses a *persistent* drawer that reserves its 240px
        # in the flex row, with the content box carrying a matching margin-left:
        # -240px to sit under it. On a phone that pushes the content half off
        # screen when the drawer opens. Below 600px, drop the drawer's reserved
        # width AND reset that coupled negative margin so content is full-width;
        # the (position:fixed) paper then overlays content like a temporary drawer.
        "@media (max-width:600px){"
        ".MuiDrawer-docked{width:0!important}"
        ".MuiDrawer-docked + .MuiBox-root{margin-left:0!important}"
        ".MuiDrawer-docked .MuiDrawer-paper{"
        "box-shadow:0 0 24px rgba(0,0,0,0.7)!important}"
        "}"
        # Home now lands on Devices (see the redirect script), so the bottom-nav
        # "Home" tab is redundant -> hide it, leaving Devices/Scenes/Settings. It's
        # the first action (stable order: Home, Devices, Scenes, Settings).
        ".MuiBottomNavigation-root>.MuiBottomNavigationAction-root:first-child{"
        "display:none!important}"
        "</style>"
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
    # Land on the device list instead of the near-empty Home page. The app uses
    # hash routing (Home = "#/", Devices = "#/Devices"); redirect the empty/home
    # hash to Devices on load and whenever it's navigated to. Runs in <head>
    # before the bundle boots, so the router initialises straight on Devices (no
    # flash). location.replace keeps it out of history (no back-button trap).
    # Deep links (#/Settings, #/device/..., etc.) are untouched.
    redirect = (
        "<script>(function(){function g(){var h=location.hash;"
        "if(h===''||h==='#'||h==='#/'){"
        "location.replace(location.href.split('#')[0]+'#/Devices');}}"
        "window.addEventListener('hashchange',g);g();})();</script>"
    )

    if cleaner not in html:
        html = html.replace("<head>", "<head>" + cleaner, 1)
    if themer not in html:
        html = html.replace("<head>", "<head>" + themer, 1)
    if bridge not in html:
        html = html.replace("<head>", "<head>" + bridge, 1)
    if redirect not in html:
        html = html.replace("<head>", "<head>" + redirect, 1)
    if header_css not in html:
        html = html.replace("<head>", "<head>" + header_css, 1)
    if declutter not in html:
        html = html.replace("<head>", "<head>" + declutter, 1)

    if html != original:
        with open(index, "w", encoding="utf-8") as handle:
            handle.write(html)
        print("[patch] index.html: de-branded title + stale-host cleaner + "
              "HA-theme follower + HA var bridge + home->devices + flat header + "
              "declutter style injected")


if __name__ == "__main__":
    patch_js()
    patch_assets()
    patch_styles()
    patch_index()
