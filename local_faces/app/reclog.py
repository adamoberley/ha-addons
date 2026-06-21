"""Recent-recognition log: name, score, snapshot, and the embedding, kept in /data.

This is the "review later" history shown on the dashboard. Each entry also keeps
the face embedding (and the model it came from), so an unknown sighting can be
named straight from the log - that enrolls the stored face without re-capturing.
The list is capped so the file stays small.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
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

    def add(self, name: str, score: float, unknown: bool, thumb: bytes,
            embedding, model: str) -> None:
        with self._lock:
            self.events.insert(0, {
                "id": secrets.token_hex(6),
                "ts": time.time(),
                "name": name,
                "score": round(float(score), 3),
                "unknown": unknown,
                "thumb": base64.b64encode(thumb).decode("ascii") if thumb else "",
                "emb": [round(float(v), 6) for v in embedding],
                "model": model,
            })
            del self.events[CAP:]
            self._save()

    def recent(self) -> list[dict]:
        """Display view for the dashboard - omits the bulky embedding."""
        with self._lock:
            return [
                {k: e[k] for k in ("id", "ts", "name", "score", "unknown", "thumb")}
                for e in self.events
            ]

    def get(self, event_id: str) -> dict | None:
        with self._lock:
            for e in self.events:
                if e.get("id") == event_id:
                    return dict(e)
        return None

    def relabel(self, event_id: str, name: str) -> None:
        with self._lock:
            for e in self.events:
                if e.get("id") == event_id:
                    e["name"] = name
                    e["unknown"] = False
                    self._save()
                    return
