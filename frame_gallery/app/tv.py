"""Push a JPEG to a Samsung Frame TV's Art Mode, on a bounded art library.

Built on samsungtvws (the library the core samsungtv integration uses). The
point over a generic art-changer: uploads do NOT pile up without limit. We keep
the last `library_size` images we uploaded (1 = the original replace-in-place
behaviour) and delete only what falls off the end - so you can keep a few days of
art on the TV to flick back through, without the library growing forever.

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
import time

from samsungtvws import SamsungTVWS

# A TV-level rejection (e.g. an unsupported matte -> error -2) is definitive:
# retrying the same call won't help, so we never retry it. Imported defensively
# because the module path has moved between samsungtvws releases.
try:
    from samsungtvws.exceptions import ResponseError
except Exception:  # pragma: no cover - older/newer layout
    class ResponseError(Exception):
        """Fallback if samsungtvws doesn't expose ResponseError."""

log = logging.getLogger("frame-gallery.tv")

DEVICE_NAME = "FrameGallery"
PAIR_TIMEOUT = 45            # first-run only: long window to tap "Allow" on the TV
CONNECT_TIMEOUT = 10         # once paired: short connect/liveness timeout per attempt
CONNECT_RETRIES = 2          # extra attempts to reach a live TV (3 tries total)
CONNECT_BACKOFF = 3.0        # seconds between connect attempts
WAKE_SETTLE = 4.0            # seconds to let the panel come up after a WoL packet


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
        self.library_size = max(1, int(library_size or 1))
        self.token_file = f"/data/tv-token-{_safe(host)}.txt"
        self.state_file = f"/data/tv-state-{_safe(host)}.json"
        self.state = self._load_state()

    def _load_state(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                    data.setdefault("current_content_id", None)
                    data.setdefault("pending_deletes", [])
                    # library: our uploads, oldest first. Pre-0.6 state only knew
                    # the current id, so seed the list from it.
                    if "library" not in data:
                        cur = data.get("current_content_id")
                        data["library"] = [cur] if cur else []
                    return data
            except (OSError, ValueError):
                pass
        return {"current_content_id": None, "pending_deletes": [], "library": []}

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

        Two phases on purpose: the REST reachability check is *retried* (a Frame
        that's asleep fails here, cheaply), while the upload runs exactly *once*
        on the art websocket - so a lost ack can never duplicate art on the TV.
        Note: supported() is REST-only, so the art websocket is opened lazily by
        the first upload and can still fail there (handled by the caller; the
        rejected upload stored nothing, so there's nothing to duplicate).
        """
        effective_matte = self.matte if matte is None else (matte or "none")
        connection = self._connect()
        if connection is None:
            return None
        tv, art = connection
        try:
            return self._upload_and_select(art, jpeg, effective_matte)
        finally:
            # art is a SEPARATE object from tv and owns the live websocket+FD;
            # closing only tv would leak it every cycle. Close both.
            with contextlib.suppress(Exception):
                art.close()
            with contextlib.suppress(Exception):
                tv.close()

    def _connect(self):
        """Open a connection to a REST-reachable, Frame-capable TV, retrying with
        backoff (and a Wake-on-LAN nudge when a MAC is set). Returns
        (client, art_channel), None if the TV has no Art Mode, or raises if it
        stays unreachable after the retries. The first run uses a long timeout so
        there's time to tap 'Allow'; once paired, a short timeout keeps a sleeping
        TV from stalling the scheduler thread."""
        timeout = CONNECT_TIMEOUT if os.path.exists(self.token_file) else PAIR_TIMEOUT
        last_exc: Exception | None = None
        for attempt in range(CONNECT_RETRIES + 1):
            if attempt and self.mac:
                log.info("%s: Wake-on-LAN nudge before retry %d", self.host, attempt)
                _wake_on_lan(self.mac)
                time.sleep(WAKE_SETTLE)
            tv = SamsungTVWS(host=self.host, port=8002, token_file=self.token_file,
                             name=DEVICE_NAME, timeout=timeout)
            art = None
            try:
                art = tv.art()
                # supported() is a REST request - confirms the TV is reachable and
                # Frame-capable (it does NOT open the art websocket).
                if not art.supported():
                    log.warning("%s has no Art Mode - skipping", self.host)
                    self._close(art, tv)
                    return None
                return tv, art
            except ResponseError:
                self._close(art, tv)
                raise               # TV gave a definitive answer; retrying won't help
            except Exception as exc:
                self._close(art, tv)
                last_exc = exc
                if attempt < CONNECT_RETRIES:
                    log.warning("%s: connect failed (%s); retrying in %.0fs",
                                self.host, exc, CONNECT_BACKOFF)
                    time.sleep(CONNECT_BACKOFF)
                    continue
                raise
        if last_exc:                # defensive; loop above always returns or raises
            raise last_exc
        return None

    @staticmethod
    def _close(art, tv) -> None:
        for obj in (art, tv):
            if obj is not None:
                with contextlib.suppress(Exception):
                    obj.close()

    def _upload_and_select(self, art, jpeg: bytes, matte: str) -> str:
        new_id = self._upload(art, jpeg, matte)
        if not new_id:
            raise RuntimeError("upload returned no content id")

        # Don't yank someone off live TV: force-show only when already in
        # Art Mode; otherwise just set the selection for next time.
        show = True
        try:
            if str(art.get_artmode()).lower() == "off":
                show = False
        except Exception:
            pass
        art.select_image(new_id, show=show)
        log.info("%s: uploaded + selected %s (matte=%s, show=%s)",
                 self.host, new_id, matte, show)

        # Keep the newest `library_size` of our uploads on the TV; anything older
        # falls off the end and is queued for deletion. Shrinking the option
        # evicts the surplus on the next push.
        library = [cid for cid in self.state.get("library", []) if cid != new_id]
        library.append(new_id)
        evicted, library = library[:-self.library_size], library[-self.library_size:]
        self.state["library"] = library
        self.state["current_content_id"] = new_id
        for cid in evicted:
            if cid and cid not in self.state["pending_deletes"]:
                self.state["pending_deletes"].append(cid)
        self._save_state()

        self._drain_deletes(art, keep=set(library))
        if self.library_size > 1:
            log.info("%s: art library at %d/%d image(s)",
                     self.host, len(library), self.library_size)
        return new_id

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
        still_pending = []
        for cid in self.state.get("pending_deletes", []):
            if cid in keep:
                continue
            try:
                art.delete(cid)
                log.info("%s: deleted previous art %s", self.host, cid)
            except Exception as exc:
                log.warning("%s: delete of %s failed, will retry: %s", self.host, cid, exc)
                still_pending.append(cid)
        self.state["pending_deletes"] = still_pending
        self._save_state()
