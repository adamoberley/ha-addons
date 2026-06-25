#!/usr/bin/env bash
# Entry point. Runs the LedFX engine (no s6/bashio - init: false).
#
# --host 0.0.0.0 is the whole trick the old add-on got wrong: it binds every
# interface, so the UI is reachable both through the HA ingress proxy and
# directly on the LAN (http://<ha-ip>:8888). Config/state persist in /data.
set -euo pipefail

CONFIG_DIR=/data/ledfx
mkdir -p "$CONFIG_DIR"

# Map the add-on's log_level option to ledfx verbosity.
log_level="$(python3 -c 'import json; print(json.load(open("/data/options.json")).get("log_level","info"))' 2>/dev/null || echo info)"
case "$log_level" in
  debug)   verbosity="-vv" ;;
  info)    verbosity="-v" ;;
  *)       verbosity="" ;;   # warning / error: ledfx default (quiet)
esac

echo "[ledfx] starting LedFX on 0.0.0.0:8888 (config: ${CONFIG_DIR}, log: ${log_level})"
# shellcheck disable=SC2086
exec ledfx --host 0.0.0.0 --port 8888 --offline --config "$CONFIG_DIR" ${verbosity}
