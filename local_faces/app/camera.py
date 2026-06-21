"""Camera frame source: an RTSP/HTTP stream, or a polled snapshot URL.

A background thread keeps only the latest frame (draining the stream so we never
process stale buffered frames), and reconnects if the camera drops. `latest()`
hands the recognition loop a fresh copy. Nothing is recorded - frames live in
memory just long enough to be analyzed.
"""
from __future__ import annotations

import contextlib
import logging
import threading

import cv2
import numpy as np
import requests

log = logging.getLogger("local-faces.camera")


def _redact(url: str) -> str:
    """Hide credentials in rtsp://user:pass@host URLs before logging."""
    if "@" in url and "//" in url:
        scheme, _, rest = url.partition("//")
        return f"{scheme}//***@{rest.split('@', 1)[1]}"
    return url


class CameraSource:
    def __init__(self, opts) -> None:
        self.url = opts.stream_url
        self.mode = opts.camera_mode
        self.poll = max(0.2, opts.detect_interval)
        self._latest: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.url:
            log.error("no stream_url configured - set your camera's RTSP/HTTP URL and restart")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        if self.mode == "snapshot":
            self._run_snapshot()
        else:
            self._run_stream()

    def _run_stream(self) -> None:
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            with contextlib.suppress(cv2.error):
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                log.error("cannot open stream %s - retrying in 5s", _redact(self.url))
                cap.release()
                self._stop.wait(5)
                continue
            log.info("camera stream opened: %s", _redact(self.url))
            fails = 0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    fails += 1
                    if fails > 30:
                        log.warning("stream stalled - reconnecting")
                        break
                    self._stop.wait(0.05)
                    continue
                fails = 0
                with self._lock:
                    self._latest = frame
            cap.release()

    def _run_snapshot(self) -> None:
        log.info("camera snapshot polling: %s every %.1fs", _redact(self.url), self.poll)
        while not self._stop.is_set():
            try:
                resp = requests.get(self.url, timeout=10)
                resp.raise_for_status()
                arr = np.frombuffer(resp.content, np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    with self._lock:
                        self._latest = frame
            except (requests.RequestException, cv2.error) as exc:
                log.warning("snapshot fetch failed: %s", exc)
            self._stop.wait(self.poll)

    def latest(self) -> np.ndarray | None:
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def stop(self) -> None:
        self._stop.set()
