"""How useful is this face for recognition? (eDifFIQA(T), CC-BY-4.0)

A sharpness score (Laplacian variance) was the obvious choice and the wrong
one: measured on real faces it rated mild motion blur *sharper* than a gentle
Gaussian blur, while the motion blur had destroyed the embedding (cosine 0.23
to the original vs 0.91), and it swings with face size. eDifFIQA is trained to
predict exactly what matters here - how well a face will match - and on the
same test set it scored the ruined samples 0.18-0.24 and every usable one 0.38+.

It runs on the 112x112 aligned crop we already keep as each face's thumbnail,
so scoring a stored sample, a sighting, or a fresh capture is the same call.
Only enrollment and the face library use it; the live recognition path doesn't.
"""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

log = logging.getLogger("local-faces.quality")

# Calibrated on YuNet-aligned faces (see module docstring). The model card puts
# clean LFW faces above 0.5.
POOR_BELOW = 0.25       # refused at enrollment unless you insist
FAIR_BELOW = 0.40       # accepted, flagged in the face library


def label(score: float | None) -> str | None:
    if score is None:
        return None
    if score < POOR_BELOW:
        return "poor"
    if score < FAIR_BELOW:
        return "fair"
    return "good"


class QualityScorer:
    def __init__(self, model_path: str | None) -> None:
        self._net = None
        self._lock = threading.Lock()      # cv2.dnn nets aren't thread-safe
        if model_path:
            try:
                self._net = cv2.dnn.readNetFromONNX(model_path)
            except cv2.error as exc:
                log.warning("could not load face quality model: %s", exc)

    @property
    def available(self) -> bool:
        return self._net is not None

    def score_aligned(self, aligned: np.ndarray) -> float | None:
        if self._net is None or aligned is None or not aligned.size:
            return None
        img = cv2.resize(aligned, (112, 112)) if aligned.shape[:2] != (112, 112) else aligned
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
        blob = np.moveaxis((((rgb / 255.0) - 0.5) / 0.5)[None, ...], -1, 1)
        with self._lock:
            self._net.setInput(blob)
            out = self._net.forward()
        return round(float(np.asarray(out).flatten()[0]), 3)

    def score_thumb(self, thumb: bytes | None) -> float | None:
        """Score a face thumbnail (the JPEG of its aligned crop)."""
        if not thumb or self._net is None:
            return None
        img = cv2.imdecode(np.frombuffer(thumb, np.uint8), cv2.IMREAD_COLOR)
        return None if img is None else self.score_aligned(img)
