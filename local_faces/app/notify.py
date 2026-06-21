"""Optional push notification on a recognition, via a Home Assistant notify service.

Calls the HA core API with the add-on's Supervisor token, so a phone ping is the
one thing that may leave your network (whatever your notify service does with it).
Blank notify_service disables it entirely.
"""
from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger("local-faces.notify")


class Notifier:
    def __init__(self, opts) -> None:
        self.service = opts.notify_service.strip()
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        if self.service and not self.token:
            log.warning("notify_service set but no Supervisor token - notifications disabled")

    def send(self, message: str, title: str = "Local Faces") -> None:
        if not self.service or not self.token:
            return
        domain, dot, service = self.service.partition(".")
        if not dot:
            domain, service = "notify", self.service
        url = f"http://supervisor/core/api/services/{domain}/{service}"
        try:
            requests.post(
                url,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"title": title, "message": message},
                timeout=10,
            )
        except requests.RequestException as exc:
            log.warning("notify failed: %s", exc)
