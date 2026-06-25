"""Publish a "Recognized Name" sensor per camera (plus an aggregate) over MQTT.

Broker details come from the Supervisor's MQTT service automatically (so the
Mosquitto app just works), or from the app options for an external broker.
Each camera gets sensor.local_faces_<slug>; sensor.local_faces_recognized_name is
kept as an "anyone known, any camera" aggregate for backward compatibility. We
publish retained discovery once, then state per camera. This is the only thing
that creates HA entities - if MQTT isn't available the app still runs
(dashboard, log, notify).
"""
from __future__ import annotations

import json
import logging
import os

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

        self.client = mqtt.Client()
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

    def stop(self) -> None:
        if not self.client:
            return
        try:
            self.client.publish(AVAIL_TOPIC, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except OSError:
            pass
