"""Expose REFRAMED Gallery to Home Assistant over MQTT (optional, automatable).

Publishes via MQTT discovery (auto-detecting the Mosquitto broker, or a manual
host), and subscribes to the command topics so HA can drive the gallery:
  - sensor.reframed_gallery_current_art  - current title (+ artist/year/... attrs)
  - button.reframed_gallery_next         - change art now
  - select.reframed_gallery_collection   - switch season/collection live
  - select.reframed_gallery_matte        - switch the TV-rendered matte live
  - text.reframed_gallery_show_link      - put one reframed.gallery URL up now
  - button.reframed_gallery_hide         - hide what's showing for good, show another

Topics, unique ids and object ids are unchanged since 0.6, so existing entities
and automations keep working. If MQTT is unavailable the app still runs.
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
MATTE_STATE = f"{NODE}/matte/state"
MATTE_CMD = f"{NODE}/matte/set"
LINK_STATE = f"{NODE}/link/state"
LINK_CMD = f"{NODE}/link/set"
HIDE_CMD = f"{NODE}/hide/press"

# Offered in the HA "Collection" select. "seasonal" auto-tracks the date;
# "weather" tracks the configured HA weather entity; "all" is the whole
# catalogue; the rest are reframed.gallery collection slugs.
SELECT_OPTIONS = ["seasonal", "weather", "all", "winter", "spring-blossoms",
                  "here-comes-the-sun", "fall", "christmas", "by-the-sea",
                  "golden-hour", "into-the-woods", "nocturnes-moonlight",
                  "in-bloom", "mountains-valleys", "wild-seas"]

# Offered in the HA "Matte" select - common Samsung matte ids (<style>_<color>).
# HA's MQTT select reads the payload "none" as "no option selected" (the entity
# went to unknown), so the no-matte choice is called "off" on the HA side only.
NO_MATTE = "off"
MATTE_OPTIONS = [NO_MATTE, "modern_polar", "modern_apricot", "modern_black",
                 "shadowbox_polar", "shadowbox_black", "flexible_polar"]


def _matte_to_ha(matte: str) -> str:
    return NO_MATTE if (matte or "none") == "none" else matte


def _matte_from_ha(payload: str) -> str:
    return "none" if payload in (NO_MATTE, "none") else payload


def _new_client(mqtt):
    """A paho client that works on both 1.x and 2.x (2.0 requires an explicit
    callback API version; VERSION1 keeps the signatures below valid on both)."""
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    return mqtt.Client()


DEVICE = {"identifiers": [NODE], "name": "REFRAMED Gallery",
          "manufacturer": "REFRAMED Gallery (open source)", "model": "reframed.gallery"}

# (component, topic segment, object_id suffix, extra discovery fields)
ENTITIES = [
    ("sensor", "current", "current_art", {
        "name": "Current Art", "state_topic": CUR_STATE,
        "json_attributes_topic": CUR_ATTR, "icon": "mdi:image-frame"}),
    ("button", "next", "next", {
        "name": "Next", "command_topic": NEXT_CMD, "icon": "mdi:skip-next"}),
    ("select", "collection", "collection", {
        "name": "Collection", "command_topic": SEL_CMD, "state_topic": SEL_STATE,
        "options": SELECT_OPTIONS, "icon": "mdi:palette"}),
    ("select", "matte", "matte", {
        "name": "Matte", "command_topic": MATTE_CMD, "state_topic": MATTE_STATE,
        "options": MATTE_OPTIONS, "icon": "mdi:image-frame"}),
    ("text", "link", "show_link", {
        "name": "Show link", "command_topic": LINK_CMD, "state_topic": LINK_STATE,
        "max": 255, "mode": "text", "icon": "mdi:link-variant"}),
    ("button", "hide", "hide", {
        "name": "Hide current art", "command_topic": HIDE_CMD, "icon": "mdi:eye-off"}),
]


def discovery_messages() -> list[tuple[str, dict]]:
    """(config topic, payload) for every entity."""
    out = []
    for component, segment, suffix, fields in ENTITIES:
        object_id = f"{NODE}_{suffix}"
        out.append((f"homeassistant/{component}/{NODE}/{segment}/config", {
            **fields, "object_id": object_id, "unique_id": object_id,
            "availability_topic": AVAIL, "device": DEVICE}))
    return out


class MqttCtl:
    def __init__(self, opts, app) -> None:
        self.opts = opts
        self.app = app                     # controller.Gallery
        self.client = None

    def _broker(self):
        """(host, port, user, password) - the manual settings, else the
        Supervisor's Mosquitto service, else (None, ...)."""
        o = self.opts
        if o.mqtt_host:
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
        if not self.opts.enable_mqtt:
            return
        host, port, user, pw = self._broker()
        if not host:
            log.warning("MQTT unavailable - HA entities disabled (install the Mosquitto "
                        "broker app, or set mqtt_host)")
            return
        import paho.mqtt.client as mqtt

        client = _new_client(mqtt)
        if user:
            client.username_pw_set(user, pw)
        client.will_set(AVAIL, "offline", retain=True)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        try:
            client.connect_async(host, port, 60)
            client.loop_start()
            self.client = client
            log.info("MQTT connecting to %s:%d", host, port)
        except OSError as exc:
            log.warning("MQTT connect failed: %s", exc)

    def _on_connect(self, client, _userdata, _flags, rc) -> None:
        if rc != 0:
            log.warning("MQTT connection refused (rc=%s)", rc)
            return
        for topic, payload in discovery_messages():
            client.publish(topic, json.dumps(payload), retain=True)
        client.publish(AVAIL, "online", retain=True)
        status = self.app.status
        client.publish(SEL_STATE, status.get("collection") or "seasonal", retain=True)
        client.publish(MATTE_STATE, _matte_to_ha(status.get("matte")), retain=True)
        client.subscribe([(t, 0) for t in (NEXT_CMD, SEL_CMD, MATTE_CMD, LINK_CMD,
                                           HIDE_CMD)])
        log.info("MQTT connected; REFRAMED Gallery entities announced")

    def _publish(self, topic: str, payload: str) -> None:
        if self.client:
            self.client.publish(topic, payload, retain=True)

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            payload = msg.payload.decode().strip()
        except (UnicodeDecodeError, AttributeError):
            return
        topic = msg.topic
        if topic == NEXT_CMD:
            log.info("HA pressed Next")
            self.app.show_next()
        elif topic == HIDE_CMD:
            log.info("HA pressed Hide: %s", self.app.hide_current()[1])
        elif topic == SEL_CMD and payload:
            log.info("HA set collection -> %s", payload)
            self._publish(SEL_STATE, payload)
            self.app.set_collection(payload)
        elif topic == MATTE_CMD and payload:
            matte = _matte_from_ha(payload)
            log.info("HA set matte -> %s", matte)
            self._publish(MATTE_STATE, _matte_to_ha(matte))
            self.app.set_matte(matte)
        elif topic == LINK_CMD and payload:
            accepted, message = self.app.queue_link(payload)
            log.info("HA set link -> %s (%s: %s)", payload,
                     "accepted" if accepted else "rejected", message)
            # Echo only accepted links, so the entity never shows a refused URL.
            if accepted:
                self._publish(LINK_STATE, payload[:255])

    def publish_current(self, art, status: dict) -> None:
        if not self.client:
            return
        self._publish(CUR_STATE, (art.title or "Unknown")[:255])
        self._publish(CUR_ATTR, json.dumps({
            "artist": art.artist, "year": art.year, "medium": art.medium,
            "movement": art.movement, "description": art.description,
            "collection": status.get("collection", ""),
            "matte": status.get("matte", "none"),
            "credit": art.credit, "source": art.source}))

    def stop(self) -> None:
        if not self.client:
            return
        try:
            self.client.publish(AVAIL, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except OSError:
            pass
