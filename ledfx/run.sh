#!/usr/bin/env bash
# Entry point. Runs the LedFX engine (no s6/bashio - init: false).
#
# --host 0.0.0.0 binds every interface, so the UI is reachable through the HA
# ingress proxy AND directly on the LAN (http://<ha-ip>:8888). Config/state
# persist in /data.
set -euo pipefail

CONFIG_DIR=/data/ledfx
mkdir -p "$CONFIG_DIR"

# --- Auto-config: scan-on-startup + Home Assistant MQTT integration -----------
# Runs once before LedFX starts (so editing config.json here is safe). It:
#   * defaults scan_on_startup=true (auto-discover WLED) WITHOUT overriding a
#     value the user later changed in Settings (setdefault),
#   * seeds the "mqtt_hass" integration pointed at the co-located Mosquitto
#     broker, with credentials pulled from the Supervisor (services: mqtt:want),
#     so there's nothing to type. Refreshes the broker connection each boot but
#     keeps the user's enable/disable choice.
# Needs no hassio_api - the Supervisor allows /services/* with just the
# mqtt:want declaration. mqtt_hass has no TLS, so we use the plaintext listener.
python3 - <<'PY' || echo "[ledfx] auto-config skipped (non-fatal)"
import json, os, urllib.request

CONFIG = "/data/ledfx/config.json"
try:
    cfg = json.load(open(CONFIG))
    if not isinstance(cfg, dict):
        cfg = {}
except Exception:
    cfg = {}

# Auto-scan for WLED on boot (default on; respect a later user change).
cfg.setdefault("scan_on_startup", True)

# Apply the Sendspin audio delay from the app options. The LedFX UI's delay
# control is buggy for Sendspin (it resets the audio source), so we set it here
# and leave whatever audio device is already selected untouched.
try:
    opts = json.load(open("/data/options.json"))
except Exception:
    opts = {}
try:
    delay_ms = int(opts.get("sendspin_delay_ms", 0) or 0)
except (TypeError, ValueError):
    delay_ms = 0
cfg.setdefault("audio", {})["delay_ms"] = delay_ms

# Look up the MQTT broker from the Supervisor.
host = user = pw = ""
port, use_ssl = 1883, False
token = os.environ.get("SUPERVISOR_TOKEN", "")
if token:
    try:
        req = urllib.request.Request(
            "http://supervisor/services/mqtt",
            headers={"Authorization": "Bearer " + token},
        )
        d = json.load(urllib.request.urlopen(req, timeout=10))
        d = d.get("data", d) if isinstance(d, dict) else {}
        host = (d.get("host") or "")
        user = (d.get("username") or "")
        pw = (d.get("password") or "")
        use_ssl = bool(d.get("ssl"))
        try:
            port = int(d.get("port") or 1883)
        except (TypeError, ValueError):
            port = 1883
    except Exception as exc:
        print("[ledfx] MQTT service lookup failed:", exc)

if host:
    if use_ssl:  # mqtt_hass can't do TLS - use the plaintext listener
        port = 1883
    ints = cfg.setdefault("integrations", [])
    if not isinstance(ints, list):
        ints = cfg["integrations"] = []
    existing = next((it for it in ints if isinstance(it, dict) and it.get("type") == "mqtt_hass"), None)
    if existing is None:
        ints.append({
            "id": "home-assistant", "type": "mqtt_hass", "active": True, "data": [],
            "config": {
                "name": "Home Assistant", "topic": "homeassistant",
                "ip_address": host, "port": port, "username": user, "password": pw,
                "description": "MQTT Integration with auto-discovery",
            },
        })
    else:
        existing.setdefault("active", True)          # keep the user's enable/disable choice
        existing.setdefault("id", "home-assistant")
        existing.setdefault("data", [])
        c = existing.setdefault("config", {})
        c.update({"ip_address": host, "port": port, "username": user, "password": pw})
        c.setdefault("name", "Home Assistant")
        c.setdefault("topic", "homeassistant")
        c.setdefault("description", "MQTT Integration with auto-discovery")
    print("[ledfx] MQTT auto-config -> %s:%s (user=%s)" % (host, port, user or "<anon>"))
else:
    print("[ledfx] no MQTT broker from Supervisor; skipping MQTT auto-config")

json.dump(cfg, open(CONFIG, "w"), indent=2)
PY

# Map the app's log_level option to ledfx verbosity.
log_level="$(python3 -c 'import json; print(json.load(open("/data/options.json")).get("log_level","info"))' 2>/dev/null || echo info)"
case "$log_level" in
  debug)   verbosity="-vv" ;;
  info)    verbosity="-v" ;;
  *)       verbosity="" ;;   # warning / error: ledfx default (quiet)
esac

echo "[ledfx] starting LedFX on 0.0.0.0:8888 (config: ${CONFIG_DIR}, log: ${log_level})"
# shellcheck disable=SC2086
exec ledfx --host 0.0.0.0 --port 8888 --offline --config "$CONFIG_DIR" ${verbosity}
