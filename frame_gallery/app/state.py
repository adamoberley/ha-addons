"""Recently-shown history and the hidden list, persisted in /data.

Two pieces of memory, both in ``/data/gallery-state.json``:

  * **recent** - the last N artwork keys (``source:id``); the picker skips
    anything still in the window, which is what stops the repeats the old
    art-changer was full of.
  * **hidden** - pieces you told the gallery never to show again. A curated
    public-domain collection still contains work you don't want on your living
    room wall for the next month, and the alternative was editing keyword
    filters until it went away. One button, gone for good.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("frame-gallery.state")

STATE_PATH = "/data/gallery-state.json"


class History:
    def __init__(self, cap: int) -> None:
        self.cap = max(0, cap)
        data = self._load()
        self.recent: list = list(data.get("recent", []))
        self.hidden: set[str] = {str(k) for k in data.get("hidden", []) if k}

    # -- persistence -------------------------------------------------------

    def _load(self) -> dict:
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, encoding="utf-8") as fh:
                    data = json.load(fh)
                return data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                pass
        return {}

    def _save(self) -> None:
        tmp = STATE_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"recent": self.recent, "hidden": sorted(self.hidden)}, fh)
            os.replace(tmp, STATE_PATH)
        except OSError as exc:
            log.warning("could not persist history: %s", exc)

    # -- the no-repeat window ---------------------------------------------

    def seen(self, key: str) -> bool:
        return self.cap > 0 and key in self.recent

    def add(self, key: str) -> None:
        if self.cap <= 0:
            return
        if key in self.recent:
            self.recent.remove(key)
        self.recent.append(key)
        if len(self.recent) > self.cap:
            self.recent = self.recent[-self.cap:]
        self._save()

    # -- the hidden list ---------------------------------------------------

    def is_hidden(self, key: str) -> bool:
        return bool(key) and key in self.hidden

    def hide(self, key: str) -> bool:
        """Never show this piece again. False if it was already hidden."""
        if not key or key in self.hidden:
            return False
        self.hidden.add(key)
        self._save()
        return True

    def unhide_all(self) -> int:
        """Forget every hidden piece. Returns how many came back."""
        count = len(self.hidden)
        if count:
            self.hidden.clear()
            self._save()
        return count
