"""The Frame's Art channel, with waits that really end.

samsungtvws opens the Art channel (`com.samsung.art-app`) expecting exactly two
frames, `ms.channel.connect` and then `ms.channel.ready`, and gives up on
anything else. Its waits also rely on the socket timeout, which a Frame keeps
resetting: the TV pings every client every ~6 s and websocket-client answers
each ping inside recv() and keeps waiting. So when the TV never sent
`ms.channel.ready` (Nov 2026: Vetro had stopped Samsung's MultiScreen service
from starting at boot, and the Art app then served nothing from the network),
a push hung for hours, freezing the whole loop, until the Art app's next
broadcast (`go_to_standby` as the screen went to sleep) ended it as
    push failed: {'data': '{"event": "go_to_standby"}', 'event': 'd2d_service_message', ...}

TolerantArt opens the channel the same way but reads past such broadcasts,
holds every wait to a real deadline (pings included), and when it gives up says
why in words.
"""
from __future__ import annotations

import json
import logging
import ssl
import time

import websocket
from samsungtvws import exceptions, helper
from samsungtvws.art import SamsungTVArt

# samsungtvws logs the pairing token at INFO ("New token ...") and whole frames,
# token included, at DEBUG. Keep its chatter out of the app log at any level.
logging.getLogger("samsungtvws").setLevel(logging.WARNING)

CONNECT = "ms.channel.connect"
READY = "ms.channel.ready"
UNAUTHORIZED = "ms.channel.unauthorized"
D2D = "d2d_service_message"

# Art app power news: the TV is going to sleep / off.
STANDBY_EVENTS = {"go_to_standby"}

# Longest wait for any one answer once the channel is open. An upload's answers
# come within seconds; this only bounds a TV that has stopped answering.
REQUEST_TIMEOUT = 60.0

_DATA = (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY)


class ArtUnavailable(exceptions.ConnectionFailure):
    """The TV took the connection but its Art channel didn't become usable."""


def _news(frame: dict) -> str:
    """A short name for a frame that isn't part of the handshake: the Art app's
    own event for a d2d broadcast (e.g. 'go_to_standby'), else the channel
    event. Never the whole frame (a connect frame can carry the pairing token)."""
    event = str(frame.get("event", "*"))
    if event == D2D:
        try:
            data = json.loads(frame.get("data") or "{}")
        except (TypeError, ValueError):
            data = {}
        if isinstance(data, dict) and data.get("event"):
            return str(data["event"])[:40]
    return event[:40]


def explain(connected: bool, news: list[str], seconds: float) -> str:
    """Why the channel didn't open, in words for the log and the panel."""
    if not connected:
        return (f"no answer from the TV's Art channel in {seconds:.0f}s - if the TV shows "
                "an 'Allow FrameGallery' prompt, accept it with the remote")
    if any(n in STANDBY_EVENTS for n in news):
        return ("the TV's Art app said it is going to standby (the TV is off or its "
                "screen is going to sleep) and didn't take the connection")
    heard = f"; it only said: {', '.join(dict.fromkeys(news))}" if news else ""
    return (f"the TV's Art app didn't get ready in {seconds:.0f}s{heard}. On a Frame "
            "running Vetro, check that its 'MultiScreen' quick win is off: it stops "
            "Samsung's MultiScreen service, and the Art app then ignores the network")


def recv_by(conn, deadline: float) -> dict | None:
    """The next data frame as a dict, or None once `deadline` (monotonic) passes.
    Pings are answered (by websocket-client) and don't extend the wait."""
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        conn.settimeout(left)
        try:
            opcode, frame = conn.recv_data_frame(True)
        except websocket.WebSocketTimeoutException:
            return None
        if opcode == websocket.ABNF.OPCODE_CLOSE:
            raise exceptions.ConnectionFailure("the TV closed the Art channel")
        if opcode in _DATA:
            return helper.process_api_response(frame.data)


class TolerantArt(SamsungTVArt):
    """SamsungTVArt whose waits end on time and whose open() reads past
    broadcasts. `news` lists what the TV said during the handshake that wasn't
    part of it, for the log."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.news: list[str] = []

    def open(self) -> websocket.WebSocket:
        if self.connection:
            return self.connection
        limit = float(self.timeout or 10)
        sslopt = {"cert_reqs": ssl.CERT_NONE} if self._is_ssl_connection() else {}
        conn = websocket.create_connection(
            self._format_websocket_url(self.endpoint), limit, sslopt=sslopt,
            connection="Connection: Upgrade")
        self.news = []
        connected = False
        deadline = time.monotonic() + limit
        try:
            while True:
                frame = recv_by(conn, deadline)
                if frame is None:
                    raise ArtUnavailable(explain(connected, self.news, limit))
                event = str(frame.get("event", "*"))
                self._websocket_event(event, frame)   # keep the library's state in step
                if event == UNAUTHORIZED:
                    raise exceptions.UnauthorizedError(
                        "the TV refused FrameGallery (it was denied, or removed from the "
                        "TV's device list)")
                if event == CONNECT and not connected:
                    connected = True
                    self._check_for_token(frame)      # first pairing: saves the token
                elif event == READY and connected:
                    conn.settimeout(limit)
                    self.connection = conn
                    return conn
                else:
                    self.news.append(_news(frame))
        except BaseException:
            conn.close()
            raise

    def _recv_frame(self):
        """samsungtvws's own reader, but a TV that stops answering fails the
        request after REQUEST_TIMEOUT instead of holding it open on pings."""
        assert self.connection
        frame = recv_by(self.connection, time.monotonic() + REQUEST_TIMEOUT)
        if frame is None:
            raise exceptions.ConnectionFailure(
                f"the TV's Art app stopped answering (nothing in {REQUEST_TIMEOUT:.0f}s)")
        event = frame.get("event", "*")
        self._websocket_event(event, frame)
        return event, frame
