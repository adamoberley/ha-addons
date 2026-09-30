"""Camera frame sources: an RTSP/HTTP stream, a polled snapshot URL, or an HA camera.

A background thread keeps only the latest frame (draining the stream so we never
process stale buffered frames), and reconnects if the camera drops. `latest()`
hands the recognition loop a fresh copy. Nothing is recorded - frames live in
memory just long enough to be analyzed.

Every source can be *paused* with ``set_active(False)`` - the app does that when
a camera's trigger entities (motion, person) are all off. A paused snapshot or
HA source stops fetching at once; a paused stream is closed after
``STREAM_IDLE_RELEASE`` seconds, since decoding a stream nobody is analyzing is
the single largest idle cost, while reopening one costs a second or two.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time

import cv2
import numpy as np
import requests

log = logging.getLogger("local-faces.camera")

STREAM_IDLE_RELEASE = 60.0      # seconds a paused stream stays open (quick resume)


def decode_jpeg(data: bytes | None) -> np.ndarray | None:
    if not data:
        return None
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return frame if frame is not None and frame.size else None


class _Pausable:
    """The active/paused switch every source shares."""

    def _init_pause(self) -> None:
        self._active = threading.Event()
        self._active.set()                     # sources start active
        self._paused_since = 0.0

    def set_active(self, active: bool) -> None:
        if active and not self._active.is_set():
            self._active.set()
        elif not active and self._active.is_set():
            self._active.clear()
            self._paused_since = time.monotonic()

    @property
    def active(self) -> bool:
        return self._active.is_set()

    def _wait_until_active(self, stop: threading.Event, step: float = 0.5) -> None:
        while not stop.is_set() and not self._active.wait(step):
            pass


def _redact(url: str) -> str:
    """Hide credentials in rtsp://user:pass@host URLs before logging."""
    if "@" in url and "//" in url:
        scheme, _, rest = url.partition("//")
        return f"{scheme}//***@{rest.split('@', 1)[1]}"
    return url


class CameraSource(_Pausable):
    def __init__(self, url: str, mode: str, poll: float) -> None:
        self.url = url
        self.mode = mode
        self.poll = max(0.2, poll)
        self._latest: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._init_pause()

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

    def _idle_too_long(self) -> bool:
        return (not self.active
                and time.monotonic() - self._paused_since > STREAM_IDLE_RELEASE)

    def _run_stream(self) -> None:
        while not self._stop.is_set():
            self._wait_until_active(self._stop)
            if self._stop.is_set():
                break
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
                if self._idle_too_long():
                    log.info("camera idle - closing stream until its triggers fire")
                    with self._lock:
                        self._latest = None     # never analyze a minutes-old frame
                    break
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
            self._wait_until_active(self._stop)
            try:
                resp = requests.get(self.url, timeout=10)
                resp.raise_for_status()
                frame = decode_jpeg(resp.content)
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
        self._active.set()          # wake a paused thread so it can exit


class HaCameraSource(_Pausable):
    """A Home Assistant camera entity, read as stills through the Core API.

    No URL or password in the app's options: HA already holds the camera's
    credentials, and ``/api/camera_proxy`` serves the same still the HA UI
    shows. The fetch interval is set by the app (fast while triggered).
    """

    def __init__(self, client, entity_id: str, poll: float) -> None:
        self.client = client
        self.entity_id = entity_id
        self.poll = max(0.2, poll)
        self._latest: np.ndarray | None = None
        self._latest_ts = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._failures = 0
        self._init_pause()

    def set_interval(self, seconds: float) -> None:
        self.poll = max(0.2, seconds)

    def start(self) -> None:
        if not self.client.available:
            log.error("camera %s needs the Home Assistant API, but there's no Supervisor "
                      "token - is homeassistant_api enabled?", self.entity_id)
            return
        self._thread = threading.Thread(target=self._run, name=f"ha:{self.entity_id}",
                                        daemon=True)
        self._thread.start()
        log.info("camera %s: Home Assistant snapshots", self.entity_id)

    def fetch_once(self) -> bool:
        """Fetch and store one frame; the unit of work the thread repeats."""
        frame = decode_jpeg(self.client.camera_image(self.entity_id))
        if frame is None:
            self._failures += 1
            if self._failures in (3, 30) or self._failures % 300 == 0:
                log.warning("no image from %s (%d attempts) - is the camera online?",
                            self.entity_id, self._failures)
            return False
        self._failures = 0
        with self._lock:
            self._latest, self._latest_ts = frame, time.monotonic()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wait_until_active(self._stop)
            if self._stop.is_set():
                break
            started = time.monotonic()
            self.fetch_once()
            self._stop.wait(max(0.0, self.poll - (time.monotonic() - started)))

    def latest(self) -> np.ndarray | None:
        with self._lock:
            if self._latest is None:
                return None
            # A frame from before the camera was paused is stale: never analyze it.
            if not self.active or time.monotonic() - self._latest_ts > max(10.0, 5 * self.poll):
                return None
            return self._latest.copy()

    def stop(self) -> None:
        self._stop.set()
        self._active.set()
