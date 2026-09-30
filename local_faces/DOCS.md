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

- **Face quality:** [eDifFIQA(T)](https://github.com/opencv/opencv_zoo/tree/main/models/face_image_quality_assessment_ediffiqa)
  (~7 MB) scores how useful a face is for recognition, so blurry or tiny
  samples are caught before they're enrolled. Only used when enrolling and in
  the face library, never on the live recognition path.

All three come from the OpenCV Zoo — YuNet under MIT, SFace under Apache-2.0,
eDifFIQA(T) under CC-BY-4.0 (Babnik et al., *eDifFIQA: Towards Efficient Face
Image Quality Assessment based on Denoising Diffusion Probabilistic Models*,
IEEE T-BIOM 2024) — and run through OpenCV's bundled DNN engine on the CPU.
They're downloaded once to `/data/models` on first start; if the quality model
can't be fetched, everything else still works, just without the blurry-sample
check.
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
2. **Add your camera** under **Cameras** in the Configuration tab. The easiest
   way is a Home Assistant camera you already have — no URL, no password:

   ```yaml
   - name: Front Porch
     camera_entity: camera.front_porch
     trigger_entities: binary_sensor.front_porch_person
   ```

   `trigger_entities` is optional but recommended: the camera is only looked
   at while one of them is on (see [Only look when something
   happens](#only-look-when-something-happens)). Or give a `stream_url`
   instead of `camera_entity`:
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
  (`none` / `unknown` when nobody known is in view), with `score`, `faces`,
  `ignored_faces`, and `timestamp` attributes. One per camera too
  (`sensor.local_faces_<camera>`).
- **A presence sensor per person** — `binary_sensor.local_faces_<name>` is *on*
  while that person has been seen recently, with `last_seen`, `camera` and
  `score` attributes. This is the entity most automations actually want:

  ```yaml
  # Hallway light + a greeting when Alex gets home
  triggers:
    - trigger: state
      entity_id: binary_sensor.local_faces_alex
      from: "off"
      to: "on"
  actions:
    - action: light.turn_on
      target: {entity_id: light.hallway}
  ```

  Entities appear as you enroll people and are removed from Home Assistant when
  you delete them — no restart either way. Turn the whole set off with the
  **One sensor per person** option, and tune how long someone stays "present"
  after their last sighting with **Presence timeout**.
- **A `local_faces_recognized` event** for every sighting, like Frigate's —
  `name` (or `null` for an unknown face), `known`, `score`, `camera`,
  `camera_slug`, `camera_entity` and `timestamp`. Trigger on a specific person
  at a specific camera without templates:

  ```yaml
  triggers:
    - trigger: event
      event_type: local_faces_recognized
      event_data: {name: Alex, camera_entity: camera.front_porch}
  ```

  Turn it off with **Fire recognition events**.
- **Push notification** — optional ping via any HA notify service. Sent in the
  background, so a slow notify service never holds up recognition (if one wedges,
  alerts are dropped rather than cameras stalling).
- **Sightings log** — name, confidence, and a snapshot thumbnail for every
  recognition, in the dashboard. Unknown faces can be named in place to enroll them,
  or ignored in place if they aren't people.
- **Ignored faces** — a second list next to *Known people*, for faces that are
  real faces but not arrivals.

## Only look when something happens

Most of the day nobody is at the door, and analyzing an empty doorstep twice a
second is wasted CPU. Give a camera **trigger entities** — the doorbell's own
person or visitor sensor, a motion sensor, a door contact — and Local Faces only
looks while one of them is on:

- **Idle:** nothing is fetched or decoded. A Home Assistant camera isn't polled
  at all; a stream camera is closed after a minute (reopening one takes a second
  or two, so a brief pause doesn't drop it).
- **The moment a trigger turns on**, recognition starts — the app follows the
  entities over Home Assistant's websocket, so there's no polling delay — and
  runs every **Interval while triggered** (0.5 s by default).
- **After the last trigger turns off**, it keeps looking for **Keep looking after
  a trigger** (10 s), because person sensors often drop while someone is still
  standing there.

The dashboard shows a resting camera as *idle, waiting for its trigger* rather
than as offline. If Home Assistant can't be reached, gated cameras fall back to
looking all the time — a missed trigger should never mean a missed face.

A camera without trigger entities behaves exactly as before: analyzed every
**Detection interval**.

## The face library

Hit **Samples** next to anyone under *Known people* to see every face saved for
them. The list tells you when someone has samples worth a look ("*2 look off*").

- **Red = worth removing.** A sample is flagged when it's **blurry** (the
  quality model rates it poor) or when it **doesn't match** the rest of that
  person's samples — it wouldn't pass the match threshold against their average.
  That second check catches the worst case: someone else's face saved under
  this name, which makes both people harder to recognize. It needs three or
  more samples to judge.
- **Tap a sample, then Remove or Move.** Move reassigns it to whoever it really
  is (a new name creates that person). Removing a person's last sample removes
  the person, and their Home Assistant entity with them.
- Each sample shows how well it matches the others; the more consistent a
  person's samples, the more reliably they're recognized.
- Samples saved before 0.9 show *no preview* — the app never kept which picture
  each one came from — but they're still judged, moved and removed normally.

**Blurry captures are caught at the door.** When you enroll a face (Capture,
Upload, or naming a sighting), it's scored first. A *poor* one is refused with
an explanation and a **Save anyway** button, because one bad sample makes
recognition worse for everyone; a *fair* one is saved with a heads-up. What
matters is the size and sharpness of the *face*, not the whole photo — a
distant face is always softer than a close one.

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
- **Are ignored faces still analyzed?** Yes, and they have to be: an ignored
  face is recognized like any other, and *then* dropped — that's how it keeps
  being ignored. A blurry face you don't want doesn't need to be ignored at all,
  though: just don't name it. Unnamed sightings aren't matched against anything
  and simply age out of the log.

## "Probably not a person"

You shouldn't have to notice a poster filling your log before you can do
something about it, so the app looks for the giveaway itself: a face that keeps
appearing **in the same spot in the frame** with the **same** embedding for half
an hour or more. People don't do that; pictures do.

When it finds one, a **Probably not a person** card appears on the dashboard with
the thumbnail, which camera, how long it has been sitting there and how many
times it's been seen:

- **Ignore** adds it to the ignore list (above) and clears its past sightings.
- **It's a person** keeps it and is remembered — that face is never suggested
  again, across restarts.

It only ever suggests; someone sitting still on a sofa can look like this for a
while, which is why nothing happens without your click. Faces that match an
enrolled person are never suggested, and ignoring one by hand is refused —
their embeddings are the same face, so ignoring the photo would stop the real
person being recognized too.

## Tuning

| Symptom | Try |
| --- | --- |
| Strangers matched to someone | Raise **Match threshold** (e.g. 0.4–0.45) |
| Known people missed | Lower **Match threshold**, add more enrollment samples |
| High CPU on a Pi | Set **Speed vs accuracy** to `fast`, raise **Detection interval** |
| Distant false detections | Raise **Minimum face size** |
| Notified too often | Raise **Re-trigger cooldown** |
| A poster / TV / photo keeps being logged | **Ignore** that sighting (see above) |
| Someone is recognized unreliably | Open their **Samples**, remove the red ones, add a few sharp shots |
| Someone stays "present" too long after leaving | Lower **Presence timeout** |
| Someone flickers between present and away | Raise **Presence timeout** |

## Notes & limits

- 64-bit only (aarch64/amd64). A Pi running 64-bit Home Assistant OS is fine; a
  32-bit OS is not supported (no OpenCV wheels).
- This is a recognition/automation aid for your own home, not a security-grade
  identity system. Lighting, angle, and enrollment quality all affect accuracy.
- No anti-spoofing (liveness) yet — don't use it as the sole factor for a lock.
