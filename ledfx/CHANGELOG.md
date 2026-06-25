# Changelog

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
