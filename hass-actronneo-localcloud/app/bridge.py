"""Bridge native NEO MQTT traffic to Home Assistant MQTT Discovery state/commands."""

from __future__ import annotations

import json
import logging
import uuid
from copy import deepcopy
from typing import Any

import paho.mqtt.client as mqtt

from config import (
    KNOWN_DEVICES_FILE,
    MQTT_HOST,
    MQTT_PASSWORD,
    MQTT_PORT,
    MQTT_USERNAME,
    PUBLISH_RAW_STATE,
    TOPIC_PREFIX,
)
from discovery import publish_discovery
from state import deep_merge, extract_event, ha_to_neo_mode, normalize_state, set_path

_LOGGER = logging.getLogger("actronneo-localcloud.bridge")


class HomeAssistantBridge:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._user_ids: dict[str, str] = {}
        self._connection_state: dict[str, bool] = {}
        self._known_devices: dict[str, dict[str, str]] = self._load_known_devices()
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"actronneo-localcloud-{uuid.uuid4().hex[:8]}",
        )
        self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def run(self) -> None:
        _LOGGER.info("Connecting HA bridge to MQTT service %s:%s", MQTT_HOST, MQTT_PORT)
        self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        self._client.loop_forever(retry_first_connection=True)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if getattr(reason_code, "is_failure", False):
            _LOGGER.error("HA MQTT bridge connection failed: %s", reason_code)
            return
        _LOGGER.info("HA MQTT bridge connected")
        client.subscribe("actron-cloud/+/neo/+/mwc/#")
        client.subscribe(f"{TOPIC_PREFIX}/+/set/#")
        client.subscribe(f"{TOPIC_PREFIX}/+/zone/+/set/#")
        for serial in self._known_devices:
            self._publish_availability(serial, False)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        topic = message.topic
        if topic.startswith("actron-cloud/"):
            self._handle_neo_message(topic, message.payload)
        elif topic.startswith(TOPIC_PREFIX + "/"):
            self._handle_ha_command(topic, message.payload)

    def device_connection(self, serial: str, online: bool) -> None:
        serial = serial.lower()
        self._connection_state[serial] = online
        if online:
            _LOGGER.info("NEO %s connected to local MQTT", serial)
        else:
            _LOGGER.info("NEO %s disconnected from local MQTT", serial)
            self._publish_availability(serial, False)

    def _handle_neo_message(self, topic: str, payload_bytes: bytes) -> None:
        parts = topic.split("/")
        if len(parts) < 6:
            return
        user_id = parts[1]
        serial = parts[3].lower()
        if parts[4] != "mwc":
            return
        message_type = parts[5]
        self._user_ids[serial] = user_id

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _LOGGER.warning("Invalid JSON from NEO %s on %s", serial, topic)
            return

        if message_type == "full-status":
            body = extract_event(payload)
            if body is None:
                _LOGGER.warning("Could not unwrap full-status from NEO %s", serial)
                return
            body = deepcopy(body)
            body.pop("type", None)
            _LOGGER.info(
                "NEO %s full-status received (%d bytes, %d top-level sections)",
                serial,
                len(payload_bytes),
                len(body),
            )
            self._states[serial] = body
            self._publish_device(serial)
            return

        if message_type == "status-change":
            body = extract_event(payload)
            if body is None:
                return
            _LOGGER.debug("NEO %s status-change received (%d keys)", serial, len(body))
            if serial not in self._states:
                _LOGGER.info("NEO %s status-change arrived before full-status; requesting getAll", serial)
                self._request_get_all(serial)
                return
            for key, value in body.items():
                if key == "type":
                    continue
                if "." in key or "[" in key:
                    set_path(self._states[serial], key, value)
                elif isinstance(value, dict) and isinstance(self._states[serial].get(key), dict):
                    deep_merge(self._states[serial][key], value)
                else:
                    self._states[serial][key] = deepcopy(value)
            self._publish_device(serial)
            return

        if message_type == "heart-beat":
            _LOGGER.debug("NEO %s heart-beat received", serial)
            self._publish_availability(serial, True)
            if serial not in self._states:
                _LOGGER.info("NEO %s heartbeat arrived before full-status; requesting getAll", serial)
                self._request_get_all(serial)
            return

        if message_type == "cmd-response":
            _LOGGER.debug("Command response from NEO %s: %s", serial, topic)
            return

        _LOGGER.debug("NEO %s message on unhandled mwc topic: %s", serial, topic)

    def _handle_ha_command(self, topic: str, payload_bytes: bytes) -> None:
        parts = topic.split("/")
        if len(parts) < 4:
            return
        serial = parts[1].lower()
        state = self._states.get(serial)
        user_id = self._user_ids.get(serial)
        if not state or not user_id:
            _LOGGER.warning("Ignoring command for %s: no current NEO state", serial)
            return

        try:
            text = payload_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            return

        try:
            if len(parts) >= 6 and parts[2] == "zone":
                zone_index = int(parts[3])
                command_name = parts[5]
                command = self._build_zone_command(state, zone_index, command_name, text)
            else:
                command_name = parts[3]
                command = self._build_system_command(state, command_name, text)
        except (ValueError, TypeError, IndexError) as exc:
            _LOGGER.warning("Invalid HA command %s: %s", topic, exc)
            return

        if command is not None:
            self._send_command(serial, user_id, command)

    def _build_system_command(
        self, state: dict[str, Any], command_name: str, text: str
    ) -> dict[str, Any] | None:
        settings = state.get("UserAirconSettings") or {}
        mode = str(settings.get("Mode", "AUTO")).upper()

        if command_name == "mode":
            if text.lower() == "off":
                return {"command": {"UserAirconSettings.isOn": False, "type": "set-settings"}}
            return {
                "command": {
                    "UserAirconSettings.isOn": True,
                    "UserAirconSettings.Mode": ha_to_neo_mode(text),
                    "type": "set-settings",
                }
            }

        if command_name == "temperature":
            temperature = float(text)
            cmd: dict[str, Any] = {"type": "set-settings"}
            if mode == "COOL":
                cmd["UserAirconSettings.TemperatureSetpoint_Cool_oC"] = temperature
            elif mode == "HEAT":
                cmd["UserAirconSettings.TemperatureSetpoint_Heat_oC"] = temperature
            elif mode == "AUTO":
                cool = float(settings.get("TemperatureSetpoint_Cool_oC", temperature))
                heat = float(settings.get("TemperatureSetpoint_Heat_oC", temperature - 2.0))
                differential = max(0.0, cool - heat)
                cmd["UserAirconSettings.TemperatureSetpoint_Cool_oC"] = temperature
                cmd["UserAirconSettings.TemperatureSetpoint_Heat_oC"] = max(10.0, temperature - differential)
            else:
                raise ValueError(f"cannot set temperature in mode {mode}")
            return {"command": cmd}

        if command_name == "fan_mode":
            requested = text.upper()
            current = str(settings.get("FanMode", ""))
            if "+CONT" in current or "-CONT" in current:
                requested += "+CONT"
            return {"command": {"UserAirconSettings.FanMode": requested, "type": "set-settings"}}

        switch_paths = {
            "quiet": "UserAirconSettings.QuietModeEnabled",
            "away": "UserAirconSettings.AwayMode",
            "turbo": "UserAirconSettings.TurboMode.Enabled",
        }
        if command_name in switch_paths:
            return {
                "command": {
                    switch_paths[command_name]: text.upper() == "ON",
                    "type": "set-settings",
                }
            }

        if command_name == "continuous_fan":
            base = str(settings.get("FanMode", "AUTO")).replace("+CONT", "").replace("-CONT", "")
            value = f"{base}+CONT" if text.upper() == "ON" else base
            return {"command": {"UserAirconSettings.FanMode": value, "type": "set-settings"}}

        return None

    def _build_zone_command(
        self,
        state: dict[str, Any],
        zone_index: int,
        command_name: str,
        text: str,
    ) -> dict[str, Any] | None:
        settings = state.get("UserAirconSettings") or {}
        zones = state.get("RemoteZoneInfo") or []
        if zone_index < 0 or zone_index >= len(zones):
            raise IndexError("zone index out of range")
        mode = str(settings.get("Mode", "AUTO")).upper()

        if command_name == "mode":
            enabled = list(settings.get("EnabledZones") or [])
            while len(enabled) <= zone_index:
                enabled.append(False)
            if text.lower() == "off":
                enabled[zone_index] = False
                return {"command": {"UserAirconSettings.EnabledZones": enabled, "type": "set-settings"}}
            enabled[zone_index] = True
            return {
                "command": {
                    "UserAirconSettings.EnabledZones": enabled,
                    "UserAirconSettings.isOn": True,
                    "UserAirconSettings.Mode": ha_to_neo_mode(text),
                    "type": "set-settings",
                }
            }

        if command_name == "temperature":
            temperature = float(text)
            cmd: dict[str, Any] = {"type": "set-settings"}
            if mode == "COOL":
                cmd[f"RemoteZoneInfo[{zone_index}].TemperatureSetpoint_Cool_oC"] = temperature
            elif mode == "HEAT":
                cmd[f"RemoteZoneInfo[{zone_index}].TemperatureSetpoint_Heat_oC"] = temperature
            elif mode == "AUTO":
                cool = float(settings.get("TemperatureSetpoint_Cool_oC", temperature))
                heat = float(settings.get("TemperatureSetpoint_Heat_oC", temperature - 2.0))
                differential = max(0.0, cool - heat)
                cmd[f"RemoteZoneInfo[{zone_index}].TemperatureSetpoint_Cool_oC"] = temperature
                cmd[f"RemoteZoneInfo[{zone_index}].TemperatureSetpoint_Heat_oC"] = max(10.0, temperature - differential)
            else:
                raise ValueError(f"cannot set zone temperature in mode {mode}")
            return {"command": cmd}

        return None

    def _send_command(self, serial: str, user_id: str, command: dict[str, Any]) -> None:
        command = deepcopy(command)
        command["correlationId"] = f"HA_LOCAL/{uuid.uuid4()}"
        command["OptOutOfLogging"] = True
        topic = f"actron-cloud/{user_id}/neo/{serial}/app/cmd"
        self._client.publish(topic, json.dumps(command, separators=(",", ":")), qos=0)

    def _request_get_all(self, serial: str) -> None:
        user_id = self._user_ids.get(serial)
        if user_id:
            _LOGGER.info("Requesting full NEO state from %s with getAll", serial)
            self._send_command(serial, user_id, {"command": {"type": "getAll"}})

    def _publish_availability(self, serial: str, online: bool) -> None:
        self._client.publish(
            f"{TOPIC_PREFIX}/{serial.lower()}/availability",
            "online" if online else "offline",
            retain=True,
        )

    def _publish_device(self, serial: str) -> None:
        raw = self._states.get(serial)
        if not raw:
            return
        normalized = normalize_state(serial, raw)
        _LOGGER.debug(
            "Publishing NEO %s state: power=%s mode=%s fan=%s zones=%d",
            serial,
            normalized.get("power"),
            normalized.get("mode"),
            normalized.get("fan_mode"),
            len(normalized.get("zones", [])),
        )
        publish_discovery(self._client, serial, normalized)
        self._client.publish(
            f"{TOPIC_PREFIX}/{serial}/state",
            json.dumps(normalized, separators=(",", ":"), allow_nan=False),
            retain=True,
        )
        if PUBLISH_RAW_STATE:
            self._client.publish(
                f"{TOPIC_PREFIX}/{serial}/raw",
                json.dumps(raw, separators=(",", ":"), allow_nan=False),
                retain=True,
            )
        self._publish_availability(serial, True)
        self._remember_device(serial, normalized)

    def _load_known_devices(self) -> dict[str, dict[str, str]]:
        try:
            if KNOWN_DEVICES_FILE.exists():
                data = json.loads(KNOWN_DEVICES_FILE.read_text())
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            _LOGGER.warning("Could not load known device cache: %s", exc)
        return {}

    def _remember_device(self, serial: str, state: dict[str, Any]) -> None:
        record = {
            "name": str(state.get("name", "")),
            "user_id": self._user_ids.get(serial, ""),
        }
        if self._known_devices.get(serial) == record:
            return
        self._known_devices[serial] = record
        try:
            KNOWN_DEVICES_FILE.write_text(json.dumps(self._known_devices, indent=2))
        except OSError as exc:
            _LOGGER.warning("Could not save known device cache: %s", exc)
