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
    patch_audio_delay()
    patch_effect_names()
    check_sendspin_client()
