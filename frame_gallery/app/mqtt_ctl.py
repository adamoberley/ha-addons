"""Expose REFRAMED Gallery to Home Assistant over MQTT (optional, automatable).

Publishes via MQTT discovery (auto-detecting the Mosquitto broker, or a manual
host), and subscribes to the command topics so HA can drive the add-on:
  - sensor.reframed_gallery_current_art  - current title (+ artist/collection attrs)
  - button.reframed_gallery_next         - press to change art now
  - select.reframed_gallery_collection   - switch season/collection live

If MQTT is unavailable the add-on still runs (the panel + interval are unaffected).
"""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger("frame-gallery.mqtt")

NODE = "reframed_gallery"
AVAIL = f"{NODE}/status"
CUR_STATE = f"{NODE}/current/state"
CUR_ATTR = f"{NODE}/current/attributes"
NEXT_CMD = f"{NODE}/next/press"
SEL_STATE = f"{NODE}/collection/state"
SEL_CMD = f"{NODE}/collection/set"

# Offered in the HA "Collection" select. "seasonal" auto-tracks the date; "all"
# is the whole catalogue; the rest are reframed.gallery collection slugs.
SELECT_OPTIONS = ["seasonal", "all", "winter", "spring-blossoms", "here-comes-the-sun",
                  "fall", "christmas", "by-the-sea", "golden-hour", "into-the-woods",
                  "nocturnes-moonlight", "in-bloom", "mountains-valleys", "wild-seas"]


def _device() -> dict:
    return {"identifiers": [NODE], "name": "REFRAMED Gallery",
            "manufacturer": "REFRAMED Gallery (open source)", "model": "reframed.gallery"}


class MqttCtl:
    def __init__(self, opts, on_next, on_collection) -> None:
        self.opts = opts
        self.on_next = on_next                 # callable() -> show next now
        self.on_collection = on_collection     # callable(slug) -> switch collection
        self.client = None
        self.current_collection = (getattr(opts, "collection", "") or "seasonal")

    def _resolve(self):
        o = self.opts
        if getattr(o, "mqtt_host", ""):
            return o.mqtt_host, o.mqtt_port, o.mqtt_username or None, o.mqtt_password or None
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            return None, 0, None, None
        try:
            r = requests.get("http://supervisor/services/mqtt",
                             headers={"Authorization": f"Bearer {token}"}, timeout=10)
            r.raise_for_status()
            d = r.json().get("data", {})
            return d.get("host"), int(d.get("port", 1883)), d.get("username"), d.get("password")
        except (requests.RequestException, ValueError) as exc:
            log.warning("could not get MQTT details from Supervisor: %s", exc)
            return None, 0, None, None

    def start(self) -> None:
        if not getattr(self.opts, "enable_mqtt", True):
            return
        host, port, user, pw = self._resolve()
        if not host:
            log.warning("MQTT unavailable - HA entities disabled (install the Mosquitto "
                        "broker add-on, or set mqtt_host)")
            return
        import paho.mqtt.client as mqtt

        self.client = mqtt.Client()
        if user:
            self.client.username_pw_set(user, pw)
        self.client.will_set(AVAIL, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
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
        client.publish(f"homeassistant/sensor/{NODE}/current/config", json.dumps({
            "name": "Current Art", "object_id": f"{NODE}_current_art",
            "unique_id": f"{NODE}_current_art", "state_topic": CUR_STATE,
            "json_attributes_topic": CUR_ATTR, "availability_topic": AVAIL,
            "icon": "mdi:image-frame", "device": _device()}), retain=True)
        client.publish(f"homeassistant/button/{NODE}/next/config", json.dumps({
            "name": "Next", "object_id": f"{NODE}_next", "unique_id": f"{NODE}_next",
            "command_topic": NEXT_CMD, "availability_topic": AVAIL,
            "icon": "mdi:skip-next", "device": _device()}), retain=True)
        client.publish(f"homeassistant/select/{NODE}/collection/config", json.dumps({
            "name": "Collection", "object_id": f"{NODE}_collection",
            "unique_id": f"{NODE}_collection", "command_topic": SEL_CMD,
            "state_topic": SEL_STATE, "options": SELECT_OPTIONS,
            "availability_topic": AVAIL, "icon": "mdi:palette", "device": _device()}), retain=True)
        client.publish(AVAIL, "online", retain=True)
        client.publish(SEL_STATE, self.current_collection, retain=True)
        client.subscribe([(NEXT_CMD, 0), (SEL_CMD, 0)])
        log.info("MQTT connected; REFRAMED Gallery entities announced")

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            payload = msg.payload.decode().strip()
        except (UnicodeDecodeError, AttributeError):
            return
        if msg.topic == NEXT_CMD:
            log.info("HA pressed Next")
            self.on_next()
        elif msg.topic == SEL_CMD and payload:
            log.info("HA set collection -> %s", payload)
            self.current_collection = payload
            if self.client:
                self.client.publish(SEL_STATE, payload, retain=True)
            self.on_collection(payload)

    def publish_current(self, art) -> None:
        if not self.client:
            return
        self.client.publish(CUR_STATE, (art.title or "Unknown")[:255], retain=True)
        self.client.publish(CUR_ATTR, json.dumps({
            "artist": art.artist, "collection": self.current_collection,
            "credit": art.credit, "source": art.source}), retain=True)

    def stop(self) -> None:
        if not self.client:
            return
        try:
            self.client.publish(AVAIL, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except OSError:
            pass
