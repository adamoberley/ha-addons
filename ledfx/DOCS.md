# LedFX

**Real-time, audio-reactive lighting — running natively on Home Assistant OS.**

LedFX listens to your music and drives the colour and motion of WLED (and other)
LED devices in real time. This add-on runs the full LedFX engine on your HA box —
no second mini-PC, no USB sound card — and gets its audio over the network from
**Music Assistant** via the **Sendspin** protocol, so the lights move in sync with
whatever's playing on your speakers.

## Why this fork

It's a ground-up cleanup of the older community LedFX add-on, fixing the things
that made it frustrating on Home Assistant:

| The old add-on | This one |
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

- **Home Assistant OS or Supervised** (where add-ons run).
- **Music Assistant** add-on **2.7+** running (it *is* the Sendspin server). Yours
  is already there if you play music through HA.
- One or more **WLED** devices (or anything LedFX supports) on your network.

## Install

1. **Settings → Add-ons → Add-on Store → ⋮ (top-right) → Repositories**, add
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

In **Devices**, LedFX auto-discovers WLED on your LAN (host networking is enabled
for exactly this), or add one by IP. Create a **virtual**, drop an audio-reactive
**effect** on it, and it'll move with the music. Save a **scene** to recall looks.

> Heads-up: while an effect is active, LedFX takes **real-time control** of that
> WLED — it'll override presets/automations using the same strip. Point LedFX at
> the lights you want it to own.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| **Log level** | `info` | `debug` is very chatty — use it only to troubleshoot, then switch back. |

That's it — everything else is configured inside the LedFX UI and persists in the
add-on's `/data`.

## Control it from Home Assistant (optional)

LedFX has a built-in **Home Assistant (MQTT)** integration that exposes your
virtuals, effects and scenes as HA entities (it uses MQTT discovery, so it pairs
with your Mosquitto broker). Enable it from **Settings → Integrations** inside
LedFX. You enter the MQTT credentials there yourself.

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
- Set **Log level → debug** and check the add-on **Log** tab for details.

## Credits

The **LedFX** engine and web UI are the work of the
[LedFX project](https://github.com/LedFx/LedFx) (frontend by *Blade* /
[LedFx-Frontend-v2](https://github.com/YeonV/LedFx-Frontend-v2)) — MIT licensed.
**Sendspin** is the [Open Home Foundation](https://www.sendspin-audio.com/) audio
protocol built into **[Music Assistant](https://music-assistant.io)**. This add-on
packages and HA-ifies them; it grew out of the community
[LedFx add-on](https://github.com/YeonV/home-assistant-addons). Not affiliated
with the LedFX project.
