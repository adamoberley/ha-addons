"""Face detection + embedding on CPU, using OpenCV's bundled YuNet and SFace.

Detection runs on a downscaled frame (cheap on a Pi); recognition runs on the
full-resolution aligned 112x112 crop SFace expects, so quality isn't lost. Each
embedding is L2-normalized, so a cosine similarity is just a dot product - that's
what FaceDB compares against enrolled people.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from models import ensure_models

log = logging.getLogger("local-faces.engine")


@dataclass
class Face:
    x: int
    y: int
    w: int
    h: int
    score: float
    embedding: np.ndarray  # (128,) float32, L2-normalized
    thumb: bytes           # aligned 112x112 crop as JPEG


def _encode_thumb(aligned: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", aligned, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else b""


class FaceEngine:
    def __init__(self, opts) -> None:
        det_path, rec_path = ensure_models()
        self.detector = cv2.FaceDetectorYN.create(
            det_path, "", (320, 320), opts.det_score_threshold, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(rec_path, "")
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
            aligned = self.recognizer.alignCrop(frame, row)
            feat = self.recognizer.feature(aligned).flatten().astype("float32")
            norm = float(np.linalg.norm(feat))
            if norm > 0:
                feat = feat / norm
            out.append(Face(x, y, fw, fh, float(row[14]), feat, _encode_thumb(aligned)))
        return out

    @staticmethod
    def annotate(frame: np.ndarray, results: list[tuple[Face, str | None, float]]) -> np.ndarray:
        img = frame.copy()
        for face, name, score in results:
            known = name is not None
            color = (0, 200, 0) if known else (40, 40, 220)  # BGR: green / red
            cv2.rectangle(img, (face.x, face.y), (face.x + face.w, face.y + face.h), color, 2)
            label = f"{name} {score:.0%}" if known else "unknown"
            cv2.putText(img, label, (face.x, max(14, face.y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
        return img
