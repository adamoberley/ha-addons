"""Publish the Home Assistant entities over MQTT: cameras, and people.

Broker details come from the Supervisor's MQTT service automatically (so the
Mosquitto app just works), or from the app options for an external broker.

  * one ``sensor.local_faces_<camera>`` per camera - who that camera can see;
  * ``sensor.local_faces_recognized_name`` - the "anyone known, any camera"
    aggregate, kept for backward compatibility;
  * one ``binary_sensor.local_faces_<person>`` per enrolled person - on while
    that person has been seen within the presence timeout, with ``last_seen``,
    ``camera`` and ``score`` attributes. This is the entity automations actually
    want ("when Alex arrives"), instead of templating over a name string.

Discovery is retained and re-announced on every (re)connect, and a person's
entity is removed from Home Assistant when you delete them. This module is the
only thing that creates entities - if MQTT isn't available the app still runs
(dashboard, log, notify).
"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

log = logging.getLogger("local-faces.mqtt")

NODE = "local_faces"
AVAIL_TOPIC = f"{NODE}/status"
AGG_SLUG = "recognized"            # the legacy aggregate sensor's slug


def _state_topic(slug: str) -> str:
    return f"{NODE}/{slug}/state"


def _attr_topic(slug: str) -> str:
    return f"{NODE}/{slug}/attributes"


def _disco_topic(slug: str) -> str:
    return f"homeassistant/sensor/{NODE}/{slug}/config"


def _person_disco_topic(slug: str) -> str:
    return f"homeassistant/binary_sensor/{NODE}/person_{slug}/config"


def person_slugs(names) -> dict[str, str]:
    """{name: entity slug} for enrolled people.

    Assigned over the sorted names so the same set always produces the same
    entity ids (an entity id that moves between restarts is worse than an ugly
    one), with a numeric suffix when two names slugify the same.
    """
    out: dict[str, str] = {}
    taken: set[str] = set()
    for name in sorted(names):
        base = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "person"
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}_{n}", n + 1
        taken.add(slug)
        out[name] = slug
    return out


def _new_client(mqtt):
    """A paho client that works on both 1.x and 2.x.

    paho-mqtt 2.0 made the callback API version explicit and refuses to build a
    client without one; asking for VERSION1 keeps the callback signatures below
    valid on either major, so the pin can move without a rewrite.
    """
    if hasattr(mqtt, "CallbackAPIVersion"):      # paho-mqtt >= 2.0
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    return mqtt.Client()


def _device() -> dict:
    return {"identifiers": [NODE], "name": "Local Faces",
            "manufacturer": "Local Faces (open source)", "model": "YuNet + SFace"}


class MqttPublisher:
    def __init__(self, opts, cameras) -> None:
        self.opts = opts
        self.cameras = list(cameras)
        self.client = None

    def _resolve(self) -> tuple[str | None, int, str | None, str | None]:
        o = self.opts
        if o.mqtt_host:
            return o.mqtt_host, o.mqtt_port, o.mqtt_username or None, o.mqtt_password or None
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            return None, 0, None, None
        try:
            resp = requests.get(
                "http://supervisor/services/mqtt",
                headers={"Authorization": f"Bearer {token}"}, timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return (data.get("host"), int(data.get("port", 1883)),
                    data.get("username"), data.get("password"))
        except (requests.RequestException, ValueError) as exc:
            log.warning("could not get MQTT details from Supervisor: %s", exc)
            return None, 0, None, None

    def start(self) -> None:
        host, port, user, password = self._resolve()
        if not host:
            log.warning("MQTT unavailable - the 'Recognized Name' sensors will be disabled "
                        "(install the Mosquitto broker app, or set mqtt_host)")
            return
        import paho.mqtt.client as mqtt

        self.client = _new_client(mqtt)
        if user:
            self.client.username_pw_set(user, password)
        self.client.will_set(AVAIL_TOPIC, "offline", retain=True)
        self.client.on_connect = self._on_connect
        try:
            self.client.connect_async(host, port, 60)
            self.client.loop_start()
            log.info("MQTT connecting to %s:%d", host, port)
        except OSError as exc:
            log.warning("MQTT connect failed: %s", exc)
            self.client = None

    def _on_connect(self, client, _userdata, _flags, rc) -> None:
        if rc != 0:
            log.warning("MQTT connection refused (rc=%s)", rc)
            return
        # One sensor per camera. object_id pins the entity_id to sensor.local_faces_<slug>.
        for cam in self.cameras:
            client.publish(_disco_topic(cam.slug), json.dumps({
                "name": cam.name,
                "object_id": f"{NODE}_{cam.slug}",
                "unique_id": f"{NODE}_{cam.slug}",
                "state_topic": _state_topic(cam.slug),
                "json_attributes_topic": _attr_topic(cam.slug),
                "availability_topic": AVAIL_TOPIC,
                "icon": "mdi:face-recognition",
                "device": _device(),
            }), retain=True)
        # Aggregate - identical to the original single-sensor discovery, so the
        # existing sensor.local_faces_recognized_name entity is preserved.
        client.publish(_disco_topic(AGG_SLUG), json.dumps({
            "name": "Recognized Name",
            "unique_id": "local_faces_recognized",
            "state_topic": _state_topic(AGG_SLUG),
            "json_attributes_topic": _attr_topic(AGG_SLUG),
            "availability_topic": AVAIL_TOPIC,
            "icon": "mdi:face-recognition",
            "device": _device(),
        }), retain=True)
        client.publish(AVAIL_TOPIC, "online", retain=True)
        log.info("MQTT connected; announced %d camera sensor(s) + aggregate", len(self.cameras))

    def publish(self, slug: str, state: str, attrs: dict) -> None:
        if not self.client:
            return
        self.client.publish(_state_topic(slug), state, retain=True)
        self.client.publish(_attr_topic(slug), json.dumps(attrs), retain=True)

    # -- per-person presence entities --------------------------------------

    def _announce_person(self, client, name: str, slug: str) -> None:
        client.publish(_person_disco_topic(slug), json.dumps({
            "name": name,
            "object_id": f"{NODE}_{slug}",
            "unique_id": f"{NODE}_person_{slug}",
            "state_topic": _state_topic(f"person_{slug}"),
            "json_attributes_topic": _attr_topic(f"person_{slug}"),
            "availability_topic": AVAIL_TOPIC,
            "device_class": "occupancy",
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:account",
            "device": _device(),
        }), retain=True)

    def announce_people(self, names) -> dict[str, str]:
        """Create/remove person entities to match the enrolled people.

        Returns {name: slug}. Safe to call on every enrollment change: only the
        difference is published, and a removed person's entity is deleted from
        Home Assistant rather than left behind as "unavailable".
        """
        wanted = person_slugs(names)
        if wanted == self.people:
            return dict(self.people)
        previous = self.people
        self.people = wanted
        if not self.client:
            return dict(wanted)
        for name, slug in wanted.items():
            self._announce_person(self.client, name, slug)
        live = set(wanted.values())
        for slug in previous.values():
            if slug not in live:
                self.clear_person(slug)
        return dict(wanted)

    def publish_person(self, slug: str, present: bool, attrs: dict) -> None:
        if not self.client:
            return
        topic = f"person_{slug}"
        self.client.publish(_state_topic(topic), "ON" if present else "OFF", retain=True)
        self.client.publish(_attr_topic(topic), json.dumps(attrs), retain=True)

    def clear_person(self, slug: str) -> None:
        """Remove a person's entity from Home Assistant (empty retained config)."""
        if not self.client:
            return
        self.client.publish(_person_disco_topic(slug), "", retain=True)
        self.client.publish(_state_topic(f"person_{slug}"), "", retain=True)
        self.client.publish(_attr_topic(f"person_{slug}"), "", retain=True)

    def stop(self) -> None:
        if not self.client:
            return
        try:
            self.client.publish(AVAIL_TOPIC, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except OSError:
            pass
