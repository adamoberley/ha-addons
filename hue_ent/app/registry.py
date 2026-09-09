"""Auto-discover entertainment zones from Home Assistant's area registry.

Talks to the HA Core WebSocket API (via the Supervisor proxy) to learn which
area each zigbee2mqtt device sits in, then groups the color-capable Philips
lights by room: one candidate zone per area. Also spots each area's Adaptive
Lighting master switch (``switch.adaptive_lighting_<area>``) so the zone can
pause it automatically while streaming.

The Zigbee side of the picture (friendly names, vendor, color capability)
comes from ``zigbee2mqtt/bridge/devices``, which the bridge already consumes;
this module only adds the HA-side room mapping.

Parsing is deliberately shape-tolerant. A registry is a shared space: every
integration on the box writes into it, only some of them correctly, and HA
doesn't validate the *inside* of a device's ``identifiers`` / ``connections``
entries. One integration storing, say, a three-element identifier used to abort
the whole discovery pass (github issue #12) and leave a working Hue setup with
no zones. So a device we cannot read is skipped and named in the log, never
fatal, and IEEE addresses are recovered by pattern from anywhere in the entry
rather than from a fixed position.

A room can also be assigned on the *entity* in HA, not the device, so entity
area overrides are honored too, and a light whose device carries no Zigbee
address at all is still matched by its entity id (z2m names it after the
friendly name).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import aiohttp

LOG = logging.getLogger("hue_ent.registry")

WS_URL = os.environ.get("HA_WS_URL", "ws://supervisor/core/websocket")

# A Zigbee IEEE address as z2m and the MQTT integration write it: 0x + 16 hex.
IEEE_RE = re.compile(r"0x[0-9a-fA-F]{16}")

# Adaptive Lighting creates several switches per config; only the bare
# switch.adaptive_lighting_<name> is the master we want to pause.
AL_PREFIX = "switch.adaptive_lighting_"
AL_SUB_SWITCHES = ("sleep_mode_", "adapt_brightness_", "adapt_color_")

MAX_ZONE_LIGHTS = 10  # Hue Entertainment frames carry at most 10 bulbs


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(name).lower()).strip("_")


@dataclass
class AreaMap:
    """Where Home Assistant thinks each light lives."""

    by_ieee: dict[str, str] = field(default_factory=dict)          # 0x… -> area name
    by_entity_slug: dict[str, str] = field(default_factory=dict)   # light slug -> area name
    al_switches: dict[str, str] = field(default_factory=dict)      # area slug -> entity_id
    areas: int = 0
    devices: int = 0
    unreadable: list[str] = field(default_factory=list)            # devices we had to skip

    def area_for(self, ieee: str, friendly_name: str) -> str | None:
        """Area for a z2m light: by Zigbee address first, then by entity id."""
        return (
            self.by_ieee.get(str(ieee).lower())
            or self.by_entity_slug.get(_slug(friendly_name))
        )


@dataclass
class Discovery:
    """Result of one discovery pass - rooms plus why they came out that way."""

    rooms: list[dict] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    areas: int = 0
    lights: int = 0
    matched: int = 0

    @property
    def summary(self) -> str:
        if not self.ok:
            if not self.error:
                return "Home Assistant rooms have not been read yet."
            return f"Home Assistant rooms could not be read: {self.error}"
        if not self.lights:
            return "No Philips lights on zigbee2mqtt yet."
        if not self.matched:
            return (
                f"None of the {self.lights} Philips light(s) is assigned to a Home "
                f"Assistant area ({self.areas} area(s) exist). Assign them in "
                "Settings → Areas, then Rescan."
            )
        return f"{self.matched} of {self.lights} Philips light(s) matched to a room."


def _walk_strings(value: Any, depth: int = 0) -> Iterator[str]:
    """Yield every string inside an arbitrarily shaped registry field."""
    if depth > 4:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item, depth + 1)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item, depth + 1)


def _ieees(dev: dict) -> set[str]:
    """IEEE addresses mentioned anywhere in a device's identifiers/connections.

    Shape-agnostic on purpose: ``[["mqtt", "zigbee2mqtt_0x00…"]]`` is the shape
    HA documents, but the same address is recovered from a flat list, a longer
    tuple, or a nested dict - whatever an integration happens to have stored.
    """
    found: set[str] = set()
    for field_name in ("identifiers", "connections"):
        for text in _walk_strings(dev.get(field_name)):
            found.update(match.group(0).lower() for match in IEEE_RE.finditer(text))
    return found


async def _fetch_registries() -> tuple[list, list, list]:
    """Return (areas, devices, entities) from HA, or raise."""
    fixture = os.environ.get("HA_REGISTRY_FIXTURE")
    if fixture:  # dev/test hook: run outside the Supervisor with canned registries
        with open(fixture, encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("areas", []), data.get("devices", []), data.get("entities", [])

    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN")
    if not token:
        raise RuntimeError("no SUPERVISOR_TOKEN/HA_TOKEN for the HA WebSocket API")

    async with aiohttp.ClientSession() as session, session.ws_connect(WS_URL, timeout=15) as ws:
        msg = await ws.receive_json()  # auth_required
        if msg.get("type") != "auth_required":
            raise RuntimeError(f"unexpected WS greeting: {msg.get('type')}")
        await ws.send_json({"type": "auth", "access_token": token})
        msg = await ws.receive_json()
        if msg.get("type") != "auth_ok":
            raise RuntimeError("HA WebSocket auth failed")

        async def command(msg_id: int, cmd: str):
            await ws.send_json({"id": msg_id, "type": cmd})
            while True:
                reply = await ws.receive_json()
                if reply.get("id") == msg_id:
                    if not reply.get("success"):
                        raise RuntimeError(f"{cmd} failed: {reply}")
                    return reply["result"]

        areas = await command(1, "config/area_registry/list")
        devices = await command(2, "config/device_registry/list")
        entities = await command(3, "config/entity_registry/list")
    return areas, devices, entities


def build_area_map(areas: list, devices: list, entities: list) -> AreaMap:
    """Fold the three HA registries into one "where does this light live" view."""
    area_names = {
        a["area_id"]: a.get("name") or a["area_id"]
        for a in areas
        if isinstance(a, dict) and a.get("area_id")
    }
    out = AreaMap(areas=len(area_names), devices=len(devices))

    device_area: dict[str, str] = {}      # device_id -> area name
    device_ieees: dict[str, set[str]] = {}  # device_id -> IEEEs
    for dev in devices:
        if not isinstance(dev, dict):
            out.unreadable.append(repr(dev)[:60])
            continue
        try:
            ieees = _ieees(dev)
            area = area_names.get(dev.get("area_id"))
        except Exception as exc:  # a malformed entry must not sink the whole pass
            out.unreadable.append(f"{dev.get('id', '?')} ({exc})")
            continue
        device_id = dev.get("id")
        if device_id:
            device_ieees[device_id] = ieees
            if area:
                device_area[device_id] = area
        if area:
            for ieee in ieees:
                out.by_ieee[ieee] = area

    al_candidates: dict[str, str] = {}  # area slug -> entity_id
    area_slugs = {_slug(name) for name in area_names.values()}
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        entity_id = str(ent.get("entity_id", ""))
        try:
            # An area set on the entity overrides the device's.
            area = area_names.get(ent.get("area_id")) or device_area.get(ent.get("device_id"))
        except TypeError:  # unhashable junk in an entity row
            LOG.debug("skipping unreadable entity registry entry %s", entity_id or "?")
            continue
        if not area:
            continue

        if entity_id.startswith("light."):
            out.by_entity_slug.setdefault(_slug(entity_id.split(".", 1)[1]), area)
            for ieee in device_ieees.get(ent.get("device_id"), ()):
                out.by_ieee[ieee] = area  # entity-level area wins over the device's

        if entity_id.startswith(AL_PREFIX):
            suffix = entity_id[len(AL_PREFIX):]
            if suffix.startswith(AL_SUB_SWITCHES):
                continue  # not the master switch
            # Prefer the switch's own area; fall back to matching by name.
            al_candidates.setdefault(_slug(area), entity_id)
            if suffix in area_slugs:
                al_candidates[suffix] = entity_id
    out.al_switches = al_candidates

    if out.unreadable:
        LOG.warning(
            "skipped %d unreadable device registry entr(ies): %s",
            len(out.unreadable), "; ".join(out.unreadable[:5]),
        )
    return out


def synthesize_rooms(z2m_lights: dict[str, dict], area_map: AreaMap) -> list[dict]:
    """Group color-capable Philips lights by area into candidate zones.

    ``z2m_lights``: {friendly_name: {"ieee": str, "color": bool}} (from the
    bridge's view of zigbee2mqtt/bridge/devices).

    Returns a list of room dicts sorted by name:
      {"name", "lights" (sorted), "pause_entities", "skipped" (non-color or >10)}
    """
    rooms: dict[str, dict] = {}
    for friendly_name, info in sorted(z2m_lights.items()):
        area = area_map.area_for(str(info.get("ieee", "")), friendly_name)
        if not area:
            continue
        room = rooms.setdefault(area, {"name": area, "lights": [], "skipped": []})
        if info.get("color"):
            room["lights"].append(friendly_name)
        else:
            room["skipped"].append(f"{friendly_name} (no color)")

    result = []
    for room in sorted(rooms.values(), key=lambda r: r["name"]):
        if len(room["lights"]) > MAX_ZONE_LIGHTS:
            room["skipped"] += [f"{fn} (zone full)" for fn in room["lights"][MAX_ZONE_LIGHTS:]]
            room["lights"] = room["lights"][:MAX_ZONE_LIGHTS]
        if not room["lights"]:
            continue
        al = area_map.al_switches.get(_slug(room["name"]))
        room["pause_entities"] = [al] if al else []
        result.append(room)
    return result


async def discover_rooms(z2m_lights: dict[str, dict], retries: int = 3) -> Discovery:
    """Fetch the HA registries (with retries) and synthesize candidate rooms."""
    result = Discovery(lights=len(z2m_lights))
    for attempt in range(retries):
        try:
            areas, devices, entities = await _fetch_registries()
            area_map = build_area_map(areas, devices, entities)
            rooms = synthesize_rooms(z2m_lights, area_map)
            matched = sum(
                1 for fn, info in z2m_lights.items()
                if area_map.area_for(str(info.get("ieee", "")), fn)
            )
            result = Discovery(
                rooms=rooms, ok=True, areas=area_map.areas,
                lights=len(z2m_lights), matched=matched,
            )
            LOG.info(
                "discovered %d room(s) with color Hue lights: %s (%d/%d light(s) "
                "matched an area, %d area(s), %d HA device(s))",
                len(rooms), ", ".join(r["name"] for r in rooms) or "-",
                matched, len(z2m_lights), area_map.areas, area_map.devices,
            )
            if z2m_lights and not matched:
                LOG.warning("%s", result.summary)
            return result
        except Exception as exc:
            result = Discovery(lights=len(z2m_lights), error=f"{type(exc).__name__}: {exc}")
            LOG.warning("area discovery failed (%s); attempt %d/%d", exc, attempt + 1, retries)
            if attempt + 1 < retries:
                await asyncio.sleep(5 * (attempt + 1))
    return result
