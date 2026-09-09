# Changelog

## 0.7.0 — 2026-09-09

- **A presence sensor for every person.** `binary_sensor.local_faces_<name>` is
  on while that person has been seen recently, with `last_seen`, `camera` and
  `score` attributes — so "when Alex gets home" is a state trigger instead of a
  template over a name string. Entities appear as you enroll and are removed
  from Home Assistant when you delete someone, with no restart either way. New
  options: **One sensor per person** (on) and **Presence timeout** (120 s).
- **"Probably not a person."** The app now finds the posters, photo frames and
  paused TVs itself: a face that keeps appearing in the *same spot* with the
  *same* embedding for half an hour or more gets a dashboard card with its
  thumbnail, the camera, and how long it's been sitting there. **Ignore** adds it
  to the ignore list and clears its past sightings; **It's a person** keeps it and
  is remembered across restarts. It only suggests — nothing is ignored without
  your click.
- **A face that matches an enrolled person can no longer be ignored.** Their
  embeddings are the same face, so ignoring a photo of someone would have stopped
  the real person being recognized. Such faces are never suggested, and doing it
  by hand is refused with an explanation.
- The dashboard's **Known people** list now shows who's here and when each person
  was last seen, and each camera's sensor gained an `ignored_faces` attribute.

## 0.6.1 — 2026-09-09

- **Notifications no longer hold up recognition.** The push was sent inline, so
  a notify service that answered slowly (or timed out) stalled the whole
  recognition loop — every camera waited behind it. Sending now happens on a
  background worker with a bounded queue; if a service is wedged, alerts are
  dropped rather than cameras going blind.
- MQTT client creation is now explicit about its callback API version, so the
  app works on paho-mqtt 2.x as well as 1.x (`paho-mqtt>=1.6,<3`).
- Back-filled this changelog with the app's earlier releases, so the store shows
  the full history.

## 0.6.0 — 2026-09-08

- **Ignore faces that aren't people.** A camera pointed at a room sees faces that
  never move — a poster, a photo frame, a paused TV, the artwork on an arcade
  cabinet — and every one of them filled *Recent sightings* with unknowns
  ([#13](https://github.com/adamoberley/ha-addons/issues/13)). Open the sighting
  (or capture the face deliberately) and hit **Ignore**: from then on it's
  matched and then dropped — no sighting, no sensor change, no notification —
  and it shows in the live view as a grey box labelled *ignored* so you can see
  it's deliberate.
  - Ignoring a face also **clears its existing sightings** out of the log, so the
    history you were cleaning up goes with it.
  - The list holds **as many entries as you like**, each with several patterns:
    hit *Ignore* on the same object from another angle and it's added to that
    label. A new **Ignored faces** card lists them, with **Stop ignoring**.
  - A label that's already an enrolled person is refused, so a member of the
    household can't be ignored by accident.
- Camera tiles now read e.g. `2 faces (+1 ignored)`, and each camera's sensor
  gained an `ignored_faces` attribute. Ignored faces no longer count toward
  `faces` or push a camera into the `unknown` state.
- Added tests for the ignore list and the recognition pipeline
  (`python -m pytest local_faces/tests`).

## 0.5.0 — 2026-06-25

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

## 0.3.0 — 2026-06-21

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

## 0.2.0 — 2026-06-21

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

## 0.1.0 — 2026-06-21

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
