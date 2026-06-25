"""App options, read from /data/options.json (written by the Supervisor)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

OPTIONS_PATH = "/data/options.json"


@dataclass(frozen=True)
class Camera:
    name: str
    slug: str
    stream_url: str
    camera_mode: str


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "camera"

# "Fast vs Accurate" maps to the width we downscale each frame to before
# detection: smaller is faster (good for a Pi), larger catches smaller/farther
# faces. Recognition always runs on the full-resolution aligned crop.
_MODE_WIDTH = {"fast": 320, "balanced": 480, "accurate": 720}


@dataclass(frozen=True)
class Options:
    stream_url: str
    camera_mode: str
    cameras: tuple
    preview_aspect: str
    mode: str
    recognition_model: str
    recognition_model_url: str
    detect_interval: float
    recognition_threshold: float
    min_face_size: int
    cooldown_seconds: int
    notify_service: str
    notify_unknown: bool
    enable_mqtt: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    log_level: str

    @property
    def proc_width(self) -> int:
        return _MODE_WIDTH.get(self.mode, 480)

    @property
    def det_score_threshold(self) -> float:
        return 0.8


def _load_raw() -> dict:
    if not os.path.exists(OPTIONS_PATH):
        return {}
    with open(OPTIONS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _cameras(raw: dict) -> tuple:
    """Build the camera list. Entries in `cameras` with a stream_url win; if there
    are none, fall back to the legacy single stream_url so older configs still work."""
    out, seen = [], set()
    for c in (raw.get("cameras") or []):
        url = str((c or {}).get("stream_url", "")).strip()
        if not url:
            continue
        name = str(c.get("name", "")).strip() or "Camera"
        slug = base = _slugify(name)
        n = 2
        while slug in seen:
            slug, n = f"{base}_{n}", n + 1
        seen.add(slug)
        mode = str(c.get("camera_mode", "stream")).strip() or "stream"
        out.append(Camera(name, slug, url, mode))
    if not out:
        url = str(raw.get("stream_url", "")).strip()
        if url:
            mode = str(raw.get("camera_mode", "stream")).strip() or "stream"
            out.append(Camera("Camera", "camera", url, mode))
    return tuple(out)


def load() -> Options:
    raw = _load_raw()
    return Options(
        stream_url=str(raw.get("stream_url", "")).strip(),
        camera_mode=str(raw.get("camera_mode", "stream")).strip() or "stream",
        cameras=_cameras(raw),
        preview_aspect=str(raw.get("preview_aspect", "auto")).strip() or "auto",
        mode=str(raw.get("mode", "balanced")).strip() or "balanced",
        recognition_model=str(raw.get("recognition_model", "sface")).strip() or "sface",
        recognition_model_url=str(raw.get("recognition_model_url", "")).strip(),
        detect_interval=float(raw.get("detect_interval", 1.0)),
        recognition_threshold=float(raw.get("recognition_threshold", 0.363)),
        min_face_size=int(raw.get("min_face_size", 60)),
        cooldown_seconds=int(raw.get("cooldown_seconds", 15)),
        notify_service=str(raw.get("notify_service", "")).strip(),
        notify_unknown=bool(raw.get("notify_unknown", True)),
        enable_mqtt=bool(raw.get("enable_mqtt", True)),
        mqtt_host=str(raw.get("mqtt_host", "")).strip(),
        mqtt_port=int(raw.get("mqtt_port", 1883)),
        mqtt_username=str(raw.get("mqtt_username", "")).strip(),
        mqtt_password=str(raw.get("mqtt_password", "")),
        log_level=str(raw.get("log_level", "info")),
    )
