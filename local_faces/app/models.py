"""Ensure the detector + the chosen recognition model are present in /data.

The detector (YuNet, MIT), the default recognizer (SFace, Apache-2.0) and the
face-quality scorer (eDifFIQA(T), CC-BY-4.0) are OpenCV Zoo models, fetched
once to /data/models. Stronger small embedders exist
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

# Face image quality (eDifFIQA(T) - Babnik et al., "eDifFIQA: Towards Efficient
# Face Image Quality Assessment based on Denoising Diffusion Probabilistic
# Models", IEEE T-BIOM 2024; CC-BY-4.0). Scores how useful an aligned face is for
# recognition; used to keep blurry/low-res samples out of the face library.
QUALITY = {
    "filename": "ediffiqa_tiny_jun2024.onnx",
    "url": os.environ.get(
        "MODEL_QUALITY_URL",
        f"{_ZOO}/face_image_quality_assessment_ediffiqa/ediffiqa_tiny_jun2024.onnx",
    ),
    "min_size": 5_000_000,
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


def ensure_quality_model() -> str | None:
    """The quality scorer's path, or None if it can't be had.

    Optional by design: without it enrollment still works, just without the
    blurry-sample warning - never worth refusing to start over.
    """
    os.makedirs(MODELS_DIR, exist_ok=True)
    try:
        return _ensure(QUALITY, what="face quality")
    except (OSError, RuntimeError, requests.RequestException) as exc:
        log.warning("face quality scoring unavailable (%s) - enrollment works, "
                    "but blurry samples won't be flagged", exc)
        return None


def ensure_models(opts) -> tuple[str, str]:
    """Return (detector_path, recognizer_path), downloading what's allowed."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    det = _ensure(DETECTOR)
    spec = RECOGNIZERS[opts.recognition_model]
    rec = _ensure(spec, opts.recognition_model_url, what=opts.recognition_model)
    return det, rec
