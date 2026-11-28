"""Opening the Frame's Art channel when the TV talks out of turn.

No TV: websocket.create_connection is replaced by a fake that plays back the
frames a Frame sent. Run from the repo root: ``python -m pytest frame_gallery/tests``
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
import websocket
from samsungtvws.exceptions import ConnectionFailure, UnauthorizedError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import artlink
import tv as tv_mod

# What the Frame sent on 2026-11-28 when its screen went to sleep mid-connect.
STANDBY = {"data": json.dumps({"event": "go_to_standby"}, indent=2),
           "event": "d2d_service_message", "from": "fdb1250-11e8-42ac-801-34b1eb431aaa"}
CONNECT = {"event": "ms.channel.connect",
           "data": {"id": "me", "token": "11112222", "clients": []}}
READY = {"event": "ms.channel.ready", "data": {}}
REFUSED = {"event": "ms.channel.unauthorized"}


PING = "ping"


class FakeSocket:
    """Plays back frames (dicts, or PING for a websocket ping); reads time out
    once they run out, like websocket-client's recv_data_frame(True)."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.closed = False
        self.timeouts: list[float] = []

    def recv_data_frame(self, control_frame=False):
        assert control_frame, "pings must come back to the caller"
        if not self.frames:
            raise websocket.WebSocketTimeoutException("timed out")
        f = self.frames.pop(0)
        if f is PING:
            return websocket.ABNF.OPCODE_PING, websocket.ABNF(opcode=9, data=b"\x00")
        return websocket.ABNF.OPCODE_TEXT, websocket.ABNF(data=json.dumps(f).encode())

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


@pytest.fixture
def tv_sends(monkeypatch):
    """tv_sends(frames...) -> the fake socket the next connection gets."""
    made = []

    def sends(*frames):
        sock = FakeSocket(frames)
        made.append(sock)
        return sock

    def create_connection(url, timeout, **kw):
        assert url.startswith("wss://10.0.0.5:8002/api/v2/channels/com.samsung.art-app")
        return made.pop(0)

    monkeypatch.setattr(artlink.websocket, "create_connection", create_connection)
    return sends


def channel(tmp_path, timeout=0.2):
    return artlink.TolerantArt("10.0.0.5", port=8002, name="FrameGallery",
                               token_file=str(tmp_path / "token.txt"), timeout=timeout)


def test_a_standby_broadcast_mid_handshake_is_read_past(tmp_path, tv_sends):
    sock = tv_sends(CONNECT, STANDBY, READY)
    art = channel(tmp_path)
    assert art.open() is sock
    assert art.news == ["go_to_standby"]
    assert (tmp_path / "token.txt").read_text() == "11112222"   # pairing still saved


def test_a_broadcast_before_connect_is_read_past_too(tmp_path, tv_sends):
    sock = tv_sends(STANDBY, CONNECT, READY)
    assert channel(tmp_path).open() is sock


def test_standby_with_no_ready_says_so_in_words(tmp_path, tv_sends):
    sock = tv_sends(CONNECT, STANDBY)
    with pytest.raises(artlink.ArtUnavailable) as err:
        channel(tmp_path).open()
    message = str(err.value)
    assert "going to standby" in message and "d2d_service_message" not in message
    assert sock.closed


def test_silence_after_connect_names_what_the_tv_did_say(tmp_path, tv_sends):
    tv_sends(CONNECT, {"event": "ms.channel.clientConnect", "data": {}})
    with pytest.raises(artlink.ArtUnavailable, match="didn't get ready.*clientConnect"):
        channel(tmp_path).open()


def test_pings_do_not_stretch_the_handshake(tmp_path, tv_sends, monkeypatch):
    """The Nov 2026 hang: connect, then nothing but a ping every 6 s, forever."""
    clock = iter(range(0, 10_000, 6))
    monkeypatch.setattr(artlink.time, "monotonic", lambda: next(clock))
    tv_sends(CONNECT, *[PING] * 1000)
    with pytest.raises(artlink.ArtUnavailable, match="MultiScreen"):
        channel(tmp_path, timeout=10).open()


def test_a_request_the_tv_never_answers_ends(tmp_path, tv_sends, monkeypatch):
    sock = tv_sends(CONNECT, READY)
    art = channel(tmp_path)
    art.open()
    sock.frames = [PING] * 1000                           # open, then only pings
    clock = iter(range(0, 10_000, 6))
    monkeypatch.setattr(artlink.time, "monotonic", lambda: next(clock))
    with pytest.raises(ConnectionFailure, match="stopped answering"):
        art._recv_frame()


def test_answers_still_come_through_after_open(tmp_path, tv_sends):
    sock = tv_sends(CONNECT, READY)
    art = channel(tmp_path)
    art.open()
    sock.frames = [PING, STANDBY]
    event, frame = art._recv_frame()
    assert event == "d2d_service_message" and "go_to_standby" in frame["data"]


def test_no_connect_at_all_points_at_the_allow_prompt(tmp_path, tv_sends):
    tv_sends()
    with pytest.raises(artlink.ArtUnavailable, match="Allow FrameGallery"):
        channel(tmp_path).open()


def test_a_refusal_is_an_unauthorized_error(tmp_path, tv_sends):
    sock = tv_sends(REFUSED)
    with pytest.raises(UnauthorizedError, match="refused FrameGallery"):
        channel(tmp_path).open()
    assert sock.closed


def test_a_slow_trickle_of_news_still_ends_at_the_deadline(tmp_path, tv_sends, monkeypatch):
    clock = iter(range(0, 1000, 2))                       # 2 s pass per frame read
    monkeypatch.setattr(artlink.time, "monotonic", lambda: next(clock))
    tv_sends(CONNECT, *[STANDBY] * 50)
    with pytest.raises(artlink.ArtUnavailable, match="going to standby"):
        channel(tmp_path, timeout=10).open()


def test_samsungtvws_never_logs_the_token(tmp_path, tv_sends, caplog):
    tv_sends(CONNECT, READY)
    with caplog.at_level(logging.DEBUG):
        channel(tmp_path).open()
    assert "11112222" not in caplog.text


# --- FrameTV._connect: retries, re-pairing -----------------------------------

@pytest.fixture
def frame(tmp_path, monkeypatch):
    monkeypatch.setattr(tv_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(artlink.TolerantArt, "supported", lambda self: True)
    t = tv_mod.FrameTV("10.0.0.5")
    t.token_file = str(tmp_path / "token.txt")
    Path(t.token_file).write_text("old-token")
    return t


def test_an_interrupted_handshake_is_retried(frame, tv_sends):
    tv_sends(CONNECT, STANDBY)              # screen going to sleep: no ready
    sock = tv_sends(CONNECT, READY)         # the retry gets in
    art = frame._connect()
    assert art.connection is sock


def test_a_refused_token_is_dropped_so_the_next_try_pairs_afresh(frame, tv_sends):
    tv_sends(REFUSED)
    with pytest.raises(UnauthorizedError, match="Device Connection Manager"):
        frame._connect()
    assert not Path(frame.token_file).exists()
