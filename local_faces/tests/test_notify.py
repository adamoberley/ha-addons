"""Notifications must never hold up recognition.

Run from the repo root: ``python -m pytest local_faces/tests``

The recognition loop analyses one camera per tick, so a notify service that
takes seconds to answer used to stall every camera behind it. Sending now
happens on a background worker.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import notify as notify_mod


class Opts:
    def __init__(self, service="notify.mobile_app_test"):
        self.notify_service = service


@pytest.fixture
def notifier(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    return notify_mod.Notifier(Opts())


def test_send_returns_immediately_when_the_service_hangs(notifier, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow_post(*_args, **_kwargs):
        started.set()
        release.wait(5)          # stands in for a service that never answers

    monkeypatch.setattr(notify_mod.requests, "post", slow_post)

    began = time.monotonic()
    notifier.send("Alex recognized at Front Door")
    elapsed = time.monotonic() - began

    assert elapsed < 0.5, f"send() blocked for {elapsed:.2f}s"
    assert started.wait(2), "the worker never made the call"
    release.set()


def test_messages_reach_the_notify_service(notifier, monkeypatch):
    calls, done = [], threading.Event()

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        done.set()

    monkeypatch.setattr(notify_mod.requests, "post", fake_post)

    notifier.send("Unknown person at Arcade")
    assert done.wait(2)

    url, payload = calls[0]
    assert url.endswith("/api/services/notify/mobile_app_test")
    assert payload == {"title": "Local Faces", "message": "Unknown person at Arcade"}


def test_a_bare_service_name_is_treated_as_a_notify_service(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    notifier = notify_mod.Notifier(Opts("mobile_app_test"))
    calls, done = [], threading.Event()
    monkeypatch.setattr(notify_mod.requests, "post",
                        lambda url, **kw: (calls.append(url), done.set()))

    notifier.send("hi")
    assert done.wait(2)
    assert calls[0].endswith("/api/services/notify/mobile_app_test")


def test_a_failing_service_does_not_kill_the_worker(notifier, monkeypatch):
    outcomes, done = [], threading.Event()

    def flaky_post(*_args, **_kwargs):
        outcomes.append(len(outcomes))
        if len(outcomes) == 1:
            raise notify_mod.requests.RequestException("boom")
        done.set()

    monkeypatch.setattr(notify_mod.requests, "post", flaky_post)

    notifier.send("first")
    notifier.send("second")

    assert done.wait(2), "the worker died on the first failure"
    assert len(outcomes) == 2


def test_a_full_queue_drops_instead_of_blocking(notifier, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(notify_mod.requests, "post",
                        lambda *a, **kw: release.wait(5))

    began = time.monotonic()
    for i in range(notify_mod.QUEUE_SIZE + 20):     # far more than the queue holds
        notifier.send(f"message {i}")
    elapsed = time.monotonic() - began
    release.set()

    assert elapsed < 1.0, f"sending {notify_mod.QUEUE_SIZE + 20} blocked for {elapsed:.2f}s"


def test_notifications_are_off_without_a_service(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    notifier = notify_mod.Notifier(Opts(""))
    monkeypatch.setattr(notify_mod.requests, "post",
                        lambda *a, **kw: pytest.fail("should not send"))
    assert not notifier.enabled
    notifier.send("nope")


def test_notifications_are_off_without_a_supervisor_token(monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    notifier = notify_mod.Notifier(Opts())
    monkeypatch.setattr(notify_mod.requests, "post",
                        lambda *a, **kw: pytest.fail("should not send"))
    assert not notifier.enabled
    notifier.send("nope")
