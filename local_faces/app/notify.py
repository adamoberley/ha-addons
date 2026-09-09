"""Optional push notification on a recognition, via a Home Assistant notify service.

Calls the HA core API with the app's Supervisor token, so a phone ping is the
one thing that may leave your network (whatever your notify service does with it).
Blank notify_service disables it entirely.

Sending happens on a small background worker, not on the caller's thread: the
recognition loop processes one camera per tick, so a notify service that takes
seconds to answer (or a broken one that times out) would otherwise stall
recognition for every camera. The queue is bounded and drops the newest message
when it's full - a backlog of alerts is worth less than a live camera.
"""
from __future__ import annotations

import logging
import os
import queue
import threading

import requests

log = logging.getLogger("local-faces.notify")

QUEUE_SIZE = 16
REQUEST_TIMEOUT = 10


class Notifier:
    def __init__(self, opts) -> None:
        self.service = opts.notify_service.strip()
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        if self.service and not self.token:
            log.warning("notify_service set but no Supervisor token - notifications disabled")
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=QUEUE_SIZE)
        self._worker: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.service and self.token)

    def send(self, message: str, title: str = "Local Faces") -> None:
        """Queue a notification. Never blocks and never raises."""
        if not self.enabled:
            return
        self._ensure_worker()
        try:
            self._queue.put_nowait((title, message))
        except queue.Full:
            log.warning("notify queue full - dropping: %s", message)

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, name="notify", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            title, message = self._queue.get()
            try:
                self._post(title, message)
            except Exception as exc:  # a bad service must not kill the worker
                log.warning("notify failed: %s", exc)
            finally:
                self._queue.task_done()

    def _post(self, title: str, message: str) -> None:
        domain, dot, service = self.service.partition(".")
        if not dot:
            domain, service = "notify", self.service
        try:
            requests.post(
                f"http://supervisor/core/api/services/{domain}/{service}",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"title": title, "message": message},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            log.warning("notify failed: %s", exc)
