"""Talking to Home Assistant itself: camera snapshots, trigger entities, events.

Everything goes through the Supervisor's proxy to Home Assistant Core with the
app's own ``SUPERVISOR_TOKEN`` (``homeassistant_api: true`` in config.yaml), so
a camera configured as an HA entity needs no RTSP URL and no camera password in
the app's options.

* ``HaClient`` - the REST side: ``camera_image()`` (the same still the HA UI
  shows, via ``/api/camera_proxy``), ``fire_event()``, ``states()``.
* ``TriggerWatcher`` - one websocket that follows the on/off state of the
  entities that gate recognition (a doorbell's person sensor, a motion sensor),
  and calls back the moment one changes, so the recognition loop can start
  looking immediately instead of on its next poll.
* ``EventSender`` - fires ``local_faces_recognized`` on a background worker, for
  the same reason notify.py does: a slow Core must never stall the camera loop.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable, Iterable

import requests

log = logging.getLogger("local-faces.hass")

CORE_API = "http://supervisor/core/api"
CORE_WS = "ws://supervisor/core/websocket"
EVENT_TYPE = "local_faces_recognized"
REQUEST_TIMEOUT = 10

# Entity states that mean "something is happening". Binary sensors are on/off;
# the rest cover the odd integration that reports motion or presence as text.
ACTIVE_STATES = frozenset({"on", "detected", "motion", "occupied", "home", "open"})


def is_active_state(state: str | None) -> bool:
    return (state or "").strip().lower() in ACTIVE_STATES


class HaClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._session = requests.Session()

    @property
    def available(self) -> bool:
        return bool(self.token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def camera_image(self, entity_id: str, timeout: float = REQUEST_TIMEOUT) -> bytes | None:
        """The camera entity's current still as JPEG bytes, or None."""
        if not self.available:
            return None
        try:
            resp = self._session.get(f"{CORE_API}/camera_proxy/{entity_id}",
                                     headers=self._headers(), timeout=timeout)
        except requests.RequestException as exc:
            log.warning("snapshot from %s failed: %s", entity_id, exc)
            return None
        if resp.status_code != 200 or not resp.content:
            log.warning("snapshot from %s failed: HTTP %s", entity_id, resp.status_code)
            return None
        return resp.content

    def fire_event(self, event_type: str, data: dict) -> bool:
        if not self.available:
            return False
        try:
            resp = self._session.post(f"{CORE_API}/events/{event_type}", headers=self._headers(),
                                      json=data, timeout=REQUEST_TIMEOUT)
            return resp.status_code == 200
        except requests.RequestException as exc:
            log.warning("could not fire %s: %s", event_type, exc)
            return False

    def states(self, entity_ids: Iterable[str]) -> dict[str, str]:
        """{entity_id: state} for the given entities (missing ones are skipped)."""
        out: dict[str, str] = {}
        if not self.available:
            return out
        for entity_id in entity_ids:
            try:
                resp = self._session.get(f"{CORE_API}/states/{entity_id}",
                                         headers=self._headers(), timeout=REQUEST_TIMEOUT)
            except requests.RequestException:
                continue
            if resp.status_code == 200:
                out[entity_id] = str(resp.json().get("state", ""))
            elif resp.status_code == 404:
                log.warning("trigger entity %s does not exist in Home Assistant", entity_id)
        return out


class TriggerWatcher:
    """Follows trigger entities over the Core websocket; thread-safe reads.

    Until the first successful connection every trigger reads as *on*: if Home
    Assistant can't tell us whether anything is happening, the safe failure is
    to keep recognizing (the pre-0.8 behavior), not to go blind.
    """

    RECONNECT_MAX = 60

    def __init__(self, entity_ids: Iterable[str], on_change: Callable[[], None] | None = None,
                 token: str | None = None) -> None:
        self.entity_ids = sorted(set(entity_ids))
        self.on_change = on_change
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._lock = threading.Lock()
        self._state: dict[str, bool] = {}
        self._last_on: dict[str, float] = {}
        self.connected = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._msg_id = 0

    # ---- reads -------------------------------------------------------------
    def is_on(self, entity_id: str) -> bool:
        with self._lock:
            if not self.connected and entity_id not in self._state:
                return True
            return self._state.get(entity_id, False)

    def last_on(self, entity_id: str) -> float:
        """When the entity was last seen on (0 if never)."""
        with self._lock:
            return self._last_on.get(entity_id, 0.0)

    # ---- state updates (also the unit-test surface) -------------------------
    def set_state(self, entity_id: str, state: str | None) -> None:
        if entity_id not in self.entity_ids:
            return
        active = is_active_state(state)
        with self._lock:
            was_on = self._state.get(entity_id, False)
            changed = self._state.get(entity_id) != active
            self._state[entity_id] = active
            # "Last on" is the last moment it *was* on: when it turns on, and
            # again when it turns off - the hold after a trigger counts from
            # the drop, however long the trigger was on before it.
            if active or was_on:
                self._last_on[entity_id] = time.time()
        if changed:
            log.debug("trigger %s -> %s", entity_id, "on" if active else "off")
            if self.on_change:
                self.on_change()

    def handle_message(self, msg: dict) -> None:
        """Apply one websocket message (a get_states result or a trigger event)."""
        if msg.get("type") == "result" and isinstance(msg.get("result"), list):
            for st in msg["result"]:
                if isinstance(st, dict):
                    self.set_state(st.get("entity_id", ""), st.get("state"))
        elif msg.get("type") == "event":
            trig = ((msg.get("event") or {}).get("variables") or {}).get("trigger") or {}
            to_state = trig.get("to_state") or {}
            self.set_state(trig.get("entity_id") or to_state.get("entity_id", ""),
                           to_state.get("state"))

    # ---- websocket lifecycle -----------------------------------------------
    def start(self) -> None:
        if not self.entity_ids:
            return
        if not self.token:
            log.warning("no Supervisor token - trigger entities can't be followed; "
                        "recognition runs continuously instead")
            return
        self._thread = threading.Thread(target=self._run, name="triggers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _run(self) -> None:
        import websocket  # websocket-client; imported here so tests don't need it

        backoff = 2
        while not self._stop.is_set():
            ws = None
            try:
                ws = websocket.create_connection(CORE_WS, timeout=30)
                self._handshake(ws)
                with self._lock:
                    self.connected = True
                log.info("following %d trigger entit%s: %s", len(self.entity_ids),
                         "y" if len(self.entity_ids) == 1 else "ies", ", ".join(self.entity_ids))
                backoff = 2
                ws.settimeout(None)
                while not self._stop.is_set():
                    raw = ws.recv()
                    if not raw:
                        break
                    self.handle_message(json.loads(raw))
            except Exception as exc:  # network, auth, protocol: all mean reconnect
                if not self._stop.is_set():
                    log.warning("trigger websocket: %s - reconnecting in %ds", exc, backoff)
            finally:
                with self._lock:
                    self.connected = False
                if ws is not None:
                    with contextlib.suppress(Exception):
                        ws.close()
            self._stop.wait(backoff)
            backoff = min(self.RECONNECT_MAX, backoff * 2)

    def _handshake(self, ws) -> None:
        hello = json.loads(ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"unexpected greeting {hello.get('type')}")
        ws.send(json.dumps({"type": "auth", "access_token": self.token}))
        auth = json.loads(ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"websocket auth failed: {auth.get('type')}")
        # Subscribe first, then read the current states, so a change landing
        # between the two can't be missed.
        ws.send(json.dumps({
            "id": self._next_id(), "type": "subscribe_trigger",
            "trigger": {"platform": "state", "entity_id": self.entity_ids},
        }))
        ws.send(json.dumps({"id": self._next_id(), "type": "get_states"}))


class EventSender:
    """Fires ``local_faces_recognized`` events without blocking the caller."""

    QUEUE_SIZE = 32

    def __init__(self, client: HaClient, enabled: bool = True) -> None:
        self.client = client
        self.enabled = enabled and client.available
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=self.QUEUE_SIZE)
        self._worker: threading.Thread | None = None

    def send(self, data: dict) -> None:
        if not self.enabled:
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._run, name="events", daemon=True)
            self._worker.start()
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            log.warning("event queue full - dropping %s event", EVENT_TYPE)

    def _run(self) -> None:
        while True:
            data = self._queue.get()
            try:
                self.client.fire_event(EVENT_TYPE, data)
            except Exception as exc:
                log.warning("could not fire %s: %s", EVENT_TYPE, exc)
            finally:
                self._queue.task_done()
