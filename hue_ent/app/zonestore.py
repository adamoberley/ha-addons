"""Persisted zone state: GUI overrides + stable DDP port assignments.

Auto-discovered rooms are only *candidates*; the user's edits from the ingress
GUI (light order, proxy, fps, enabled/disabled, ...) live here in
``/data/zones.json`` and are overlaid on top. Ports are allocated once per
zone slug and remembered forever, so adding a room later never renumbers
existing zones (which would churn the auto-provisioned LedFX devices).

Effective config = auto rooms  ⊕  saved overrides  ⊕  manual ``zones:`` from
the app options (manual zones win on slug collision - the escape hatch).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOG = logging.getLogger("hue_ent.zonestore")

BASE_PORT = 4048
OVERRIDE_KEYS = (
    "enabled", "lights", "proxy", "fps", "idle_timeout_s",
    "auto_start", "brightness_scale", "pause_entities",
)


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")


class ZoneStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("ZONE_STORE", "/data/zones.json")
        self.ports: dict[str, int] = {}
        self.overrides: dict[str, dict] = {}
        self._warned: set[tuple] = set()
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.ports = {k: int(v) for k, v in data.get("ports", {}).items()}
            self.overrides = data.get("overrides", {})
        except FileNotFoundError:
            pass
        except Exception:
            LOG.exception("failed to load %s - starting fresh", self.path)

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"ports": self.ports, "overrides": self.overrides}, handle, indent=2)
        os.replace(tmp, self.path)

    def port_for(self, slug: str) -> int:
        if slug not in self.ports:
            used = set(self.ports.values())
            port = BASE_PORT
            while port in used:
                port += 1
            self.ports[slug] = port
            self.save()
        return self.ports[slug]

    def set_override(self, slug: str, values: dict,
                     auto_pause: list[str] | None = None) -> None:
        clean = {k: values[k] for k in OVERRIDE_KEYS if k in values}
        # The panel sends every field on each save. Keeping pause entities that
        # merely echo what discovery found would freeze them: rename or replace
        # the room's Adaptive Lighting switch later and the zone would go on
        # pausing an entity that no longer exists. Only a real edit is saved.
        if auto_pause is not None and list(clean.get("pause_entities", ())) == list(auto_pause):
            clean.pop("pause_entities", None)
        self.overrides[slug] = clean
        self.save()

    # -- assembly ---------------------------------------------------------

    def assemble(self, auto_rooms: list[dict], manual_zones: list[dict],
                 auto_enabled: bool,
                 known_entities: set[str] | None = None) -> tuple[list[dict], list[dict]]:
        """Merge auto rooms + overrides + manual zones into final zone configs.

        Returns (zone_configs, room_views). ``room_views`` mirrors what the GUI
        shows: every candidate room with its effective settings and whether it
        is enabled/manual.

        ``known_entities`` (every entity HA has, when known) drops saved pause
        entities that no longer exist; a room left with none falls back to the
        one discovery found.
        """
        configs: list[dict] = []
        views: list[dict] = []
        manual_slugs = {_slug(z["name"]) for z in manual_zones}

        if auto_enabled:
            for room in auto_rooms:
                slug = _slug(room["name"])
                if slug in manual_slugs:
                    continue  # manual definition wins outright
                override = self.overrides.get(slug, {})
                available = list(room["lights"])
                # Honor saved light order/subset, dropping lights that vanished
                # and appending any newly discovered ones at the end.
                lights = [fn for fn in override.get("lights", available) if fn in available]
                lights += [fn for fn in available if fn not in lights
                           and "lights" not in override]
                cfg: dict[str, Any] = {
                    "name": room["name"],
                    "lights": lights,
                    "ddp_port": self.port_for(slug),
                    "pause_entities": self._pause_entities(
                        room, override, known_entities),
                }
                for key in ("proxy", "fps", "idle_timeout_s", "auto_start",
                            "brightness_scale"):
                    if key in override:
                        cfg[key] = override[key]
                if cfg.get("proxy") not in lights:
                    cfg.pop("proxy", None)
                enabled = bool(override.get("enabled", True)) and bool(lights)
                views.append({
                    "slug": slug, "source": "auto", "enabled": enabled,
                    "available_lights": available, "skipped": room.get("skipped", []),
                    "config": cfg,
                })
                if enabled:
                    configs.append(cfg)

        for zone in manual_zones:
            slug = _slug(zone["name"])
            cfg = dict(zone)
            cfg.setdefault("ddp_port", self.port_for(slug))
            views.append({
                "slug": slug, "source": "manual", "enabled": True,
                "available_lights": list(zone.get("lights", [])), "skipped": [],
                "config": cfg,
            })
            configs.append(cfg)

        return configs, views

    def _pause_entities(self, room: dict, override: dict,
                        known: set[str] | None) -> list[str]:
        auto = list(room.get("pause_entities", []))
        if "pause_entities" not in override:
            return auto
        saved = list(override["pause_entities"])
        if known is None:
            return saved
        kept = [e for e in saved if e in known]
        gone = [e for e in saved if e not in known]
        if gone:
            key = (room["name"], tuple(gone))
            if key not in self._warned:
                self._warned.add(key)
                LOG.warning(
                    "[%s] saved pause entit%s %s no longer exist%s in Home Assistant - "
                    "ignoring%s", room["name"], "y" if len(gone) == 1 else "ies",
                    ", ".join(gone), "s" if len(gone) == 1 else "",
                    f"; using {', '.join(auto)} instead" if not kept and auto else "",
                )
        if saved and not kept:
            return auto
        return kept
