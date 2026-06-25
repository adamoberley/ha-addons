# Adam Oberley's Home Assistant Add-ons

*A small collection of **local-first** Home Assistant add-ons — each one runs
natively on Home Assistant OS, does its work on your own box, and keeps your data
off the cloud.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Home Assistant add-on](https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5.svg)](https://www.home-assistant.io/)

These are three independent add-ons that happen to share a philosophy: do the work
**on-device**, keep your data **local**, and fit into Home Assistant *properly* —
sidebar ingress, MQTT entities, auto-discovery from integrations you already have —
instead of bolting on a cloud account or a second machine.

| Add-on | What it does | Version |
| --- | --- | --- |
| **[REFRAMED Gallery](frame_gallery/DOCS.md)** | Curated public-domain art on a Samsung **The Frame** TV — switches daily, never repeats, replaces in place | `0.4.1` |
| **[Local Faces](local_faces/DOCS.md)** | On-device **face recognition** from your cameras — recognized names become an HA sensor | `0.5.0` |
| **[LedFX](ledfx/DOCS.md)** | Real-time **audio-reactive lighting** for WLED, fed by Music Assistant over Sendspin | `1.0.1` |

## Install

All three live in this single repository. Add it once, then install whichever you
want:

1. **Settings → Add-ons → Add-on Store → ⋮ (top-right) → Repositories**:

   [![Add repository to your Home Assistant.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fadamoberley%2Fha-addons)

   …or paste `https://github.com/adamoberley/ha-addons`.
2. They appear in the store under **Adam Oberley's Home Assistant Add-ons**.
   Install one, **Start** it, and open its sidebar panel.

Each add-on has its own setup guide (linked per section below). Most need little or
no configuration.

---

## REFRAMED Gallery

*Turn a Samsung **The Frame** into a self-running gallery of curated public-domain
art.*

Point it at your Frame and forget it: on a schedule (daily by default) it pulls a
fresh, family-safe public-domain piece, fits it to the panel, and shows it in Art
Mode — **replacing** the previous upload so the art library never piles up, and
**never repeating** recently shown works. No automation required.

- **Curated by default** — pulls from **[reframed.gallery](https://reframed.gallery)**,
  a Frame-ready public-domain collection, including **seasonal** sets that
  auto-track the date (Winter/Spring/Summer/Fall, Christmas in December, with a
  Southern-hemisphere flip). Or switch the source to the **Art Institute of
  Chicago**'s full catalogue, or shape either with a free-text `query`.
- **Family-safe** — public-domain (CC0) works only by default, plus a keyword
  content filter you can tune.
- **Fits your panel** — 4K or 1080p; cropped to fill, or matted like a framed print.
- **HA-native** — auto-discovers the Frame from the Samsung TV integration; exposes
  a *Current Art* sensor, a *Next* button, and a *Collection* select over MQTT; a
  sidebar panel shows the current piece with a "show next" button.

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
  add-on's `/data`; only an optional push notification ever leaves your network.

→ Full setup & tuning: [`local_faces/DOCS.md`](local_faces/DOCS.md)

## LedFX

*Real-time, audio-reactive lighting — running natively on Home Assistant OS.*

LedFX listens to your music and drives the colour and motion of your **WLED** (and
other) lights in sync with it. This add-on runs the full engine on your HA box and
takes its audio over the network from **Music Assistant** via the **Sendspin**
protocol — **no sound card, no second mini-PC, no VBAN-from-a-PC**.

It's a clean fork of the community LedFX add-on, fixed for a first-class HA
experience:

- **Ingress that actually works** — the web UI runs in the HA sidebar (and via Nabu
  Casa), not just on `localhost`; also reachable directly at `http://<ha-ip>:8888`.
- **Audio with no hardware** — Sendspin from Music Assistant (2.7+); no mic, no
  loopback, no capture card.
- **De-branded** — clean name, icon, logo, and sidebar panel.
- A recent LedFX engine (pinned just past 2.1.9 for the Sendspin watchdog fix and
  now-playing metadata), with an optional Home Assistant (MQTT) integration.

> **Heads up:** LedFX is under active development and getting a larger overhaul, so
> expect things to move. See [`ledfx/CHANGELOG.md`](ledfx/CHANGELOG.md) for the
> latest.

→ Full setup, including the Music Assistant / Sendspin wiring:
[`ledfx/DOCS.md`](ledfx/DOCS.md)

---

## What ties them together

- **Local-first.** Your art history, enrolled faces, and audio stay on the box.
  The only thing that can leave is an optional notification you opt into.
- **Native to Home Assistant OS.** Sidebar ingress (authenticated by HA — no extra
  login), MQTT discovery for entities, and auto-discovery from integrations you
  already run. Everything is configured from the add-on UI; state lives in `/data`.
- **Runs on a Pi.** Multi-arch images (`aarch64` / `amd64` / `armv7`).

## Repo layout & development

Each add-on is a self-contained folder — `frame_gallery/`, `local_faces/`,
`ledfx/` — with its own `Dockerfile`, `config.yaml` (manifest + version + options
schema), and `DOCS.md`. Versions are bumped independently in each `config.yaml`;
release notes for all three live in [`CHANGELOG.md`](CHANGELOG.md). Python is
linted with [ruff](https://docs.astral.sh/ruff/) (`ruff.toml`).

## Credits & license

Code: **MIT** (see [LICENSE](LICENSE)).

- **REFRAMED Gallery** talks to the TV with
  [`samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api); art comes
  from [reframed.gallery](https://reframed.gallery) and the
  [Art Institute of Chicago API](https://api.artic.edu/docs/) (CC0 public-domain
  works). The TV-side approach (upload → select → delete, Art-Mode-aware push,
  auto-discovery) grew out of the
  [Bird Frame](https://github.com/adamoberley/HABirdDashboard) add-on.
- **Local Faces** uses YuNet + SFace from the
  [OpenCV Zoo](https://github.com/opencv/opencv_zoo).
- **LedFX** is a fork of [LedFX](https://github.com/LedFx/LedFx) and the community
  Home Assistant add-on.

Not affiliated with Samsung, any museum, the Home Assistant project, or the LedFX
project.
