# Changelog

## 1.7.1 — 2026-06-25

- **Tidied the bottom nav.** Now that Home opens on your devices, the separate
  "Home" tab was redundant — the bottom bar is now **Devices / Scenes /
  Settings**, opening on Devices.

## 1.7.0 — 2026-06-25

- **Much better on a phone.** The left navigation used a *persistent* drawer that
  reserved 240px and shoved the page half off-screen on a narrow display. Below
  600px it now behaves like a proper slide-over: the content stays full-width and
  the drawer floats on top (with a shadow) when you open it. (Popups/dialogs were
  already responsive — verified the Add-Device form and menus fit and scroll on a
  phone-width screen.)
- **Home now opens on your devices.** The landing page was a near-empty
  placeholder (a search bar + a row of setup/utility buttons). It now goes
  straight to the device list — the page you actually use. Deep links to Settings,
  Scenes, and individual devices are unchanged.
- Note: the old Home utility buttons (re-run intro/tour, scan, reset) are no
  longer on the landing page; their functions live in the ⋮ menu / Settings / the
  **+** button. (Relocating them into Settings itself needs a frontend source
  build — see the repo notes.)

## 1.6.0 — 2026-06-25

- **Cleaner page header** — removed the little pixel QR-connect icon that sat
  next to every page title. (It was a LAN "scan to connect a client" shortcut you
  don't need under Home Assistant.)
- **Readable read-only fields** — the greyed-out audio fields (Sample Rate, Mic
  Rate, FFT Size) rendered at 50% opacity and were hard to read. They now use
  Home Assistant's secondary-text colour, so they're legible while still reading
  as read-only. (Added `--ha-text-secondary` to the HA variable bridge.)
- The rest of the Settings panels and the effect editor were audited live and
  already match HA well (dark surfaces, blue accents, tidy forms), so no
  redesign — just these targeted refinements.

## 1.5.0 — 2026-06-25

- **The slide-out menu header now matches too.** Opening the left navigation
  drawer revealed a leftover solid-blue block (with a stray blue badge box from
  the old "BLADE MOD" badge). It's now the same flat Home Assistant surface as
  the top bar — the white LedFX logo stays, the blue badge is gone — driven by
  the same live HA theme variables, so the whole chrome is consistent. Verified
  in-browser on the running instance.

## 1.4.0 — 2026-06-25

- **The top bar now looks like the Home Assistant header**, not a big solid blue
  bar. LedFX painted its app bar with the theme's primary color; HA's modern
  header (2026.2+) is flat and blends with the surface. The bar is now HA's
  surface color with HA's header text/icon color, no drop shadow, and a 1px
  bottom divider at HA's 56px height. It reads HA's *live* header variables from
  the ingress parent, so it tracks your actual HA theme (including a custom one)
  and updates if you switch HA light/dark — falling back to the dark HA look on
  direct LAN access.
- **Fonts match HA (Roboto).** LedFX shipped Roboto but only under per-weight
  names, so its Nunito-first UI fell back to a system font. The app now defines a
  real Roboto family (400/500/700/900) from the bundled files and uses HA's
  `Roboto, Noto, …` stack, so the type matches Home Assistant.

## 1.3.0 — 2026-06-25

- **The UI now follows your Home Assistant theme.** LedFX's blue themes were
  retuned to Home Assistant's exact palette — dark: HA blue (`#03a9f4`) accents
  on the `#111` / `#1c1c1c` backgrounds and `#e1e1e1` text; light: the same blue
  on HA's `#fafafa` / `#fff`. When the UI runs under HA ingress it reads HA's own
  theme variables (it's an iframe on HA's origin) and mirrors HA's **light/dark
  mode**, so it matches whether you run HA light or dark. Your own pick in
  **Settings → Theme** is still respected within a mode; only the mode follows HA.
  On direct LAN access (no HA parent) it defaults to the dark HA-matched theme.

- **The audio-delay fix is now upstream too.** The merge-before-validate fix we
  ship via `patch_backend.py` was sent to LedFx as
  [PR #1831](https://github.com/LedFx/LedFx/pull/1831) with a regression test, so
  a future engine bump keeps the fix even once we drop the local patch.

## 1.2.0 — 2026-06-25

- **Fixed the audio-delay bug for real** (not just the option workaround). LedFX
  had an upstream regression (from PR #1770) where changing the audio **delay**
  silently reset the audio source from Sendspin to the default ALSA device, so the
  lights went dead. The add-on now patches `ledfx/effects/audio.py` to merge a
  partial audio update over the existing config *before* schema validation, so the
  Sendspin device + name are preserved. The in-UI delay control works now, for all
  callers (UI / REST / automations). The `sendspin_delay_ms` option stays one more
  release as a safety net.
- **De-Blade the effect names** — "Blade Power+" → "Power+" (etc.). These names
  live in the LedFX *engine*, so it's a backend patch (`NAME = "Blade …"`).
- **Decluttered Home** — hides the two rows of stat gauges and the external-links
  (GitHub / Docs / Discord) button row for a cleaner dashboard.
- **Sendspin always-on by default** — effects react the instant playback starts;
  no need to open the UI to "wake" the audio.
- **Lower idle CPU** — default `visualisation_fps` to 15 on the headless box (the
  UI visualiser usually isn't open; raise it in Settings if you want).
- **Dropped armv7** — Home Assistant stopped shipping 32-bit and the from-source
  build breaks there; now aarch64 + amd64 only.

## 1.1.2 — 2026-06-25

- **Fix the ingress reload loop** introduced in 1.1.1. Clearing the saved host on
  every load fought LedFX's own "host unusable → set host + reload" recovery, so
  each reload wiped it again → an infinite flash. Now the add-on *sets*
  `ledfx-host` (and the Known-Hosts list) to the current origin on every load, so
  it's always present and correct (handles the rotating ingress token) and that
  recovery effect never fires. (LAN access unaffected.)

## 1.1.1 — 2026-06-25

- **Fix ingress host flapping / "404, no core" after a while.** The frontend
  keeps the backend URL in `localStorage`, but the HA ingress token rotates each
  session, so a saved host (a stale token URL, the bare Nabu Casa origin,
  `localhost`, the LAN IP) goes 404. The app now clears the saved host +
  Known-Hosts list on every load, so the UI always talks to the **live origin**.
- **Sendspin audio delay option.** New `sendspin_delay_ms` app option. LedFX's
  in-UI delay control is buggy for Sendspin (it silently resets the audio source),
  so set the delay here instead — the app applies it on start and keeps the
  Sendspin device selected. (0–5000 ms; restart to apply.)

## 1.1.0 — 2026-06-25

A polish release: zero-config Home Assistant control, no onboarding friction, and
clean branding.

- **Home Assistant MQTT integration ON by default, auto-configured.** The app
  now declares `services: mqtt:want` and, on start, reads the Mosquitto broker
  host/credentials the Supervisor provides and seeds LedFX's `mqtt_hass`
  integration — **no credentials to type**. It connects on the plaintext `1883`
  listener (the integration has no TLS). You get the standard entities: a light
  per virtual, scene/audio/transition selectors, a play/pause switch, and a pixel
  sensor. (Heads-up: that entity set is intentionally sparse *upstream* — there's
  no per-effect parameter or dedicated brightness entity. Richer control would
  need a separate HACS integration or a custom card against LedFX's REST API.)
- **No onboarding wizard.** The "Setup Assistant" is suppressed and LedFX
  **auto-scans for WLED on startup** (`scan_on_startup`, defaulted on). Re-scan
  any time from **Settings → General → Scan on startup** or by hitting
  `/api/find_devices`.
- **De-Blade.** Removed the "BLADE MOD" sidebar badge and the "Blade Scene"
  onboarding step/strings. (The page title was already de-branded.)

## 1.0.3 — 2026-06-25

- **Fix the UI under Home Assistant ingress** (the LAN URL worked, but the
  sidebar / Nabu Casa stayed blank). Two ingress-specific issues:
  - **Router basename** is now `"/"`. Under ingress the router's in-app location
    is `/`, so the previous dynamic mount-path basename (the full
    `/api/hassio_ingress/<token>/`) didn't match and rendered nothing.
  - **Stale backend host** — clear a `localhost:8888` host left in `localStorage`
    (`ledfx-host` / `ledfx-frontend`) by the old app at the same Nabu Casa
    origin, so the UI talks to its own origin instead of issuing blocked
    mixed-content `ws://localhost:8888` / `http://localhost:8888` calls.

## 1.0.2 — 2026-06-25

- **Fix the blank/black web UI.** The HASS frontend build set the React Router
  `basename` to `"."`, which normalises to `"/."` — and since no URL starts with
  `/.`, the router rendered nothing (blank page on both ingress and the LAN). We
  now set the basename to the actual mount path (`new URL(document.baseURI).pathname`),
  so it matches and renders at the LAN root **and** under the ingress sub-path.

## 1.0.1 — 2026-06-25

- **Fix a startup crash on boxes with no sound card** ("tuple index out of range"
  during audio-device enumeration): ship a null ALSA default device so the device
  list is never empty. Audio still arrives over the network via Sendspin.
- Ensure the engine is the **git-pinned build past 2.1.9**, so the Sendspin
  watchdog fix (no idle reconnect churn) and now-playing metadata are present.
  (1.0.0 images built before the pin landed had the 2.1.9 release.)

## 1.0.0 — 2026-06-25

First release — a clean, HA-native fork of the community LedFX app.

- **Ships the LedFX engine pinned just past 2.1.9** (upstream commit `90bebef8`)
  with the ingress-ready official web UI. The post-release pin brings the
  **Sendspin watchdog fix** (no more idle "no audio → reconnect" churn) and
  **Sendspin now-playing metadata**.
- **Ingress fixed.** The web UI now works through Home Assistant ingress (sidebar
  and Nabu Casa), not just on `localhost`. The frontend was patched to talk to its
  own origin instead of a hard-coded `localhost:8888`, and a stale cached host is
  cleared automatically.
- **Reachable on the LAN.** The engine binds `0.0.0.0`, so `http://<ha-ip>:8888`
  works directly — the old app bound `127.0.0.1` and was unreachable.
- **Audio via Sendspin.** Designed to take its audio from Music Assistant over the
  Sendspin protocol — no sound card, no second machine, no VBAN-from-a-PC.
- **De-branded** packaging: clean name, icon, logo, and panel; no devil-emoji icon
  or "Blade" app branding. (The upstream LedFX UI is unchanged.)
- **Quieter, simpler config:** a single `log_level` option; everything else lives
  in the LedFX UI and persists in `/data`.
