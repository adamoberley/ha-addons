"""Enrolled people: name -> one or more face embeddings, persisted in /data.

Matching is the max cosine similarity over every enrolled sample (embeddings are
already L2-normalized, so the dot product is the cosine). The best person wins if
it clears the threshold; otherwise the face is "unknown". A small thumbnail per
person is kept for the dashboard. Everything stays on disk in /data/faces.json -
it never leaves the box.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading

import numpy as np

log = logging.getLogger("local-faces.facedb")

DB_PATH = "/data/faces.json"


class FaceDB:
    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self._lock = threading.Lock()
        self._emb: dict[str, np.ndarray] = {}   # name -> (k, 128) normalized
        self._thumb: dict[str, str] = {}         # name -> base64 jpeg
        self._load()

    def _load(self) -> None:
        if not os.path.exists(DB_PATH):
            return
        try:
            with open(DB_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("could not read %s: %s", DB_PATH, exc)
            return
        for name, person in (data.get("people") or {}).items():
            vecs = np.array(person.get("embeddings", []), dtype="float32")
            if vecs.size:
                self._emb[name] = vecs.reshape(-1, vecs.shape[-1])
                self._thumb[name] = person.get("thumb", "")
        log.info("loaded %d enrolled %s", len(self._emb),
                 "person" if len(self._emb) == 1 else "people")

    def _save(self) -> None:
        data = {
            "people": {
                name: {"embeddings": self._emb[name].tolist(), "thumb": self._thumb.get(name, "")}
                for name in self._emb
            }
        }
        tmp = DB_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, DB_PATH)
        except OSError as exc:
            log.warning("could not persist faces: %s", exc)

    def add(self, name: str, embedding: np.ndarray, thumb: bytes) -> int:
        vec = embedding.reshape(1, -1).astype("float32")
        with self._lock:
            if name in self._emb:
                self._emb[name] = np.vstack([self._emb[name], vec])
            else:
                self._emb[name] = vec
            if thumb:
                self._thumb[name] = base64.b64encode(thumb).decode("ascii")
            samples = int(self._emb[name].shape[0])
            self._save()
        return samples

    def delete(self, name: str) -> bool:
        with self._lock:
            existed = self._emb.pop(name, None) is not None
            self._thumb.pop(name, None)
            if existed:
                self._save()
        return existed

    def people(self) -> list[dict]:
        with self._lock:
            return [
                {"name": name, "samples": int(self._emb[name].shape[0]),
                 "thumb": self._thumb.get(name, "")}
                for name in sorted(self._emb)
            ]

    def match(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Return (name, score) for the best enrolled match, or (None, best_score)."""
        best_name, best = None, -1.0
        with self._lock:
            for name, vecs in self._emb.items():
                score = float((vecs @ embedding).max())
                if score > best:
                    best, best_name = score, name
        return (best_name, best) if best >= self.threshold else (None, best)
