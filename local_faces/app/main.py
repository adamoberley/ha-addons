"""Local Faces entry point - open-source, on-device face recognition for HA.

options.json -> pull frames from your camera -> detect faces (YuNet) and match
them to enrolled people (SFace), all on CPU. Recognized names are exposed to Home
Assistant over MQTT, optionally pushed to your phone, and logged with a snapshot
in the ingress dashboard where you enroll faces. Recognition, enrollment, and the
log all stay local; the only thing that can leave your network is a notification.
"""
from __future__ import annotations

import base64
import logging
import secrets
import signal
import sys
import threading
import time

import cv2
import numpy as np
import options as options_mod
import server
from camera import CameraSource
from engine import FaceEngine
from facedb import FaceDB
from mqtt_pub import MqttPublisher
from notify import Notifier
from reclog import RecognitionLog

SERVER_PORT = 8099
UNKNOWN_KEY = "__unknown__"

log = logging.getLogger("local-faces")
_stop = threading.Event()


def _setup_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _handle_signal(signum, _frame) -> None:
    log.info("signal %s received, shutting down", signum)
    _stop.set()


class App:
    """Owns the pipeline and the actions the ingress dashboard calls into."""

    def __init__(self, opts) -> None:
        self.opts = opts
        self.engine = FaceEngine(opts)
        self.db = FaceDB(opts.recognition_threshold, opts.recognition_model)
        self.reclog = RecognitionLog()
        self.camera = CameraSource(opts)
        self.mqtt = MqttPublisher(opts) if opts.enable_mqtt else None
        self.notifier = Notifier(opts)
        self.httpd = None

        self.running = True
        self._lock = threading.Lock()
        self._preview: bytes | None = None
        self._cooldown: dict[str, float] = {}
        self._last_state: str | None = None
        self._pending: dict[str, dict] = {}  # token -> staged enrollment
        self.status = {
            "camera_ok": False,
            "faces": 0,
            "recognized": "",
            "score": 0.0,
            "state": "idle",  # idle | known | unknown
            "people": 0,
            "last_ts": 0.0,
            "mode": opts.mode,
            "model": opts.recognition_model,
            "mqtt": bool(self.mqtt),
            "stream_set": bool(opts.stream_url),
        }

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self.camera.start()
        if self.mqtt:
            self.mqtt.start()
        self.httpd = server.make_server(self, port=SERVER_PORT)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        log.info("dashboard on :%d", SERVER_PORT)

    def stop(self) -> None:
        self.running = False
        self.camera.stop()
        if self.mqtt:
            self.mqtt.stop()
        if self.httpd:
            self.httpd.shutdown()

    # ---- recognition loop --------------------------------------------------
    def tick(self) -> None:
        frame = self.camera.latest()
        if frame is None:
            self.status["camera_ok"] = False
            return
        self.status["camera_ok"] = True

        faces = self.engine.detect(frame)
        results: list[tuple] = []
        top_name, top_score = None, 0.0
        for face in faces:
            name, score = self.db.match(face.embedding)
            results.append((face, name, score))
            if name and score > top_score:
                top_name, top_score = name, score
            self._handle_event(face, name, score)

        annotated = self.engine.annotate(frame, results)
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with self._lock:
                self._preview = buf.tobytes()

        if top_name:
            state = "known"
        elif any(n is None for _, n, _ in results):
            state = "unknown"
        else:
            state = "idle"
        self.status.update(faces=len(faces), recognized=top_name or "",
                           score=round(top_score, 3) if top_name else 0.0, state=state,
                           people=len(self.db.people()), last_ts=time.time())
        self._publish_state(top_name, results, top_score)

    def _handle_event(self, face, name: str | None, score: float) -> None:
        """Debounce per identity, then log + (optionally) notify."""
        key = name or UNKNOWN_KEY
        now = time.time()
        if now - self._cooldown.get(key, 0.0) < self.opts.cooldown_seconds:
            return
        self._cooldown[key] = now

        unknown = name is None
        self.reclog.add(name or "Unknown", score, unknown, face.thumb,
                        face.embedding, self.opts.recognition_model)
        log.info("event: %s (score=%.3f)", name or "unknown", score)
        if unknown and not self.opts.notify_unknown:
            return
        if name:
            self.notifier.send(f"{name} recognized ({score:.0%})")
        else:
            self.notifier.send("Unknown person detected")

    def _publish_state(self, top_name, results, top_score: float) -> None:
        if not self.mqtt:
            return
        if top_name:
            state = top_name
        elif any(n is None for _, n, _ in results):
            state = "unknown"
        else:
            state = "none"
        if state == self._last_state:
            return
        self._last_state = state
        self.mqtt.publish_state(state, {
            "score": round(top_score, 3) if top_name else None,
            "faces": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })

    # ---- dashboard actions -------------------------------------------------
    def preview_jpeg(self) -> bytes | None:
        with self._lock:
            return self._preview

    def public_status(self) -> dict:
        return dict(self.status)

    def stage_from_frame(self) -> dict:
        """Detect a face in the live frame and hold it for confirmation."""
        return self._stage(self.camera.latest())

    def stage_from_image(self, data: bytes) -> dict:
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        return self._stage(frame)

    def _stage(self, frame) -> dict:
        if frame is None:
            return {"ok": False,
                    "message": "No camera image yet. Check the camera connection, then try again."}
        faces = self.engine.detect(frame)
        if not faces:
            return {"ok": False,
                    "message": "No face found. Face the camera straight on and try again."}
        face = max(faces, key=lambda f: f.w * f.h)
        token = secrets.token_hex(8)
        now = time.time()
        with self._lock:
            self._pending = {t: v for t, v in self._pending.items() if now - v["ts"] < 600}
            self._pending[token] = {"emb": face.embedding, "thumb": face.thumb, "ts": now}
        return {"ok": True, "token": token,
                "thumb": base64.b64encode(face.thumb).decode("ascii"),
                "message": "Face captured. Give it a name to save."}

    def commit_enrollment(self, token: str, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            return {"ok": False, "message": "Enter a name to save this face."}
        with self._lock:
            pending = self._pending.pop(token, None)
        if not pending:
            return {"ok": False, "message": "That capture expired. Capture the face again."}
        samples = self.db.add(name, pending["emb"], pending["thumb"])
        word = "sample" if samples == 1 else "samples"
        return {"ok": True, "message": f"Saved {name} ({samples} {word})."}

    def cancel_enrollment(self, token: str) -> dict:
        with self._lock:
            self._pending.pop(token, None)
        return {"ok": True}

    def name_sighting(self, sighting_id: str, name: str) -> dict:
        """Enroll an unknown face straight from the log entry that captured it."""
        name = (name or "").strip()
        if not name:
            return {"ok": False, "message": "Enter a name for this face."}
        event = self.reclog.get(sighting_id)
        if not event:
            return {"ok": False, "message": "That sighting has scrolled out of the log."}
        if event.get("model") != self.opts.recognition_model:
            return {"ok": False,
                    "message": "That face was captured with a different recognition model. "
                               "Use Capture instead."}
        emb = np.array(event.get("emb", []), dtype="float32")
        if emb.size == 0:
            return {"ok": False, "message": "That sighting has no usable face data."}
        thumb = base64.b64decode(event["thumb"]) if event.get("thumb") else b""
        samples = self.db.add(name, emb, thumb)
        self.reclog.relabel(sighting_id, name)
        word = "sample" if samples == 1 else "samples"
        return {"ok": True, "message": f"Saved {name} ({samples} {word})."}

    def delete_person(self, name: str) -> dict:
        if self.db.delete((name or "").strip()):
            return {"ok": True, "message": f"Removed {name}."}
        return {"ok": False, "message": f"{name} not found."}


def main() -> int:
    opts = options_mod.load()
    _setup_logging(opts.log_level)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    app = App(opts)
    app.start()
    log.info("ready: mode=%s, threshold=%.3f, every %.1fs (camera %s)",
             opts.mode, opts.recognition_threshold, opts.detect_interval,
             "set" if opts.stream_url else "NOT set - configure stream_url")

    try:
        while not _stop.is_set():
            try:
                app.tick()
            except Exception as exc:  # one bad frame must not kill the loop
                log.error("recognition cycle failed (will retry): %s", exc)
            _stop.wait(timeout=opts.detect_interval)
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
