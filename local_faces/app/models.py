"""Ensure the two small ONNX models are present in /data, downloading once.

We use the open-source OpenCV Zoo models (Apache-2.0): YuNet for detection and
SFace for recognition - the lightweight, CPU-friendly analog to the UltraFace +
MobileFaceNet pairing. They total ~37 MB and are fetched once to /data/models on
first start, then reused. Set MODEL_DETECTOR_URL / MODEL_RECOGNIZER_URL to point
at a local mirror if your box has no internet (the only time anything is fetched).
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("local-faces.models")

MODELS_DIR = "/data/models"

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "detector": {
        "filename": "face_detection_yunet_2023mar.onnx",
        "url": os.environ.get(
            "MODEL_DETECTOR_URL",
            f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        ),
        "min_size": 200_000,
    },
    "recognizer": {
        "filename": "face_recognition_sface_2021dec.onnx",
        "url": os.environ.get(
            "MODEL_RECOGNIZER_URL",
            f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        ),
        "min_size": 30_000_000,
    },
}


def _ensure_one(spec: dict) -> str:
    path = os.path.join(MODELS_DIR, spec["filename"])
    if os.path.exists(path) and os.path.getsize(path) >= spec["min_size"]:
        return path

    log.info("downloading model %s ...", spec["filename"])
    tmp = path + ".tmp"
    with requests.get(spec["url"], stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)

    if os.path.getsize(tmp) < spec["min_size"]:
        os.remove(tmp)
        raise RuntimeError(f"downloaded {spec['filename']} looks truncated")
    os.replace(tmp, path)
    log.info("saved %s (%d bytes)", spec["filename"], os.path.getsize(path))
    return path


def ensure_models() -> tuple[str, str]:
    """Return (detector_path, recognizer_path), downloading if needed."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    return _ensure_one(MODELS["detector"]), _ensure_one(MODELS["recognizer"])
