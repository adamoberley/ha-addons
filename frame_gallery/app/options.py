"""App options, read from /data/options.json (written by the Supervisor)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

OPTIONS_PATH = "/data/options.json"


@dataclass(frozen=True)
class Options:
    tv_ip: str
    tv_mac: str
    interval_minutes: int
    daily_time: str
    width: int
    height: int
    query: str
    source: str
    collection: str
    hemisphere: str
    weather_entity: str
    public_domain_only: bool
    exclude_keywords: tuple
    fit: str
    mat_color: str
    tv_matte: str
    active_hours: str
    avoid_repeat_count: int
    enable_mqtt: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    log_level: str

    @property
    def interval_seconds(self) -> int:
        return max(60, self.interval_minutes * 60)


def _load_raw() -> dict:
    if not os.path.exists(OPTIONS_PATH):
        return {}
    with open(OPTIONS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _keywords(raw: str) -> tuple:
    return tuple(w.strip().lower() for w in str(raw or "").split(",") if w.strip())


def load() -> Options:
    raw = _load_raw()
    res = str(raw.get("resolution", "3840x2160"))
    try:
        w_str, h_str = res.lower().split("x", 1)
        width, height = int(w_str), int(h_str)
    except ValueError:
        width, height = 3840, 2160

    return Options(
        tv_ip=str(raw.get("tv_ip", "")).strip(),
        tv_mac=str(raw.get("tv_mac", "")).strip(),
        interval_minutes=int(raw.get("interval_minutes", 1440)),
        daily_time=str(raw.get("daily_time", "04:00")).strip(),
        width=width,
        height=height,
        query=str(raw.get("query", "")).strip(),
        source=str(raw.get("source", "reframed")).strip() or "reframed",
        collection=str(raw.get("collection", "seasonal")).strip() or "seasonal",
        hemisphere=str(raw.get("hemisphere", "north")).strip() or "north",
        weather_entity=str(raw.get("weather_entity", "")).strip(),
        public_domain_only=bool(raw.get("public_domain_only", True)),
        exclude_keywords=_keywords(raw.get("exclude_keywords", "")),
        fit=str(raw.get("fit", "crop")),
        mat_color=str(raw.get("mat_color", "#141414")).strip() or "#141414",
        tv_matte=str(raw.get("tv_matte", "none")).strip() or "none",
        active_hours=str(raw.get("active_hours", "")).strip(),
        avoid_repeat_count=int(raw.get("avoid_repeat_count", 2000)),
        enable_mqtt=bool(raw.get("enable_mqtt", True)),
        mqtt_host=str(raw.get("mqtt_host", "")).strip(),
        mqtt_port=int(raw.get("mqtt_port", 1883)),
        mqtt_username=str(raw.get("mqtt_username", "")).strip(),
        mqtt_password=str(raw.get("mqtt_password", "")),
        log_level=str(raw.get("log_level", "info")),
    )
