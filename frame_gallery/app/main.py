"""REFRAMED Gallery entry point.

options.json -> find the Frame TV(s) -> start the control panel and the HA
entities -> run the gallery loop (controller.Gallery) until the Supervisor
stops us. Everything the app *does* lives in the controller; this file only
wires the pieces together.
"""
from __future__ import annotations

import logging
import signal
import sys
import threading

import discover
import options as options_mod
import server
import urllib3
from controller import Gallery
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
SOURCES = {"reframed": ReframedSource, "artic": ArticSource}

log = logging.getLogger("frame-gallery")


def main() -> int:
    opts = options_mod.load()
    logging.basicConfig(
        level=getattr(logging, opts.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    hosts = discover.discover_tv_hosts(opts.tv_ip)
    if not hosts:
        log.error("no Frame TV found or set - fill in tv_ip and restart")
        return 1
    # Optional MACs pair with the hosts by position, for a Wake-on-LAN nudge.
    macs = [m.strip() for m in opts.tv_mac.split(",")]
    tvs = [FrameTV(host, matte=opts.tv_matte, library_size=opts.library_size,
                   mac=macs[i] if i < len(macs) else "")
           for i, host in enumerate(hosts)]

    app = Gallery(opts, tvs, History(opts.avoid_repeat_count),
                  SOURCES.get(opts.source, ReframedSource)(), preview_path=PREVIEW_PATH)

    def _on_signal(signum, _frame):
        log.info("signal %s received, shutting down", signum)
        app.shutdown()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    mqtt = MqttCtl(opts, app)
    app.listeners.append(mqtt.publish_current)
    mqtt.start()

    httpd = server.make_server(app, port=SERVER_PORT,
                               debug=opts.log_level == "debug")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    sched = (f"daily at {opts.daily_time}" if opts.daily_time
             else f"every {opts.interval_minutes} min")
    library = opts.library_size or "every piece"
    log.info("ready: %dx%d to %s, %s (source=%s, collection=%s, fit=%s, keep on TV=%s); "
             "panel on :%d", opts.width, opts.height, ", ".join(hosts), sched,
             opts.source, opts.collection, opts.fit, library, SERVER_PORT)
    try:
        app.run()
    finally:
        mqtt.stop()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
