# Changelog

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
