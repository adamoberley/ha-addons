# Local Faces

On-device, open-source face recognition for Home Assistant. Point it at a camera,
enroll a few people from the built-in dashboard, and recognized names show up in
HA as a sensor you can automate off. It runs entirely on the CPU and is light
enough for a Raspberry Pi 4/5 — no GPU, no cloud, no per-face subscription.

**Everything stays local.** Detection, enrollment, and the recognition log all
live in the app's `/data`. The only thing that can ever leave your network is
an optional push notification (and only if you turn one on).

## How it works

- **Detection:** [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
  — a tiny (~230 KB) CNN face detector.
- **Recognition:** [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
  — a MobileFaceNet-style embedding model (~37 MB) that turns each face into a
  128-D vector; faces are matched by cosine similarity.

Both are Apache-2.0 models from the OpenCV Zoo, run through OpenCV's bundled DNN
engine on the CPU. They're downloaded once to `/data/models` on first start.
This is the open-source counterpart to the UltraFace + MobileFaceNet pairing —
small, fast, and accurate enough for a front door or hallway. Placement and good
enrollment photos matter more than the model.

## Choosing a recognition model

The embedder is pluggable via the **Recognition model** option:

| Model | Size | Notes | License |
| --- | --- | --- | --- |
| `sface` *(default)* | ~37 MB | Bundled, auto-downloaded, zero setup | **Apache-2.0** — free to use |
| `mobilefacenet_w600k` | ~3.4 MB | Smaller *and* more accurate (InsightFace buffalo_s, trained on WebFace600K) | **Non-commercial / research-only** |

`sface` is the right choice for almost everyone — it's clean-licensed and works
out of the box. Pick `mobilefacenet_w600k` only if you want the extra accuracy and
are comfortable with its license.

**Using a non-bundled model:** because of the license, Local Faces won't fetch it
for you. Obtain `w600k_mbf.onnx` from the InsightFace `buffalo_s` release, then
either:

- drop the file at `/data/models/w600k_mbf.onnx` (e.g. via the *Samba*/*SSH*
  app), or
- set **Recognition model URL** to a direct link you control.

Switching models is safe: **enrollments are kept per model**, so the first time
you select a new model you'll re-enroll once, and switching back to a model you've
used before restores its people. Note the optimal **Match threshold** differs by
model — `sface` is good at `0.363`; for `mobilefacenet_w600k` start lower (around
`0.3`) and tune.

> Other strong tiny models exist (EdgeFace, GhostFaceNets). They're not included
> because their pretrained weights also carry research-only licenses; any
> ArcFace-style 112×112 ONNX model that outputs an embedding will work through the
> `mobilefacenet_w600k` path if you point the URL at it.

## Setup

1. **Install an MQTT broker** (the official *Mosquitto broker* app) if you
   want the HA sensor. Local Faces auto-detects it — no broker config needed.
2. **Set the camera URL** in the Configuration tab:
   - `stream` mode: an RTSP URL like `rtsp://user:pass@192.168.1.50/stream`, or
     an HTTP/MJPEG stream.
   - `snapshot` mode: a still-image URL that returns a fresh JPEG per request.
3. **Start the app** and open it (sidebar → **Local Faces**). The dashboard
   shows a live view, who's enrolled, and recent sightings.
4. **Enroll** each person, two ways:
   - **Capture or upload:** type a name, hit **Capture from camera** (best — uses
     the real camera angle) or **Upload photo**, check the captured face, then
     **Save**. Add a few angles per person.
   - **Name from the log:** when an unrecognized face shows up under **Recent
     sightings**, hit **Name**, type who it is, and save — that face is enrolled
     and recognized from then on. No re-capture needed.
5. Recognized faces now appear under **Recent sightings** and on the
   `sensor.recognized_name` entity.
6. **Ignore the faces that aren't people.** If a poster, a photo frame, a TV, or
   an arcade cabinet's artwork keeps showing up as an unknown sighting, open that
   sighting and hit **Ignore** (optionally labelling it, e.g. *Arcade cabinet*).
   See below.

## What you get

- **HA sensor** — `sensor.recognized_name` holds the last recognized name
  (`none` / `unknown` when nobody known is in view), with `score`, `faces`, and
  `timestamp` attributes. Automate freely: unlock for known people, alert on
  unknown, announce arrivals.
- **Push notification** — optional ping via any HA notify service.
- **Sightings log** — name, confidence, and a snapshot thumbnail for every
  recognition, in the dashboard. Unknown faces can be named in place to enroll them,
  or ignored in place if they aren't people.
- **Ignored faces** — a second list next to *Known people*, for faces that are
  real faces but not arrivals.

## Ignoring faces that aren't people

A camera pointed at a room often sees faces that never move: the people printed
on a poster, a photo in a frame, a paused TV, the artwork on an arcade cabinet.
The detector is right to find them — they *are* faces — so the fix isn't to
detect less, it's to recognize them and then drop them.

Open the sighting (or **Capture** the face deliberately) and hit **Ignore**.
From then on that face is:

- kept out of **Recent sightings**,
- never published to the sensors — it doesn't count as a face, and it can't put
  a camera into the `unknown` state,
- never notified,
- drawn in the live view as a grey box labelled *ignored*, so you can see it's
  being matched on purpose.

Ignoring also **clears that face's existing sightings** out of the log, so the
history you were trying to clean up goes with it.

Notes:

- The list holds **as many entries as you like**, and each entry can hold
  several patterns — hit *Ignore* on the same object from a different angle and
  it's added to that label rather than replacing it. More patterns = more
  reliable skipping.
- Labels are cosmetic; the matching is the same cosine test as recognition, at
  the same **Match threshold**. If an ignored face is *sometimes* still logged,
  add another pattern of it (or lower the threshold slightly).
- A name that already belongs to an enrolled person is refused, so you can't
  accidentally ignore a member of the household.
- **Stop ignoring** in the *Ignored faces* card removes an entry; past sightings
  are not restored (they're gone from the log).
- Entries are stored per recognition model, like enrollments, in
  `/data/faces.json`. Nothing leaves the box.

## Tuning

| Symptom | Try |
| --- | --- |
| Strangers matched to someone | Raise **Match threshold** (e.g. 0.4–0.45) |
| Known people missed | Lower **Match threshold**, add more enrollment samples |
| High CPU on a Pi | Set **Speed vs accuracy** to `fast`, raise **Detection interval** |
| Distant false detections | Raise **Minimum face size** |
| Notified too often | Raise **Re-trigger cooldown** |
| A poster / TV / photo keeps being logged | **Ignore** that sighting (see above) |

## Notes & limits

- 64-bit only (aarch64/amd64). A Pi running 64-bit Home Assistant OS is fine; a
  32-bit OS is not supported (no OpenCV wheels).
- This is a recognition/automation aid for your own home, not a security-grade
  identity system. Lighting, angle, and enrollment quality all affect accuracy.
- No anti-spoofing (liveness) yet — don't use it as the sole factor for a lock.
