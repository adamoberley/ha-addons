"""Frame Gallery entry point.

options.json -> discover Frame TV(s) -> on an interval (or the panel's "show
next" button): pick a public-domain piece (filtered, never a recent repeat),
fit it to the panel, push it to the Frame's bounded art library. Idles outside
active_hours. No automation needed.

Paste a reframed.gallery artwork link into the panel (or the HA "Show link" text
entity) and that exact piece goes up instead - filters and no-repeat don't apply
to something you asked for by name.

"Never show this" (panel button or the HA Hide button) drops the current piece
into a persisted hidden list and immediately picks a replacement, so a piece you
don't want off your wall is gone in one click instead of a keyword-filter puzzle.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta

import discover
import gallery
import options as options_mod
import server
import urllib3
import weather
from imaging import fit_to_panel
from mqtt_ctl import MqttCtl
from sources.artic import ArticSource
from sources.reframed import ReframedSource, normalize_artwork_url
from state import History
from tv import FrameTV

# The TV serves a self-signed cert on :8002; samsungtvws connects without
# verification, so silence urllib3's repeated InsecureRequestWarning.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_PORT = 8099
PREVIEW_PATH = "/data/last.jpg"
# Art sources, picked by the `source` option: reframed = curated, artic = full AIC.
_SOURCES = {"reframed": ReframedSource, "artic": ArticSource}

log = logging.getLogger("frame-gallery")
_stop = threading.Event()
_wake = threading.Event()           # wakes the scheduler loop (any intent below sets it)
_trigger = threading.Event()        # intent: pick a fresh piece
_repush = threading.Event()         # intent: re-send the current image as-is
_remat = threading.Event()          # intent: re-render the current piece with the new matte
_direct = threading.Event()         # intent: show the queued reframed.gallery link
_hide = threading.Event()           # intent: hide the current piece, then pick another


def _setup_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _within_active_hours(spec: str, now: datetime) -> bool:
    if not spec:
        return True
    try:
        start_s, end_s = spec.split("-")
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
    except (ValueError, AttributeError):
        log.warning("bad active_hours %r - treating as always-on", spec)
        return True
    cur, start, end = now.hour * 60 + now.minute, sh * 60 + sm, eh * 60 + em
    if start == end:
        return True
    return start <= cur < end if start < end else (cur >= start or cur < end)


def _seconds_until(daily_time: str, now: datetime) -> int | None:
    """Seconds until the next HH:MM (local) occurrence, or None if unset/invalid."""
    if not daily_time:
        return None
    try:
        hh, mm = (int(x) for x in daily_time.split(":"))
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
    except (ValueError, AttributeError):
        log.warning("bad daily_time %r - using the interval instead", daily_time)
        return None
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1, int((target - now).total_seconds()))


def _handle_signal(signum, _frame) -> None:
    log.info("signal %s received, shutting down", signum)
    _stop.set()
    _wake.set()


def main() -> int:
    opts = options_mod.load()
    _setup_logging(opts.log_level)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    tv_hosts = discover.discover_tv_hosts(opts.tv_ip)
    if not tv_hosts:
        log.error("no Frame TV found or set - fill in tv_ip and restart")
        return 1
    # Optional per-TV MACs (comma-separated, paired with tv_hosts by position)
    # enable a Wake-on-LAN nudge before a retry.
    macs = [m.strip() for m in (opts.tv_mac or "").split(",")]
    tvs = [FrameTV(host, matte=opts.tv_matte, mac=(macs[i] if i < len(macs) else ""),
                   library_size=opts.library_size)
           for i, host in enumerate(tv_hosts)]
    history = History(opts.avoid_repeat_count)
    sources = [_SOURCES.get(opts.source, ReframedSource)()]
    reframed_src = next((s for s in sources if getattr(s, "name", "") == "reframed"), None)

    status = {
        "busy": False, "last_ts": 0, "last_error": None, "note": None,
        "title": "", "artist": "", "year": "", "medium": "", "movement": "",
        "credit": "", "source": opts.source,
        "collection": opts.collection, "matte": opts.tv_matte,
        "tv_count": len(tvs), "tv_ok": 0, "link": "", "key": "",
        "hidden_count": len(history.hidden),
        "interval_minutes": opts.interval_minutes, "daily_time": opts.daily_time,
        "library_size": opts.library_size,
        "_debug": opts.log_level == "debug",
    }
    # The source bytes + matte the current /data/last.jpg was rendered from, so a
    # matte change can re-render the same piece and a re-push uses the right matte.
    render_state = {"source": None, "matte": opts.tv_matte}
    pending = {"url": ""}               # the link queued by the panel / HA text entity

    def _show_next():
        _trigger.set()
        _wake.set()

    def _hide_current():
        """Never show the current piece again, then pick a replacement now.

        Answers the click immediately (the pick happens on the loop) and returns
        (hidden, message) so the panel can say what happened."""
        key = status.get("key") or ""
        if not key:
            return False, "Nothing is showing yet"
        title = status.get("title") or "this piece"
        if not history.hide(key):
            return False, f"'{title}' is already hidden"
        status["hidden_count"] = len(history.hidden)
        log.info("hiding '%s' (%s) - %d hidden in total", title, key, len(history.hidden))
        _hide.set()
        _wake.set()
        return True, f"Hidden '{title}' - picking another"

    def _unhide_all():
        count = history.unhide_all()
        status["hidden_count"] = 0
        log.info("un-hid %d piece(s)", count)
        return True, (f"{count} piece(s) can appear again" if count
                      else "Nothing was hidden")

    def _set_collection(slug):
        if reframed_src is not None:
            reframed_src.override = slug   # active_collection() reads seasonal/weather/all/slug
        status["collection"] = slug
        _trigger.set()
        _wake.set()

    def _set_matte(matte_id):
        m = matte_id or "none"
        for tv in tvs:
            tv.matte = m
        status["matte"] = m
        _remat.set()                      # re-frame the current piece, don't re-pick
        _wake.set()

    def _queue_url(raw):
        """Validate a pasted reframed.gallery link and queue it for the loop.
        Returns (accepted, message) so the panel can answer the click at once
        instead of waiting on the fetch + push."""
        page_url = normalize_artwork_url(raw)
        if not page_url:
            return False, "Not a reframed.gallery artwork link"
        if reframed_src is None:
            return False, "Set Art source to \"reframed\" to show links"
        pending["url"] = page_url        # a second paste before the tick wins
        _direct.set()
        _wake.set()
        return True, "Fetching your piece…"

    mqttctl = MqttCtl(opts, _show_next, _set_collection, _set_matte, _queue_url,
                      on_hide=_hide_current)
    mqttctl.start()

    httpd = server.make_server(_trigger, status, _repush, _wake,
                               on_url=_queue_url, on_hide=_hide_current,
                               on_unhide=_unhide_all, port=SERVER_PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("control panel on :%d", SERVER_PORT)
    sched = (f"daily at {opts.daily_time}" if opts.daily_time
             else f"every {opts.interval_minutes} min")
    log.info("ready: %dx%d to %s, %s (source=%s, collection=%s, fit=%s, library=%d)",
             opts.width, opts.height, ", ".join(tv_hosts), sched,
             opts.source, opts.collection, opts.fit, opts.library_size)

    def _write_preview(jpeg: bytes) -> None:
        tmp = PREVIEW_PATH + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(jpeg)
        os.replace(tmp, PREVIEW_PATH)

    def _push_all(jpeg: bytes, matte: str, what: str) -> int:
        """Push to every TV with a single matte snapshot; bail early on shutdown.
        Returns the count that succeeded."""
        ok = 0
        for tv in tvs:
            if _stop.is_set():
                break
            try:
                tv.push(jpeg, matte=matte)
                ok += 1
            except Exception as exc:
                log.error("%s %s failed: %s", tv.host, what, exc)
        return ok

    def _record(ok: int) -> None:
        # last_error stays for genuine failures; a partial push is informational.
        status.update(tv_ok=ok, last_ts=time.time(), last_error=None,
                      note=None if ok == len(tvs) else f"reached {ok}/{len(tvs)} TV(s)")

    def _render_and_push(data: bytes, what: str) -> int:
        """Fit the source bytes to the panel using the live matte, save the
        preview, push to every TV, and remember what we rendered from (so a later
        matte change or re-push reuses the same source). Returns the TVs reached.

        With a TV-rendered matte we send full-bleed 16:9 so the TV draws the mat
        (no in-image bars to double-frame); otherwise the configured fit applies."""
        active_matte = status.get("matte", "none")
        fit_mode = "crop" if active_matte and active_matte != "none" else opts.fit
        jpeg = fit_to_panel(data, opts.width, opts.height, fit_mode, opts.mat_color)
        _write_preview(jpeg)
        ok = _push_all(jpeg, active_matte, what)
        render_state["source"] = data
        render_state["matte"] = active_matte
        return ok

    def _show(art, data: bytes, what: str, link: str = "") -> None:
        """Render + push one resolved artwork and publish it everywhere."""
        ok = _render_and_push(data, what)
        history.add(art.key)
        status.update(title=art.title, artist=art.artist, credit=art.credit,
                      year=getattr(art, "year", ""), medium=getattr(art, "medium", ""),
                      movement=getattr(art, "movement", ""), source=art.source,
                      link=link, key=art.key)
        _record(ok)
        log.info("showing '%s' by %s (%s) -> %d/%d TV(s)",
                 art.title, art.artist, art.credit, ok, len(tvs))
        mqttctl.publish_current(art)

    def cycle() -> None:
        status["busy"] = True
        try:
            # Weather-aware mode: refresh the HA condition so reframed can map it
            # to a collection (only when "weather" is the active choice).
            if reframed_src is not None:
                chosen = (reframed_src.override or opts.collection or "").strip().lower()
                if chosen == "weather" and opts.weather_entity:
                    cond = weather.current_condition(opts.weather_entity)
                    if cond:        # keep last-known-good on a transient read failure
                        reframed_src.weather_condition = cond
                elif chosen == "weather":
                    log.warning("collection 'weather' selected but no weather_entity "
                                "set - using seasonal art")
            art, data = gallery.pick(opts, history, sources)
            if not art:
                status.update(last_error="no artwork found (try a broader query)", note=None)
                log.error("no usable artwork this cycle")
                return
            _show(art, data, "push")
        except Exception as exc:
            status["last_error"] = str(exc)
            log.error("cycle failed (will retry): %s", exc)
        finally:
            status["busy"] = False

    def show_url(page_url: str) -> None:
        """Show one specific reframed.gallery piece. An explicit request beats the
        collection, the keyword filter and the no-repeat window - you asked for
        this piece by name - but it still joins the history so the random picker
        won't come straight back to it."""
        if not page_url or reframed_src is None:
            return
        status["busy"] = True
        try:
            art = reframed_src.artwork_from_url(page_url)
            if art is None:
                status.update(last_error=f"couldn't read {page_url}", note=None)
                log.error("link didn't resolve to an artwork: %s", page_url)
                return
            data = gallery.download(art.image_url)
            if not data:
                status.update(last_error=f"couldn't download '{art.title}'", note=None)
                log.error("link resolved but the image wouldn't download: %s", page_url)
                return
            _show(art, data, "link push", link=page_url)
        except Exception as exc:
            status["last_error"] = str(exc)
            log.error("showing the link failed: %s", exc)
        finally:
            status["busy"] = False

    def remat() -> None:
        """Re-render the current piece with the live matte and re-push, so a matte
        change re-frames what's showing instead of picking a new piece."""
        src = render_state.get("source")
        if not src:
            cycle()                  # nothing cached yet - just show something
            return
        status["busy"] = True
        try:
            ok = _render_and_push(src, "re-matte push")
            _record(ok)
            log.info("re-matted current piece (%s) -> %d/%d TV(s)",
                     status.get("matte", "none"), ok, len(tvs))
        except Exception as exc:
            status["last_error"] = str(exc)
            log.error("re-matte failed: %s", exc)
        finally:
            status["busy"] = False

    def repush_last() -> None:
        """Re-send the current image to the TV(s) without picking a new piece -
        handy if a TV was off or got switched away. Uses the matte the cached
        image was rendered with, so the framing always matches."""
        if not os.path.exists(PREVIEW_PATH):
            log.info("re-push requested but nothing has been shown yet")
            return
        status["busy"] = True
        try:
            with open(PREVIEW_PATH, "rb") as fh:
                jpeg = fh.read()
            ok = _push_all(jpeg, render_state.get("matte", "none"), "re-push")
            _record(ok)
            log.info("re-pushed current image -> %d/%d TV(s)", ok, len(tvs))
        except Exception as exc:
            status["last_error"] = str(exc)
            log.error("re-push failed: %s", exc)
        finally:
            status["busy"] = False

    try:
        # First change happens immediately when within active_hours (always, if
        # active_hours is unset), so a restart usually doubles as a "show now".
        while not _stop.is_set():
            now = datetime.now()
            # Compute the next wake BEFORE doing work, so a long push (or a remat/
            # repush landing near the daily time) can't roll the target a full day
            # forward and skip that day's scheduled change.
            wait_s = _seconds_until(opts.daily_time, now) or opts.interval_seconds
            want_direct = _direct.is_set()
            want_next = _trigger.is_set() or _hide.is_set()
            want_remat = _remat.is_set()
            want_repush = _repush.is_set()
            _direct.clear()
            _trigger.clear()
            _hide.clear()
            _remat.clear()
            _repush.clear()
            _wake.clear()
            intent = want_direct or want_next or want_remat or want_repush
            in_window = _within_active_hours(opts.active_hours, now)
            # A named piece wins, then a fresh pick; a bare timeout cycles only
            # in-hours (an explicit request ignores active_hours - you asked now).
            if want_direct:
                show_url(pending.get("url", ""))
            elif want_next or (not intent and in_window):
                cycle()
            elif want_remat:
                remat()
            elif want_repush:
                repush_last()
            elif not intent:
                log.info("outside active_hours %s - idling", opts.active_hours)
            _wake.wait(timeout=wait_s)
    finally:
        mqttctl.stop()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
