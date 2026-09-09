"""Face detection + embedding on CPU.

Detection (YuNet) runs on a downscaled frame - cheap on a Pi. Embedding is
delegated to a pluggable backend (see embedders.py): SFace by default, or an
ArcFace-style ONNX model. Recognition always runs on the full-resolution face, so
quality isn't lost to the detection downscale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from embedders import build_embedder
from models import ensure_models

log = logging.getLogger("local-faces.engine")


@dataclass
class Face:
    x: int
    y: int
    w: int
    h: int
    score: float
    embedding: np.ndarray  # L2-normalized, dimensionality depends on the model
    thumb: bytes           # aligned crop as JPEG


class FaceEngine:
    def __init__(self, opts) -> None:
        det_path, rec_path = ensure_models(opts)
        self.detector = cv2.FaceDetectorYN.create(
            det_path, "", (320, 320), opts.det_score_threshold, 0.3, 5000
        )
        self.embedder = build_embedder(opts.recognition_model, rec_path)
        self.proc_width = opts.proc_width
        self.min_face = opts.min_face_size
        log.info("engine ready (proc_width=%d, min_face=%dpx)", self.proc_width, self.min_face)

    def detect(self, frame: np.ndarray) -> list[Face]:
        h, w = frame.shape[:2]
        scale = 1.0
        det_img = frame
        if self.proc_width and w > self.proc_width:
            scale = self.proc_width / w
            det_img = cv2.resize(frame, (self.proc_width, max(1, int(h * scale))))

        dh, dw = det_img.shape[:2]
        self.detector.setInputSize((dw, dh))
        _, faces = self.detector.detect(det_img)
        if faces is None:
            return []

        out: list[Face] = []
        for raw in faces:
            row = raw.astype("float32").copy()
            if scale != 1.0:
                row[:14] = row[:14] / scale  # back to full-resolution coords
            x, y, fw, fh = (round(v) for v in row[:4])
            if fh < self.min_face:
                continue
            embedding, thumb = self.embedder.embed(frame, row)
            out.append(Face(x, y, fw, fh, float(row[14]), embedding, thumb))
        return out

    @staticmethod
    def annotate(
        frame: np.ndarray, results: list[tuple[Face, str | None, float, bool]]
    ) -> np.ndarray:
        """Box every detection: green = known, red = unknown, grey = ignored."""
        img = frame.copy()
        for face, name, score, ignored in results:
            known = name is not None
            if ignored:
                color, label, weight = (150, 150, 150), f"ignored ({name})", 1
            elif known:
                color, label, weight = (0, 200, 0), f"{name} {score:.0%}", 2
            else:
                color, label, weight = (40, 40, 220), "unknown", 2
            cv2.rectangle(img, (face.x, face.y), (face.x + face.w, face.y + face.h),
                          color, weight)
            cv2.putText(img, label, (face.x, max(14, face.y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, weight, cv2.LINE_AA)
        return img
