# Changelog

## 0.8.0 — 2026-11-27

- **Keep every piece on the TV, if you like.** *Pieces to keep on the TV*
  (`library_size`, formerly *Art library size*) now takes `0` = keep every piece
  and never delete, alongside `1` (today's piece replaces yesterday's, the
  default) and any number up to 1000 (keep the last N days to browse back
  through with the remote).
- **A failed change is retried in 15 minutes** instead of the next day. Before,
  if the 04:00 change found nothing (the source was down, say), the TV kept
  yesterday's art for another whole day.
- **The HA Matte select shows "off"** when no TV matte is set. It used to sit at
  *unknown*: Home Assistant reads an MQTT select value of `none` as "nothing
  selected". Choosing `off` turns the TV matte off. **If an automation
  selects `none` on that entity, change it to `off`** (HA only accepts listed
  options); automations that set a named matte are unaffected.
- **A TV without Art Mode no longer counts as reached** in the panel's TV
  count.
- **Deletes the TV doesn't confirm are retried** (up to 5 changes) instead of
  being logged as done, so the library can't quietly grow past your setting.
  With `0` nothing is ever deleted, including deletes queued under an earlier
  setting.
- The panel's Collection chip shows what `seasonal`/`weather` resolved to, e.g.
  *seasonal · fall*.
- Under the hood: the app was restructured from one 400-line function into a
  gallery controller (the actions and the loop), a schedule module and a thin
  entry point. The panel page is its own file, the art sources share one HTTP
  helper, and state shared between the panel, HA and the loop is now locked.
  Tests went from 33 to 86 (new: schedule, controller, MQTT entities, TV
  library). Entity ids, topics, `/data` files and options are unchanged.

## 0.7.2 — 2026-11-27

- **Art changes again.** One fall piece on reframed.gallery (*Autumn Landscape*
  by Walter Moras) is a damaged file, cut off just before its end. It was the
  last fall piece you hadn't seen yet, so every change and every **Show next**
  ended in "image file is truncated (27 bytes not processed)". Each image is now
  checked before it's used, and a damaged one is skipped (and not downloaded
  again until the app restarts).
- **A collection that runs out repeats instead of stopping.** When every piece
  in the current collection has been shown within the no-repeat window, the one
  shown longest ago goes up again, instead of nothing at all. Fall has 45 pieces
  and Christmas, which `seasonal` switches to in December, has 29, so this was
  going to stop the gallery again on December 30.
- A pasted link to a damaged piece now says so, instead of failing with a
  decoder error.

## 0.7.1 — 2026-10-08

- **Art shows up again.** reframed.gallery moved its images to a new CDN, so
  every artwork page looked image-less and each change ended in "no usable
  artwork this cycle" — scheduled changes, **Show next**, and pasted links alike.
  The app now reads the page's artwork data (schema.org `VisualArtwork`) and
  pulls the **full-resolution 3840×2160 original** — sharper than the 1400px
  version it used before.
- Titles and artists now come from the gallery itself (proper capitalisation and
  punctuation instead of being rebuilt from the link), and the piece's
  description shows on the panel and in HA.
- Pieces keep the same ids as before, so your no-repeat history and hidden list
  carry over.

## 0.7.0 — 2026-09-09

- **"Never show this."** Curated doesn't mean *to your taste* — when a piece goes
  up that you'd rather not look at all day, one press on the panel retires it for
  good and picks a replacement immediately. The hidden list lives in `/data` next
  to the no-repeat history, so it survives restarts; the panel shows how many
  pieces are hidden with an **Un-hide all** next to it. Previously the only way
  to get rid of a specific piece was to guess a keyword filter that excluded it.
- **New `button.reframed_gallery_hide` entity** — the same thing from Home
  Assistant, so a dashboard tile (or a voice assistant) can retire a piece
  without opening the panel.
- Added tests for the history/hidden store and the panel's endpoints.

## 0.6.1 — 2026-09-09

- MQTT client creation is now explicit about its callback API version, so the
  app works on paho-mqtt 2.x as well as 1.x (`paho-mqtt>=1.6,<3`). No change to
  the entities themselves.
- This changelog now ships with the app, so Home Assistant shows the release
  history in the store.

## 0.6.0 — 2026-08-01

Two things you asked the gallery for: show *this* piece, and stop throwing the old
ones away.

- **Show a specific piece by link** — paste a
  [reframed.gallery](https://www.reframed.gallery) artwork URL into the new **Show
  a specific piece** box on the panel and that exact piece goes up now. Any form of
  the link works (with or without `https://`/`www.`, or just `/artist/artwork`), and
  a link that isn't an artwork page is refused immediately instead of blanking the
  TV. An explicit request skips the collection, the keyword filter and the
  no-repeat window — but still joins the history, so the random picker won't come
  straight back to it. The piece holds until the next scheduled change.
- **New `text.reframed_gallery_show_link` entity** — the same thing from Home
  Assistant, so an automation can put a favourite piece up for a birthday or a
  holiday (`text.set_value` with the URL). Only accepted links are echoed back, so
  the entity never shows a URL the app refused.
- **`library_size` option — keep past days on the TV** — how many pieces stay in
  the Frame's own art library. `1` (the default) keeps the original
  replace-in-place behaviour; `7` keeps a week you can browse back through with the
  remote, deleting the oldest as each new one arrives. Shrinking the number evicts
  the surplus on the next push, a failed delete is still retried, and the app only
  ever deletes images it uploaded itself — your own art and Art Store pieces are
  untouched.
- **Panel chips for both** — a *Your link* chip when the current piece came from a
  link, and *Keeps N on TV* when the library is bigger than one.

## 0.5.0 — 2026-06-25

A feature pass inspired by [Docent](https://github.com/danmunz/docent) — richer
art info, a reworked panel, sturdier TV pushing, TV-rendered mattes, and
weather-aware art. No LLMs, no API keys, no captions burned into the image.

- **Richer artwork details** — the Art Institute source now also pulls **year,
  medium, and movement**, surfaced on the panel and in the *Current Art* sensor's
  attributes. Title / artist / year become quiet **Wikipedia "learn more" links**
  on the panel (hover to reveal) — context without altering the artwork.
- **Reworked control panel** — a larger hero preview; a full caption
  (title · artist · year · medium · movement · source); a status pill showing
  **how many TVs were reached** and a relative "changed N min ago"; collection and
  matte chips; and the browser-tab favicon tints to the current piece.
- **Re-push button** — re-send the current image to the TV(s) without picking a new
  piece (handy when a TV was off or got switched away). Replaces in place.
- **Sturdier TV pushing** — the connect step now **retries with backoff** and,
  given a TV MAC, sends a **Wake-on-LAN** nudge before retrying; the upload itself
  runs exactly once on a verified-live connection, so a lost ack can't duplicate
  art. A definitive TV rejection isn't retried. New **`tv_mac`** option.
- **TV-rendered mattes** — new **`tv_matte`** option (and a **Matte** select in HA)
  to have the Frame draw a real museum mat (e.g. `modern_apricot`,
  `shadowbox_polar`); art is sent full-bleed so it isn't double-framed, and an
  unsupported matte id falls back to none.
- **Weather-aware art** — set Collection to **`weather`** with a **`weather_entity`**
  to map the current HA condition to a fitting collection (rain → nocturnes,
  snow → winter, sun → summer…), falling back to the season.
- **`/healthz` endpoint** — JSON health (status, last change, TVs reached) for
  container/uptime monitoring.

## 0.1.0 — 2026-06-14

First release.

- Self-running Home Assistant app: pushes curated art to a Samsung Frame TV's
  Art Mode on an interval — no automation required.
- **Art Institute of Chicago** source (no API key; CC0 public-domain works via
  high-resolution IIIF images), behind a small plug-in `ArtSource` interface so
  more museums can be added.
- **Content control:** public-domain-only by default, a keyword blocklist
  (family-safe), and a free-text search to shape the collection.
- **No repeats:** remembers the last *N* pieces and cycles instead of
  re-rolling at random.
- **No pile-up:** uploads replace in place (upload → select → delete previous),
  so the TV's art library stays at one image per TV.
- **Auto-discovery:** reads the Frame's IP from the Samsung TV integration; the
  push is Art-Mode-aware (won't interrupt live TV).
- **Fit:** any aspect ratio matted like a framed print, or cropped to fill 16:9.
- **Ingress panel:** shows the current piece with a "Show next now" button.
