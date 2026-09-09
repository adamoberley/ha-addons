"""Spot the faces that never move, and offer to ignore them.

The ignore list (facedb) fixes posters, photo frames, paused TVs and arcade
artwork - but only once you notice one filling the log and think to ignore it.
This finds them for you: an unknown face that keeps turning up in the *same
place* in the frame, with the *same* embedding, for half an hour or more is
almost certainly a picture, not a person arriving.

It only ever *suggests*. Someone sitting still on a sofa can look like this for
a while, so a suggestion is a card with a thumbnail and two buttons - ignore it,
or say it isn't a picture, which is remembered so you aren't asked again.

Known faces are deliberately never suggested: a framed photo of an enrolled
person can't be ignored safely (its embedding is the person's, so ignoring it
would shadow the real person too), and facedb refuses that on the way in.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger("local-faces.statics")

DISMISSED_PATH = "/data/static-dismissed.json"

MIN_HITS = 12            # sightings before a candidate can be suggested
MIN_SPAN_S = 30 * 60     # ...spanning at least this long: people move, pictures don't
MIN_IOU = 0.7            # how much the box must overlap to count as "the same spot"
FORGET_AFTER_S = 3 * 3600  # a candidate not seen for this long was a passer-by
MAX_CANDIDATES = 60      # bounded: this runs forever on a small box


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    """Intersection over union of two (x, y, w, h) boxes."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    overlap = ix * iy
    union = aw * ah + bw * bh - overlap
    return overlap / union if union > 0 else 0.0


def describe_span(seconds: float) -> str:
    """"3h 12m" / "45m" - how long the thing has been sitting there."""
    minutes = int(max(0, seconds) // 60)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60:02d}m"


@dataclass
class Candidate:
    """One face that keeps appearing in the same place on one camera."""

    id: str
    camera: str
    box: tuple[int, int, int, int]
    embedding: np.ndarray
    thumb: bytes = b""
    first_ts: float = field(default_factory=time.time)
    last_ts: float = field(default_factory=time.time)
    hits: int = 1

    @property
    def span_s(self) -> float:
        return self.last_ts - self.first_ts

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "camera": self.camera,
            "hits": self.hits,
            "span_s": round(self.span_s),
            "span": describe_span(self.span_s),
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "thumb": base64.b64encode(self.thumb).decode("ascii") if self.thumb else "",
        }


class StaticWatcher:
    """Tracks unknown faces per camera and reports the ones that never move."""

    def __init__(self, threshold: float, model: str,
                 min_hits: int = MIN_HITS, min_span_s: float = MIN_SPAN_S) -> None:
        self.threshold = threshold
        self.model = model
        self.min_hits = min_hits
        self.min_span_s = min_span_s
        self._lock = threading.Lock()
        self._candidates: dict[str, Candidate] = {}
        self._dismissed: list[np.ndarray] = []
        self._load_dismissed()

    # -- dismissals persist, so a restart doesn't re-ask ------------------

    def _load_dismissed(self) -> None:
        if not os.path.exists(DISMISSED_PATH):
            return
        try:
            with open(DISMISSED_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            log.warning("could not read %s: %s", DISMISSED_PATH, exc)
            return
        if data.get("model") != self.model:
            return          # embeddings from another model aren't comparable
        for row in data.get("embeddings", []):
            vec = np.array(row, dtype="float32")
            if vec.size:
                self._dismissed.append(vec)
        if self._dismissed:
            log.info("%d dismissed static-face suggestion(s) remembered", len(self._dismissed))

    def _save_dismissed(self) -> None:
        tmp = DISMISSED_PATH + ".tmp"
        payload = {
            "model": self.model,
            "embeddings": [[round(float(v), 6) for v in vec] for vec in self._dismissed],
        }
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, DISMISSED_PATH)
        except OSError as exc:
            log.warning("could not persist dismissals: %s", exc)

    # -- observation ------------------------------------------------------

    def _similar(self, vecs: list[np.ndarray], embedding: np.ndarray) -> bool:
        return any(
            vec.shape[-1] == embedding.shape[-1] and float(vec @ embedding) >= self.threshold
            for vec in vecs
        )

    def observe(self, camera: str, box: tuple[int, int, int, int],
                embedding: np.ndarray, thumb: bytes = b"", now: float | None = None) -> None:
        """Record one unknown face sighting."""
        now = time.time() if now is None else now
        with self._lock:
            self._prune(now)
            if self._similar(self._dismissed, embedding):
                return                    # you already told us it's a person
            for cand in self._candidates.values():
                if (cand.camera == camera
                        and _iou(cand.box, box) >= MIN_IOU
                        and self._similar([cand.embedding], embedding)):
                    cand.hits += 1
                    cand.last_ts = now
                    cand.box = box
                    if thumb:
                        cand.thumb = thumb
                    return
            if len(self._candidates) >= MAX_CANDIDATES:
                oldest = min(self._candidates.values(), key=lambda c: c.last_ts)
                self._candidates.pop(oldest.id, None)
            cand = Candidate(id=secrets.token_hex(6), camera=camera, box=box,
                             embedding=embedding.copy(), thumb=thumb,
                             first_ts=now, last_ts=now)
            self._candidates[cand.id] = cand

    def _prune(self, now: float) -> None:
        for cid in [c.id for c in self._candidates.values()
                    if now - c.last_ts > FORGET_AFTER_S]:
            self._candidates.pop(cid, None)

    # -- what to show -----------------------------------------------------

    def suggestions(self) -> list[dict]:
        """Candidates that look like pictures, longest-standing first."""
        with self._lock:
            ripe = [c for c in self._candidates.values()
                    if c.hits >= self.min_hits and c.span_s >= self.min_span_s]
            ripe.sort(key=lambda c: c.span_s, reverse=True)
            return [c.as_dict() for c in ripe]

    def get(self, candidate_id: str) -> Candidate | None:
        with self._lock:
            return self._candidates.get(candidate_id)

    def drop(self, candidate_id: str) -> None:
        """Stop tracking (it's been ignored, so facedb handles it now)."""
        with self._lock:
            self._candidates.pop(candidate_id, None)

    def dismiss(self, candidate_id: str) -> bool:
        """"That's a person" - remember it and never suggest it again."""
        with self._lock:
            cand = self._candidates.pop(candidate_id, None)
            if cand is None:
                return False
            self._dismissed.append(cand.embedding)
            del self._dismissed[:-200]     # keep the file small
            self._save_dismissed()
        return True
