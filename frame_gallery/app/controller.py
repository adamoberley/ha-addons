"""The gallery itself: what's showing, what's been asked for, and the loop.

Three threads touch it - the scheduler loop (run()), the ingress panel and the
MQTT client - so the split is deliberate:

  * The panel and HA only *ask*. Their methods validate, record an intent and
    wake the loop; they answer the click at once and never fetch or push.
  * The loop does all the slow work (sources, downloads, TV pushes), one thing
    at a time, so two pushes can never race on a TV.
  * Status is a locked dict the loop writes and everyone else reads.

Intents, highest priority first, when several arrive at once:
  LINK    show the queued reframed.gallery link (the URL rides with the intent)
  NEXT    pick a fresh piece (also what "Never show this" asks for)
  REMAT   re-render the current piece with the new TV matte
  REPUSH  re-send the current image as-is
With no intent, a timeout changes the art only inside active_hours.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

import gallery
from imaging import fit_to_panel
from schedule import seconds_until, within_active_hours
from sources.reframed import ReframedSource, normalize_artwork_url

log = logging.getLogger("frame-gallery")

LINK, NEXT, REMAT, REPUSH = "link", "next", "remat", "repush"
# A scheduled change that found nothing (source down, every image damaged) is
# tried again this soon instead of waiting a whole day for the next slot.
RETRY_SECONDS = 15 * 60


class Status:
    """The panel's and healthz's view of the gallery. Thread-safe."""

    def __init__(self, **initial) -> None:
        self._lock = threading.Lock()
        self._data = dict(initial)

    def update(self, **fields) -> None:
        with self._lock:
            self._data.update(fields)

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)


class Intents:
    """Requests from the panel/HA for the loop, plus the event that wakes it.
    Each intent carries an optional payload (the link's URL), stored and taken
    under the same lock so a request and its data can't land in different
    passes of the loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, object] = {}
        self._wake = threading.Event()

    def request(self, intent: str, payload=None) -> None:
        with self._lock:
            self._pending[intent] = payload     # a newer request replaces an older one
            self._wake.set()

    def take(self) -> dict[str, object]:
        with self._lock:
            pending, self._pending = self._pending, {}
            self._wake.clear()
            return pending

    def wait(self, timeout: float) -> None:
        self._wake.wait(timeout)

    def interrupt(self) -> None:
        """Wake the loop without asking for anything (shutdown)."""
        self._wake.set()


class Gallery:
    def __init__(self, opts, tvs, history, source, *, preview_path: str) -> None:
        self.opts = opts
        self.tvs = tvs
        self.history = history
        self.source = source
        self.preview_path = preview_path
        self.intents = Intents()
        self.stop = threading.Event()
        self.listeners: list = []           # callables(art, status_snapshot) after a show
        # monotonic time a failed scheduled change is due to be tried again
        self._retry_at: float | None = None
        # The source bytes + matte the preview was rendered from, so a matte
        # change re-renders the same piece and a re-push uses the right matte.
        self._rendered_from: bytes | None = None
        self._rendered_matte = opts.tv_matte
        self.status = Status(
            busy=False, last_ts=0, last_error=None, note=None,
            title="", artist="", year="", medium="", movement="", credit="",
            source=opts.source, link="", key="",
            collection=opts.collection, showing_collection="", matte=opts.tv_matte,
            tv_count=len(tvs), tv_ok=0,
            interval_minutes=opts.interval_minutes, daily_time=opts.daily_time,
            library_size=opts.library_size,
        )

    @property
    def reframed(self) -> ReframedSource | None:
        return self.source if isinstance(self.source, ReframedSource) else None

    def snapshot(self) -> dict:
        """Status for the panel. The hidden count is read from the history
        itself, so hides and un-hides racing from two threads can't leave it
        stale."""
        return {**self.status.snapshot(), "hidden_count": len(self.history.hidden)}

    # -- requests from the panel and HA (any thread; never block) -----------

    def show_next(self) -> None:
        self.intents.request(NEXT)

    def repush(self) -> None:
        self.intents.request(REPUSH)

    def hide_current(self) -> tuple[bool, str]:
        """Never show the current piece again, then pick a replacement."""
        now = self.status.snapshot()           # key and title from the same piece
        key, title = now.get("key"), now.get("title") or "this piece"
        if not key:
            return False, "Nothing is showing yet"
        if not self.history.hide(key):
            return False, f"'{title}' is already hidden"
        log.info("hiding '%s' (%s) - %d hidden in total",
                 title, key, len(self.history.hidden))
        self.intents.request(NEXT)
        return True, f"Hidden '{title}' - picking another"

    def unhide_all(self) -> tuple[bool, str]:
        count = self.history.unhide_all()
        log.info("un-hid %d piece(s)", count)
        return True, (f"{count} piece(s) can appear again" if count
                      else "Nothing was hidden")

    def queue_link(self, raw: str) -> tuple[bool, str]:
        """Validate a pasted reframed.gallery link and queue it."""
        page_url = normalize_artwork_url(raw)
        if not page_url:
            return False, "Not a reframed.gallery artwork link"
        if self.reframed is None:
            return False, 'Set Art source to "reframed" to show links'
        self.intents.request(LINK, page_url)   # a second paste before the loop runs wins
        return True, "Fetching your piece…"

    def set_collection(self, slug: str) -> None:
        if self.reframed is not None:
            self.reframed.override = slug
        self.status.update(collection=slug)
        self.intents.request(NEXT)

    def set_matte(self, matte_id: str) -> None:
        matte = matte_id or "none"
        for tv in self.tvs:
            tv.matte = matte
        self.status.update(matte=matte)
        self.intents.request(REMAT)

    # -- the loop -----------------------------------------------------------

    def run(self) -> None:
        """Change the art on schedule and act on requests until stop is set.
        The first pass runs at once, so a restart doubles as "show now"
        (inside active_hours)."""
        while not self.stop.is_set():
            # Fix the next slot BEFORE doing work and sleep only what's left of it
            # afterwards, so a long push can neither roll the daily target a day
            # forward nor push the scheduled change past its time.
            slot_wait = (seconds_until(self.opts.daily_time, datetime.now())
                         or self.opts.interval_seconds)
            deadline = time.monotonic() + slot_wait
            wanted = self.intents.take()
            if self.stop.is_set():           # shutdown raced the take(); don't start work
                break
            if LINK in wanted:
                self._show_link(str(wanted[LINK] or ""))
            elif NEXT in wanted:
                if self._cycle():
                    self._retry_at = None
            elif REMAT in wanted:
                self._remat()
            elif REPUSH in wanted:
                self._repush()
            else:
                self._scheduled_change()
            if self.retry_pending:
                deadline = min(deadline, self._retry_at)
            if self.stop.is_set():
                break
            self.intents.wait(max(0.0, deadline - time.monotonic()))

    @property
    def retry_pending(self) -> bool:
        return self._retry_at is not None

    def _scheduled_change(self) -> None:
        """A timeout: the daily slot, the interval, or a retry came due."""
        self._retry_at = None
        if not within_active_hours(self.opts.active_hours, datetime.now()):
            log.info("outside active_hours %s - idling", self.opts.active_hours)
            return
        if not self._cycle():
            self._retry_at = time.monotonic() + RETRY_SECONDS
            log.info("will try again in %d min", RETRY_SECONDS // 60)

    def shutdown(self) -> None:
        self.stop.set()
        self.intents.interrupt()

    # -- the work (loop thread only) ----------------------------------------

    def _busy(self, what: str, fn, *args) -> bool:
        """Run one unit of work with the busy flag up; a failure lands in the
        status instead of killing the loop."""
        self.status.update(busy=True)
        try:
            return bool(fn(*args))
        except Exception as exc:
            self.status.update(last_error=str(exc), note=None)
            log.exception("%s failed", what)
            return False
        finally:
            self.status.update(busy=False)

    def _fail(self, message: str) -> bool:
        self.status.update(last_error=message, note=None)
        log.error("%s", message)
        return False

    def _cycle(self) -> bool:
        return self._busy("changing the art", self._do_cycle)

    def _do_cycle(self) -> bool:
        art, data = gallery.pick(self.opts, self.history, self.source)
        if not art:
            return self._fail("no artwork found (try a broader query or collection)")
        # The pool this piece came from, not whatever the collection is by now.
        self._show(art, data, collection=getattr(self.source, "last_pool", ""))
        return True

    def _show_link(self, page_url: str) -> bool:
        """Show one specific reframed.gallery piece. You asked for it by name, so
        it skips the collection, the keyword filter and the no-repeat window -
        but joins the history so the random picker won't come straight back."""
        if not page_url or self.reframed is None:
            return False
        return self._busy("showing the link", self._do_show_link, page_url)

    def _do_show_link(self, page_url: str) -> bool:
        art = self.reframed.artwork_from_url(page_url)
        if art is None:
            return self._fail(f"couldn't read {page_url}")
        data = gallery.fetch_image(art)
        if not data:
            return self._fail(f"couldn't get a usable image of '{art.title}' "
                              "(download failed or the file is damaged)")
        self._show(art, data, link=page_url)
        return True

    def _remat(self) -> bool:
        """Re-frame the current piece with the live matte (no new pick)."""
        if self._rendered_from is None:
            return self._cycle()             # nothing cached yet - just show something
        return self._busy("re-matting", self._do_remat)

    def _do_remat(self) -> bool:
        ok = self._render_and_push(self._rendered_from)
        log.info("re-matted current piece (%s) -> %d/%d TV(s)",
                 self._rendered_matte, ok, len(self.tvs))
        return True

    def _repush(self) -> bool:
        """Re-send the current image (a TV was off or got switched away)."""
        if not os.path.exists(self.preview_path):
            log.info("re-push requested but nothing has been shown yet")
            return False
        return self._busy("re-pushing", self._do_repush)

    def _do_repush(self) -> bool:
        with open(self.preview_path, "rb") as fh:
            jpeg = fh.read()
        ok = self._push_all(jpeg, self._rendered_matte)
        log.info("re-pushed current image -> %d/%d TV(s)", ok, len(self.tvs))
        return True

    def _show(self, art, data: bytes, link: str = "", collection: str = "") -> None:
        """Render + push one resolved artwork and publish it everywhere."""
        ok = self._render_and_push(data)
        self.history.add(art.key)
        self.status.update(title=art.title, artist=art.artist, credit=art.credit,
                           year=art.year, medium=art.medium, movement=art.movement,
                           source=art.source, link=link, key=art.key,
                           showing_collection=collection)
        log.info("showing '%s' by %s (%s) -> %d/%d TV(s)",
                 art.title, art.artist, art.credit, ok, len(self.tvs))
        snapshot = self.snapshot()
        for listener in self.listeners:
            try:
                listener(art, snapshot)
            except Exception:
                log.exception("publishing the new piece failed")

    def _render_and_push(self, data: bytes) -> int:
        """Fit the source bytes to the panel using the live matte, save the
        preview, push to every TV and record the result. Returns TVs reached.

        With a TV-rendered matte we send full-bleed 16:9 so the TV draws the mat
        (no in-image bars to double-frame); otherwise the configured fit applies."""
        matte = self.status.get("matte") or "none"
        fit = "crop" if matte != "none" else self.opts.fit
        jpeg = fit_to_panel(data, self.opts.width, self.opts.height, fit, self.opts.mat_color)
        self._write_preview(jpeg)
        self._rendered_from, self._rendered_matte = data, matte
        return self._push_all(jpeg, matte)

    def _write_preview(self, jpeg: bytes) -> None:
        tmp = self.preview_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(jpeg)
        os.replace(tmp, self.preview_path)

    def _push_all(self, jpeg: bytes, matte: str) -> int:
        """Push to every Frame with one matte snapshot and record how many took
        it. A TV without Art Mode doesn't count as reached."""
        ok = 0
        for tv in self.tvs:
            if self.stop.is_set():
                break
            try:
                if tv.push(jpeg, matte=matte):
                    ok += 1
            except Exception as exc:
                log.error("%s: push failed: %s", tv.host, exc)
        total = len(self.tvs)
        # last_error is for real failures; a partial push is only a note.
        self.status.update(tv_ok=ok, last_ts=time.time(), last_error=None,
                           note=None if ok == total else f"reached {ok}/{total} TV(s)")
        return ok
