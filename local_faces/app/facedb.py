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

Each sample also has its own record next to its embedding - a stable id, the
face thumbnail it came from, when it was added and its quality score - so the
face library can show, remove or reassign one bad sample instead of all of a
person. That list sits *beside* ``embeddings`` in the file rather than
replacing it, so an older version of the app still reads the file. Samples
enrolled before per-sample records existed get an id but no thumbnail (there
is no way to recover which picture they came from); they can still be judged,
moved and removed by their embedding.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading
import time

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
        self._meta: dict[str, list[dict]] = {}   # name -> one record per embedding row
        self._load()

    @staticmethod
    def _new_sample(thumb_b64: str = "", quality: float | None = None,
                    added: float | None = None) -> dict:
        return {"id": secrets.token_hex(4), "thumb": thumb_b64, "added": added,
                "quality": quality}

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
                meta = person.get("samples")
                rows = self._emb[name].shape[0]
                if not isinstance(meta, list) or len(meta) != rows:
                    meta = [self._new_sample() for _ in range(rows)]   # pre-0.9 entry
                self._meta[name] = [{**self._new_sample(), **m} for m in meta]
        enrolled = len(self._emb) - len(self._ignored)
        log.info("loaded %d enrolled %s (+%d ignored) for model '%s'", enrolled,
                 "person" if enrolled == 1 else "people", len(self._ignored), self.model_id)

    def _save(self) -> None:
        self._all.setdefault("models", {})[self.model_id] = {
            "people": {
                name: {
                    "embeddings": self._emb[name].tolist(),
                    "thumb": self._thumb.get(name, ""),
                    "samples": self._meta.get(name, []),
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
            ignored: bool = False, quality: float | None = None) -> int:
        """Add a sample to ``name``, creating it as a person or an ignored face.

        An existing name keeps whichever bucket it is already in - see kind().
        """
        vec = embedding.reshape(1, -1).astype("float32")
        thumb_b64 = base64.b64encode(thumb).decode("ascii") if thumb else ""
        with self._lock:
            self._append(name, vec, self._new_sample(thumb_b64, quality, time.time()), ignored)
            samples = int(self._emb[name].shape[0])
            self._save()
        return samples

    def _append(self, name: str, vec: np.ndarray, meta: dict, ignored: bool) -> None:
        """Add one row + its record (caller holds the lock)."""
        if name in self._emb:
            self._emb[name] = np.vstack([self._emb[name], vec])
            self._meta.setdefault(name, []).append(meta)
        else:
            self._emb[name] = vec
            self._meta[name] = [meta]
            if ignored:
                self._ignored.add(name)
        if meta.get("thumb"):
            self._thumb[name] = meta["thumb"]

    def delete(self, name: str) -> bool:
        with self._lock:
            existed = self._emb.pop(name, None) is not None
            self._thumb.pop(name, None)
            self._meta.pop(name, None)
            self._ignored.discard(name)
            if existed:
                self._save()
        return existed

    # ---- individual samples (the face library) -----------------------------
    def samples(self, name: str) -> list[dict] | None:
        """One record per sample, with how well it fits the others.

        ``similarity`` is the cosine to the mean of the person's *other*
        samples, and ``outlier`` flags a sample that wouldn't even pass the
        match threshold against them - a blurry shot, a bad angle, or someone
        else's face saved under this name. Needs 3+ samples to mean anything.
        """
        with self._lock:
            vecs = self._emb.get(name)
            if vecs is None:
                return None
            meta = list(self._meta.get(name, []))
            k = vecs.shape[0]
            out = []
            for i in range(k):
                sim = None
                if k >= 3:
                    rest = np.delete(vecs, i, axis=0).mean(axis=0)
                    norm = float(np.linalg.norm(rest))
                    if norm > 0:
                        sim = round(float(vecs[i] @ (rest / norm)), 3)
                m = meta[i] if i < len(meta) else self._new_sample()
                out.append({"id": m["id"], "thumb": m.get("thumb", ""),
                            "added": m.get("added"), "quality": m.get("quality"),
                            "similarity": sim,
                            "outlier": sim is not None and sim < self.threshold})
            return out

    def _index_of(self, name: str, sample_id: str) -> int | None:
        for i, m in enumerate(self._meta.get(name, [])):
            if m.get("id") == sample_id:
                return i
        return None

    def _take(self, name: str, sample_id: str) -> tuple[np.ndarray, dict] | None:
        """Remove one sample from ``name`` and return it (caller holds the lock).

        A person left with no samples is removed entirely.
        """
        i = self._index_of(name, sample_id)
        if i is None:
            return None
        vec = self._emb[name][i:i + 1].copy()
        meta = self._meta[name].pop(i)
        remaining = np.delete(self._emb[name], i, axis=0)
        if remaining.shape[0] == 0:
            self._emb.pop(name)
            self._thumb.pop(name, None)
            self._meta.pop(name, None)
            self._ignored.discard(name)
        else:
            self._emb[name] = remaining
            if meta.get("thumb") and self._thumb.get(name) == meta["thumb"]:
                # The cover picture was this sample: fall back to the newest one left.
                left = [m["thumb"] for m in self._meta[name] if m.get("thumb")]
                self._thumb[name] = left[-1] if left else ""
        return vec, meta

    def delete_sample(self, name: str, sample_id: str) -> int | None:
        """Remove one sample. Returns how many are left (0 = person removed), or None."""
        with self._lock:
            if self._take(name, sample_id) is None:
                return None
            left = int(self._emb[name].shape[0]) if name in self._emb else 0
            self._save()
        return left

    def move_sample(self, name: str, sample_id: str, to: str) -> tuple[bool, str]:
        """Reassign one sample to another person (created if new)."""
        to = (to or "").strip()
        if not to:
            return False, "Pick who this face really is."
        if to == name:
            return False, f"That sample already belongs to {name}."
        with self._lock:
            if to in self._ignored:
                return False, f"{to} is an ignored face, not a person."
            if name in self._ignored:
                return False, "Samples of an ignored face can't be moved to a person."
            taken = self._take(name, sample_id)
            if taken is None:
                return False, "That sample no longer exists - refresh and try again."
            vec, meta = taken
            self._append(to, vec, meta, ignored=False)
            self._save()
        return True, f"Moved to {to}."

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
