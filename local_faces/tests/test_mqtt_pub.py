"""The real MqttPublisher, against a recording stand-in for the paho client.

Everything else in these tests uses FakeMqtt, which is why 0.7.0 shipped with a
publisher that crashed on its first call (``self.people`` was never set - #21).
These drive the actual class, so a missing attribute or a lost announce fails
here instead of on someone's box.

Run from the repo root: ``python -m pytest local_faces/tests``
"""

from __future__ import annotations

import json

from helpers import FakeCamera, face_at, make_app, vec
from mqtt_pub import MqttPublisher, _person_disco_topic, _state_topic


class RecordingClient:
    """The paho calls MqttPublisher makes, recorded as (topic, payload)."""

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def publish(self, topic, payload, retain=False):
        self.sent.append((topic, payload))

    def last(self, topic):
        for t, payload in reversed(self.sent):
            if t == topic:
                return payload
        return None


def publisher(cameras=()) -> MqttPublisher:
    return MqttPublisher(opts=None, cameras=[FakeCamera(c, c.title()) for c in cameras])


def connect(pub: MqttPublisher) -> RecordingClient:
    """What paho does once the async connect succeeds."""
    client = RecordingClient()
    pub.client = client
    pub._on_connect(client, None, None, 0)
    return client


# --- the 0.7.0 crash -------------------------------------------------------

def test_announcing_people_on_a_fresh_publisher_does_not_crash():
    pub = publisher()
    assert pub.announce_people(["Alex", "Sam"]) == {"Alex": "alex", "Sam": "sam"}
    assert pub.announce_people(["Alex", "Sam"]) == {"Alex": "alex", "Sam": "sam"}   # no-op path


def test_the_app_starts_with_the_real_publisher(db, log):
    db.add("Alex", vec(1, 0, 0), b"")
    app, _ = make_app(db, log)
    app.mqtt = publisher(["arcade"])       # what App.start() hands _announce_people
    app._announce_people()
    assert app._person_slugs == {"Alex": "alex"}


# --- announce before connect (the normal boot order) ------------------------

def test_people_announced_before_the_connection_reach_ha_on_connect():
    pub = publisher(["arcade"])
    pub.announce_people(["Alex"])          # app.start(): connect is still in flight
    pub.publish_person("alex", False, {"last_seen": None})

    client = connect(pub)

    config = json.loads(client.last(_person_disco_topic("alex")))
    assert config["unique_id"] == "local_faces_person_alex"
    assert client.last(_state_topic("person_alex")) == "OFF"


def test_a_reconnect_resends_each_persons_latest_state():
    pub = publisher()
    pub.announce_people(["Alex"])
    connect(pub)
    pub.publish_person("alex", True, {"camera": "Arcade"})

    client = connect(pub)                  # broker restarted

    assert client.last(_state_topic("person_alex")) == "ON"


def test_a_stale_on_is_corrected_when_the_app_restarts():
    """Retained "ON" from before a crash must not outlive the restart."""
    pub = publisher()                      # new process: nobody seen yet
    pub.announce_people(["Alex"])
    pub.publish_person("alex", False, {})

    client = connect(pub)

    assert client.last(_state_topic("person_alex")) == "OFF"


def test_a_removed_person_is_deleted_and_not_brought_back_on_reconnect():
    pub = publisher()
    pub.announce_people(["Alex", "Sam"])
    client = connect(pub)
    pub.publish_person("sam", True, {})

    pub.announce_people(["Alex"])

    assert client.last(_person_disco_topic("sam")) == ""      # HA drops the entity
    again = connect(pub)
    assert again.last(_person_disco_topic("sam")) is None
    assert again.last(_state_topic("person_sam")) is None
    assert again.last(_person_disco_topic("alex")) is not None


def test_presence_from_the_pipeline_goes_out_through_the_real_publisher(db, log):
    alex = vec(1, 0, 0)
    db.add("Alex", alex, b"")
    app, _ = make_app(db, log, [face_at(alex)])
    app.mqtt = publisher(["arcade"])
    app._announce_people()
    client = connect(app.mqtt)

    app.tick()

    assert client.last(_state_topic("person_alex")) == "ON"
