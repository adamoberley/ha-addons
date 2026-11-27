"""The ingress panel's endpoints, driven over a real socket.

Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import server as server_mod
from controller import Status


class FakeGallery:
    """Just the surface the panel drives; records what it was asked."""

    def __init__(self, preview_path: str, **status) -> None:
        self.calls: list = []
        self.preview_path = preview_path
        self.status = Status(**{
            "busy": False, "last_ts": 1_757_000_000, "last_error": None, "note": None,
            "title": "Wheatfield", "artist": "Someone", "key": "artic:42",
            "hidden_count": 0, "tv_count": 1, "tv_ok": 1, **status})
        self.hide_result = (True, "Hidden 'Wheatfield' - picking another")

    def show_next(self):
        self.calls.append("next")

    def repush(self):
        self.calls.append("repush")

    def hide_current(self):
        self.calls.append("hide")
        return self.hide_result

    def unhide_all(self):
        self.calls.append("unhide")
        return True, "3 piece(s) can appear again"

    def queue_link(self, raw):
        self.calls.append(("link", raw))
        if "reframed.gallery/" in raw:
            return True, "Fetching your piece…"
        return False, "Not a reframed.gallery artwork link"


class Panel:
    def __init__(self, app: FakeGallery) -> None:
        self.app = app
        self.httpd = server_mod.make_server(app, host="127.0.0.1", port=0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def get(self, path: str):
        return self._request(path)

    def post(self, path: str, body: bytes | None = None):
        return self._request(path, method="POST", body=body)

    def _request(self, path: str, method: str = "GET", body: bytes | None = None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"} if body else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def panel(tmp_path):
    p = Panel(FakeGallery(str(tmp_path / "last.jpg")))
    yield p
    p.close()


def test_hide_calls_through_and_answers_the_click(panel):
    code, body = panel.post("/hide")
    assert code == 200
    assert json.loads(body) == {"ok": True, "message": "Hidden 'Wheatfield' - picking another"}
    assert panel.app.calls == ["hide"]


def test_unhide_calls_through(panel):
    code, body = panel.post("/unhide")
    assert code == 200
    assert json.loads(body)["ok"] is True
    assert panel.app.calls == ["unhide"]


def test_a_refused_hide_answers_400_with_the_reason(panel):
    panel.app.hide_result = (False, "Nothing is showing yet")
    code, body = panel.post("/hide")
    assert code == 400
    assert json.loads(body) == {"ok": False, "message": "Nothing is showing yet"}


def test_status_is_the_gallery_status(panel):
    panel.app.status.update(hidden_count=4)
    code, body = panel.get("/status")
    data = json.loads(body)
    assert code == 200
    assert data["hidden_count"] == 4
    assert data["key"] == "artic:42"


def test_next_and_repush_ask_the_gallery(panel):
    assert panel.post("/next")[0] == 200
    assert panel.post("/repush")[0] == 200
    assert panel.app.calls == ["next", "repush"]


def test_show_passes_the_form_field_and_relays_the_answer(panel):
    code, body = panel.post("/show", b"url=https%3A%2F%2Fwww.reframed.gallery%2Fa%2Fb")
    assert (code, json.loads(body)["accepted"]) == (200, True)
    code, body = panel.post("/show", b"url=https%3A%2F%2Fexample.com%2F")
    assert code == 400
    assert json.loads(body)["message"] == "Not a reframed.gallery artwork link"
    assert panel.app.calls[0] == ("link", "https://www.reframed.gallery/a/b")


def test_the_panel_page_is_served(panel):
    code, body = panel.get("/")
    assert code == 200
    assert b"Never show this" in body
    assert rb"match(/\d{4}/)" in body           # the year regex survived the move to a file


def test_preview_is_404_until_something_is_shown_then_served(panel):
    assert panel.get("/preview.jpg")[0] == 404
    Path(panel.app.preview_path).write_bytes(b"\xff\xd8jpeg")
    assert panel.get("/preview.jpg") == (200, b"\xff\xd8jpeg")


def test_an_unknown_path_is_404(panel):
    assert panel.get("/nope")[0] == 404
    assert panel.post("/nope")[0] == 404


@pytest.mark.parametrize(("status", "expected"), [
    ({"last_ts": 0}, (200, "starting")),
    ({}, (200, "ok")),
    ({"tv_count": 2, "tv_ok": 1}, (200, "ok")),           # partial push is healthy
    ({"tv_ok": 0}, (503, "degraded")),                     # reached no TV
    ({"last_error": "boom"}, (503, "degraded")),
])
def test_healthz(status, expected):
    base = {"last_ts": 1, "last_error": None, "tv_count": 1, "tv_ok": 1, **status}
    code, body = server_mod.health(base)
    assert (code, body["status"]) == expected
