"""Publish the "Recognized Name" sensor to Home Assistant over MQTT discovery.

Broker details come from the Supervisor's MQTT service automatically (so the
Mosquitto add-on just works), or from the add-on options if you run your own
broker. We publish a retained discovery config once, then the recognized name as
state with score/timestamp attributes. This is the only thing that creates an HA
entity - if MQTT isn't available the add-on still runs (dashboard, log, notify).
"""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger("local-faces.mqtt")

NODE = "local_faces"
DISCOVERY = f"homeassistant/sensor/{NODE}/recognized/config"
STATE_TOPIC = f"{NODE}/recognized/state"
ATTR_TOPIC = f"{NODE}/recognized/attributes"
AVAIL_TOPIC = f"{NODE}/status"


class MqttPublisher:
    def __init__(self, opts) -> None:
        self.opts = opts
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
            log.warning("MQTT unavailable - the 'Recognized Name' sensor will be disabled "
                        "(install the Mosquitto broker add-on, or set mqtt_host)")
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
        config = {
            "name": "Recognized Name",
            "unique_id": "local_faces_recognized",
            "state_topic": STATE_TOPIC,
            "json_attributes_topic": ATTR_TOPIC,
            "availability_topic": AVAIL_TOPIC,
            "icon": "mdi:face-recognition",
            "device": {
                "identifiers": [NODE],
                "name": "Local Faces",
                "manufacturer": "Local Faces (open source)",
                "model": "YuNet + SFace",
            },
        }
        client.publish(DISCOVERY, json.dumps(config), retain=True)
        client.publish(AVAIL_TOPIC, "online", retain=True)
        log.info("MQTT connected; 'Recognized Name' sensor announced")

    def publish_state(self, state: str, attrs: dict) -> None:
        if not self.client:
            return
        self.client.publish(STATE_TOPIC, state, retain=True)
        self.client.publish(ATTR_TOPIC, json.dumps(attrs), retain=True)

    def stop(self) -> None:
        if not self.client:
            return
        try:
            self.client.publish(AVAIL_TOPIC, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except OSError:
            pass
