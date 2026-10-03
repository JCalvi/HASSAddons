"""Runtime configuration for Actron NEO Local Cloud."""

from __future__ import annotations

import os
from pathlib import Path

LOCAL_IP = os.environ["LOCAL_IP"]
LOCAL_USER_ID = os.environ["LOCAL_USER_ID"]
NEO_MQTT_PORT = int(os.getenv("NEO_MQTT_PORT", "28883"))
NIMBUS_ACCOUNT_DELAY_IP = os.getenv("NIMBUS_ACCOUNT_DELAY_IP", "").strip()
NIMBUS_ACCOUNT_DELAY_SECONDS = int(os.getenv("NIMBUS_ACCOUNT_DELAY_SECONDS", "0"))
MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
TOPIC_PREFIX = os.getenv("TOPIC_PREFIX", "hass-actronneo-localcloud").strip("/")
DISCOVERY_PREFIX = os.getenv("DISCOVERY_PREFIX", "homeassistant").strip("/")
CERT_FILE = os.getenv("CERT_FILE", "/data/nimbus.crt")
KEY_FILE = os.getenv("KEY_FILE", "/data/nimbus.key")
PUBLISH_RAW_STATE = os.getenv("PUBLISH_RAW_STATE", "true").lower() == "true"
KNOWN_DEVICES_FILE = Path("/data/known_devices.json")
