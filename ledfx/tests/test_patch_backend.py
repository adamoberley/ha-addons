"""The Sendspin clock fix patch_backend.py applies to ledfx at build time (#23).

The real target is ledfx/sendspin/stream.py at the pinned SHA; these use a
trimmed copy of its two comparison sites so the tests run without ledfx
installed. The patch was also checked against the full pinned file when it was
written (both sites patched, result compiles, second run is a no-op).

Run from the repo root: ``python -m pytest ledfx/tests``
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import patch_backend as pb

# The shape of the pinned stream.py around both comparisons.
STREAM = '''\
import logging
_LOGGER = logging.getLogger(__name__)


class SendspinAudioStream:
    def _schedule_mono_samples(self, samples, play_time_us, sample_rate):
        now_us = int(self._loop.time() * 1_000_000)
        if n_full > 0:
            with self._buffer_lock:
                for i in range(n_full):
                    sub_play = base_ts + i * sub_duration_us
                    if sub_play < now_us:
                        continue
                    self._push(sub_play)

    async def _playback_scheduler(self):
        while self._active:
            with self._buffer_lock:
                if self._chunk_buffer:
                    play_time_us = self._chunk_buffer[0][0]
                    now_us = int(self._loop.time() * 1_000_000)
                    if play_time_us <= now_us:
                        self._pop()
'''


def test_both_comparisons_move_to_the_client_clock():
    out, what = pb.fix_sendspin_clock(STREAM)
    assert "2 sites" in what
    assert out.count("self._client.now_us() if self._client is not None") == 2
    assert "now_us = int(self._loop.time()" not in out      # no bare loop-clock reads left
    compile(out, "stream.py", "exec")


def test_patching_twice_changes_nothing():
    once, _ = pb.fix_sendspin_clock(STREAM)
    twice, what = pb.fix_sendspin_clock(once)
    assert twice == once
    assert what == "already applied"


def test_a_moved_anchor_fails_the_build():
    moved = STREAM.replace(pb.CLOCK_ANCHOR, "now = self._loop.time()", 1)
    with pytest.raises(SystemExit, match="anchors moved"):
        pb.fix_sendspin_clock(moved)


def test_an_upstream_fix_is_left_alone():
    fixed = STREAM.replace("int(self._loop.time() * 1_000_000)", "self._client.now_us()")
    out, what = pb.fix_sendspin_clock(fixed)
    assert out == fixed
    assert "nothing to do" in what


# --- behavior of the patched code ---------------------------------------------

class _Clock:
    def __init__(self, us):
        self.us = us

    def now_us(self):
        return self.us


class _Loop:
    def __init__(self, seconds):
        self.seconds = seconds

    def time(self):
        return self.seconds


def _patched_stream(client_us, loop_s):
    """An instance of the patched class with the two clocks set."""
    ns: dict = {}
    exec(pb.fix_sendspin_clock(STREAM)[0], ns)
    stream = ns["SendspinAudioStream"]()
    stream._client, stream._loop = _Clock(client_us), _Loop(loop_s)
    stream._buffer_lock = type("L", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None})()
    stream.pushed = []
    stream._push = stream.pushed.append
    return stream, ns


def test_audio_is_kept_when_the_loop_clock_runs_ahead():
    """The #23 failure: loop clock 21 s ahead of the Sendspin clock."""
    client_now = 100_000_000                       # 100 s on the raw clock
    stream, ns = _patched_stream(client_now, loop_s=121.3)
    ns.update(n_full=3, base_ts=client_now + 50_000, sub_duration_us=10_000)
    stream._schedule_mono_samples.__globals__.update(ns)

    stream._schedule_mono_samples(None, 0, 48_000)

    assert len(stream.pushed) == 3                 # before the fix: all 3 dropped


def test_late_drops_warn_only_when_seconds_late(monkeypatch, caplog):
    ns: dict = {}
    exec(pb.fix_sendspin_clock(STREAM)[0], ns)
    note = ns["_ha_note_late_drop"]
    clock = iter([1000.0, 1001.0, 1040.0])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))

    with caplog.at_level("WARNING"):
        note(20_000)                                # 20 ms: jitter, silent
        note(21_300_000)                            # 21 s late: warn
        note(21_300_000)                            # 1 s later: rate-limited
        note(22_000_000)                            # 40 s later: warn again
    warnings = [r for r in caplog.records if "dropped" in r.getMessage()]
    assert len(warnings) == 2
    assert "21.3 s" in warnings[0].getMessage()
