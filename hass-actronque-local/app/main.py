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
        K0 ^ extract32(seed[0:4]),
        K1 ^ extract32(seed[4:8]),
        K2 ^ extract32(seed[8:12]),
    ]

    pad_length = max(2, 512 - 12 - 1 - len(data))

    padding = bytearray()
    while len(padding) < pad_length:
        for b in os.urandom(pad_length - len(padding)):
            if b:
                padding.append(b)

    plain = bytes(padding) + b"\x00" + data
    encrypted = bytes(b ^ next_byte(state) for b in plain)

    return base64.b64encode(seed + encrypted) + b"\n"


def decrypt_walllink(encoded: bytes) -> Dict[str, Any]:
    raw = base64.b64decode(encoded.strip(), validate=True)

    if len(raw) <= 12:
        raise ValueError("WallLink frame too short")

    state = [
        K0 ^ extract32(raw[0:4]),
        K1 ^ extract32(raw[4:8]),
        K2 ^ extract32(raw[8:12]),
    ]

    output = bytearray()
    in_padding = True

    for encrypted_byte in raw[12:]:
        plain_byte = encrypted_byte ^ next_byte(state)

        if in_padding:
            if plain_byte == 0:
                in_padding = False
        else:
            output.append(plain_byte)

    if in_padding:
        raise ValueError("WallLink padding terminator not found")

    return json.loads(output.decode("utf-8"))


_PATH_PART_RE = re.compile(r"^(.*?)(?:\[(\d+)\])?$")


def set_state_path(root: Dict[str, Any], path: str, value: Any) -> None:
    """Apply QUE paths such as RemoteZoneInfo[0].TemperatureSetpoint_Heat_oC."""
    parts = path.split(".")
    current: Any = root

    for index, part in enumerate(parts):
        match = _PATH_PART_RE.match(part)
        if not match:
            return

        key = match.group(1)
        array_index = match.group(2)
        last = index == len(parts) - 1

        if array_index is None:
            if last:
                if isinstance(current, dict):
                    current[key] = value
                return

            if not isinstance(current, dict):
                return

            if key not in current or not isinstance(current[key], (dict, list)):
                current[key] = {}

            current = current[key]
            continue

        idx = int(array_index)

        if not isinstance(current, dict):
            return

        if key not in current or not isinstance(current[key], list):
            current[key] = []

        arr = current[key]
        while len(arr) <= idx:
            arr.append({})

        if last:
            arr[idx] = value
            return

        if not isinstance(arr[idx], dict):
            arr[idx] = {}

        current = arr[idx]


def get_nested(root: Dict[str, Any], *keys, default=None):
    current: Any = root
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


class WallLinkClient:
    def __init__(self, on_message, on_online):
        self.host = str(OPTIONS["master_ip"])
        self.port = int(OPTIONS["master_port"])
        self.serial = str(OPTIONS["serial"])
        self.firmware = str(OPTIONS["firmware"])
        self.socket_timeout = int(OPTIONS["socket_timeout"])
        self.reconnect_delay = int(OPTIONS["reconnect_delay"])

        self.on_message = on_message
        self.on_online = on_online

        self.sock: Optional[socket.socket] = None
        self.send_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.connected = False

    def close_socket(self):
        sock = self.sock
        self.sock = None
        self.connected = False

        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def stop(self):
        self.stop_event.set()
        self.close_socket()

    def _send_json(self, obj: Dict[str, Any]):
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        frame = encrypt_walllink(raw)

        with self.send_lock:
            if self.sock is None:
                raise ConnectionError("WallLink is not connected")
            self.sock.sendall(frame)

    def send_change(self, path: str, value: Any):
        message = {
            "Data_Change": {
                path: value,
            },
            "id": {
                "fw_version": self.firmware,
                "serial": self.serial,
            },
        }

        LOG.info("WallLink write: %s = %r", path, value)
        self._send_json(message)

    def _connect(self) -> Tuple[socket.socket, Dict[str, Any], bytes]:
        LOG.info(
            "Connecting WallLink to %s:%s as %s",
            self.host,
            self.port,
            self.serial,
        )

        sock = socket.create_connection((self.host, self.port), timeout=10)
        sock.settimeout(self.socket_timeout)
        self.sock = sock

        hello = {
            "Data_Change": {},
            "Message": "Thank you for connecting me",
            "id": {
                "fw_version": self.firmware,
                "serial": self.serial,
            },
        }

        self._send_json(hello)

        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("Master closed connection during handshake")
            buffer += chunk

        frame, remainder = buffer.split(b"\n", 1)
        reply = decrypt_walllink(frame + b"\n")

        message = str(reply.get("Message", ""))
        if not message.startswith("Connection is successful"):
            raise ConnectionError(f"Master rejected WallLink connection: {message}")

        return sock, reply, remainder

    def run_forever(self):
        while not self.stop_event.is_set():
            try:
                sock, first, buffer = self._connect()
                self.connected = True

                master_serial = get_nested(first, "id", "serial", default="?")
                LOG.info("WallLink accepted by master %s", master_serial)

                self.on_online(True)
                self.on_message(first)

                while not self.stop_event.is_set():
                    while b"\n" in buffer:
                        frame, buffer = buffer.split(b"\n", 1)
                        if not frame.strip():
                            continue

                        try:
                            obj = decrypt_walllink(frame + b"\n")
                        except Exception:
                            LOG.exception("Failed to decrypt/parse WallLink frame")
                            continue

                        self.on_message(obj)

                    chunk = sock.recv(65536)
                    if not chunk:
                        raise ConnectionError("QUE master closed WallLink socket")

                    buffer += chunk

            except socket.timeout:
                LOG.warning(
                    "No WallLink traffic for %ss; reconnecting",
                    self.socket_timeout,
                )
            except Exception as exc:
                if not self.stop_event.is_set():
                    LOG.warning("WallLink disconnected: %s", exc)
            finally:
                self.close_socket()
                self.on_online(False)

            if not self.stop_event.is_set():
                time.sleep(self.reconnect_delay)


class ActronQueBridge:
    def __init__(self):
        self.state: Dict[str, Any] = {}
        self.state_lock = threading.RLock()

        self.topic_prefix = str(OPTIONS["topic_prefix"]).rstrip("/")
        self.discovery_prefix = str(OPTIONS["discovery_prefix"]).rstrip("/")
        self.publish_raw_state = bool(OPTIONS["publish_raw_state"])
        self.log_data_changes = bool(OPTIONS["log_data_changes"])

        self.master_serial = "unknown"
        self.master_fw = str(OPTIONS["firmware"])
        self.system_name = "QUE"

        self.walllink = WallLinkClient(
            on_message=self.handle_walllink_message,
            on_online=self.set_walllink_online,
        )

        client_id = f"actronque-local-{str(OPTIONS['serial']).lower()}"

        self.mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )

        username = os.environ.get("MQTT_USERNAME", "")
        password = os.environ.get("MQTT_PASSWORD", "")

        if username:
            self.mqtt.username_pw_set(username, password)

        self.mqtt.on_connect = self.on_mqtt_connect
        self.mqtt.on_disconnect = self.on_mqtt_disconnect
        self.mqtt.on_message = self.on_mqtt_message

        self.mqtt.will_set(
            f"{self.topic_prefix}/bridge/status",
            "offline",
            qos=1,
            retain=True,
        )

        self.walllink_online = False
        self.mqtt_connected = False
        self.discovery_published_for: Optional[str] = None

    def mqtt_publish(self, topic: str, payload: Any, retain=True):
        if not self.mqtt_connected:
            return

        if not isinstance(payload, (str, bytes)):
            payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        self.mqtt.publish(topic, payload, qos=1, retain=retain)

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code != 0:
            LOG.error("MQTT connection failed: %s", reason_code)
            return

        self.mqtt_connected = True
        LOG.info("MQTT connected")

        self.mqtt_publish(
            f"{self.topic_prefix}/bridge/status",
            "online",
            retain=True,
        )

        self.mqtt_publish(
            f"{self.topic_prefix}/status",
            "online" if self.walllink_online else "offline",
            retain=True,
        )

        self.mqtt_publish(
            f"{self.topic_prefix}/walllink/state",
            "ON" if self.walllink_online else "OFF",
            retain=True,
        )

        self.mqtt.subscribe(
            f"{self.topic_prefix}/quiet_mode/set",
            qos=1,
        )

        if self.state:
            self.publish_discovery()
            self.publish_current_state()

    def on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.mqtt_connected = False

        if reason_code != 0:
            LOG.warning("MQTT disconnected unexpectedly: %s", reason_code)
        else:
            LOG.info("MQTT disconnected")

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", "replace").strip()

        if topic == f"{self.topic_prefix}/quiet_mode/set":
            upper = payload.upper()

            if upper in ("ON", "TRUE", "1"):
                value = True
            elif upper in ("OFF", "FALSE", "0"):
                value = False
            else:
                LOG.warning("Ignoring invalid Quiet Mode command: %r", payload)
                return

            try:
                self.walllink.send_change(
                    "UserAirconSettings.QuietMode",
                    value,
                )
            except Exception as exc:
                LOG.error("Quiet Mode write failed: %s", exc)

    def set_walllink_online(self, online: bool):
        self.walllink_online = online

        LOG.info("WallLink %s", "online" if online else "offline")

        self.mqtt_publish(
            f"{self.topic_prefix}/status",
            "online" if online else "offline",
            retain=True,
        )

        self.mqtt_publish(
            f"{self.topic_prefix}/walllink/state",
            "ON" if online else "OFF",
            retain=True,
        )

    def handle_walllink_message(self, obj: Dict[str, Any]):
        with self.state_lock:
            data_all = obj.get("Data_All")

            if isinstance(data_all, dict):
                self.state = copy.deepcopy(data_all)

                LOG.info(
                    "Initial/refresh Data_All received (%d top-level keys)",
                    len(self.state),
                )

                self.master_serial = str(
                    get_nested(obj, "id", "serial", default=self.master_serial)
                )

                self.master_fw = str(
                    get_nested(obj, "id", "fw_version", default=self.master_fw)
                )

                self.system_name = str(
                    get_nested(
                        self.state,
                        "NV_SystemSettings",
                        "SystemName",
                        default=self.system_name,
                    )
                )

                if (
                    self.mqtt_connected
                    and self.discovery_published_for != self.master_serial
                ):
                    self.publish_discovery()

            data_change = obj.get("Data_Change")

            if isinstance(data_change, dict):
                if self.log_data_changes:
                    LOG.info(
                        "Data_Change: %s",
                        json.dumps(
                            data_change,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    )

                for path, value in data_change.items():
                    set_state_path(self.state, path, value)

                self.mqtt_publish(
                    f"{self.topic_prefix}/event/change",
                    data_change,
                    retain=False,
                )

        self.publish_current_state()

    def device_info(self):
        identifier_serial = (
            self.master_serial
            if self.master_serial != "unknown"
            else str(OPTIONS["serial"])
        )

        return {
            "identifiers": [f"actronque_{identifier_serial.lower()}"],
            "name": f"Actron QUE {self.system_name}",
            "manufacturer": "ActronAir",
            "model": "QUE",
            "sw_version": self.master_fw,
        }

    def publish_discovery_entity(self, domain: str, object_id: str, config: Dict[str, Any]):
        config = dict(config)
        config.setdefault("unique_id", f"actronque_{self.master_serial.lower()}_{object_id}")
        config.setdefault("device", self.device_info())

        topic = (
            f"{self.discovery_prefix}/{domain}/"
            f"actronque_local/{object_id}/config"
        )

        self.mqtt_publish(topic, config, retain=True)

    def publish_discovery(self):
        if not self.mqtt_connected:
            return

        availability = {
            "availability_topic": f"{self.topic_prefix}/status",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        bridge_availability = {
            "availability_topic": f"{self.topic_prefix}/bridge/status",
            "payload_available": "online",
            "payload_not_available": "offline",
        }

        self.publish_discovery_entity(
            "binary_sensor",
            "walllink_connected",
            {
                "name": "WallLink Connected",
                "state_topic": f"{self.topic_prefix}/walllink/state",
                "payload_on": "ON",
                "payload_off": "OFF",
                "entity_category": "diagnostic",
                **bridge_availability,
            },
        )

        self.publish_discovery_entity(
            "binary_sensor",
            "aircon_on",
            {
                "name": "Aircon On",
                "state_topic": f"{self.topic_prefix}/aircon_on/state",
                "payload_on": "ON",
                "payload_off": "OFF",
                **availability,
            },
        )

        self.publish_discovery_entity(
            "sensor",
            "mode",
            {
                "name": "Mode",
                "state_topic": f"{self.topic_prefix}/mode/state",
                **availability,
            },
        )

        self.publish_discovery_entity(
            "sensor",
            "fan_mode",
            {
                "name": "Fan Mode",
                "state_topic": f"{self.topic_prefix}/fan_mode/state",
                **availability,
            },
        )

        self.publish_discovery_entity(
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
                **availability,
            },
        )

        self.publish_discovery_entity(
            "sensor",
            "system_name",
            {
                "name": "System Name",
                "state_topic": f"{self.topic_prefix}/system_name/state",
                "entity_category": "diagnostic",
                **availability,
            },
        )

        self.publish_discovery_entity(
            "sensor",
            "master_serial",
            {
                "name": "Master Serial",
                "state_topic": f"{self.topic_prefix}/master_serial/state",
                "entity_category": "diagnostic",
                **availability,
            },
        )

        self.discovery_published_for = self.master_serial

    def publish_current_state(self):
        with self.state_lock:
            state = copy.deepcopy(self.state)

        if not state:
            return

        settings = state.get("UserAirconSettings", {})
        system_settings = state.get("NV_SystemSettings", {})

        is_on = settings.get("isOn")
        if isinstance(is_on, bool):
            self.mqtt_publish(
                f"{self.topic_prefix}/aircon_on/state",
                "ON" if is_on else "OFF",
                retain=True,
            )

        mode = settings.get("Mode")
        if mode is not None:
            self.mqtt_publish(
                f"{self.topic_prefix}/mode/state",
                str(mode),
                retain=True,
            )

        fan_mode = settings.get("FanMode")
        if fan_mode is not None:
            self.mqtt_publish(
                f"{self.topic_prefix}/fan_mode/state",
                str(fan_mode),
                retain=True,
            )

        quiet_mode = settings.get("QuietMode")
        if isinstance(quiet_mode, bool):
            self.mqtt_publish(
                f"{self.topic_prefix}/quiet_mode/state",
                "ON" if quiet_mode else "OFF",
                retain=True,
            )

        system_name = system_settings.get("SystemName")
        if system_name is not None:
            self.mqtt_publish(
                f"{self.topic_prefix}/system_name/state",
                str(system_name),
                retain=True,
            )

        if self.master_serial != "unknown":
            self.mqtt_publish(
                f"{self.topic_prefix}/master_serial/state",
                self.master_serial,
                retain=True,
            )

        if self.publish_raw_state:
            self.mqtt_publish(
                f"{self.topic_prefix}/raw/state",
                state,
                retain=True,
            )

    def run(self):
        mqtt_host = os.environ.get("MQTT_HOST", "")
        mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))

        if not mqtt_host:
            raise RuntimeError("Supervisor MQTT service did not provide a host")

        LOG.info("Connecting MQTT to %s:%s", mqtt_host, mqtt_port)

        self.mqtt.connect_async(
            mqtt_host,
            mqtt_port,
            keepalive=60,
        )
        self.mqtt.loop_start()

        walllink_thread = threading.Thread(
            target=self.walllink.run_forever,
            name="walllink",
            daemon=True,
        )
        walllink_thread.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            LOG.info("Stopping")
        finally:
            self.walllink.stop()
            self.mqtt_publish(
                f"{self.topic_prefix}/status",
                "offline",
                retain=True,
            )
            self.mqtt_publish(
                f"{self.topic_prefix}/bridge/status",
                "offline",
                retain=True,
            )
            self.mqtt.loop_stop()
            self.mqtt.disconnect()


if __name__ == "__main__":
    ActronQueBridge().run()
