"""Ingress GUI: a small zone editor served in the Home Assistant sidebar.

The hard parts of zone setup are exactly the human ones - which bulb is which
(pixel order), which bulb should be the proxy, how bright - so the GUI focuses
on those: per-room cards with light reordering, a per-bulb "blink" button to
identify fixtures, proxy selection, fps/brightness, and enable toggles. Edits
persist to the zone store and apply live (no app restart).

Everything is same-origin and relative-path, so it works both through HA
ingress and directly on the LAN port.
"""

from __future__ import annotations

import logging
import os

from aiohttp import web as aioweb

LOG = logging.getLogger("hue_ent.web")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _state(bridge) -> dict:
    rooms = []
    for view in bridge.room_views:
        slug = view["slug"]
        runner = bridge.runners.get(slug)
        cfg = view["config"]
        rooms.append({
            "slug": slug,
            "source": view["source"],
            "enabled": view["enabled"],
            "armed": bool(runner and runner.armed),
            "active": slug in bridge.zones,
            "name": cfg.get("name", slug),
            "lights": cfg.get("lights", []),
            "available_lights": view["available_lights"],
            "skipped": view.get("skipped", []),
            "proxy": cfg.get("proxy") or (cfg.get("lights") or [None])[0],
            "fps": cfg.get("fps", 20),
            "brightness_scale": cfg.get("brightness_scale", 1.0),
            "auto_start": cfg.get("auto_start", True),
            "idle_timeout_s": cfg.get("idle_timeout_s", 30),
            "pause_entities": cfg.get("pause_entities", []),
            "ddp_port": cfg.get("ddp_port"),
        })
    return {
        "rooms": rooms,
        "auto_zones": bool(bridge.options.get("auto_zones", True)),
        "devices_seen": bridge.devices_seen.is_set(),
        "ledfx_url": str(bridge.options.get("ledfx_url", "http://127.0.0.1:8888") or ""),
        # Why room discovery produced what it did - the panel shows this when no
        # rooms come back, so a failure isn't log-only.
        "discovery": {
            "ok": bridge.discovery.ok,
            "error": bridge.discovery.error,
            "summary": bridge.discovery.summary,
            "areas": bridge.discovery.areas,
            "lights": bridge.discovery.lights,
            "matched": bridge.discovery.matched,
        },
    }


def make_app(bridge) -> aioweb.Application:
    routes = aioweb.RouteTableDef()

    @routes.get("/")
    async def index(request: aioweb.Request) -> aioweb.FileResponse:
        return aioweb.FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @routes.get("/api/state")
    async def state(request: aioweb.Request) -> aioweb.Response:
        return aioweb.json_response(_state(bridge))

    @routes.post("/api/zone/{slug}")
    async def save_zone(request: aioweb.Request) -> aioweb.Response:
        slug = request.match_info["slug"]
        body = await request.json()
        if not any(v["slug"] == slug and v["source"] == "auto" for v in bridge.room_views):
            return aioweb.json_response(
                {"error": "unknown or manual zone (edit manual zones in the app options)"},
                status=400,
            )
        bridge.store.set_override(slug, body)
        await bridge.rebuild_zones()
        return aioweb.json_response(_state(bridge))

    @routes.post("/api/rescan")
    async def rescan(request: aioweb.Request) -> aioweb.Response:
        await bridge.rescan_rooms()
        return aioweb.json_response(_state(bridge))

    @routes.post("/api/blink")
    async def blink(request: aioweb.Request) -> aioweb.Response:
        body = await request.json()
        light = str(body.get("light", ""))
        if light not in bridge.nwk:
            return aioweb.json_response({"error": "unknown light"}, status=400)
        z2m_base = os.environ.get("Z2M_BASE_TOPIC", "zigbee2mqtt")
        await bridge.publish(f"{z2m_base}/{light}/set", '{"effect": "blink"}')
        return aioweb.json_response({"ok": True})

    @routes.post("/api/arm/{slug}")
    async def arm(request: aioweb.Request) -> aioweb.Response:
        slug = request.match_info["slug"]
        body = await request.json()
        runner = bridge.runners.get(slug)
        if runner is None:
            return aioweb.json_response({"error": "zone not active"}, status=400)
        if body.get("armed"):
            await bridge.arm_zone(slug)
        else:
            await runner.manual_off()
        return aioweb.json_response(_state(bridge))

    app = aioweb.Application()
    app.add_routes(routes)
    return app


async def start(bridge, port: int) -> aioweb.AppRunner:
    runner = aioweb.AppRunner(make_app(bridge), access_log=None)
    await runner.setup()
    site = aioweb.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    LOG.info("GUI listening on :%d", port)
    return runner
