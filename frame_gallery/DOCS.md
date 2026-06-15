# Frame Gallery

Curated **public-domain art on your Samsung Frame TV**, changed on its own
interval — no Google/Bing, no automation, no pile-up, no repeats, and content
you control.

## Why this instead of the older art-changers

| Old art-changer | Frame Gallery |
| --- | --- |
| **Unpredictable, sometimes mature** images from Google Art | Public-domain museum art + a keyword content filter + a search to shape the collection |
| The **same pieces** over and over | Remembers the last *N* shown; never repeats until the pool is exhausted |
| Uploads **pile up** in the art library | Upload → select → **delete the previous one**; one image, swapped in place |
| Needed an **automation** to run | A long-running service with its own interval |

## How it works

Each interval — or when you press **Show next** on the panel — it:

1. asks an open museum API for a batch of works;
2. filters them (public-domain, keyword blocklist, not shown recently);
3. downloads one and fits it to your panel (matted like a framed print, or
   cropped to fill);
4. pushes it to the Frame, **deleting** the piece it replaces.

The push is Art-Mode-aware: if you're watching TV it just sets the next art
without interrupting; switch to Art Mode to see it. Source for v0.1: the **Art
Institute of Chicago** (no key, CC0 IIIF images). More can be added — the source
layer is a plug-in.

## Setup

1. **Install** this app (you added the repo under *Settings → Add-ons → ⋮ →
   Repositories*).
2. Usually **nothing to configure** — it auto-discovers your Frame from the
   Samsung TV integration. Optionally set **Art search** (e.g. `landscape`).
3. **Start** it with the TV **on** and the remote handy, and accept on the TV:
   - the one-time *"Allow this device to connect?"* pairing prompt, and
   - the **Art Store / terms** prompt the first time (the TV blocks uploads
     until these are accepted — the usual cause of a first upload failing).
4. Put the TV in **Art Mode**. A new piece appears each interval.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| **Art search** (`query`) | *(blank)* | Free-text search that shapes the whole collection: `landscape`, `impressionism`, `ukiyo-e`, `Monet`… Blank = all public-domain works. |
| **Public domain only** | on | Only show CC0 works (recommended — clean licensing). |
| **Excluded keywords** | *(mature-content terms)* | Comma-separated; any work whose title/artist/tags match a listed term is skipped. Blank to disable. |
| **Change interval** | 60 | Minutes between pieces. |
| **Fit** | matte | `matte` frames the whole work on a mat (nothing cropped); `crop` fills the panel and trims the edges. |
| **Mat color** | `#141414` | Background behind matted art (hex). Dark avoids glare at night. |
| **No-repeat memory** | 500 | Don't repeat the last *N* pieces (0 = allow repeats). |
| **Active hours** | *(blank)* | Blank = 24/7, or a local-time window like `07:00-23:00`. |
| **Panel resolution** | 3840x2160 | Match your panel (1920x1080 for 32"/pre-2021). |
| **Frame TV IP(s)** | *(blank)* | Blank = auto-discover; or comma-separated IPs to override. |

The sidebar **Frame Gallery** panel shows the current piece (title, artist,
source) with a **Show next now** button for instant changes.

## Content safety

Three layers, all under your control:

- **Public-domain only** keeps the pool to CC0 works.
- **Art search** lets you pick benign themes (landscapes, still lifes, a specific
  movement or artist) so the whole collection fits your room.
- **Excluded keywords** vetoes anything whose museum metadata (title, artist,
  department, classification, subject) matches a word you list.

This is metadata-based, not a content rating, so it isn't infallible on its own —
but combining a focused `query` with the keyword filter makes mature imagery
extremely unlikely. Tighten `query` if you want a guaranteed-tame collection.

## Troubleshooting

- **First upload fails / `ms.channel.timeOut` / `send_image error -2`** — accept
  the **Allow** and **Art Store terms** prompts on the TV (it blocks uploads
  until you do), then restart.
- **Image is set but the TV doesn't switch to it** — it uses Art-Mode-aware
  pushing; switch the TV to Art Mode to see it.
- **"no artwork found"** — your `query` is too narrow or everything matched a
  blocked keyword; broaden or clear `query`.
- **TV not found** — set **Frame TV IP(s)** manually (the Samsung TV integration
  must be configured, or pass the IP).
- **Rate-limited source** — transient; it backs off and retries next cycle. Set
  **Log level** to `debug` to see source and TV steps.

## Credits

Talks to the TV with [`samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api).
Art via the [Art Institute of Chicago API](https://api.artic.edu/docs/)
(public domain / CC0). Not affiliated with the museum.
