# Changelog

## 1.0.3 — 2026-06-25

- **Fix the UI under Home Assistant ingress** (the LAN URL worked, but the
  sidebar / Nabu Casa stayed blank). Two ingress-specific issues:
  - **Router basename** is now `"/"`. Under ingress the router's in-app location
    is `/`, so the previous dynamic mount-path basename (the full
    `/api/hassio_ingress/<token>/`) didn't match and rendered nothing.
  - **Stale backend host** — clear a `localhost:8888` host left in `localStorage`
    (`ledfx-host` / `ledfx-frontend`) by the old add-on at the same Nabu Casa
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

First release — a clean, HA-native fork of the community LedFX add-on.

- **Ships the LedFX engine pinned just past 2.1.9** (upstream commit `90bebef8`)
  with the ingress-ready official web UI. The post-release pin brings the
  **Sendspin watchdog fix** (no more idle "no audio → reconnect" churn) and
  **Sendspin now-playing metadata**.
- **Ingress fixed.** The web UI now works through Home Assistant ingress (sidebar
  and Nabu Casa), not just on `localhost`. The frontend was patched to talk to its
  own origin instead of a hard-coded `localhost:8888`, and a stale cached host is
  cleared automatically.
- **Reachable on the LAN.** The engine binds `0.0.0.0`, so `http://<ha-ip>:8888`
  works directly — the old add-on bound `127.0.0.1` and was unreachable.
- **Audio via Sendspin.** Designed to take its audio from Music Assistant over the
  Sendspin protocol — no sound card, no second machine, no VBAN-from-a-PC.
- **De-branded** packaging: clean name, icon, logo, and panel; no devil-emoji icon
  or "Blade" add-on branding. (The upstream LedFX UI is unchanged.)
- **Quieter, simpler config:** a single `log_level` option; everything else lives
  in the LedFX UI and persists in `/data`.
