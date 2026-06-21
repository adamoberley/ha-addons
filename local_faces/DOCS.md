# Local Faces

On-device, open-source face recognition for Home Assistant. Point it at a camera,
enroll a few people from the built-in dashboard, and recognized names show up in
HA as a sensor you can automate off. It runs entirely on the CPU and is light
enough for a Raspberry Pi 4/5 — no GPU, no cloud, no per-face subscription.

**Everything stays local.** Detection, enrollment, and the recognition log all
live in the add-on's `/data`. The only thing that can ever leave your network is
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

## Setup

1. **Install an MQTT broker** (the official *Mosquitto broker* add-on) if you
   want the HA sensor. Local Faces auto-detects it — no broker config needed.
2. **Set the camera URL** in the Configuration tab:
   - `stream` mode: an RTSP URL like `rtsp://user:pass@192.168.1.50/stream`, or
     an HTTP/MJPEG stream.
   - `snapshot` mode: a still-image URL that returns a fresh JPEG per request.
3. **Start the add-on** and open it (sidebar → **Local Faces**).
4. **Enroll** each person: type a name, then **Capture from camera** (best — uses
   the real camera angle) or **Upload photo**. Add a few samples per person.
5. Recognized faces now appear in the **Recent recognitions** list and on the
   `sensor.recognized_name` entity.

## What you get

- **HA sensor** — `sensor.recognized_name` holds the last recognized name
  (`none` / `unknown` when nobody known is in view), with `score`, `faces`, and
  `timestamp` attributes. Automate freely: unlock for known people, alert on
  unknown, announce arrivals.
- **Push notification** — optional ping via any HA notify service.
- **Log** — name, confidence, and a snapshot thumbnail for every recognition,
  in the dashboard.

## Tuning

| Symptom | Try |
| --- | --- |
| Strangers matched to someone | Raise **Match threshold** (e.g. 0.4–0.45) |
| Known people missed | Lower **Match threshold**, add more enrollment samples |
| High CPU on a Pi | Set **Speed vs accuracy** to `fast`, raise **Detection interval** |
| Distant false detections | Raise **Minimum face size** |
| Notified too often | Raise **Re-trigger cooldown** |

## Notes & limits

- 64-bit only (aarch64/amd64). A Pi running 64-bit Home Assistant OS is fine; a
  32-bit OS is not supported (no OpenCV wheels).
- This is a recognition/automation aid for your own home, not a security-grade
  identity system. Lighting, angle, and enrollment quality all affect accuracy.
- No anti-spoofing (liveness) yet — don't use it as the sole factor for a lock.
