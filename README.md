# Frame Gallery

*A Home Assistant app that turns your Samsung **The Frame** into a self-running
gallery of curated public-domain art.*

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Home Assistant add-on](https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5.svg)](https://www.home-assistant.io/)

Point it at your Frame and forget it: every so often it pulls a fresh, family-safe
public-domain piece from a museum, fits it to the panel, and shows it in Art
Mode — **replacing** the last one so nothing piles up, and **never repeating**
recently shown works.

It's a ground-up replacement for the older Google/Bing art-changers, built to fix
the things that made them frustrating:

| The old way | Frame Gallery |
| --- | --- |
| **Unpredictable, sometimes not-family-friendly** images from Google Art | Public-domain museum art you shape with a **search** + a **keyword content filter** |
| The **same few pieces** on repeat | Remembers the last *N* shown and cycles — no re-rolling |
| Uploads **pile up** in the TV's art library forever | Each piece **replaces** the last (upload → select → delete) |
| Needed a separate **automation** to fire it | A long-running service with its **own interval** |
| One opaque source | A **plug-in source layer** — add museums freely |

## Requirements

- A Samsung **The Frame** TV (the line with Art Mode), reachable on your network.
- **Home Assistant OS or Supervised** (where add-ons/apps run).
- The **Samsung TV integration** set up for your Frame (for auto-discovery) —
  or just enter the TV's IP.

## Install

1. **Settings → Add-ons → Add-on Store → ⋮ (top-right) → Repositories**, and add:

   [![Add repository to your Home Assistant.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fadamoberley%2Fha-frame-gallery)

   …or paste `https://github.com/adamoberley/ha-frame-gallery`.
2. Install **Frame Gallery** and **Start** it, with the TV **on** and the remote
   handy — accept the *"Allow connection?"* (and first-time **Art Store terms**)
   prompts on the TV.
3. Put the TV in **Art Mode**. A new piece appears each interval.

Usually **no configuration is needed** — it auto-discovers your Frame. Tweak the
look and the collection from the **Configuration** tab; full reference in
[`frame_gallery/DOCS.md`](frame_gallery/DOCS.md).

## Also in this repository: Local Faces

A second, independent add-on: **[Local Faces](local_faces/DOCS.md)** — open-source,
on-device **face recognition** for Home Assistant. Point it at a camera, enroll a
few people from its dashboard, and recognized names show up in HA as a
`sensor.recognized_name` you can automate off (unlock for known people, alert on
unknown, announce arrivals).

- **On-device, CPU-only** — light enough for a Raspberry Pi 4/5; no GPU, no cloud.
- **Open models** — YuNet (detection) + SFace, a MobileFaceNet-style embedder
  (recognition), both Apache-2.0 from the OpenCV Zoo, run via OpenCV's bundled DNN.
- **Local by default** — recognition, enrollment, and the log stay on the box;
  only an optional push notification ever leaves your network.

Install it from the same repository (it appears alongside Frame Gallery). Full
setup and tuning in [`local_faces/DOCS.md`](local_faces/DOCS.md).

## Shaping the collection (and keeping it family-friendly)

- **`query`** — a free-text search that defines the whole gallery, e.g.
  `landscape`, `impressionism`, `ukiyo-e`, `still life`, `Monet`. Blank pulls
  from the entire public-domain catalogue.
- **`public_domain_only`** (default on) — only CC0 works, so the licensing is
  always clean for display.
- **`exclude_keywords`** — a content filter: any work whose title/artist/subject
  tags match a listed term is skipped. Ships with sensible mature-content
  defaults; edit to taste.

Choosing a focused `query` *and* keeping the keyword filter on lets you curate a
room-appropriate collection, rather than trusting an opaque "random art" feed.

## How it works

Each interval (or when you press **Show next** on the sidebar panel):

1. ask an open museum API for a batch of works;
2. filter — public-domain, keyword blocklist, and not shown recently;
3. download one and fit it to the panel (matted like a framed print, or cropped
   to fill);
4. push it to the Frame, **deleting** the piece it replaces.

State (pairing token, current-art id, recent history) lives in the add-on's
`/data`.

## Adding an art source

Sources are a thin plug-in. To add one (Met, Rijksmuseum, Smithsonian, Wikimedia,
Unsplash, …), subclass `ArtSource` in `frame_gallery/app/sources/` and implement
one method:

```python
from sources.base import Artwork, ArtSource

class MetSource(ArtSource):
    name = "met"
    def candidates(self, opts, count=100) -> list[Artwork]:
        # query your API; return Artwork(source, id, title, artist, image_url,
        # public_domain=..., tags="lowercased searchable text", credit="...")
        ...
```

Then add it to the `sources` list in `main.py`. The picker handles filtering,
de-duplication, downloading, and fitting; the `tags` string is what the keyword
blocklist matches against.

## Roadmap

- More sources (Met Open Access is key-free and next), with per-source toggles.
- Department/collection pickers (beyond free-text search).
- A small test suite for the source adapters.

## Credits & license

Code: **MIT** (see [LICENSE](LICENSE)). Talks to the TV with
[`samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api). Artwork via
the [Art Institute of Chicago API](https://api.artic.edu/docs/) — public-domain
works are CC0. Not affiliated with any museum.

The TV-side approach (upload → select → delete, Art-Mode-aware push,
auto-discovery from the Samsung TV integration) grew out of the
[Bird Frame](https://github.com/adamoberley/HABirdDashboard) add-on.
