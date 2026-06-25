"""Ensure the detector + the chosen recognition model are present in /data.

The detector (YuNet) and the default recognizer (SFace) are Apache-2.0 OpenCV
Zoo models, fetched once to /data/models. Stronger small embedders exist
(InsightFace's w600k MobileFaceNet, EdgeFace, ...) but their *pretrained weights*
ship under non-commercial / research-only licenses, so we don't bundle or
auto-download them: select one and supply the file yourself (recognition_model_url,
or drop it in /data/models), which is also where you accept its license.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("local-faces.models")

MODELS_DIR = "/data/models"

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"

DETECTOR = {
    "filename": "face_detection_yunet_2023mar.onnx",
    "url": os.environ.get(
        "MODEL_DETECTOR_URL",
        f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "min_size": 200_000,
}

# Recognition embedders. Only Apache-2.0 SFace is bundled (has a default URL);
# others must be supplied by the user (url=None) because of their licenses.
RECOGNIZERS = {
    "sface": {
        "filename": "face_recognition_sface_2021dec.onnx",
        "url": os.environ.get(
            "MODEL_RECOGNIZER_URL",
            f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        ),
        "min_size": 30_000_000,
    },
    "mobilefacenet_w600k": {
        # InsightFace buffalo_s recognizer (MobileFaceNet trained on WebFace600K).
        # Smaller and more accurate than SFace, but NON-COMMERCIAL research license.
        "filename": "w600k_mbf.onnx",
        "url": None,
        "min_size": 3_000_000,
    },
}


def _download(url: str, path: str, min_size: int) -> None:
    log.info("downloading %s ...", os.path.basename(path))
    tmp = path + ".tmp"
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    if os.path.getsize(tmp) < min_size:
        os.remove(tmp)
        raise RuntimeError(f"downloaded {os.path.basename(path)} looks truncated")
    os.replace(tmp, path)
    log.info("saved %s (%d bytes)", os.path.basename(path), os.path.getsize(path))


def _ensure(spec: dict, custom_url: str = "", what: str = "") -> str:
    path = os.path.join(MODELS_DIR, spec["filename"])
    if os.path.exists(path) and os.path.getsize(path) >= spec["min_size"]:
        return path
    url = custom_url or spec["url"]
    if not url:
        raise RuntimeError(
            f"the '{what}' model is not bundled (non-commercial license). Download "
            f"{spec['filename']} from its source, accept its license, then place it at "
            f"{path} or set recognition_model_url. See the app docs."
        )
    _download(url, path, spec["min_size"])
    return path


def ensure_models(opts) -> tuple[str, str]:
    """Return (detector_path, recognizer_path), downloading what's allowed."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    det = _ensure(DETECTOR)
    spec = RECOGNIZERS[opts.recognition_model]
    rec = _ensure(spec, opts.recognition_model_url, what=opts.recognition_model)
    return det, rec
