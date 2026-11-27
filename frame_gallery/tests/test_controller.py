"""The gallery controller: requests, the loop's choices, and what it records.

No TV, network or clock: TVs and sources are fakes, and the loop is run one
pass at a time. Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import controller as controller_mod
import gallery as gallery_mod
import state as state_mod
from sources.base import Artwork
from sources.reframed import ReframedSource


def jpeg(color=(10, 120, 200)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, format="JPEG")
    return buf.getvalue()


def options(**overrides):
    base = dict(
        tv_matte="none", source="artic", collection="seasonal", hemisphere="north",
        weather_entity="", query="", interval_minutes=1440, interval_seconds=86400,
        daily_time="04:00", library_size=1, active_hours="", fit="crop",
        width=32, height=18, mat_color="#141414", public_domain_only=True,
        exclude_keywords=())
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeTV:
    def __init__(self, host="tv1", art_mode=True, fails=False):
        self.host, self.matte, self.art_mode, self.fails = host, "none", art_mode, fails
        self.pushes: list[tuple[bytes, str]] = []

    def push(self, data, matte=None):
        if self.fails:
            raise OSError("TV unreachable")
        self.pushes.append((data, matte))
        return "MY_F0001" if self.art_mode else None


class FakeSource:
    name = "artic"

    def __init__(self, arts=()):
        self.arts = list(arts)

    def candidates(self, opts, count=100):
        return list(self.arts)


def art(n: int) -> Artwork:
    return Artwork(source="artic", id=str(n), title=f"Piece {n}", artist="A",
                   image_url=f"https://img/{n}.jpg", year="1889")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(gallery_mod, "download", lambda url: jpeg())
    monkeypatch.setattr(gallery_mod, "_broken", set())


def make(tmp_path, *, arts=(art(1), art(2)), tvs=None, source=None, **opts):
    tvs = tvs if tvs is not None else [FakeTV()]
    app = controller_mod.Gallery(options(**opts), tvs, state_mod.History(100),
                                 source or FakeSource(arts),
                                 preview_path=str(tmp_path / "last.jpg"))
    return app


def one_pass(app) -> list:
    """Run the loop once; returns the wait it chose."""
    waits = []

    def wait(timeout):
        waits.append(timeout)
        app.stop.set()

    app.intents.wait = wait
    app.run()
    app.stop.clear()
    return waits


# --- the loop --------------------------------------------------------------

def test_the_first_pass_shows_a_piece_and_records_it(tmp_path):
    app = make(tmp_path)
    shown = []
    app.listeners.append(lambda a, status: shown.append((a.key, status["title"])))
    one_pass(app)

    status = app.status.snapshot()
    assert status["key"] in ("artic:1", "artic:2")
    assert (status["tv_ok"], status["last_error"], status["busy"]) == (1, None, False)
    assert status["year"] == "1889"
    assert app.history.seen(status["key"])
    assert shown == [(status["key"], status["title"])]
    assert Path(app.preview_path).read_bytes()[:2] == b"\xff\xd8"


def test_a_failed_scheduled_change_retries_soon(tmp_path):
    app = make(tmp_path, arts=(), daily_time="")         # interval 24 h, no clock edge
    (wait,) = one_pass(app)
    assert controller_mod.RETRY_SECONDS - 5 < wait <= controller_mod.RETRY_SECONDS
    assert app.status.get("last_error").startswith("no artwork found")


def test_a_manual_action_does_not_cancel_a_pending_retry(tmp_path):
    app = make(tmp_path, arts=(), daily_time="")
    one_pass(app)                                       # scheduled change fails
    app.repush()
    (wait,) = one_pass(app)                             # a re-push wakes the loop
    assert wait <= controller_mod.RETRY_SECONDS         # still due in <= 15 min
    assert app.retry_pending


def test_the_retry_is_cleared_once_it_runs(tmp_path):
    app = make(tmp_path, arts=(), daily_time="", interval_seconds=6 * 3600)
    one_pass(app)
    app.source.arts = [art(1)]
    assert one_pass(app) == [pytest.approx(6 * 3600, abs=5)]   # retry ran and worked
    assert not app.retry_pending


def test_time_spent_working_comes_off_the_wait(tmp_path, monkeypatch):
    clock = iter([1000.0, 1400.0])                      # before work, after work
    monkeypatch.setattr(controller_mod.time, "monotonic", lambda: next(clock))
    app = make(tmp_path, daily_time="", interval_seconds=3600)
    app.status.update = lambda **kw: None               # keep time.time() out of it
    assert one_pass(app) == [3200.0]


def test_shutdown_after_taking_requests_starts_no_work(tmp_path):
    app = make(tmp_path)
    take = app.intents.take

    def take_then_stop():
        got = take()
        app.shutdown()                                  # SIGTERM lands right here
        return got

    app.intents.take = take_then_stop
    app.run()
    assert app.status.get("last_ts") == 0


def test_a_good_scheduled_change_waits_for_the_next_slot(tmp_path):
    app = make(tmp_path, daily_time="", interval_seconds=6 * 3600)
    assert one_pass(app) == [pytest.approx(6 * 3600, abs=5)]


def test_outside_active_hours_a_timeout_does_nothing(tmp_path, monkeypatch):
    app = make(tmp_path, active_hours="07:00-07:01")
    monkeypatch.setattr(controller_mod, "within_active_hours", lambda spec, now: False)
    one_pass(app)
    assert app.status.get("last_ts") == 0


def test_a_request_ignores_active_hours(tmp_path, monkeypatch):
    app = make(tmp_path)
    monkeypatch.setattr(controller_mod, "within_active_hours", lambda spec, now: False)
    app.show_next()
    one_pass(app)
    assert app.status.get("key")


def test_a_link_beats_a_fresh_pick_and_requests_are_consumed(tmp_path):
    app = make(tmp_path)
    order = []
    app._show_link = lambda url: order.append(("link", url))
    app._cycle = lambda: order.append("cycle") or True
    app.intents.request(controller_mod.NEXT)
    app.intents.request(controller_mod.REPUSH)
    app.intents.request(controller_mod.LINK, "https://www.reframed.gallery/a/b")
    one_pass(app)
    assert order == [("link", "https://www.reframed.gallery/a/b")]
    assert app.intents.take() == {}              # the rest were dropped, not left over


def test_a_tv_without_art_mode_is_not_counted_as_reached(tmp_path):
    app = make(tmp_path, tvs=[FakeTV("a"), FakeTV("b", art_mode=False)])
    one_pass(app)
    assert (app.status.get("tv_ok"), app.status.get("note")) == (1, "reached 1/2 TV(s)")


def test_an_unreachable_tv_is_a_note_not_a_crash(tmp_path):
    app = make(tmp_path, tvs=[FakeTV("a", fails=True)])
    one_pass(app)
    status = app.status.snapshot()
    assert status["key"] and status["tv_ok"] == 0
    assert status["note"] == "reached 0/1 TV(s)"


def test_an_exception_lands_in_the_status_and_the_loop_survives(tmp_path, monkeypatch):
    app = make(tmp_path)
    monkeypatch.setattr(controller_mod, "fit_to_panel",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("bad pixels")))
    one_pass(app)
    assert app.status.get("last_error") == "bad pixels"
    assert app.status.get("busy") is False


# --- requests from the panel / HA -----------------------------------------

def test_hide_needs_something_showing(tmp_path):
    app = make(tmp_path)
    assert app.hide_current() == (False, "Nothing is showing yet")


def test_hide_retires_the_piece_and_asks_for_another(tmp_path):
    app = make(tmp_path)
    one_pass(app)
    key = app.status.get("key")
    ok, message = app.hide_current()
    assert ok and message.startswith("Hidden '")
    assert app.history.is_hidden(key)
    assert app.snapshot()["hidden_count"] == 1
    assert app.intents.take() == {controller_mod.NEXT: None}
    assert app.hide_current()[0] is False        # already hidden


def test_unhide_all_resets_the_count(tmp_path):
    app = make(tmp_path)
    app.history.hide("artic:9")
    assert app.snapshot()["hidden_count"] == 1
    assert app.unhide_all() == (True, "1 piece(s) can appear again")
    assert app.snapshot()["hidden_count"] == 0


def test_links_are_validated_and_need_the_reframed_source(tmp_path):
    app = make(tmp_path)
    assert app.queue_link("https://example.com/x/y") == \
        (False, "Not a reframed.gallery artwork link")
    assert app.queue_link("reframed.gallery/a/b")[0] is False    # artic source
    reframed = make(tmp_path, source=ReframedSource())
    assert reframed.queue_link("reframed.gallery/A/B")[0] is True
    assert reframed.queue_link("reframed.gallery/C/D")[0] is True   # the later paste wins
    assert reframed.intents.take() == {
        controller_mod.LINK: "https://www.reframed.gallery/c/d"}


def test_a_matte_change_re_frames_the_same_piece(tmp_path):
    tv = FakeTV()
    app = make(tmp_path, tvs=[tv], fit="matte")
    one_pass(app)
    key = app.status.get("key")
    app.set_matte("shadowbox_polar")
    assert tv.matte == "shadowbox_polar"
    one_pass(app)
    assert app.status.get("key") == key           # not a new pick
    assert tv.pushes[-1][1] == "shadowbox_polar"
    assert len(tv.pushes) == 2


def test_repush_sends_the_preview_with_the_matte_it_was_rendered_with(tmp_path):
    tv = FakeTV()
    app = make(tmp_path, tvs=[tv])
    app.repush()
    one_pass(app)
    assert tv.pushes == []                        # nothing shown yet
    one_pass(app)                                 # a scheduled change
    assert len(tv.pushes) == 1
    app.status.update(matte="modern_polar")       # the live matte moves on...
    app.repush()
    one_pass(app)
    assert len(tv.pushes) == 2                    # ...the re-push really happened,
    assert tv.pushes[-1] == (Path(app.preview_path).read_bytes(), "none")   # as rendered


def test_a_collection_change_switches_the_source_and_picks_again(tmp_path):
    src = ReframedSource()
    app = make(tmp_path, source=src)
    app.set_collection("by-the-sea")
    assert src.override == "by-the-sea"
    assert app.status.get("collection") == "by-the-sea"
    assert app.intents.take() == {controller_mod.NEXT: None}


def test_the_collection_shown_is_the_pool_the_piece_came_from(tmp_path):
    src = FakeSource([art(1)])
    src.last_pool = "fall"
    app = make(tmp_path, source=src)
    one_pass(app)
    assert app.status.get("showing_collection") == "fall"
