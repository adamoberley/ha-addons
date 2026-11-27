"""Schedule arithmetic, the MQTT entity contract, and the TV art library.

Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import mqtt_ctl
import schedule
import tv as tv_mod
from controller import Status

# --- schedule ---------------------------------------------------------------

AT = datetime(2026, 11, 27, 3, 30)


@pytest.mark.parametrize(("spec", "now", "inside"), [
    ("", AT, True),
    ("07:00-23:00", AT, False),
    ("07:00-23:00", AT.replace(hour=12), True),
    ("22:00-06:00", AT, True),                    # crosses midnight
    ("22:00-06:00", AT.replace(hour=12), False),
    ("08:00-08:00", AT, True),                    # zero-length = always
    ("nonsense", AT, True),
    ("25:00-26:00", AT, True),                    # out of range = always
])
def test_active_hours(spec, now, inside):
    assert schedule.within_active_hours(spec, now) is inside


def test_seconds_until_today_and_tomorrow():
    assert schedule.seconds_until("04:00", AT) == 30 * 60
    assert schedule.seconds_until("03:00", AT) == 23 * 3600 + 30 * 60
    assert schedule.seconds_until("03:30", AT) == 24 * 3600    # exactly now = tomorrow


@pytest.mark.parametrize("bad", ["", "4", "24:00", "ab:cd"])
def test_seconds_until_without_a_usable_time(bad):
    assert schedule.seconds_until(bad, AT) is None


# --- MQTT ------------------------------------------------------------------

def test_discovery_keeps_the_entity_ids_existing_installs_have():
    configs = dict(mqtt_ctl.discovery_messages())
    assert {topic: c["unique_id"] for topic, c in configs.items()} == {
        "homeassistant/sensor/reframed_gallery/current/config": "reframed_gallery_current_art",
        "homeassistant/button/reframed_gallery/next/config": "reframed_gallery_next",
        "homeassistant/select/reframed_gallery/collection/config": "reframed_gallery_collection",
        "homeassistant/select/reframed_gallery/matte/config": "reframed_gallery_matte",
        "homeassistant/text/reframed_gallery/link/config": "reframed_gallery_show_link",
        "homeassistant/button/reframed_gallery/hide/config": "reframed_gallery_hide",
    }
    for c in configs.values():
        assert c["object_id"] == c["unique_id"]
        assert c["availability_topic"] == mqtt_ctl.AVAIL


def test_no_matte_is_never_offered_to_ha_as_none():
    """HA's MQTT select treats the payload "none" as no option selected."""
    assert "none" not in mqtt_ctl.MATTE_OPTIONS
    assert mqtt_ctl._matte_to_ha("none") == "off"
    assert mqtt_ctl._matte_from_ha("off") == "none"
    assert mqtt_ctl._matte_from_ha("modern_polar") == "modern_polar"


class FakeApp:
    def __init__(self):
        self.calls = []
        self.status = Status(collection="seasonal", matte="none")

    def show_next(self):
        self.calls.append("next")

    def hide_current(self):
        self.calls.append("hide")
        return True, "hidden"

    def set_collection(self, slug):
        self.calls.append(("collection", slug))

    def set_matte(self, matte):
        self.calls.append(("matte", matte))

    def queue_link(self, url):
        self.calls.append(("link", url))
        return url.startswith("https://www.reframed.gallery/"), "msg"


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload))


def message(topic, payload):
    return SimpleNamespace(topic=topic, payload=payload.encode())


@pytest.fixture
def ctl():
    c = mqtt_ctl.MqttCtl(SimpleNamespace(), FakeApp())
    c.client = FakeClient()
    return c


def test_commands_reach_the_gallery_and_echo_state(ctl):
    ctl._on_message(None, None, message(mqtt_ctl.NEXT_CMD, "PRESS"))
    ctl._on_message(None, None, message(mqtt_ctl.HIDE_CMD, "PRESS"))
    ctl._on_message(None, None, message(mqtt_ctl.SEL_CMD, "fall"))
    ctl._on_message(None, None, message(mqtt_ctl.MATTE_CMD, "off"))
    assert ctl.app.calls == ["next", "hide", ("collection", "fall"), ("matte", "none")]
    assert (mqtt_ctl.SEL_STATE, "fall") in ctl.client.published
    assert (mqtt_ctl.MATTE_STATE, "off") in ctl.client.published


def test_only_accepted_links_are_echoed(ctl):
    ctl._on_message(None, None, message(mqtt_ctl.LINK_CMD, "https://example.com/"))
    ctl._on_message(None, None, message(mqtt_ctl.LINK_CMD,
                                        "https://www.reframed.gallery/a/b"))
    echoed = [p for t, p in ctl.client.published if t == mqtt_ctl.LINK_STATE]
    assert echoed == ["https://www.reframed.gallery/a/b"]


def test_connect_announces_everything_and_publishes_current_selects(ctl):
    client = FakeClient()
    client.subscribe = lambda topics: setattr(client, "subscribed", topics)
    ctl._on_connect(client, None, None, 0)
    topics = [t for t, _ in client.published]
    assert sum(t.endswith("/config") for t in topics) == len(mqtt_ctl.ENTITIES)
    assert (mqtt_ctl.MATTE_STATE, "off") in client.published
    assert (mqtt_ctl.SEL_STATE, "seasonal") in client.published
    assert len(client.subscribed) == 5


def test_current_art_attributes(ctl):
    art = SimpleNamespace(title="T", artist="A", year="1", medium="m", movement="v",
                          description="d", credit="c", source="s")
    ctl.publish_current(art, {"collection": "fall", "matte": "none"})
    attrs = json.loads(dict(ctl.client.published)[mqtt_ctl.CUR_ATTR])
    assert attrs["collection"] == "fall" and attrs["year"] == "1"


# --- the TV art library -----------------------------------------------------

class FakeArt:
    def __init__(self, fail_delete=()):
        self.n = 0
        self.deleted: list[str] = []
        self.fail_delete = set(fail_delete)

    def upload(self, data, **kw):
        self.n += 1
        return f"MY_F{self.n:04d}"

    def get_artmode(self):
        return "on"

    def select_image(self, cid, show=True):
        pass

    def delete(self, cid):
        if cid in self.fail_delete:
            raise OSError("busy")
        self.deleted.append(cid)


@pytest.fixture
def frame(tmp_path, monkeypatch):
    def build(size):
        t = tv_mod.FrameTV("10.0.0.5", library_size=size)
        t.state_file = str(tmp_path / f"state-{size}.json")
        t.state = t._load_state()
        return t
    return build


def test_size_one_replaces_yesterdays_art(frame):
    t, art = frame(1), FakeArt()
    for _ in range(3):
        t._upload_and_select(art, b"x", "none")
    assert art.deleted == ["MY_F0001", "MY_F0002"]
    assert t.state["library"] == ["MY_F0003"]


def test_size_n_keeps_the_last_n(frame):
    t, art = frame(3), FakeArt()
    for _ in range(5):
        t._upload_and_select(art, b"x", "none")
    assert art.deleted == ["MY_F0001", "MY_F0002"]
    assert t.state["library"] == ["MY_F0003", "MY_F0004", "MY_F0005"]


def test_size_zero_keeps_every_piece(frame):
    t, art = frame(0), FakeArt()
    for _ in range(5):
        t._upload_and_select(art, b"x", "none")
    assert art.deleted == []
    assert len(t.state["library"]) == 5


def test_a_failed_delete_is_retried_on_the_next_push(frame):
    t, art = frame(1), FakeArt(fail_delete={"MY_F0001"})
    t._upload_and_select(art, b"x", "none")
    t._upload_and_select(art, b"x", "none")
    assert t.state["pending_deletes"] == ["MY_F0001"]
    art.fail_delete.clear()
    t._upload_and_select(art, b"x", "none")
    assert art.deleted == ["MY_F0001", "MY_F0002"]
    assert t.state["pending_deletes"] == []
