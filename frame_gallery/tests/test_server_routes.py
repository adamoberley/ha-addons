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


class Panel:
    """A running panel plus the events/callbacks it drives."""

    def __init__(self, status: dict, **kwargs):
        self.trigger = threading.Event()
        self.repush = threading.Event()
        self.wake = threading.Event()
        self.status = status
        self.httpd = server_mod.make_server(
            self.trigger, status, self.repush, self.wake, host="127.0.0.1", port=0, **kwargs
        )
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


def status_dict(**overrides) -> dict:
    base = {
        "busy": False, "last_ts": 1_757_000_000, "last_error": None, "note": None,
        "title": "Wheatfield", "artist": "Someone", "key": "artic:42",
        "hidden_count": 0, "tv_count": 1, "tv_ok": 1, "_debug": False,
    }
    base.update(overrides)
    return base


@pytest.fixture
def hide_calls():
    return []


@pytest.fixture
def panel(hide_calls):
    def on_hide():
        hide_calls.append("hide")
        return True, "Hidden 'Wheatfield' - picking another"

    def on_unhide():
        hide_calls.append("unhide")
        return True, "3 piece(s) can appear again"

    p = Panel(status_dict(), on_hide=on_hide, on_unhide=on_unhide)
    yield p
    p.close()


def test_hide_calls_through_and_answers_the_click(panel, hide_calls):
    code, body = panel.post("/hide")
    assert code == 200
    assert json.loads(body) == {"ok": True, "message": "Hidden 'Wheatfield' - picking another"}
    assert hide_calls == ["hide"]


def test_unhide_calls_through(panel, hide_calls):
    code, body = panel.post("/unhide")
    assert code == 200
    assert json.loads(body)["ok"] is True
    assert hide_calls == ["unhide"]


def test_a_refused_hide_answers_400_with_the_reason():
    p = Panel(status_dict(key=""), on_hide=lambda: (False, "Nothing is showing yet"))
    try:
        code, body = p.post("/hide")
        assert code == 400
        assert json.loads(body) == {"ok": False, "message": "Nothing is showing yet"}
    finally:
        p.close()


def test_hide_without_a_handler_is_reported_not_available():
    p = Panel(status_dict())
    try:
        code, body = p.post("/hide")
        assert code == 400
        assert json.loads(body)["message"] == "not available"
    finally:
        p.close()


def test_status_exposes_the_hidden_count_and_hides_private_keys(panel):
    panel.status["hidden_count"] = 4
    code, body = panel.get("/status")
    data = json.loads(body)
    assert code == 200
    assert data["hidden_count"] == 4
    assert data["key"] == "artic:42"
    assert not [k for k in data if k.startswith("_")]


def test_next_and_repush_still_set_their_events(panel):
    assert panel.post("/next")[0] == 200
    assert panel.trigger.is_set() and panel.wake.is_set()
    panel.wake.clear()
    assert panel.post("/repush")[0] == 200
    assert panel.repush.is_set() and panel.wake.is_set()


def test_the_panel_and_healthz_are_served(panel):
    code, body = panel.get("/")
    assert code == 200
    assert b"Never show this" in body        # the new button ships in the page

    code, body = panel.get("/healthz")
    assert (code, json.loads(body)["status"]) == (200, "ok")


def test_an_unknown_path_is_404(panel):
    assert panel.get("/nope")[0] == 404
