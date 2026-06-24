"""Frame Gallery entry point.

options.json -> discover Frame TV(s) -> on an interval (or the panel's "show
next" button): pick a public-domain piece (filtered, never a recent repeat),
fit it to the panel, push it to the Frame replacing the previous upload. Idles
outside active_hours. No automation needed.
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
from imaging import fit_to_panel
from mqtt_ctl import MqttCtl
from sources.artic import ArticSource
from sources.reframed import ReframedSource
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
_trigger = threading.Event()


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
    _trigger.set()


def main() -> int:
    opts = options_mod.load()
    _setup_logging(opts.log_level)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    tv_hosts = discover.discover_tv_hosts(opts.tv_ip)
    if not tv_hosts:
        log.error("no Frame TV found or set - fill in tv_ip and restart")
        return 1
    tvs = [FrameTV(host) for host in tv_hosts]
    history = History(opts.avoid_repeat_count)
    sources = [_SOURCES.get(opts.source, ReframedSource)()]
    reframed_src = next((s for s in sources if getattr(s, "name", "") == "reframed"), None)

    def _show_next():
        _trigger.set()

    def _set_collection(slug):
        if reframed_src is not None:
            reframed_src.override = slug   # active_collection() interprets seasonal/all/slug
        _trigger.set()

    mqttctl = MqttCtl(opts, _show_next, _set_collection)
    mqttctl.start()

    status = {
        "busy": False, "last_ts": 0, "last_error": None,
        "title": "", "artist": "", "credit": "",
        "tv_count": len(tvs), "interval_minutes": opts.interval_minutes,
        "_debug": opts.log_level == "debug",
    }
    httpd = server.make_server(_trigger, status, port=SERVER_PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("control panel on :%d", SERVER_PORT)
    sched = f"daily at {opts.daily_time}" if opts.daily_time else f"every {opts.interval_minutes} min"
    log.info("ready: %dx%d to %s, %s (source=%s, collection=%s, fit=%s)",
             opts.width, opts.height, ", ".join(tv_hosts), sched,
             opts.source, opts.collection, opts.fit)

    def cycle() -> None:
        status["busy"] = True
        try:
            art, data = gallery.pick(opts, history, sources)
            if not art:
                status["last_error"] = "no artwork found (try a broader query)"
                log.error("no usable artwork this cycle")
                return
            jpeg = fit_to_panel(data, opts.width, opts.height, opts.fit, opts.mat_color)
            tmp = PREVIEW_PATH + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(jpeg)
            os.replace(tmp, PREVIEW_PATH)
            ok = 0
            for tv in tvs:
                try:
                    tv.push(jpeg)
                    ok += 1
                except Exception as exc:
                    log.error("%s push failed: %s", tv.host, exc)
            history.add(art.key)
            status.update(title=art.title, artist=art.artist, credit=art.credit,
                          last_ts=time.time(),
                          last_error=None if ok == len(tvs) else f"pushed to {ok}/{len(tvs)} TV(s)")
            log.info("showing '%s' by %s (%s) -> %d/%d TV(s)",
                     art.title, art.artist, art.credit, ok, len(tvs))
            mqttctl.publish_current(art)
        except Exception as exc:
            status["last_error"] = str(exc)
            log.error("cycle failed (will retry): %s", exc)
        finally:
            status["busy"] = False

    try:
        # First change happens immediately, so a restart is also a "show now".
        while not _stop.is_set():
            manual = _trigger.is_set()
            _trigger.clear()
            if manual or _within_active_hours(opts.active_hours, datetime.now()):
                cycle()
            else:
                log.info("outside active_hours %s - idling", opts.active_hours)
            wait_s = _seconds_until(opts.daily_time, datetime.now()) or opts.interval_seconds
            _trigger.wait(timeout=wait_s)
    finally:
        mqttctl.stop()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
