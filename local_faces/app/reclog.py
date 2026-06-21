"""Recent-recognition log: name, score, and a snapshot thumbnail, kept in /data.

This is the "review later" history shown on the dashboard. It's capped so the
file stays small; thumbnails are the aligned 112x112 crops, base64-encoded.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time

log = logging.getLogger("local-faces.reclog")

LOG_PATH = "/data/recognition-log.json"
CAP = 40


class RecognitionLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, encoding="utf-8") as fh:
                    return list(json.load(fh).get("events", []))[:CAP]
            except (OSError, ValueError):
                pass
        return []

    def _save(self) -> None:
        tmp = LOG_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"events": self.events}, fh)
            os.replace(tmp, LOG_PATH)
        except OSError as exc:
            log.warning("could not persist log: %s", exc)

    def add(self, name: str, score: float, unknown: bool, thumb: bytes) -> None:
        with self._lock:
            self.events.insert(0, {
                "ts": time.time(),
                "name": name,
                "score": round(float(score), 3),
                "unknown": unknown,
                "thumb": base64.b64encode(thumb).decode("ascii") if thumb else "",
            })
            del self.events[CAP:]
            self._save()

    def recent(self) -> list[dict]:
        with self._lock:
            return list(self.events)
