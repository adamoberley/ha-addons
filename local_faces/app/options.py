"""Add-on options, read from /data/options.json (written by the Supervisor)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

OPTIONS_PATH = "/data/options.json"

# "Fast vs Accurate" maps to the width we downscale each frame to before
# detection: smaller is faster (good for a Pi), larger catches smaller/farther
# faces. Recognition always runs on the full-resolution aligned crop.
_MODE_WIDTH = {"fast": 320, "balanced": 480, "accurate": 720}


@dataclass(frozen=True)
class Options:
    stream_url: str
    camera_mode: str
    mode: str
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


def load() -> Options:
    raw = _load_raw()
    return Options(
        stream_url=str(raw.get("stream_url", "")).strip(),
        camera_mode=str(raw.get("camera_mode", "stream")).strip() or "stream",
        mode=str(raw.get("mode", "balanced")).strip() or "balanced",
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
