# Adam Oberley's Home Assistant Apps

*A small collection of **local-first** Home Assistant apps — each one runs
natively on Home Assistant OS, does its work on your own box, and keeps your data
off the cloud.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Home Assistant app](https://img.shields.io/badge/Home%20Assistant-app-41BDF5.svg)](https://www.home-assistant.io/)

These are independent apps that happen to share a philosophy: do the work
**on-device**, keep your data **local**, and fit into Home Assistant *properly* —
sidebar ingress, MQTT entities, auto-discovery from integrations you already have —
instead of bolting on a cloud account or a second machine.

| App | What it does | Version |
| --- | --- | --- |
| **[REFRAMED Gallery](frame_gallery/DOCS.md)** | Curated public-domain art on a Samsung **The Frame** TV — switches daily, never repeats, or show any piece by link | `0.6.0` |
| **[Local Faces](local_faces/DOCS.md)** | On-device **face recognition** from your cameras — recognized names become an HA sensor | `0.5.0` |
| **[LedFX](ledfx/DOCS.md)** | Real-time **audio-reactive lighting** for WLED, fed by Music Assistant over Sendspin | `1.7.2` |
| **[Hue Entertainment](hue_ent/DOCS.md)** | Stream LedFX effects to **Philips Hue Zigbee bulbs** on zigbee2mqtt at 20–25 fps — no Hue Bridge | `0.3.0` |

## Install

They all live in this single repository. Add it once, then install whichever you
want:

1. **Settings → Apps → App Store → ⋮ (top-right) → Repositories**:

   [![Add repository to your Home Assistant.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fadamoberley%2Fha-addons)

   …or paste `https://github.com/adamoberley/ha-addons`.
2. They appear in the store under **Adam Oberley's Home Assistant Apps**.
   Install one, **Start** it, and open its sidebar panel.

Each app has its own setup guide (linked per section below). Most need little or
no configuration.

---

## REFRAMED Gallery

*Turn a Samsung **The Frame** into a self-running gallery of curated public-domain
art.*

Point it at your Frame and forget it: on a schedule (daily by default) it pulls a
fresh, family-safe public-domain piece, fits it to the panel, and shows it in Art
Mode — **replacing** the previous upload so the art library never piles up, and
**never repeating** recently shown works. No automation required.

- **Or show one specific piece** — paste a reframed.gallery artwork link into the
  panel (or set the *Show link* entity from an automation) and that exact piece
  goes up now, whatever the collection says. Good for birthdays and holidays.
- **Keeps a library, if you want one** — `library_size` decides how many pieces
  stay in the TV's own art library: 1 replaces in place, 7 keeps a week you can
  browse back through with the remote.
- **Curated by default** — pulls from **[reframed.gallery](https://reframed.gallery)**,
  a Frame-ready public-domain collection, including **seasonal** sets that
  auto-track the date (Winter/Spring/Summer/Fall, Christmas in December, with a
  Southern-hemisphere flip). Or switch the source to the **Art Institute of
  Chicago**'s full catalogue, or shape either with a free-text `query`.
- **Family-safe** — public-domain (CC0) works only by default, plus a keyword
  content filter you can tune.
- **Fits your panel** — 4K or 1080p; cropped to fill, matted like a framed print,
  or with a **TV-rendered Samsung matte** (the Frame draws a real museum mat).
- **Knows its art** — pulls **year, medium, and movement**, shown on the panel and
  in the *Current Art* sensor, with quiet **Wikipedia "learn more" links**.
- **Weather-aware (optional)** — point it at a weather entity and it picks a
  collection to match the day (rain → nocturnes, snow → winter, sun → summer…).
- **HA-native** — auto-discovers the Frame from the Samsung TV integration; exposes
  *Current Art*, *Next*, *Collection*, *Matte*, and *Show link* entities over MQTT;
  a reworked sidebar panel shows the current piece (with details) plus *Show next*
  and *Re-push to TV* buttons. Sturdy pushing with retry + optional Wake-on-LAN.

→ Full setup & options: [`frame_gallery/DOCS.md`](frame_gallery/DOCS.md)

## Local Faces

*On-device, open-source face recognition for Home Assistant.*

Point it at one or more cameras, enroll a few people from the built-in dashboard,
and recognized names show up in HA as a sensor you can automate off — unlock for
known people, alert on an unknown at the door, announce arrivals.

- **On-device, CPU-only** — light enough for a Raspberry Pi 4/5; no GPU, no cloud,
  no per-face subscription.
- **Open models** — YuNet (detection) + SFace (recognition), both Apache-2.0 from
  the OpenCV Zoo; optionally swap in a stronger ArcFace/MobileFaceNet embedder.
- **Multi-camera** — analyzes several streams round-robin (flat CPU as you add
  cameras); each gets its own recognized-name sensor, plus an aggregate.
- **Enrollment dashboard** — live camera view; capture or upload a face; **click
  any recent sighting to blow it up and name it**, with name autocomplete so you
  can feed several shots of the same person and sharpen recognition over time.
- **Local by default** — detection, enrollment, and the sighting log live in the
  app's `/data`; only an optional push notification ever leaves your network.

→ Full setup & tuning: [`local_faces/DOCS.md`](local_faces/DOCS.md)

## LedFX

*Real-time, audio-reactive lighting — running natively on Home Assistant OS.*

LedFX listens to your music and drives the colour and motion of your **WLED** (and
other) lights in sync with it. This app runs the full engine on your HA box and
takes its audio over the network from **Music Assistant** via the **Sendspin**
protocol — **no sound card, no second mini-PC, no VBAN-from-a-PC**.

It's a clean fork of the community LedFX app, fixed for a first-class HA
experience:

- **Ingress that actually works** — the web UI runs in the HA sidebar (and via Nabu
  Casa), not just on `localhost`; also reachable directly at `http://<ha-ip>:8888`.
- **Audio with no hardware** — Sendspin from Music Assistant (2.7+); no mic, no
  loopback, no capture card. An optional `sendspin_delay_ms` lines the lights up
  with your speakers.
- **Zero-config** — no setup wizard: it **auto-scans for WLED** on start, and the
  **Home Assistant (MQTT)** integration turns on automatically using your
  Mosquitto broker (no credentials to enter).
- **De-branded** — clean name, icon, logo, and sidebar panel.
- A recent LedFX engine (pinned just past 2.1.9 for the Sendspin watchdog fix and
  now-playing metadata).

> **Heads up:** LedFX is under active development and getting a larger overhaul, so
> expect things to move. See [`ledfx/CHANGELOG.md`](ledfx/CHANGELOG.md) for the
> latest.

→ Full setup, including the Music Assistant / Sendspin wiring:
[`ledfx/DOCS.md`](ledfx/DOCS.md)

## Hue Entertainment

*Audio-reactive **Philips Hue** — driven by LedFX, straight over zigbee2mqtt, no
Hue Bridge.*

Most Hue setups get audio-reactive lighting only through a Hue Bridge and the
Entertainment API. If your Hue bulbs are paired to **zigbee2mqtt** instead, the
obvious path — one MQTT `set` per bulb per frame — tops out around **6 fps** and
floods the Zigbee queue, so it's unusable. This app makes it actually work: it
takes LedFX's pixel output and speaks the reverse-engineered **Hue Entertainment**
Zigbee protocol through Z2M, hitting a smooth **20–25 fps** with no Bridge and no
special coordinator firmware.

- **The fast path Hue uses itself** — one compact Zigbee frame per zone per tick,
  unicast to a single *proxy* bulb that re-broadcasts to the rest. Bulbs
  **interpolate** between targets (the same trick a real Hue Bridge uses), so
  20–25 fps looks continuous. That's ~4× the naive rate, without the queue flood.
- **Stock Z2M, no Bridge** — rides zigbee2mqtt's generic `zclcommand` passthrough
  (needs Z2M **2.1.1+**); no forked Z2M, no exotic radio firmware. Verified on a
  plain TI CC2652.
- **Per-room zones** — up to 10 bulbs each (the Zigbee frame limit). Each zone gets
  its own DDP input and target frame rate.
- **Zones build themselves** — color Hue bulbs are grouped by HA area into one
  zone per room (Adaptive Lighting switch auto-detected too); a **sidebar panel**
  handles the human parts: pixel order with a per-bulb *Blink* identifier, proxy
  choice, brightness, and per-room enable toggles. Edits apply live.
- **HA-native & tidy** — one **Hue Entertainment \<zone\>** switch per zone via MQTT
  discovery. Arming captures each bulb's state and **pauses your Adaptive Lighting**
  for that room; disarming **restores every bulb** to exactly where it was. Auto-arms
  when LedFX starts sending and releases the lights when the music stops — and *off
  means off* if you kill a zone by hand mid-song.
- **Feeds straight from LedFX, zero mirroring** — it auto-creates one matching
  DDP device per zone in the LedFX app (also in this repo) through LedFX's API;
  you just pick effects.

> **Heads up:** this rides a reverse-engineered protocol, so treat it as
> experimental. It's been validated end-to-end on real hardware, but firmware and
> Z2M updates could move things.

→ Full setup, zones, and LedFX wiring: [`hue_ent/DOCS.md`](hue_ent/DOCS.md)

---

## What ties them together

- **Local-first.** Your art history, enrolled faces, and audio stay on the box.
  The only thing that can leave is an optional notification you opt into.
- **Native to Home Assistant OS.** Sidebar ingress (authenticated by HA — no extra
  login), MQTT discovery for entities, and auto-discovery from integrations you
  already run. Everything is configured from the app UI; state lives in `/data`.
- **Runs on a Pi.** Multi-arch images (`aarch64` / `amd64` / `armv7`).

## Repo layout & development

Each app is a self-contained folder — `frame_gallery/`, `local_faces/`,
`ledfx/`, `hue_ent/` — with its own `Dockerfile`, `config.yaml` (manifest +
version + options schema), and `DOCS.md`. Versions are bumped independently in
each `config.yaml`; release notes live in the repo-wide
[`CHANGELOG.md`](CHANGELOG.md) (LedFX also keeps a per-app `ledfx/CHANGELOG.md`
for its in-app Changelog tab). Python is linted with
[ruff](https://docs.astral.sh/ruff/) (`ruff.toml`).

**Why one repo (not branches per app):** this is the standard Home Assistant
*app/add-on repository* layout — the Supervisor reads every app folder from a
**single branch** (`main`), so one repository URL exposes all three in the store.
Separate branches wouldn't "come together": HA only ever reads one branch, so they
can't form a unified store, and you'd lose the one-URL install. The folder-per-app
+ independent `config.yaml` versions you have here *is* the best-practice way to
keep three apps tidy in one repo. (Splitting into three separate repos is possible
but means three URLs to add and three READMEs to maintain — more overhead, not
less, for a personal collection.)

## Credits & license

Code: **MIT** (see [LICENSE](LICENSE)).

- **REFRAMED Gallery** talks to the TV with
  [`samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api); art comes
  from [reframed.gallery](https://reframed.gallery) and the
  [Art Institute of Chicago API](https://api.artic.edu/docs/) (CC0 public-domain
  works). The TV-side approach (upload → select → delete, Art-Mode-aware push,
  auto-discovery) grew out of the
  [Bird Frame](https://github.com/adamoberley/HABirdDashboard) app.
- **Local Faces** uses YuNet + SFace from the
  [OpenCV Zoo](https://github.com/opencv/opencv_zoo).
- **LedFX** is a fork of [LedFX](https://github.com/LedFx/LedFx) and the community
  Home Assistant app.
- **Hue Entertainment** builds on the reverse-engineering of Hue's Zigbee
  Entertainment protocol by [Hypfer/BambiHeavy](https://github.com/Hypfer/BambiHeavy)
  and [chrivers/bifrost](https://github.com/chrivers/bifrost), and the
  [zigbee2mqtt discussion](https://github.com/Koenkk/zigbee2mqtt/discussions/5830)
  that started it. It drives bulbs through stock
  [zigbee2mqtt](https://github.com/Koenkk/zigbee2mqtt).

Not affiliated with Samsung, any museum, Philips/Signify, the Home Assistant
project, the LedFX project, or the zigbee2mqtt project.
