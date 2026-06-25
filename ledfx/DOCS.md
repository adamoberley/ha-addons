# LedFX

**Real-time, audio-reactive lighting — running natively on Home Assistant OS.**

LedFX listens to your music and drives the colour and motion of WLED (and other)
LED devices in real time. This app runs the full LedFX engine on your HA box —
no second mini-PC, no USB sound card — and gets its audio over the network from
**Music Assistant** via the **Sendspin** protocol, so the lights move in sync with
whatever's playing on your speakers.

## Why this fork

It's a ground-up cleanup of the older community LedFX app, fixing the things
that made it frustrating on Home Assistant:

| The old app | This one |
| --- | --- |
| Web UI only worked on `localhost` — **"no core found" / dead graphs through ingress** | UI works under **HA ingress** (sidebar, Nabu Casa) *and* directly on the LAN |
| Bound to `127.0.0.1` — **unreachable at `http://<ha-ip>:8888`** | Binds the LAN, so direct access just works |
| Experimental "Blade" branding + devil-emoji icon | Clean LedFX packaging |
| Audio needed a sound card / VBAN from a PC | **Sendspin** from Music Assistant — no hardware, no second box |

The LedFX **engine** is upstream LedFX pinned just *past* the 2.1.9 release, to
pick up post-release fixes that matter here — most importantly the **Sendspin
watchdog** no longer forcing a reconnect while a stream is idle (the old "no audio
for 20s → reconnect" churn), plus **Sendspin now-playing metadata**. The **web UI**
is the official LedFX frontend (the HASS-optimised build, which uses relative paths
so it works under ingress); we patch only how it discovers its backend.

## Requirements

- **Home Assistant OS or Supervised** (where apps run).
- **Music Assistant** app **2.7+** running (it *is* the Sendspin server). Yours
  is already there if you play music through HA.
- One or more **WLED** devices (or anything LedFX supports) on your network.

## Install

1. **Settings → Apps → App Store → ⋮ (top-right) → Repositories**, add
   `https://github.com/adamoberley/ha-addons`.
2. Install **LedFX** and **Start** it. (First start builds the image — a few
   minutes.)
3. Open it from the **LedFX** sidebar panel, or directly at
   `http://<your-ha-ip>:8888`.

## Connect the audio (Music Assistant → Sendspin)

LedFX needs to *hear* the music. Sendspin streams it over the network — no mic, no
loopback:

1. In the LedFX UI: **Settings → Sendspin** (a.k.a. *Sendspin Audio Streaming*).
2. **Auto-discover**, or add the server manually:
   - **Server URL:** `ws://<your-ha-ip>:8927/sendspin`
   - **Client name:** `LedFx`
3. Pick the **Sendspin** entry as the active audio device.
4. Play something in Music Assistant — the audio meter should move.

> Tip: turning on **"Sendspin always on"** keeps the link live so effects react
> instantly when playback starts.

## Add your lights

LedFX **auto-scans for WLED on startup** (host networking is enabled for exactly
this), so your devices show up in **Devices** on their own — there's no setup
wizard. Need to scan again? **Settings → General → Scan on startup** (or just
restart the app); you can also add a device by IP. Then drop an audio-reactive
**effect** on a device and it'll move with the music. Save a **scene** to recall
looks.

> Heads-up: while an effect is active, LedFX takes **real-time control** of that
> WLED — it'll override presets/automations using the same strip. Point LedFX at
> the lights you want it to own.

> **Seeing "2 devices" but only one card?** A device is the controller; the card
> is its *virtual*. If a virtual didn't get created, restart the app (the
> startup scan re-adds it) or re-add the device by IP. Giving each controller a
> unique name avoids an ID collision that can drop the second virtual.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| **Log level** | `info` | `debug` is very chatty — use it only to troubleshoot, then switch back. |

That's it — everything else is configured inside the LedFX UI and persists in the
app's `/data`.

## Control it from Home Assistant

This is set up **automatically** — no configuration. On start, the app reads
your **Mosquitto** broker details from the Supervisor and turns on LedFX's
built-in **Home Assistant (MQTT)** integration, so LedFX entities appear in HA via
MQTT discovery with **no credentials to enter**. You get:

- a **light** per virtual (on/off, plus colour when the effect is *Single Color*,
  and effect selection),
- **selects** for the active **scene**, **audio** input, and **transition** type,
- a **Transition time** number, a global **Play/Pause** switch, and a **Used
  Pixels** sensor.

> **Scope:** this is LedFX's upstream integration and its controls are
> deliberately limited — there's no per-effect parameter or dedicated brightness
> entity. For richer dashboard control, a custom Lovelace card driving LedFX's
> REST API is the way (a possible future addition). To turn the integration off,
> disable it in **Settings → Integrations** inside LedFX — the app won't
> re-enable a choice you've made.

If your Mosquitto only exposes the TLS listener (8883), enable the plaintext
**1883** listener too — LedFX's MQTT integration doesn't do TLS.

## Accessing the UI

- **Sidebar / ingress** — authenticated by Home Assistant, works remotely via
  Nabu Casa. Best for everyday use.
- **Direct LAN** — `http://<your-ha-ip>:8888`, full-speed, no extra login. Best
  for first-time setup and heavy editing. Note this port is **unauthenticated on
  your LAN** (like WLED or Music Assistant themselves).

## Troubleshooting

- **"No core found" / can't save / blank graphs through the sidebar** — hard-reload
  the page (the UI caches its backend host; this build clears a stale
  `localhost` one automatically, but a forced refresh helps). If it persists, use
  the direct `http://<ha-ip>:8888` URL and confirm there.
- **Lights don't react** — make sure something is *playing* in Music Assistant and
  the **Sendspin** device is the active audio input. (This build's watchdog stays
  quiet while playback is idle and only reconnects on a genuinely stalled stream.)
- **WLED not found** — add it by IP in **Devices**; confirm the strip is reachable
  from HA.
- **Sendspin server not discovered** — add it manually:
  `ws://<your-ha-ip>:8927/sendspin`.
- **Effects stutter / high CPU** — lower the effect's FPS or the device pixel
  count; real-time audio effects are CPU-bound.
- Set **Log level → debug** and check the app **Log** tab for details.

## Credits

The **LedFX** engine and web UI are the work of the
[LedFX project](https://github.com/LedFx/LedFx) (frontend by *Blade* /
[LedFx-Frontend-v2](https://github.com/YeonV/LedFx-Frontend-v2)) — MIT licensed.
**Sendspin** is the [Open Home Foundation](https://www.sendspin-audio.com/) audio
protocol built into **[Music Assistant](https://music-assistant.io)**. This app
packages and HA-ifies them; it grew out of the community
[LedFx app](https://github.com/YeonV/home-assistant-addons). Not affiliated
with the LedFX project.
