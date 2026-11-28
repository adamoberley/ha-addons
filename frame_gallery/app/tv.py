"""Push a JPEG to a Samsung Frame TV's Art Mode, on a bounded art library.

Built on samsungtvws (the library the core samsungtv integration uses). The
point over a generic art-changer: uploads do NOT pile up without limit. We keep
the last `library_size` images we uploaded (1 = the original replace-in-place
behaviour) and delete only what falls off the end - so you can keep a few days of
art on the TV to flick back through, without the library growing forever. 0
keeps every upload (nothing is ever deleted), for anyone who wants that.

Safety ordering, per TV:
  1. upload + select the NEW image      (throws -> change nothing; old stays up)
  2. record new id, queue evicted ones  (durable, before any delete runs)
  3. delete queued ids                  (failures retried next cycle)
Only ids we uploaded are ever deleted.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import socket
import threading
import time

# A TV-level rejection (e.g. an unsupported matte -> error -2) is definitive:
# retrying the same call won't help, so we never retry it. A refused pairing
# (UnauthorizedError) is definitive too, until someone allows the app again.
from samsungtvws.exceptions import ResponseError, UnauthorizedError

from artlink import TolerantArt

log = logging.getLogger("frame-gallery.tv")

# A delete the TV answers without confirming is retried on later pushes, then
# given up on (logged) so one stubborn id can't be retried forever.
MAX_DELETE_ATTEMPTS = 5

DEVICE_NAME = "FrameGallery"
PAIR_TIMEOUT = 45            # first-run only: long window to tap "Allow" on the TV
CONNECT_TIMEOUT = 10         # once paired: short connect/liveness timeout per attempt
CONNECT_RETRIES = 2          # extra attempts to reach a live TV (3 tries total)
CONNECT_BACKOFF = 3.0        # seconds between connect attempts
WAKE_SETTLE = 4.0            # seconds to let the panel come up after a WoL packet
PUSH_DEADLINE = 300.0        # hard cap on one push, connect retries and pairing included


def _safe(host: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", host)


def _wake_on_lan(mac: str) -> None:
    """Best-effort Wake-on-LAN magic packet (UDP broadcast :9). No-op on a bad MAC."""
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) != 12:
        return
    payload = bytes.fromhex("ff" * 6 + clean * 16)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, ("255.255.255.255", 9))
    except OSError as exc:
        log.debug("Wake-on-LAN send failed: %s", exc)


class FrameTV:
    def __init__(self, host: str, matte: str = "none", mac: str = "",
                 library_size: int = 1) -> None:
        self.host = host
        self.matte = matte or "none"
        self.mac = mac or ""          # optional, enables Wake-on-LAN on retry
        self.library_size = max(0, int(library_size))   # 0 = keep every upload
        self.token_file = f"/data/tv-token-{_safe(host)}.txt"
        self.state_file = f"/data/tv-state-{_safe(host)}.json"
        self.state = self._load_state()
        self._live = None             # the Art channel the watchdog may shut
        self._aborted = False

    def _load_state(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                    data.setdefault("current_content_id", None)
                    data.setdefault("pending_deletes", [])
                    data.setdefault("delete_attempts", {})
                    # library: our uploads, oldest first. Pre-0.6 state only knew
                    # the current id, so seed the list from it.
                    if "library" not in data:
                        cur = data.get("current_content_id")
                        data["library"] = [cur] if cur else []
                    return data
            except (OSError, ValueError):
                pass
        return {"current_content_id": None, "pending_deletes": [], "library": [],
                "delete_attempts": {}}

    def _save_state(self) -> None:
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh)
        os.replace(tmp, self.state_file)

    def push(self, jpeg: bytes, matte: str | None = None) -> str | None:
        """Upload+select `jpeg`, evicting our oldest upload once the library is
        full. Returns the new content id, or None if the TV has no Art Mode.
        Raises on a real upload/select failure (old image left intact). `matte` overrides this
        TV's matte for this push (so the caller can keep the rendered image and
        the matte in sync); None uses self.matte.

        Two phases on purpose: connecting (REST check + Art channel handshake) is
        *retried*, while the upload runs exactly *once* on the open channel - so
        a lost ack can't duplicate art within a push.

        The whole push runs under a watchdog: after PUSH_DEADLINE it shuts the
        socket, which ends any read still blocked on a TV that trickles or
        chatters without answering, so no push can hold up the gallery's loop.
        """
        effective_matte = self.matte if matte is None else (matte or "none")
        watchdog = threading.Timer(PUSH_DEADLINE, self._abort)
        watchdog.daemon = True
        watchdog.start()
        art = None
        try:
            art = self._connect()
            if art is None:
                return None
            return self._upload_and_select(art, jpeg, effective_matte)
        except Exception as exc:
            if self._aborted:
                raise TimeoutError(f"the TV took longer than {PUSH_DEADLINE:.0f}s "
                                   "over one change; gave up") from exc
            raise
        finally:
            watchdog.cancel()
            self._live, self._aborted = None, False
            # The art channel owns the live websocket + FD; close it every cycle.
            self._close(art)

    def _abort(self) -> None:
        """Watchdog: shut the live channel's socket so a blocked read returns."""
        self._aborted = True
        live = self._live
        if live is not None:
            live.abort()

    def _connect(self):
        """Open the Art channel of a REST-reachable, Frame-capable TV, retrying
        with backoff (and a Wake-on-LAN nudge when a MAC is set). Returns the open
        channel, None if the TV has no Art Mode, or raises if it stays out of
        reach after the retries. The first run uses a long timeout so there's
        time to tap 'Allow'; once paired, a short timeout keeps a sleeping TV
        from stalling the scheduler thread.

        The websocket is opened here, inside the retries, so a handshake the TV
        interrupts (its screen going to sleep mid-connect, say) is tried again
        like any other connect failure rather than failing the whole push."""
        timeout = CONNECT_TIMEOUT if os.path.exists(self.token_file) else PAIR_TIMEOUT
        for attempt in range(CONNECT_RETRIES + 1):
            if attempt and self.mac:
                log.info("%s: Wake-on-LAN nudge before retry %d", self.host, attempt)
                _wake_on_lan(self.mac)
                time.sleep(WAKE_SETTLE)
            if self._aborted:
                raise TimeoutError("the watchdog ended this change")
            art = self._live = TolerantArt(self.host, port=8002, token_file=self.token_file,
                                           name=DEVICE_NAME, timeout=timeout)
            try:
                # supported() is a REST request: the TV is reachable and Frame-capable.
                if not art.supported():
                    log.warning("%s has no Art Mode - skipping", self.host)
                    self._close(art)
                    return None
                art.open()
                if art.news:
                    log.info("%s: the TV said %s while connecting", self.host,
                             ", ".join(dict.fromkeys(art.news)))
                return art
            except UnauthorizedError as exc:
                # The saved token is kept: allowing FrameGallery again in the
                # TV's Device List makes it valid again, and dropping it would
                # bring an 'Allow' prompt up on the TV at every retry.
                self._close(art)
                raise UnauthorizedError(
                    f"{exc}. Allow it again: TV Settings > General > External Device "
                    "Manager > Device Connection Manager > Device List") from None
            except ResponseError:
                self._close(art)
                raise               # TV gave a definitive answer; retrying won't help
            except Exception as exc:
                self._close(art)
                if attempt == CONNECT_RETRIES:
                    raise
                log.warning("%s: connect failed (%s); retrying in %.0fs",
                            self.host, exc, CONNECT_BACKOFF)
                time.sleep(CONNECT_BACKOFF)
        raise AssertionError("unreachable: the last attempt returns or raises")

    @staticmethod
    def _close(*objs) -> None:
        for obj in objs:
            if obj is not None:
                with contextlib.suppress(Exception):
                    obj.close()

    def _upload_and_select(self, art, jpeg: bytes, matte: str) -> str:
        new_id = self._upload(art, jpeg, matte)
        if not new_id:
            raise RuntimeError("upload returned no content id")

        # Don't yank someone off live TV: force-show only when the TV says it is
        # in Art Mode; otherwise (including when it doesn't say) just set the
        # selection, which Art Mode shows next time it comes on.
        show = False
        try:
            show = str(art.get_artmode()).lower() == "on"
        except Exception as exc:
            log.info("%s: couldn't read Art Mode (%s); selecting without showing",
                     self.host, exc)
        art.select_image(new_id, show=show)
        log.info("%s: uploaded + selected %s (matte=%s, show=%s)",
                 self.host, new_id, matte, show)

        # Keep the newest `library_size` of our uploads on the TV; anything older
        # falls off the end and is queued for deletion. Shrinking the option
        # evicts the surplus on the next push; 0 never evicts.
        library = [cid for cid in self.state.get("library", []) if cid != new_id]
        library.append(new_id)
        library, evicted = self._split_library(library, self.library_size)
        self.state["library"] = library
        self.state["current_content_id"] = new_id
        for cid in evicted:
            if cid and cid not in self.state["pending_deletes"]:
                self.state["pending_deletes"].append(cid)
        self._save_state()

        if self.library_size:
            self._drain_deletes(art, keep=set(library))
        # library_size 0 promises nothing is deleted, so even deletes queued
        # under an earlier limit wait until a limit is set again.
        if self.library_size != 1:
            log.info("%s: art library at %d/%s image(s)", self.host, len(library),
                     self.library_size or "unlimited")
        return new_id

    @staticmethod
    def _split_library(library: list, size: int) -> tuple[list, list]:
        """(kept, evicted): the newest `size` uploads stay; 0 keeps them all."""
        if size <= 0:
            return library, []
        return library[-size:], library[:-size]

    def _upload(self, art, jpeg: bytes, matte: str) -> str | None:
        """Single upload attempt. Both mattes must match (a mismatch makes 2022+
        Frames reject send_image with error -2). If a TV-native matte id is
        rejected (older Frames lack some mattes), fall back to none rather than
        failing the whole push - the rejected upload stored nothing, so a second
        attempt can't duplicate."""
        try:
            return art.upload(jpeg, file_type="JPEG",
                              matte=matte, portrait_matte=matte)
        except ResponseError as exc:
            if matte and matte != "none":
                log.warning("%s: matte %r rejected (%s); retrying without a matte",
                            self.host, matte, exc)
                return art.upload(jpeg, file_type="JPEG",
                                  matte="none", portrait_matte="none")
            raise

    def _drain_deletes(self, art, keep: set) -> None:
        """Delete queued uploads. samsungtvws returns False when the TV's answer
        doesn't confirm the id, so only True counts as deleted; anything else is
        retried on later pushes, up to MAX_DELETE_ATTEMPTS."""
        still_pending = []
        attempts = self.state.setdefault("delete_attempts", {})
        for cid in self.state.get("pending_deletes", []):
            if cid in keep:
                attempts.pop(cid, None)
                continue
            try:
                confirmed, why = bool(art.delete(cid)), "the TV didn't confirm it"
            except Exception as exc:
                confirmed, why = False, str(exc)
            if confirmed:
                attempts.pop(cid, None)
                log.info("%s: deleted previous art %s", self.host, cid)
                continue
            attempts[cid] = attempts.get(cid, 0) + 1
            if attempts[cid] >= MAX_DELETE_ATTEMPTS:
                attempts.pop(cid)
                log.warning("%s: giving up deleting %s after %d tries (%s) - remove it "
                            "from the TV's art library by hand if it's still there",
                            self.host, cid, MAX_DELETE_ATTEMPTS, why)
                continue
            log.warning("%s: delete of %s failed, will retry: %s", self.host, cid, why)
            still_pending.append(cid)
        self.state["pending_deletes"] = still_pending
        self._save_state()
