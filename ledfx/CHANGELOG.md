# Changelog

## 1.0.0 — 2026-06-25

First release — a clean, HA-native fork of the community LedFX add-on.

- **Ships LedFX 2.1.9** (the official engine) with the ingress-ready official web UI.
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
