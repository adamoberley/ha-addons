"""Add-on options, read from /data/options.json (written by the Supervisor)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

OPTIONS_PATH = "/data/options.json"


@dataclass(frozen=True)
class Options:
    tv_ip: str
    interval_minutes: int
    width: int
    height: int
    query: str
    source: str
    public_domain_only: bool
    exclude_keywords: tuple
    fit: str
    mat_color: str
    active_hours: str
    avoid_repeat_count: int
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
        interval_minutes=int(raw.get("interval_minutes", 60)),
        width=width,
        height=height,
        query=str(raw.get("query", "")).strip(),
        source=str(raw.get("source", "reframed")).strip() or "reframed",
        public_domain_only=bool(raw.get("public_domain_only", True)),
        exclude_keywords=_keywords(raw.get("exclude_keywords", "")),
        fit=str(raw.get("fit", "matte")),
        mat_color=str(raw.get("mat_color", "#141414")).strip() or "#141414",
        active_hours=str(raw.get("active_hours", "")).strip(),
        avoid_repeat_count=int(raw.get("avoid_repeat_count", 500)),
        log_level=str(raw.get("log_level", "info")),
    )
