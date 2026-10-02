"""Auto-provision matching DDP devices in LedFX.

The bridge already knows everything LedFX needs per zone (port, pixel count,
frame rate), so instead of making the user mirror each zone by hand in the
LedFX UI, we create the devices through LedFX's REST API: one DDP device named
``Hue <zone>`` per zone (LedFX auto-creates a matching virtual). Idempotent -
an existing device with the right settings is left completely alone (including
whatever effect the user put on it); a device whose settings drifted from the
zone config is deleted and recreated (which resets its effect - logged).

LedFX may boot after us, so provisioning retries until the API answers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import urllib.error
import urllib.request

LOG = logging.getLogger("hue_ent.ledfx")

RETRY_S = 30.0

# LedFX's slowest frame rate; a zone asking for less gets this instead.
LEDFX_MIN_FPS = 10
# How far above the requested rate LedFX's snap can land (its grid is
# 1000/n fps, so the steps stay well under this across 10-126 fps).
FPS_SNAP_SLACK = 1.15

# Keys LedFX can change on a live device; anything else (the target address)
# needs the device recreated.
UPDATABLE_KEYS = ("port", "pixel_count", "refresh_rate")

# Serializes passes: cancelling the asyncio task doesn't stop a pass already
# running in its worker thread, so a rebuild during one could otherwise race it
# (both see the old listing, both act on it).
_PASS_LOCK = threading.Lock()


def _request(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def desired_config(zone, target_ip: str) -> dict:
    return {
        "name": f"Hue {zone.name}",
        "ip_address": target_ip,
        "port": zone.ddp_port,
        "pixel_count": len(zone.lights),
        "refresh_rate": int(zone.fps),
    }


def _fps_ok(have, want: int) -> bool:
    """Is LedFX's stored refresh rate what it would make of ``want``?"""
    if not isinstance(have, (int, float)):
        return False
    return want <= have <= max(want * FPS_SNAP_SLACK, LEDFX_MIN_FPS)


def drifted_keys(existing: dict, want: dict) -> list[str]:
    """The keys of ``want`` that the existing LedFX config doesn't satisfy."""
    out = []
    for key, value in want.items():
        if key == "refresh_rate":
            if not _fps_ok(existing.get(key), value):
                out.append(key)
        elif existing.get(key) != value:
            out.append(key)
    return out


def _provision_pass(base_url: str, target_ip: str, zones) -> None:
    """One synchronous pass; raises on API errors so the caller can retry."""
    listing = _request(f"{base_url}/api/devices")
    devices = listing.get("devices", listing) or {}

    by_name: dict[str, tuple[str, dict]] = {}
    for dev_id, dev in devices.items():
        if isinstance(dev, dict):
            cfg = dev.get("config", dev)
            if isinstance(cfg, dict) and cfg.get("name"):
                by_name[cfg["name"]] = (dev_id, cfg)

    for zone in zones:
        want = desired_config(zone, target_ip)
        existing = by_name.get(want["name"])
        if existing is not None:
            dev_id, cfg = existing
            drift = drifted_keys(cfg, want)
            if not drift:
                LOG.debug("[%s] LedFX device '%s' already in sync", zone.name, want["name"])
                continue
            changes = ", ".join(f"{k} {cfg.get(k)!r} -> {want[k]!r}" for k in drift)
            if all(k in UPDATABLE_KEYS for k in drift):
                # Send the whole config: LedFX saves exactly what it's given,
                # so a partial one would drop the user's other device settings.
                _request(f"{base_url}/api/devices/{dev_id}", method="PUT",
                         body={"config": {**cfg, **want}})
                LOG.info("[%s] updated LedFX device '%s' in place (%s)",
                         zone.name, want["name"], changes)
                continue
            LOG.warning(
                "[%s] LedFX device '%s' changed (%s) - recreating "
                "(its effect selection resets)", zone.name, want["name"], changes,
            )
            _request(f"{base_url}/api/devices/{dev_id}", method="DELETE")
        _request(f"{base_url}/api/devices", method="POST", body={"type": "ddp", "config": want})
        LOG.info(
            "[%s] created LedFX DDP device '%s' (%s:%d, %d px, %d fps)",
            zone.name, want["name"], target_ip, want["port"],
            want["pixel_count"], want["refresh_rate"],
        )


def _provision_once(base_url: str, target_ip: str, zones) -> None:
    with _PASS_LOCK:
        _provision_pass(base_url, target_ip, zones)


async def provision_forever(base_url: str, target_ip: str, zones) -> None:
    """Retry until one full pass succeeds (LedFX may still be booting)."""
    base_url = base_url.rstrip("/")
    while True:
        try:
            await asyncio.to_thread(_provision_once, base_url, target_ip, zones)
            LOG.info("LedFX provisioning complete (%s)", base_url)
            return
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError) as exc:
            LOG.info(
                "LedFX not reachable yet at %s (%s) - retrying in %.0fs", base_url, exc, RETRY_S
            )
        except Exception:
            LOG.exception("LedFX provisioning failed - retrying in %.0fs", RETRY_S)
        await asyncio.sleep(RETRY_S)
