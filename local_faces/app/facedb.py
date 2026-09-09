"""Enrolled people: name -> one or more face embeddings, persisted in /data.

Embeddings from different recognition models aren't comparable (different spaces,
even different dimensions), so enrollments are namespaced by model id: switching
models shows that model's own people, and switching back keeps the originals -
no re-enroll needed once you've done each model once.

Matching is the max cosine similarity over a person's samples (vectors are
L2-normalized, so the dot product is the cosine); the best person wins if it
clears the threshold, else the face is "unknown". Everything stays on disk in
/data/faces.json - it never leaves the box.

An entry can also be marked *ignored* instead of naming a person: the faces in a
poster, a photo frame, or an arcade cabinet's artwork are real faces, and the
detector is right to find them, but they aren't people arriving. Ignored entries
match exactly like enrolled ones and are then dropped - out of the sightings log,
the sensors, and the notifications. They live in the same per-model namespace
(one flag on the entry), so switching models keeps them separate too.
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
    def __init__(self, threshold: float, model_id: str) -> None:
        self.threshold = threshold
        self.model_id = model_id
        self._lock = threading.Lock()
        self._all: dict = {"version": 2, "models": {}}
        self._emb: dict[str, np.ndarray] = {}   # name -> (k, dim) normalized
        self._thumb: dict[str, str] = {}         # name -> base64 jpeg
        self._ignored: set[str] = set()          # names matched, then deliberately dropped
        self._load()

    def _load(self) -> None:
        if os.path.exists(DB_PATH):
            try:
                with open(DB_PATH, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as exc:
                log.warning("could not read %s: %s", DB_PATH, exc)
                data = {}
            if "models" in data:
                self._all = data
                self._all.setdefault("models", {})
            elif "people" in data:  # migrate v1 (SFace-only) layout
                self._all = {"version": 2, "models": {"sface": {"people": data["people"]}}}
                log.info("migrated existing enrollments to the 'sface' namespace")

        people = (self._all["models"].get(self.model_id) or {}).get("people", {})
        for name, person in people.items():
            vecs = np.array(person.get("embeddings", []), dtype="float32")
            if vecs.size:
                self._emb[name] = vecs.reshape(-1, vecs.shape[-1])
                self._thumb[name] = person.get("thumb", "")
                if person.get("ignored"):
                    self._ignored.add(name)
        enrolled = len(self._emb) - len(self._ignored)
        log.info("loaded %d enrolled %s (+%d ignored) for model '%s'", enrolled,
                 "person" if enrolled == 1 else "people", len(self._ignored), self.model_id)

    def _save(self) -> None:
        self._all.setdefault("models", {})[self.model_id] = {
            "people": {
                name: {
                    "embeddings": self._emb[name].tolist(),
                    "thumb": self._thumb.get(name, ""),
                    **({"ignored": True} if name in self._ignored else {}),
                }
                for name in self._emb
            }
        }
        tmp = DB_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._all, fh)
            os.replace(tmp, DB_PATH)
        except OSError as exc:
            log.warning("could not persist faces: %s", exc)

    def add(self, name: str, embedding: np.ndarray, thumb: bytes,
            ignored: bool = False) -> int:
        """Add a sample to ``name``, creating it as a person or an ignored face.

        An existing name keeps whichever bucket it is already in - see kind().
        """
        vec = embedding.reshape(1, -1).astype("float32")
        with self._lock:
            if name in self._emb:
                self._emb[name] = np.vstack([self._emb[name], vec])
            else:
                self._emb[name] = vec
                if ignored:
                    self._ignored.add(name)
            if thumb:
                self._thumb[name] = base64.b64encode(thumb).decode("ascii")
            samples = int(self._emb[name].shape[0])
            self._save()
        return samples

    def delete(self, name: str) -> bool:
        with self._lock:
            existed = self._emb.pop(name, None) is not None
            self._thumb.pop(name, None)
            self._ignored.discard(name)
            if existed:
                self._save()
        return existed

    def kind(self, name: str) -> str | None:
        """"person", "ignored", or None if the name is unused."""
        with self._lock:
            if name not in self._emb:
                return None
            return "ignored" if name in self._ignored else "person"

    def is_ignored(self, name: str | None) -> bool:
        if not name:
            return False
        with self._lock:
            return name in self._ignored

    def embeddings_for(self, name: str) -> np.ndarray | None:
        with self._lock:
            vecs = self._emb.get(name)
            return None if vecs is None else vecs.copy()

    def people(self) -> list[dict]:
        return self._listing(ignored=False)

    def ignored_faces(self) -> list[dict]:
        """The "not a person" entries, same shape as people()."""
        return self._listing(ignored=True)

    def _listing(self, ignored: bool) -> list[dict]:
        with self._lock:
            return [
                {"name": name, "samples": int(self._emb[name].shape[0]),
                 "thumb": self._thumb.get(name, "")}
                for name in sorted(self._emb)
                if (name in self._ignored) == ignored
            ]

    def match(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Return (name, score) for the best enrolled match, or (None, best_score)."""
        best_name, best = None, -1.0
        with self._lock:
            for name, vecs in self._emb.items():
                if vecs.shape[-1] != embedding.shape[-1]:
                    continue  # guard against any stale, wrong-dimension samples
                score = float((vecs @ embedding).max())
                if score > best:
                    best, best_name = score, name
        return (best_name, best) if best >= self.threshold else (None, best)
