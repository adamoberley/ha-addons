# Changelog

## LedFX 1.7.2 — 2026-09-08

**Sendspin audio couldn't connect at all.** Every attempt failed before it reached
the network with `SendspinClient.__init__() got an unexpected keyword argument
'client_id'`, so the lights never heard Music Assistant
([#11](https://github.com/adamoberley/ha-addons/issues/11)). `aiosendspin` 7.0
replaced the client's `client_id` with an X25519 identity plus a pairing store, and
LedFX still asks for a bare `aiosendspin>=4.0.0` — so any image built after 7.0
shipped got an incompatible library. Now pinned to `aiosendspin==6.1.1` (the range
upstream LedFX itself caps to), and the build *verifies* the client API so a future
dependency drift fails loudly instead of shipping silent-audio lights. **Rebuild
the app** after updating so the image picks up the pin.

## REFRAMED Gallery 0.6.0 — 2026-08-01

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

## Hue Entertainment 0.3.0 — 2026-07-02

Zero-config setup: zones now build themselves from your Home Assistant rooms
(color Hue bulbs grouped by area, Adaptive Lighting switch auto-detected), and
a new sidebar panel handles the human parts — pixel order with a per-bulb
Blink identifier, proxy choice, fps/brightness, enable toggles, and a
test-stream button. Edits apply live.

## Hue Entertainment 0.2.0 — 2026-07-02

LedFX auto-provisioning: the app now creates one matching DDP device per zone
in LedFX through its API — configure zones once, pick effects in LedFX, done.
New `ledfx_url` / `ledfx_ddp_target` options (empty URL disables it).

## Hue Entertainment 0.1.0 — 2026-07-02

New app: stream LedFX effects to Philips Hue Zigbee bulbs on zigbee2mqtt at
20–25 fps — no Hue Bridge — via the reverse-engineered Hue Entertainment
protocol (one Zigbee frame per zone per tick through Z2M's `zclcommand`
passthrough, re-broadcast by a proxy bulb). Per-room zones (up to 10 bulbs),
one `Hue Entertainment <zone>` switch each, automatic start/stop around the DDP
stream, Adaptive Lighting pause/resume, and full bulb-state restore.

## REFRAMED Gallery 0.5.0 — 2026-06-25

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

## LedFX 1.1.0–1.1.2 — 2026-06-25

A polish pass — see [`ledfx/CHANGELOG.md`](ledfx/CHANGELOG.md) for the per-release
detail.

- **Home Assistant MQTT integration on by default**, auto-configured from your
  Mosquitto broker (no credentials to enter) via `services: mqtt:want`. Exposes
  the standard LedFX entities (a light per virtual, scene/audio/transition
  selects, play/pause, pixel sensor) — that set is an upstream limit.
- **No onboarding wizard** — auto-scans for WLED on start (`scan_on_startup`);
  re-scan from Settings.
- **De-Blade** — removed the "BLADE MOD" sidebar badge and the "Blade Scene"
  onboarding step/strings.
- **Ingress stability** — the UI always points at the live origin, fixing the host
  404s and a reload loop caused by the rotating ingress token.
- **`sendspin_delay_ms` option** — delay the Sendspin audio to line the lights up
  with your speakers (the in-UI delay control is buggy for Sendspin).

## LedFX 1.0.2 — 2026-06-25

- Fix the blank/black web UI: the HASS frontend set the React Router `basename`
  to `"."` (normalised to `"/."`, which matches no URL), so it rendered nothing.
  Set it to the actual mount path so the UI renders at the LAN root and under the
  ingress sub-path.

## Local Faces 0.5.0 — 2026-06-25

- **Desktop split layout** — on wider screens the live camera preview now sits in
  a left column with Enroll, Known people, and Recent sightings stacked to its
  right (instead of below it), and the preview stays in view while you scroll the
  list. Narrow screens keep the single-column layout with the preview on top.
- **Click a sighting to name it** — every recent sighting opens a lightbox with a
  blown-up face and a name field right underneath. It works on recognized faces
  too, not just unknowns: confirming more shots of the same person enrolls them as
  extra samples, sharpening that face's recognition over time.
- **Name autocomplete** — already-enrolled names are suggested as you type, in both
  the enroll field and the sighting lightbox, so adding several photos to one
  person stays quick and consistent.

## LedFX 1.0.1 — 2026-06-25

- Fix a startup crash on boxes with no sound card ("tuple index out of range" in
  audio-device enumeration) by shipping a null ALSA default device. Audio still
  arrives over the network via Sendspin.
- Ensure the git-pinned engine (past 2.1.9) is in the image, so the Sendspin
  watchdog fix and now-playing metadata are present.

## LedFX 1.0.0 — 2026-06-25

First release of a third app in this repository: **LedFX**, the real-time,
audio-reactive LED controller, running natively on Home Assistant OS.

- Ships the **LedFX engine pinned just past 2.1.9** (upstream commit `90bebef8`)
  with the ingress-ready LedFX web UI — the post-release pin brings the **Sendspin
  watchdog fix** (no more idle "no audio → reconnect" churn) and **Sendspin
  now-playing metadata**.
- **Ingress fixed** — the UI works through Home Assistant ingress (sidebar +
  Nabu Casa), not just on `localhost`. The frontend was patched to use its own
  origin instead of a hard-coded `localhost:8888`, with a stale-host auto-clear.
- **Reachable on the LAN** — the engine binds `0.0.0.0`, so `http://<ha-ip>:8888`
  works directly (the community app bound `127.0.0.1` and couldn't be reached).
- **Audio via Sendspin** — takes its audio from **Music Assistant** over the
  Sendspin protocol: no sound card, no second machine, no VBAN-from-a-PC.
- **De-branded** packaging (clean name, icon, logo, panel; no devil-emoji icon or
  "Blade" app branding) and a single `log_level` option; the rest lives in the
  LedFX UI and persists in `/data`.

## Local Faces 0.3.0 — 2026-06-21

- **Redesigned dashboard** — a "porch-lantern" console: a live MJPEG viewport as
  the centerpiece that glows amber when a known face is present and coral for an
  unknown one, with a monospace-label instrument styling, light/dark themes, and
  a responsive layout that works on the HA mobile app.
- **Smooth live view** — replaced the polled still image with an MJPEG stream.
- **Capture → confirm → save enrollment** — you now see the captured face before
  naming it, with proper busy states (no accidental double-enrollments).
- **Name from the log** — tap an unknown face in the sightings list and name it to
  enroll it on the spot; the log now stores each sighting's embedding for this.
- **Security fix** — enrolled names are rendered as text (no longer interpolated
  into HTML), closing a stored-XSS vector via a crafted name.

## Local Faces 0.2.0 — 2026-06-21

- **Pluggable recognition model.** New `recognition_model` option: keep the
  bundled, Apache-2.0 **SFace** (default), or switch to a stronger small embedder
  such as InsightFace's **`mobilefacenet_w600k`** (smaller and more accurate, but
  non-commercial license — you supply the `.onnx` via `recognition_model_url` or
  `/data/models`, accepting its license).
- ArcFace-style ONNX models run via `onnxruntime` with standard 5-point alignment
  (new `align.py`); SFace keeps using OpenCV's built-in alignment. A shared
  embedder interface (`embedders.py`) hides the difference from the rest of the app.
- Enrollments are now **namespaced by model** in `faces.json`, so switching models
  doesn't mix incompatible embeddings; v1 (SFace-only) files migrate automatically.
- Dashboard status line shows the active recognition model.

## Local Faces 0.1.0 — 2026-06-21

First release of a second app in this repository.

- **On-device, open-source face recognition** for Home Assistant: pulls frames
  from an RTSP/HTTP stream (or polled snapshot URL), detects faces, and matches
  them against people you enroll — all on the CPU, light enough for a Pi 4/5.
- **Open models:** YuNet detector + SFace embedder (Apache-2.0, OpenCV Zoo) via
  OpenCV's bundled DNN — the open counterpart to UltraFace + MobileFaceNet.
  Downloaded once to `/data/models` on first start.
- **Enrollment dashboard (ingress):** add people by capturing from the live
  camera or uploading a photo; live annotated view; a recognition log with
  snapshot thumbnails.
- **HA integration:** publishes a `Recognized Name` sensor via MQTT discovery
  (auto-detects the Mosquitto broker app); optional push notification via any
  HA notify service, with a per-identity cooldown.
- **Local by default:** recognition, enrollment, and the log never leave the box;
  only a notification can.
- Tunable: Fast/Balanced/Accurate processing size, match threshold, minimum face
  size, and detection interval.

## Frame Gallery 0.1.0 — 2026-06-14

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
