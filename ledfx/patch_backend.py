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
"""
from __future__ import annotations

import glob
import os

import ledfx

ROOT = os.path.dirname(ledfx.__file__)

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


def patch_audio_delay() -> None:
    path = os.path.join(ROOT, "effects", "audio.py")
    with open(path, encoding="utf-8") as handle:
        src = handle.read()

    if AUDIO_DONE_MARK in src:
        print("[patch-backend] audio delay fix: already applied")
        return

    hits = src.count(AUDIO_ANCHOR)
    if hits != 1:
        print(f"[patch-backend] WARNING: audio delay anchor found {hits}x (expected 1) - NOT patching")
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
        print("[patch-backend] note: no 'NAME = \"Blade ' effect names found (may already be patched)")


if __name__ == "__main__":
    patch_audio_delay()
    patch_effect_names()
