#!/usr/bin/env python3
"""Actron NEO Local Cloud add-on entry point."""

from __future__ import annotations

import logging
import os
import threading
import time

from bridge import HomeAssistantBridge
from mqtt_proxy import NeoMqttProxy
from nimbus import run_nimbus

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    bridge = HomeAssistantBridge()
    threading.Thread(target=run_nimbus, daemon=True, name="nimbus-emulator").start()
    proxy = NeoMqttProxy(connection_callback=bridge.device_connection)
    threading.Thread(target=proxy.serve_forever, daemon=True, name="neo-mqtt-proxy").start()
    time.sleep(0.5)
    bridge.run()


if __name__ == "__main__":
    main()
