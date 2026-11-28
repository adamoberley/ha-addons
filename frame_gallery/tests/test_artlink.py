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
CLOSE = "close"


class FakeSocket:
    """Plays back frames (dicts, or PING for a websocket ping); reads time out
    once they run out, like websocket-client's recv_data_frame(True)."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.closed = False
        self.shut = False
        self.sent: list = []
        self.timeouts: list[float] = []

    def recv_data_frame(self, control_frame=False):
        assert control_frame, "pings must come back to the caller"
        if not self.frames:
            raise websocket.WebSocketTimeoutException("timed out")
        f = self.frames.pop(0)
        if f is PING:
            return websocket.ABNF.OPCODE_PING, websocket.ABNF(opcode=9, data=b"\x00")
        if f is CLOSE:
            return websocket.ABNF.OPCODE_CLOSE, websocket.ABNF(opcode=8, data=b"")
        return websocket.ABNF.OPCODE_TEXT, websocket.ABNF(data=json.dumps(f).encode())

    def send(self, payload, opcode=None):
        self.sent.append(payload)

    def shutdown(self):
        self.shut = True

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
    with pytest.raises(artlink.ArtUnavailable, match=r"didn't get ready.*clientConnect"):
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


def test_broadcasts_skipped_while_waiting_share_one_deadline(tmp_path, tv_sends, monkeypatch):
    """samsungtvws skips unrelated broadcasts and reads again; those reads must
    not each get a fresh budget, or a chatty TV holds a request open forever."""
    sock = tv_sends(CONNECT, READY)
    art = channel(tmp_path)
    art.open()
    now = [0.0]
    monkeypatch.setattr(artlink.time, "monotonic", lambda: now[0])
    art.send_command({"method": "ms.channel.emit"})      # the clock starts here
    sock.frames = [STANDBY] * 1000

    def tick(control_frame=False, _real=sock.recv_data_frame):
        now[0] += 7                                        # a broadcast every 7 s
        return _real(control_frame)
    sock.recv_data_frame = tick
    with pytest.raises(ConnectionFailure, match="stopped answering"):
        while True:
            art._recv_frame()                              # what samsungtvws loops on
    assert now[0] <= artlink.REQUEST_TIMEOUT + 7


def test_a_close_from_the_tv_shuts_the_socket(tmp_path, tv_sends):
    sock = tv_sends(CONNECT, CLOSE)
    with pytest.raises(ConnectionFailure, match="closed the Art channel"):
        channel(tmp_path).open()
    assert sock.shut


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


def test_a_refusal_keeps_the_token_and_says_where_to_allow(frame, tv_sends):
    tv_sends(REFUSED)
    with pytest.raises(UnauthorizedError, match="Device Connection Manager"):
        frame._connect()
    # Dropping it would put an Allow prompt on the TV at every retry.
    assert Path(frame.token_file).read_text() == "old-token"


# --- the push watchdog and Art Mode --------------------------------------------

class StuckArt:
    """An Art channel whose upload blocks until abort() is called."""

    def __init__(self, *a, **kw):
        import threading
        self.news, self.released = [], threading.Event()
        self.closed = False

    def supported(self):
        return True

    def open(self):
        pass

    def upload(self, *a, **kw):
        self.released.wait(5)
        raise OSError("socket shut")

    def abort(self):
        self.released.set()

    def close(self):
        self.closed = True


def test_the_watchdog_ends_a_push_that_never_finishes(frame, monkeypatch):
    made = []
    monkeypatch.setattr(tv_mod, "TolerantArt", lambda *a, **kw: made.append(StuckArt()) or made[-1])
    monkeypatch.setattr(tv_mod, "PUSH_DEADLINE", 0.2)
    with pytest.raises(TimeoutError, match="longer than"):
        frame.push(b"jpeg")
    assert made[0].closed and frame._live is None and not frame._aborted


class ArtModeUnknown:
    def __init__(self):
        self.selected = []

    def upload(self, *a, **kw):
        return "MY_F0001"

    def get_artmode(self):
        raise ConnectionFailure("the TV's Art app stopped answering")

    def select_image(self, cid, show=True):
        self.selected.append((cid, show))

    def delete(self, cid):
        return True


def test_an_unknown_art_mode_never_forces_the_art_on_screen(frame, tmp_path):
    frame.state_file = str(tmp_path / "state.json")
    art = ArtModeUnknown()
    frame._upload_and_select(art, b"jpeg", "none")
    assert art.selected == [("MY_F0001", False)]
