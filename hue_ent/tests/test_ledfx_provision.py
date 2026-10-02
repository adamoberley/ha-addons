"""LedFX auto-provisioning: leave in-sync devices alone, fix drift in place.

Run from the repo root: ``python -m pytest hue_ent/tests``

The regression (#30): LedFX snaps a device's ``refresh_rate`` up to a rate its
frame clock can hit - nothing below ~10 fps - so a 5 fps zone read back as 10,
never "matched", and every provisioning pass deleted and recreated the device,
resetting its effect (and briefly orphaning its virtual, which tripped a crash
in LedFX's own MQTT integration).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hue_ent.app import ledfx as ledfx_mod
from hue_ent.app import main as main_mod

BASE = "http://ledfx"


def ledfx_fps_grid() -> list[int]:
    """LedFX's AVAILABLE_FPS on Linux (1 ms sleep ticks, 10-126 fps)."""
    return sorted({int(1 / (0.001 * i)) for i in range(8, 100)})


def ledfx_snap(fps: int) -> int:
    """What LedFX's fps_validator stores for a requested refresh rate."""
    grid = ledfx_fps_grid()
    return next((f for f in grid if f >= fps), grid[-1])


class FakeLedFx:
    """The slice of LedFX's REST API provisioning uses, with its fps snapping."""

    def __init__(self):
        self.devices: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []

    def _store(self, cfg: dict) -> dict:
        cfg = dict(cfg)
        cfg.setdefault("icon_name", "mdi:led-strip")
        cfg.setdefault("destination_id", 1)
        cfg["refresh_rate"] = ledfx_snap(cfg["refresh_rate"])
        return cfg

    def request(self, url: str, method: str = "GET", body: dict | None = None) -> dict:
        path = url.removeprefix(BASE)
        self.calls.append((method, path))
        if method == "GET":
            return {"status": "success", "devices": {
                dev_id: {"id": dev_id, "type": "ddp", "config": cfg}
                for dev_id, cfg in self.devices.items()
            }}
        if method == "POST":
            dev_id = body["config"]["name"].lower().replace(" ", "-")
            self.devices[dev_id] = self._store(body["config"])
            return {"status": "success"}
        dev_id = path.rsplit("/", 1)[-1]
        if method == "PUT":
            self.devices[dev_id] = self._store({**self.devices[dev_id], **body["config"]})
        elif method == "DELETE":
            del self.devices[dev_id]
        return {"status": "success"}

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]


@pytest.fixture
def fake(monkeypatch):
    fake = FakeLedFx()
    monkeypatch.setattr(ledfx_mod, "_request", fake.request)
    return fake


def zone(fps=5, lights=("A", "B", "C"), port=4048, name="Wohnzimmer"):
    return main_mod.Zone({"name": name, "lights": list(lights), "ddp_port": port, "fps": fps})


def provision(z, target="127.0.0.1"):
    ledfx_mod._provision_once(BASE, target, [z])


@pytest.mark.parametrize("fps", [5, 9, 10, 15, 20, 23, 24, 25])
def test_a_device_ledfx_snapped_is_left_alone(fake, fps):
    """The bug: the second pass "drifted" and recreated the device every time."""
    provision(zone(fps=fps))
    assert fake.writes() == [("POST", "/api/devices")]
    fake.calls.clear()

    provision(zone(fps=fps))
    provision(zone(fps=fps))

    assert fake.writes() == [], "an in-sync device must not be touched"


def test_every_zone_rate_survives_ledfx_snapping():
    """Whatever LedFX makes of any sane rate, it reads back as in sync (zones
    are capped at 25 fps; LedFX itself tops out around 125)."""
    for fps in range(1, 121):
        assert ledfx_mod._fps_ok(ledfx_snap(fps), fps), fps


def test_a_rate_ledfx_would_not_have_picked_is_drift():
    assert not ledfx_mod._fps_ok(10, 20)      # too slow for a 20 fps zone
    assert not ledfx_mod._fps_ok(60, 20)      # LedFX's default, never set by us
    assert not ledfx_mod._fps_ok(None, 20)


def test_a_changed_pixel_count_is_updated_in_place(fake):
    provision(zone(lights=("A", "B", "C")))
    fake.devices["hue-wohnzimmer"]["icon_name"] = "mdi:sofa"   # a user tweak
    fake.calls.clear()

    provision(zone(lights=("A", "B", "C", "D")))

    assert fake.writes() == [("PUT", "/api/devices/hue-wohnzimmer")]
    dev = fake.devices["hue-wohnzimmer"]
    assert dev["pixel_count"] == 4
    assert dev["icon_name"] == "mdi:sofa", "the full config is sent, not a partial one"


def test_a_faster_zone_raises_the_rate_in_place(fake):
    provision(zone(fps=5))
    fake.calls.clear()

    provision(zone(fps=20))

    assert fake.writes() == [("PUT", "/api/devices/hue-wohnzimmer")]
    assert fake.devices["hue-wohnzimmer"]["refresh_rate"] == 20


def test_a_new_target_address_recreates_the_device(fake):
    """LedFX resolves the address once at creation, so this one can't be PUT."""
    provision(zone(), target="127.0.0.1")
    fake.calls.clear()

    provision(zone(), target="192.168.1.20")

    assert fake.writes() == [
        ("DELETE", "/api/devices/hue-wohnzimmer"), ("POST", "/api/devices"),
    ]
    assert fake.devices["hue-wohnzimmer"]["ip_address"] == "192.168.1.20"
