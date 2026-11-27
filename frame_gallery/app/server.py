"""Ingress control panel: the current piece, its details, and quick actions.

Bound to 0.0.0.0 for ingress (HA authenticates it). The page (panel.html) uses
relative URLs so it works under the ingress token path. Every action only asks
the gallery (controller.Gallery) and answers at once; the gallery's loop does
the fetching and pushing.

Endpoints: GET / (panel), /status (JSON), /preview.jpg, /healthz;
POST /next, /repush, /show, /hide, /unhide.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("frame-gallery.server")

PANEL_HTML = (Path(__file__).with_name("panel.html")).read_bytes()
MAX_BODY = 4096          # a URL, not an upload endpoint


def health(status: dict) -> tuple[int, dict]:
    """(HTTP code, body) for /healthz. Degraded only on a real failure: a hard
    error, or a completed push that reached zero TVs. A partial push is fine."""
    err, last_ts = status.get("last_error"), status.get("last_ts")
    tv_count, tv_ok = status.get("tv_count", 0), status.get("tv_ok", 0)
    if err or (last_ts and tv_count and tv_ok == 0):
        state, code = "degraded", 503
    elif last_ts:
        state, code = "ok", 200
    else:
        state, code = "starting", 200
    return code, {"status": state, "busy": status.get("busy", False),
                  "last_ts": last_ts or 0, "last_error": err, "note": status.get("note"),
                  "tv_ok": tv_ok, "tv_count": tv_count}


def make_server(app, host: str = "0.0.0.0", port: int = 8099, debug: bool = False):
    """A threading HTTP server for the panel, driving `app` (controller.Gallery)."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if debug:
                log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if ctype.startswith("application/json"):
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code: int, data: dict) -> None:
            self._send(code, "application/json", json.dumps(data).encode())

        def _body_field(self, name: str) -> str:
            """One field from a form-encoded (or JSON) POST body."""
            try:
                length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
            except ValueError:
                return ""
            if length <= 0:
                return ""
            raw = self.rfile.read(length).decode("utf-8", "replace")
            if raw.lstrip().startswith("{"):
                try:
                    return str(json.loads(raw).get(name, ""))
                except (ValueError, AttributeError):
                    return ""
            return (parse_qs(raw).get(name) or [""])[0]

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/next":
                log.info("manual 'show next' requested from control panel")
                app.show_next()
                self._json(200, {"queued": True})
            elif path == "/repush":
                log.info("manual 're-push' requested from control panel")
                app.repush()
                self._json(200, {"queued": True})
            elif path in ("/hide", "/unhide"):
                ok, message = app.hide_current() if path == "/hide" else app.unhide_all()
                self._json(200 if ok else 400, {"ok": ok, "message": message})
            elif path == "/show":
                url = self._body_field("url").strip()
                accepted, message = app.queue_link(url)
                log.info("link %s from control panel: %s",
                         "accepted" if accepted else "rejected", url or "(empty)")
                self._json(200 if accepted else 400,
                           {"accepted": accepted, "message": message})
            else:
                self._send(404, "text/plain", b"not found")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", ""):
                self._send(200, "text/html; charset=utf-8", PANEL_HTML)
            elif path == "/status":
                self._json(200, app.snapshot())
            elif path == "/healthz":
                self._json(*health(app.snapshot()))
            elif path == "/preview.jpg":
                try:
                    body = Path(app.preview_path).read_bytes()
                except OSError:
                    self._send(404, "text/plain", b"no preview yet")
                    return
                self._send(200, "image/jpeg", body)
            else:
                self._send(404, "text/plain", b"not found")

        do_HEAD = do_GET

    return ThreadingHTTPServer((host, port), Handler)
