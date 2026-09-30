#!/usr/bin/env python3
"""Build-time patches to the installed `ledfx` Python package (site-packages).

Anchored, hit-count-guarded, idempotent — mirrors patch_frontend.py's discipline
so a future `ledfx` SHA bump that moves an anchor fails the build loudly instead
of silently regressing.

1. Audio delay / Sendspin-reset bug (upstream regression from LedFX PR #1770).
   A delay-only update — PUT {"audio":{"delay_ms":N}} — re-validates the bare
   dict through AUDIO_CONFIG_SCHEMA, which injects schema DEFAULTS for every
   absent key (audio_device -> the ALSA "default" index, audio_device_name -> "")
   and then `self._config = new_config` overwrites the live config, wiping the
   selected SENDSPIN source before the name-based restore can run. Result: change
   the delay in the UI and the audio source silently drops to "default" -> lights
   die. We merge the incoming delta over the existing in-memory config *before*
   validation, so absent keys are preserved. Fixes the UI delay control for ALL
   callers (web UI, REST, automations) and all partial audio fields.

2. De-Blade effect display names ("Blade Power+" -> "Power+", etc.). These come
   from the Python class attribute NAME in ledfx/effects/*.py, not the frontend.
   Renaming NAME is display-only (scenes/presets reference the effect *type*, not
   the name), so this is safe.

3. Sendspin clock domains (github issue #23). ledfx/sendspin/stream.py compares
   Sendspin play times - from SendspinClient.compute_play_time(), which runs on
   aiosendspin's RawMonotonicClock (CLOCK_MONOTONIC_RAW on Linux) - against
   `self._loop.time()` (CLOCK_MONOTONIC). Those clocks drift apart with uptime
   (~21 s on the reporter's box), and once the loop clock is ahead every decoded
   sub-chunk looks "late" and is silently dropped: Sendspin connects, audio
   decodes, audio-reactive effects stay black. Both comparisons now use
   `self._client.now_us()`, the client's own clock. Still present on upstream
   main as of 2026-09-30, so a SHA bump won't fix it. Also logs (rate-limited)
   when sub-chunks are dropped for being more than a second late - a delay that
   size is a clock problem, not network jitter - so this failure is visible.

It also *verifies* (patches nothing) that the resolved aiosendspin still speaks
the API this ledfx build calls: aiosendspin 7.0 replaced the client's `client_id`
with a Noise identity + pairing store, so a drifting pin would produce an app
whose Sendspin audio can never connect (github issue #11). requirements.txt pins
the compatible release; this fails the build if that ever stops holding.
"""
from __future__ import annotations

import glob
import importlib.metadata
import inspect
import os
import sys

# Resolved in main(), so tests can import the pure patch functions without ledfx.
ROOT = ""

# 1. delay/Sendspin-reset fix
AUDIO_ANCHOR = "new_config = self.AUDIO_CONFIG_SCHEMA.fget()(config)"
AUDIO_MERGE = (
    'if hasattr(self, "_config") and isinstance(self._config, dict):\n'
    "            config = {**self._config, **config}\n"
    "        " + AUDIO_ANCHOR
)
AUDIO_DONE_MARK = "{**self._config, **config}"

# 2. de-Blade effect names
BLADE_NAME_PREFIX = 'NAME = "Blade '

# 3. Sendspin clock domains. Two loop-clock reads, one per comparison site; the
# fallback only applies once the client is gone (shutdown), when nothing
# buffered is going to play anyway.
CLOCK_ANCHOR = "now_us = int(self._loop.time() * 1_000_000)"
CLOCK_FIXED = (
    "now_us = (self._client.now_us() if self._client is not None"
    " else int(self._loop.time() * 1_000_000))"
)
CLOCK_EXPECTED_HITS = 2
LATE_ANCHOR = (
    "                    if sub_play < now_us:\n"
    "                        continue\n"
)
LATE_FIXED = (
    "                    if sub_play < now_us:\n"
    "                        _ha_note_late_drop(now_us - sub_play)\n"
    "                        continue\n"
)
LATE_HELPER = '''

# --- added by the Home Assistant app's patch_backend.py (issue #23) ---------
_HA_LATE = {"count": 0, "worst_us": 0, "since": 0.0}


def _ha_note_late_drop(late_us):
    """Warn (at most every 30 s) when audio is dropped for being >1 s late.

    Sub-second drops are ordinary jitter and stay silent. A second or more
    means play times and "now" are on different clocks, which otherwise looks
    exactly like a working stream with black effects.
    """
    import time as _time

    if late_us < 1_000_000:
        return
    _HA_LATE["count"] += 1
    _HA_LATE["worst_us"] = max(_HA_LATE["worst_us"], late_us)
    now = _time.monotonic()
    if now - _HA_LATE["since"] >= 30:
        _LOGGER.warning(
            "Sendspin: dropped %d audio sub-chunk(s) arriving >1 s late "
            "(worst %.1f s). Play times and the playback clock disagree - "
            "audio-reactive effects will stay dark.",
            _HA_LATE["count"], _HA_LATE["worst_us"] / 1e6,
        )
        _HA_LATE.update(count=0, worst_us=0, since=now)
'''
CLOCK_DONE_MARK = "self._client.now_us() if self._client is not None"


def patch_audio_delay() -> None:
    path = os.path.join(ROOT, "effects", "audio.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read()

    if AUDIO_DONE_MARK in src:
        print("[patch-backend] audio delay fix: already applied")
        return

    hits = src.count(AUDIO_ANCHOR)
    if hits != 1:
        print(f"[patch-backend] WARNING: audio delay anchor found {hits}x"
              " (expected 1) - NOT patching")
        return

    src = src.replace(AUDIO_ANCHOR, AUDIO_MERGE, 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(src)
    print("[patch-backend] audio delay fix: merged delta over existing config before validation")


def patch_effect_names() -> None:
    total = 0
    for path in glob.glob(os.path.join(ROOT, "effects", "*.py")):
        with open(path, encoding="utf-8") as handle:
            src = handle.read()
        n = src.count(BLADE_NAME_PREFIX)
        if not n:
            continue
        src = src.replace(BLADE_NAME_PREFIX, 'NAME = "')
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(src)
        total += n
        print(f"[patch-backend] de-Blade effect name in {os.path.basename(path)}: {n}")
    if not total:
        print("[patch-backend] note: no 'NAME = \"Blade ' effect names found"
              " (may already be patched)")


def fix_sendspin_clock(src: str) -> tuple[str, str]:
    """Return (patched stream.py source, what happened). Pure, for the tests.

    Exits the build if the anchors moved: shipping without this fix means black
    audio-reactive effects, which is worse than a failed build that says why.
    """
    if CLOCK_DONE_MARK in src:
        return src, "already applied"
    hits = src.count(CLOCK_ANCHOR)
    if hits == 0 and "now_us()" in src and "_loop.time()" not in src:
        return src, "upstream no longer mixes clocks - nothing to do"
    if hits != CLOCK_EXPECTED_HITS or src.count(LATE_ANCHOR) != 1:
        sys.exit(
            f"[patch-backend] FATAL: Sendspin clock anchors moved (loop-clock reads: {hits}, "
            f"expected {CLOCK_EXPECTED_HITS}; late-drop branch: {src.count(LATE_ANCHOR)}, "
            "expected 1). Re-check ledfx/sendspin/stream.py against github issue #23 "
            "before shipping - without the fix, audio-reactive effects stay black."
        )
    src = src.replace(CLOCK_ANCHOR, CLOCK_FIXED)
    src = src.replace(LATE_ANCHOR, LATE_FIXED, 1)
    return src.rstrip("\n") + "\n" + LATE_HELPER, (
        f"compare play times on the Sendspin client clock ({hits} sites) + log late drops"
    )


def patch_sendspin_clock() -> None:
    path = os.path.join(ROOT, "sendspin", "stream.py")
    if not os.path.exists(path):
        print("[patch-backend] note: no ledfx/sendspin/stream.py - skipping clock fix")
        return
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    patched, what = fix_sendspin_clock(src)
    if patched != src:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(patched)
    print(f"[patch-backend] Sendspin clock fix: {what}")


def check_sendspin_client() -> None:
    """Fail the build if aiosendspin no longer takes ledfx's `client_id` argument.

    ledfx (and upstream main) construct SendspinClient(client_id=..., ...); 7.0
    swapped that for an X25519 identity + pairing store. Catching it here beats
    shipping an app that only reveals the mismatch as a per-reconnect TypeError.
    """
    try:
        from aiosendspin.client import SendspinClient
    except ImportError as exc:
        print(f"[patch-backend] WARNING: aiosendspin not importable ({exc})"
              " - Sendspin audio unavailable")
        return

    try:
        version = importlib.metadata.version("aiosendspin")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    if "client_id" not in inspect.signature(SendspinClient.__init__).parameters:
        sys.exit(
            f"[patch-backend] FATAL: aiosendspin {version} dropped SendspinClient(client_id=...), "
            "which this ledfx build calls - Sendspin audio could never connect. "
            "Pin aiosendspin <7.0 in requirements.txt, or bump the ledfx SHA to a "
            "commit that uses the identity/pairing-store API."
        )
    print(f"[patch-backend] aiosendspin {version}: SendspinClient(client_id=...) accepted")


if __name__ == "__main__":
    import ledfx

    ROOT = os.path.dirname(ledfx.__file__)
    patch_audio_delay()
    patch_effect_names()
    patch_sendspin_clock()
    check_sendspin_client()
