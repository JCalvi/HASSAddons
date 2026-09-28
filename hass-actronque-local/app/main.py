#!/usr/bin/env python3

import base64
import copy
import json
import logging
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import paho.mqtt.client as mqtt


OPTIONS_FILE = Path("/data/options.json")

K0 = 0xFE2D85CD
K1 = 0x043E9190
K2 = 0x2E0EA4A4
MASK = 0xFFFFFFFF


def load_options() -> Dict[str, Any]:
    defaults = {
        "master_ip": "192.168.1.218",
        "master_port": 19296,
        "serial": "FA000001",
        "firmware": "1.456.1.598",
        "separate_heat_cool_targets": False,
        "topic_prefix": "hass-actronque-local",
        "discovery_prefix": "homeassistant",
        "reconnect_delay": 5,
        "socket_timeout": 60,
        "log_data_changes": True,
        "publish_raw_state": True,
        "log_level": "INFO",
    }

    if OPTIONS_FILE.exists():
        with OPTIONS_FILE.open("r", encoding="utf-8") as f:
            user = json.load(f)
        defaults.update(user)

    return defaults


OPTIONS = load_options()

logging.basicConfig(
    level=getattr(logging, str(OPTIONS["log_level"]).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
LOG = logging.getLogger("actronque")


def extract32(data: bytes) -> int:
    value = 0
    for b in data:
        signed = b if b < 128 else b - 256
        value = (signed | ((value << 8) & MASK)) & MASK
    return value


def next_bit(state) -> int:
    x, y, z = state

    fb0 = (
        (x >> 6)
        ^ (x >> 31)
        ^ x
        ^ (x >> 4)
        ^ (x >> 2)
        ^ ((x << 1) & MASK)
    ) & MASK

    x = ((x >> 1) | ((fb0 & 1) << 31)) & MASK

    fb1 = ((y >> 30) ^ (y >> 2)) & 1
    y = ((y >> 1) | (fb1 << 30)) & MASK

    zs = z >> 1
    fb2 = (zs ^ (z >> 28)) & 1
    z = (zs | (fb2 << 28)) & MASK

    state[:] = [x, y, z]
    return (x ^ y ^ z) & 1


def next_byte(state) -> int:
    value = 0
    for _ in range(8):
        value = ((value << 1) & 0xFE) | next_bit(state)
    return value


def encrypt_walllink(data: bytes) -> bytes:
    seed = os.urandom(12)
    state = [
        extract32(seed[0:4]) ^ K0,
        extract32(seed[4:8]) ^ K1,
        extract32(seed[8:12]) ^ K2,
    ]
    encrypted = bytearray(seed)
    encrypted.extend((b ^ next_byte(state)) for b in data)
    encrypted.append(0x0A)
    return bytes(encrypted)


def decrypt_walllink(frame: bytes) -> Dict[str, Any]:
    if frame.endswith(b"\n"):
        frame = frame[:-1]
    if len(frame) < 12:
        raise ValueError("encrypted WallLink frame shorter than 12-byte seed")

    seed = frame[:12]
    state = [
        extract32(seed[0:4]) ^ K0,
        extract32(seed[4:8]) ^ K1,
        extract32(seed[8:12]) ^ K2,
    ]
    plain = bytes(b ^ next_byte(state) for b in frame[12:])
    return json.loads(plain.decode("utf-8"))


def set_state_path(root: Dict[str, Any], path: str, value: Any) -> None:
    """Apply dotted / indexed WallLink Data_Change paths to the cached state."""
    parts = re.split(r"\.(?![^\[]*\])", path)
    current: Any = root

    for index, part in enumerate(parts):
        match = re.fullmatch(r"([^\[]+)\[(\d+)\]", part)
        last = index == len(parts) - 1

        if match:
            key = match.group(1)
            item_index = int(match.group(2))
            if not isinstance(current, dict):
                return
            items = current.setdefault(key, [])
            if not isinstance(items, list):
                return
            while len(items) <= item_index:
                items.append({})
            if last:
                items[item_index] = value
            else:
                if not isinstance(items[item_index], dict):
                    items[item_index] = {}
                current = items[item_index]
        else:
            if not isinstance(current, dict):
                return
            if last:
                current[part] = value
            else:
                child = current.setdefault(part, {})
                if not isinstance(child, dict):
                    child = {}
                    current[part] = child
                current = child


class WallLinkClient:
    def __init__(self, bridge):
        self.bridge = bridge
        self.host = str(OPTIONS["master_ip"])
        self.port = int(OPTIONS["master_port"])
        self.serial = str(OPTIONS["serial"])
        self.firmware = str(OPTIONS.get("firmware", "1.456.1.598"))
        self.reconnect_delay = int(OPTIONS["reconnect_delay"])
        self.socket_timeout = int(OPTIONS["socket_timeout"])
        self.stop_event = threading.Event()
        self.sock: Optional[socket.socket] = None
        self.send_lock = threading.Lock()

    def _send_json(self, obj: Dict[str, Any]) -> None:
        payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        frame = encrypt_walllink(payload)
        with self.send_lock:
            if self.sock is None:
                raise ConnectionError("WallLink is not connected")
            self.sock.sendall(frame)

    def send_change(self, path: str, value: Any) -> None:
        self._send_json(
            {
                "Data_Change": {path: value},
                "id": {"fw_version": self.firmware, "serial": self.serial},
            }
        )

    def stop(self) -> None:
        self.stop_event.set()
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                LOG.info("Connecting to QUE WallLink at %s:%s", self.host, self.port)
                with socket.create_connection((self.host, self.port), timeout=10) as sock:
                    self.sock = sock
                    sock.settimeout(self.socket_timeout)
                    self._send_json(
                        {
                            "Data_Change": {},
                            "Message": "Thank you for connecting me",
                            "id": {"fw_version": self.firmware, "serial": self.serial},
                        }
                    )

                    buffer = b""
                    while not self.stop_event.is_set():
                        chunk = sock.recv(65536)
                        if not chunk:
                            raise ConnectionError("QUE master closed WallLink connection")
                        buffer += chunk

                        while b"\n" in buffer:
                            frame, buffer = buffer.split(b"\n", 1)
                            if not frame:
                                continue
                            try:
                                obj = decrypt_walllink(frame + b"\n")
                                self.bridge.handle_walllink_message(obj)
                            except Exception:
                                LOG.exception("Unable to process WallLink frame")
            except Exception as exc:
                if not self.stop_event.is_set():
                    LOG.warning("WallLink disconnected: %s", exc)
                    self.bridge.set_walllink_online(False)
                    time.sleep(self.reconnect_delay)
            finally:
                self.sock = None


class ActronQueBridge:
    def __init__(self):
        self.topic_prefix = str(OPTIONS["topic_prefix"]).rstrip("/")
        self.discovery_prefix = str(OPTIONS["discovery_prefix"]).rstrip("/")
        self.state: Dict[str, Any] = {}
        self.state_lock = threading.RLock()
        self.master_serial = "unknown"
        self.master_fw = "unknown"
        self.system_name = "Home"
        self.walllink_online = False
        self.mqtt_connected = False
        self._discovery_published = False
        self._stop = threading.Event()
        self.walllink = WallLinkClient(self)

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        username = os.getenv("MQTT_USERNAME", "")
        password = os.getenv("MQTT_PASSWORD", "")
        if username:
            self.mqtt.username_pw_set(username, password)

        self.mqtt.on_connect = self.on_mqtt_connect
        self.mqtt.on_disconnect = self.on_mqtt_disconnect
        self.mqtt.on_message = self.on_mqtt_message
        self.mqtt.will_set(f"{self.topic_prefix}/bridge/status", "offline", qos=1, retain=True)

    def mqtt_publish(self, topic: str, payload: Any, retain: bool = False):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, separators=(",", ":"))
        self.mqtt.publish(topic, payload, qos=1, retain=retain)

    def device_info(self):
        return {
            "identifiers": [f"actronque_local_{self.master_serial}"],
            "name": f"Actron QUE Local ({self.system_name})",
            "manufacturer": "ActronAir",
            "model": "QUE Local WallLink",
            "sw_version": self.master_fw,
        }

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            LOG.error("MQTT connection failed: %s", reason_code)
            return
        self.mqtt_connected = True
        LOG.info("Connected to MQTT broker")
        self.mqtt_publish(f"{self.topic_prefix}/bridge/status", "online", retain=True)
        self.mqtt.subscribe(f"{self.topic_prefix}/quiet_mode/set", qos=1)
        self.mqtt.subscribe(f"{self.topic_prefix}/raw/request", qos=1)
        if self.state:
            self.publish_discovery()
            self.publish_current_state()

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.mqtt_connected = False
        LOG.warning("Disconnected from MQTT broker: %s", reason_code)

    def on_mqtt_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace").strip()
        if msg.topic == f"{self.topic_prefix}/quiet_mode/set":
            value = payload.upper() in ("ON", "TRUE", "1")
            self.walllink.send_change("UserAirconSettings.QuietMode", value)
        elif msg.topic == f"{self.topic_prefix}/raw/request":
            with self.state_lock:
                snapshot = copy.deepcopy(self.state)
            self.mqtt_publish(f"{self.topic_prefix}/raw/state", snapshot, retain=True)

    def on_mqtt_connect_legacy(self, client, userdata, flags, rc):
        return self.on_mqtt_connect(client, userdata, flags, rc, None)

    def handle_walllink_message(self, obj: Dict[str, Any]) -> None:
        message = str(obj.get("Message", ""))
        if message.startswith("Connection is successful"):
            self.set_walllink_online(True)
            LOG.info("QUE master accepted synthetic controller %s", self.walllink.serial)

        data_all = obj.get("Data_All")
        if isinstance(data_all, dict):
            with self.state_lock:
                self.state = data_all
            self._update_identity(data_all, obj)
            self.publish_discovery()
            self.publish_current_state()

        changes = obj.get("Data_Change")
        if isinstance(changes, dict) and changes:
            with self.state_lock:
                for path, value in changes.items():
                    set_state_path(self.state, path, value)
            if OPTIONS.get("log_data_changes", True):
                LOG.info("Data_Change: %s", json.dumps(changes, separators=(",", ":")))
            self.mqtt_publish(f"{self.topic_prefix}/event/change", changes)
            self.publish_current_state()

    def _update_identity(self, data_all: Dict[str, Any], envelope: Dict[str, Any]) -> None:
        system = data_all.get("NV_SystemSettings", {})
        if isinstance(system, dict):
            self.system_name = str(system.get("SystemName") or self.system_name)

        env_id = envelope.get("id", {})
        if isinstance(env_id, dict):
            self.master_serial = str(env_id.get("serial") or self.master_serial)
            self.master_fw = str(env_id.get("fw_version") or self.master_fw)

    def set_walllink_online(self, online: bool) -> None:
        self.walllink_online = online
        if self.mqtt_connected:
            self.mqtt_publish(
                f"{self.topic_prefix}/status",
                "online" if online else "offline",
                retain=True,
            )

    def publish_discovery(self) -> None:
        if not self.mqtt_connected or not self.state:
            return

        device = self.device_info()
        availability = {
            "availability_topic": f"{self.topic_prefix}/status",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        entities = [
            (
                "binary_sensor",
                "walllink_connected",
                {
                    "name": "WallLink Connected",
                    "state_topic": f"{self.topic_prefix}/status",
                    "payload_on": "online",
                    "payload_off": "offline",
                    "device_class": "connectivity",
                    "entity_category": "diagnostic",
                },
            ),
            (
                "binary_sensor",
                "aircon_on",
                {
                    "name": "Air Conditioner",
                    "state_topic": f"{self.topic_prefix}/aircon/state",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "running",
                },
            ),
            (
                "sensor",
                "mode",
                {"name": "Mode", "state_topic": f"{self.topic_prefix}/mode/state"},
            ),
            (
                "sensor",
                "fan_mode",
                {"name": "Fan Mode", "state_topic": f"{self.topic_prefix}/fan_mode/state"},
            ),
            (
                "switch",
                "quiet_mode",
                {
                    "name": "Quiet Mode",
                    "state_topic": f"{self.topic_prefix}/quiet_mode/state",
                    "command_topic": f"{self.topic_prefix}/quiet_mode/set",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "state_on": "ON",
                    "state_off": "OFF",
                },
            ),
            (
                "sensor",
                "system_name",
                {"name": "System Name", "state_topic": f"{self.topic_prefix}/system/name"},
            ),
            (
                "sensor",
                "master_serial",
                {"name": "Master Serial", "state_topic": f"{self.topic_prefix}/system/master_serial"},
            ),
        ]

        for domain, object_id, config in entities:
            config = dict(config)
            config["unique_id"] = f"actronque_local_{self.master_serial}_{object_id}"
            config["device"] = device
            config.update(availability)
            topic = f"{self.discovery_prefix}/{domain}/actronque_local/{object_id}/config"
            self.mqtt_publish(topic, config, retain=True)

        self._discovery_published = True

    def publish_current_state(self) -> None:
        with self.state_lock:
            state = copy.deepcopy(self.state)

        settings = state.get("UserAirconSettings", {}) if isinstance(state, dict) else {}
        master_info = state.get("MasterInfo", {}) if isinstance(state, dict) else {}
        system = state.get("NV_SystemSettings", {}) if isinstance(state, dict) else {}

        is_on = settings.get("isOn")
        if isinstance(is_on, bool):
            self.mqtt_publish(f"{self.topic_prefix}/aircon/state", "ON" if is_on else "OFF", retain=True)

        mode = settings.get("Mode")
        if mode is not None:
            self.mqtt_publish(f"{self.topic_prefix}/mode/state", mode, retain=True)

        fan_mode = settings.get("FanMode")
        if fan_mode is not None:
            self.mqtt_publish(f"{self.topic_prefix}/fan_mode/state", fan_mode, retain=True)

        quiet = settings.get("QuietMode")
        if isinstance(quiet, bool):
            self.mqtt_publish(f"{self.topic_prefix}/quiet_mode/state", "ON" if quiet else "OFF", retain=True)

        live_temp = master_info.get("LiveTemp_oC")
        if live_temp is not None:
            self.mqtt_publish(f"{self.topic_prefix}/temperature/state", live_temp, retain=True)

        system_name = system.get("SystemName")
        if system_name is not None:
            self.mqtt_publish(f"{self.topic_prefix}/system/name", system_name, retain=True)

        if self.master_serial != "unknown":
            self.mqtt_publish(f"{self.topic_prefix}/system/master_serial", self.master_serial, retain=True)

        if OPTIONS.get("publish_raw_state", True):
            self.mqtt_publish(f"{self.topic_prefix}/raw/state", state, retain=True)

    def run(self) -> None:
        mqtt_host = os.getenv("MQTT_HOST", "core-mosquitto")
        mqtt_port = int(os.getenv("MQTT_PORT", "1883"))

        LOG.info("Connecting to MQTT at %s:%s", mqtt_host, mqtt_port)
        self.mqtt.connect(mqtt_host, mqtt_port, keepalive=60)
        self.mqtt.loop_start()

        walllink_thread = threading.Thread(target=self.walllink.run, name="walllink", daemon=True)
        walllink_thread.start()

        try:
            while walllink_thread.is_alive():
                walllink_thread.join(timeout=1)
        except KeyboardInterrupt:
            LOG.info("Stopping")
        finally:
            self.walllink.stop()
            self._stop.set()
            self.mqtt.loop_stop()
            self.mqtt.disconnect()


if __name__ == "__main__":
    ActronQueBridge().run()
