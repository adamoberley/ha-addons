# Changelog

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

First release of a third add-on in this repository: **LedFX**, the real-time,
audio-reactive LED controller, running natively on Home Assistant OS.

- Ships the **LedFX engine pinned just past 2.1.9** (upstream commit `90bebef8`)
  with the ingress-ready LedFX web UI — the post-release pin brings the **Sendspin
  watchdog fix** (no more idle "no audio → reconnect" churn) and **Sendspin
  now-playing metadata**.
- **Ingress fixed** — the UI works through Home Assistant ingress (sidebar +
  Nabu Casa), not just on `localhost`. The frontend was patched to use its own
  origin instead of a hard-coded `localhost:8888`, with a stale-host auto-clear.
- **Reachable on the LAN** — the engine binds `0.0.0.0`, so `http://<ha-ip>:8888`
  works directly (the community add-on bound `127.0.0.1` and couldn't be reached).
- **Audio via Sendspin** — takes its audio from **Music Assistant** over the
  Sendspin protocol: no sound card, no second machine, no VBAN-from-a-PC.
- **De-branded** packaging (clean name, icon, logo, panel; no devil-emoji icon or
  "Blade" add-on branding) and a single `log_level` option; the rest lives in the
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

First release of a second add-on in this repository.

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
  (auto-detects the Mosquitto broker add-on); optional push notification via any
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
