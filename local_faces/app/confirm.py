"""Confirm a recognition across frames before reporting it (Frigate-style).

One frame is a weak witness: a face half-turned toward the camera, motion blur,
or a stranger who happens to land just over the threshold for a single frame is
enough to log, notify and flip a presence sensor. So an identity at a camera is
only *confirmed* once it has been the match in ``need`` of that camera's last
``need + 1`` analyzed frames, and the score it's reported with is the average
over those frames, weighted by face size - a big, close face is better evidence
than a small, distant one.

Counting frames rather than seconds keeps the rule the same at any detection
interval (a triggered doorbell at 0.5 s and a hallway camera at 30 s). Frames
with no face still count as frames, so "2 of the last 3" really means the face
kept being there. ``need = 1`` confirms everything immediately - the pre-0.10
behavior.
"""
from __future__ import annotations

from collections import deque


class FrameConfirmer:
    def __init__(self, frames: int) -> None:
        self.need = max(1, int(frames))
        self._history: dict[str, deque] = {}     # camera slug -> recent frames

    def reset(self, camera: str) -> None:
        """Forget a camera's history (it went idle; old frames are no evidence)."""
        self._history.pop(camera, None)

    def observe(self, camera: str, detections) -> dict:
        """Record one analyzed frame; say which of its identities are confirmed.

        ``detections`` is an iterable of ``(identity, score, face_size)`` for
        this frame (an empty one is still a frame). Returns ``{identity:
        (confirmed, score)}`` for the identities in *this* frame, where score is
        the size-weighted mean over the frames that matched it.
        """
        frame: dict = {}
        for identity, score, size in detections:
            best = frame.get(identity)
            if best is None or score > best[0]:
                frame[identity] = (float(score), max(1.0, float(size)))
        hist = self._history.setdefault(camera, deque(maxlen=self.need + 1))
        hist.append(frame)

        out = {}
        for identity in frame:
            hits = [f[identity] for f in hist if identity in f]
            weight = sum(size for _, size in hits)
            score = sum(s * size for s, size in hits) / weight
            out[identity] = (len(hits) >= self.need, score)
        return out
