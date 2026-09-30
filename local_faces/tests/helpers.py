"""Shared fakes for the Local Faces tests: a whole App with no camera or broker.

The pipeline is the interesting part to test - what reaches the log, the
sensors and the notifier - so the pieces that talk to the outside world (camera,
MQTT, notify) are stubbed and the rest is the real thing, including
``App._process`` and the real annotator.
"""

from __future__ import annotations

import threading

import engine as engine_mod
import hass as hass_mod
import main as main_mod
import numpy as np
import options as options_mod


def vec(*values: float) -> np.ndarray:
    """A unit-length embedding, so dot products are cosines."""
    arr = np.array(values, dtype="float32")
    return arr / np.linalg.norm(arr)


def face_at(embedding: np.ndarray, x: int = 10, y: int = 10, size: int = 40):
    return engine_mod.Face(x=x, y=y, w=size, h=size, score=0.99,
                           embedding=embedding, thumb=b"jpeg")


class FakeCamera:
    def __init__(self, slug: str = "arcade", name: str = "Arcade", triggers=(),
                 camera_entity: str = ""):
        self.slug = slug
        self.name = name
        self.triggers = tuple(triggers)
        self.camera_entity = camera_entity
        self.source_kind = "ha" if camera_entity else "stream"


class FakeQuality:
    """Scores every face ``score`` (None = no quality model, gate off)."""

    def __init__(self, score=None):
        self.score = score

    def score_thumb(self, _thumb):
        return self.score


class FakeEvents:
    """Records the local_faces_recognized events that would have been fired."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, data):
        self.sent.append(data)


class FakeSource:
    def __init__(self, frame):
        self._frame = frame
        self.active = True

    def latest(self):
        return self._frame

    def set_active(self, active):
        self.active = active


class FakeMqtt:
    """Records what would have been published, including person entities."""

    def __init__(self):
        self.published: list[tuple] = []
        self.people: dict[str, str] = {}
        self.person_states: list[tuple] = []
        self.cleared: list[str] = []

    def publish(self, slug, state, attrs):
        self.published.append((slug, state, attrs))

    def announce_people(self, names):
        from mqtt_pub import person_slugs
        self.people = person_slugs(names)
        return dict(self.people)

    def publish_person(self, slug, present, attrs):
        self.person_states.append((slug, present, attrs))

    def clear_person(self, slug):
        self.cleared.append(slug)

    def person_state(self, slug: str):
        """The last state published for one person, or None."""
        for s, present, attrs in reversed(self.person_states):
            if s == slug:
                return present, attrs
        return None


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, message):
        self.sent.append(message)


class FakeEngine:
    """Returns pre-baked detections; annotate() is the real implementation."""

    def __init__(self, faces):
        self.faces = list(faces)

    def detect(self, _frame):
        return list(self.faces)

    @staticmethod
    def annotate(frame, results):
        return engine_mod.FaceEngine.annotate(frame, results)


def make_options(**overrides) -> options_mod.Options:
    base = dict(
        stream_url="", camera_mode="stream", cameras=(), preview_aspect="auto",
        mode="balanced", recognition_model="sface", recognition_model_url="",
        detect_interval=1.0, recognition_threshold=0.5, min_face_size=60,
        cooldown_seconds=0, notify_service="notify.test", notify_unknown=True,
        person_sensors=True, presence_timeout_seconds=120,
        active_interval=0.5, trigger_hold_seconds=10, fire_events=True,
        enable_mqtt=True, mqtt_host="", mqtt_port=1883, mqtt_username="",
        mqtt_password="", log_level="info",
    )
    base.update(overrides)
    return options_mod.Options(**base)


def make_app(db, log, faces=(), cameras=("arcade",), statics=None, triggers=None,
             **opt_overrides):
    """An App with the real pipeline and stubbed edges. Returns (app, cameras).

    ``triggers`` maps a camera slug to its trigger entities; the app gets a real
    TriggerWatcher (never started - tests drive it with set_state()).
    """
    app = main_mod.App.__new__(main_mod.App)
    app.opts = make_options(**opt_overrides)
    triggers = triggers or {}
    cams = [FakeCamera(slug, slug.title(), triggers.get(slug, ())) for slug in cameras]
    app.cameras = cams
    app.engine = FakeEngine(faces)
    app.db = db
    app.reclog = log
    app.statics = statics if statics is not None else _NullWatcher()
    app.sources = {c.slug: FakeSource(np.zeros((120, 160, 3), dtype="uint8")) for c in cams}
    app.mqtt = FakeMqtt()
    app.notifier = FakeNotifier()
    app.ha = None
    app.wake = threading.Event()
    app.triggers = hass_mod.TriggerWatcher([t for c in cams for t in c.triggers],
                                           on_change=app.wake.set, token="test")
    app.triggers.connected = True          # as if the websocket were up
    app.events = FakeEvents()
    app.quality = FakeQuality()
    app.httpd = None
    app.running = True
    app._lock = threading.Lock()
    app._previews = {}
    app._status = {c.slug: main_mod.App._blank(c) for c in cams}
    app._cooldown = {}
    app._last_pub = {}
    app._pending = {}
    app._seen = {}
    app._person_slugs = {}
    app._rr = 0
    app._announce_people()
    return app, cams


class _NullWatcher:
    """Stands in for StaticWatcher when a test doesn't care about suggestions."""

    def observe(self, *args, **kwargs):
        pass

    def suggestions(self):
        return []

    def get(self, _candidate_id):
        return None

    def drop(self, _candidate_id):
        pass

    def dismiss(self, _candidate_id):
        return False
