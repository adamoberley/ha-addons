#!/usr/bin/env bash
# Entry point. The app reads its settings from /data/options.json (written by
# the Supervisor from the add-on config) itself - no bashio needed.
set -euo pipefail
echo "[local-faces] starting"
exec python3 /app/main.py
