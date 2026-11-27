"""When to change the art: the daily time, the interval, and active hours.

Pure functions of the option strings and the current local time, so the
scheduler's arithmetic is testable without a clock.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("frame-gallery.schedule")


def _hhmm(text: str) -> tuple[int, int]:
    hh, mm = (int(x) for x in text.strip().split(":"))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(text)
    return hh, mm


def within_active_hours(spec: str, now: datetime) -> bool:
    """True if `now` is inside an "HH:MM-HH:MM" window (which may cross
    midnight). Blank, malformed or zero-length windows mean always on."""
    if not spec:
        return True
    try:
        start_s, end_s = spec.split("-")
        sh, sm = _hhmm(start_s)
        eh, em = _hhmm(end_s)
    except ValueError:
        log.warning("bad active_hours %r - treating as always-on", spec)
        return True
    cur, start, end = now.hour * 60 + now.minute, sh * 60 + sm, eh * 60 + em
    if start == end:
        return True
    return start <= cur < end if start < end else (cur >= start or cur < end)


# A wake a hair before the slot (clock jitter) counts as the slot itself, so the
# pass it runs isn't followed by a second change a second later.
SLOT_GRACE = 2


def seconds_until(daily_time: str, now: datetime) -> int | None:
    """Seconds until the next HH:MM (local) occurrence, or None if unset/invalid."""
    if not daily_time:
        return None
    try:
        hh, mm = _hhmm(daily_time)
    except ValueError:
        log.warning("bad daily_time %r - using the interval instead", daily_time)
        return None
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if (target - now).total_seconds() < SLOT_GRACE:
        target += timedelta(days=1)
    return max(1, int((target - now).total_seconds()))
