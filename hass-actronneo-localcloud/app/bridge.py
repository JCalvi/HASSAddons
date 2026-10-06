"""Bridge native NEO MQTT traffic to Home Assistant MQTT Discovery state/commands."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
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
_COMMAND_SETTLE_SECONDS = 6.0
_ACTIVE_REFRESH_SECONDS = 5.0
_IDLE_REFRESH_SECONDS = 30.0
_REFRESH_LOOP_SECONDS = 1.0
_RAW_MQTT_PREVIEW_CHARS = 16384


def _debug_change_fields(value: Any, prefix: str = "") -> list[str]:
    """Return changed field paths while exposing values only for booleans.

    This is deliberately conservative for DEBUG logging: nested field names are
    useful when mapping undocumented NEO controls, while arbitrary string or
    numeric payload values are not emitted.
    """
    if isinstance(value, dict):
        fields: list[str] = []
        for key, nested in value.items():
            if key == "type":
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(_debug_change_fields(nested, path))
        return fields
    if isinstance(value, bool):
        return [f"{prefix}={'true' if value else 'false'}"] if prefix else []
    return [prefix] if prefix else []


def _safe_mqtt_preview(payload_bytes: bytes) -> str:
    """Return a generously bounded, redacted representation of an MQTT payload."""
    text = payload_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return "<empty>"

    text = re.sub(
        r'(?i)(access[_-]?token|refresh[_-]?token|authorization|password|secret)(\s*["\'=:\-]+\s*)([^,\s}"]+)',
        r"\1\2<redacted>",
        text,
    )
    text = re.sub(
        r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}",
        "<redacted-jwt>",
        text,
    )
    text = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "<redacted-email>",
        text,
    )
    text = re.sub(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "<uuid>",
        text,
    )

    if len(text) > _RAW_MQTT_PREVIEW_CHARS:
        return text[:_RAW_MQTT_PREVIEW_CHARS] + "...<truncated>"
    return text


def _safe_neo_topic(topic: str) -> str:
    """Redact the Nimbus user/account identifier while retaining routing context."""
    parts = topic.split("/")
    if len(parts) > 1 and parts[0] == "actron-cloud":
        parts[1] = "<user-id>"
    return "/".join(parts)


class HomeAssistantBridge:
    def __init__(self) -> None:
        self._states: dict[str, dict[str, Any]] = {}
        self._user_ids: dict[str, str] = {}
        self._connection_state: dict[str, bool] = {}
        self._known_devices: dict[str, dict[str, str]] = self._load_known_devices()
        self._suppress_until: dict[str, float] = {}
        self._suppress_lock = threading.Lock()
        self._last_full_status: dict[str, float] = {}
        self._last_getall_request: dict[str, float] = {}
        self._diag_condition = threading.Condition()
        self._diag_cmd_responses: dict[tuple[str, str], dict[str, Any]] = {}
        self._diag_status_events: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        self._diag_full_events: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        self._schedule_test_running: set[str] = set()
        self._schedule_test_results: dict[str, str] = {}
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
        refresh_thread = threading.Thread(
            target=self._telemetry_refresh_loop,
            name="neo-telemetry-refresh",
            daemon=True,
        )
        refresh_thread.start()
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
            with self._suppress_lock:
                self._suppress_until.pop(serial, None)
            self._last_full_status.pop(serial, None)
            self._last_getall_request.pop(serial, None)
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

        if message_type in ("status-change", "cmd-response"):
            _LOGGER.debug(
                "Raw NEO MQTT RX topic=%s bytes=%d payload=%s",
                _safe_neo_topic(topic),
                len(payload_bytes),
                _safe_mqtt_preview(payload_bytes),
            )

        if message_type == "cmd-response":
            _LOGGER.debug(
                "Command response from NEO %s (%d bytes): %r",
                serial,
                len(payload_bytes),
                _safe_mqtt_preview(payload_bytes),
            )
            try:
                response_payload = json.loads(payload_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                response_payload = None
            if isinstance(response_payload, dict):
                correlation_id = str(response_payload.get("correlationId") or "")
                if correlation_id:
                    with self._diag_condition:
                        self._diag_cmd_responses[(serial, correlation_id)] = deepcopy(response_payload)
                        self._diag_condition.notify_all()
            return

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
            with self._diag_condition:
                events = self._diag_full_events.setdefault(serial, [])
                events.append((time.monotonic(), deepcopy(body)))
                del events[:-20]
                self._diag_condition.notify_all()
            if self._is_command_settling(serial):
                _LOGGER.debug(
                    "NEO %s full-status suppressed during %.1fs command settling window",
                    serial,
                    _COMMAND_SETTLE_SECONDS,
                )
                return
            self._states[serial] = body
            self._last_full_status[serial] = time.monotonic()
            self._publish_device(serial)
            return

        if message_type == "status-change":
            body = extract_event(payload)
            if body is None:
                return
            changed_fields = _debug_change_fields(body)
            _LOGGER.debug(
                "NEO %s status-change received (%d keys): %s",
                serial,
                len(body),
                ", ".join(changed_fields) if changed_fields else "<none>",
            )
            with self._diag_condition:
                events = self._diag_status_events.setdefault(serial, [])
                events.append((time.monotonic(), deepcopy(body)))
                del events[:-50]
                self._diag_condition.notify_all()
            if serial not in self._states:
                _LOGGER.info("NEO %s status-change arrived before full-status; requesting getAll", serial)
                self._request_get_all(serial)
                return
            if self._is_command_settling(serial):
                _LOGGER.debug(
                    "NEO %s status-change suppressed during %.1fs command settling window",
                    serial,
                    _COMMAND_SETTLE_SECONDS,
                )
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
                if command_name == "schedule_endtime_test":
                    if text.upper() not in ("PRESS", "RUN", "ON"):
                        raise ValueError("schedule EndTime test expects PRESS")
                    self._start_schedule_endtime_test(serial, user_id)
                    return
                command = self._build_system_command(state, command_name, text)
        except (ValueError, TypeError, IndexError) as exc:
            _LOGGER.warning("Invalid HA command %s: %s", topic, exc)
            return

        if command is not None:
            self._send_command(serial, user_id, command)
            self._begin_command_settle(serial, command)

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

        if command_name in ("away_heat_setpoint", "away_cool_setpoint"):
            value = float(text)
            suffix = "Heat" if command_name == "away_heat_setpoint" else "Cool"
            path = f"NV_SystemSettings.AwayMode.TemperatureSetpoint_{suffix}_oC"
            return {"command": {path: value, "type": "set-settings"}}

        if command_name == "schedule":
            requested = text.upper()
            if requested not in ("ON", "OFF"):
                raise ValueError("schedule command must be ON or OFF")

            schedule = state.get("NV_Schedule")
            if not isinstance(schedule, dict):
                raise ValueError("no learned NV_Schedule state; refusing schedule write")

            events = schedule.get("Events")
            if not isinstance(events, list) or not events:
                raise ValueError("no learned NV_Schedule.Events; refusing schedule write")

            enabled = requested == "ON"
            cmd: dict[str, Any] = {"type": "set-settings"}
            for index, event in enumerate(events):
                if not isinstance(event, dict) or "Enabled" not in event:
                    raise ValueError(
                        f"NV_Schedule.Events[{index}] has no Enabled field; refusing schedule write"
                    )
                cmd[f"NV_Schedule.Events[{index}].Enabled"] = enabled

            _LOGGER.info(
                "NEO Schedule write: setting %d learned event(s) Enabled=%s using NEO Connect property paths",
                len(events),
                enabled,
            )
            return {"command": cmd}

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
            enabled = text.lower() != "off"
            return {
                "command": {
                    f"UserAirconSettings.EnabledZones[{zone_index}]": enabled,
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

        if command_name == "airflow":
            value = float(text)
            return {
                "command": {
                    f"RemoteZoneInfo[{zone_index}].AirflowSetpoint": value,
                    "type": "set-settings",
                }
            }

        if command_name == "name":
            value = text.strip()
            if not value:
                raise ValueError("zone name cannot be empty")
            return {
                "command": {
                    f"RemoteZoneInfo[{zone_index}].NV_Title": value,
                    "type": "set-settings",
                }
            }

        return None

    @staticmethod
    def _schedule_endtime_from_state(state: dict[str, Any]) -> str | None:
        schedule = state.get("NV_Schedule")
        if not isinstance(schedule, dict):
            return None
        events = schedule.get("Events")
        if not isinstance(events, list) or not events or not isinstance(events[0], dict):
            return None
        value = events[0].get("EndTime")
        return str(value) if value is not None else None

    @staticmethod
    def _schedule_endtime_from_change(body: dict[str, Any]) -> str | None:
        direct = body.get("NV_Schedule.Events[0].EndTime")
        if direct is not None:
            return str(direct)
        events = body.get("NV_Schedule.Events")
        if isinstance(events, list) and events and isinstance(events[0], dict):
            value = events[0].get("EndTime")
            if value is not None:
                return str(value)
        return HomeAssistantBridge._schedule_endtime_from_state(body)

    @staticmethod
    def _schedule_test_time(original: str) -> str:
        match = re.fullmatch(r"T(\d{2}):(\d{2})(?::(\d{2}))?", original)
        if not match:
            raise ValueError(f"unsupported EndTime format {original!r}")
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(f"invalid EndTime {original!r}")
        total = (hour * 60 + minute + 5) % (24 * 60)
        suffix = f":{match.group(3)}" if match.group(3) is not None else ""
        return f"T{total // 60:02d}:{total % 60:02d}{suffix}"

    def _set_schedule_test_result(self, serial: str, result: str) -> None:
        with self._diag_condition:
            self._schedule_test_results[serial] = result
        self._publish_device(serial)

    def _start_schedule_endtime_test(self, serial: str, user_id: str) -> None:
        with self._diag_condition:
            if serial in self._schedule_test_running:
                _LOGGER.warning("NEO %s Schedule EndTime self-test already running", serial)
                return
            self._schedule_test_running.add(serial)
            self._schedule_test_results[serial] = "RUNNING"
        self._publish_device(serial)
        thread = threading.Thread(
            target=self._run_schedule_endtime_test,
            args=(serial, user_id),
            name=f"schedule-endtime-test-{serial}",
            daemon=True,
        )
        thread.start()

    def _wait_diag_response(
        self, serial: str, correlation_id: str, timeout: float = 4.0
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        key = (serial, correlation_id)
        with self._diag_condition:
            while True:
                response = self._diag_cmd_responses.pop(key, None)
                if response is not None:
                    return response
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._diag_condition.wait(remaining)

    def _wait_diag_endtime(
        self,
        serial: str,
        expected: str,
        *,
        full_status: bool,
        since: float,
        timeout: float = 4.0,
    ) -> bool:
        deadline = time.monotonic() + timeout
        store = self._diag_full_events if full_status else self._diag_status_events
        extractor = (
            self._schedule_endtime_from_state
            if full_status
            else self._schedule_endtime_from_change
        )
        with self._diag_condition:
            while True:
                for timestamp, body in store.get(serial, []):
                    if timestamp >= since and extractor(body) == expected:
                        return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._diag_condition.wait(remaining)

    @staticmethod
    def _diag_ack_matches(
        response: dict[str, Any] | None, path: str, expected: Any
    ) -> bool:
        if not isinstance(response, dict):
            return False
        command_response = response.get("commandResponse")
        if not isinstance(command_response, dict) or command_response.get("type") != "ack":
            return False
        value = command_response.get("value")
        return isinstance(value, dict) and value.get(path) == expected

    @staticmethod
    def _diag_getall_ack(response: dict[str, Any] | None) -> bool:
        if not isinstance(response, dict):
            return False
        command_response = response.get("commandResponse")
        if not isinstance(command_response, dict) or command_response.get("type") != "ack":
            return False
        value = command_response.get("value")
        return isinstance(value, dict) and value.get("getAll") is True

    def _run_schedule_endtime_test(self, serial: str, user_id: str) -> None:
        path = "NV_Schedule.Events[0].EndTime"
        failures: list[str] = []
        original: str | None = None
        test_value: str | None = None

        try:
            state = self._states.get(serial)
            if not isinstance(state, dict):
                raise ValueError("no current NEO state")
            original = self._schedule_endtime_from_state(state)
            if original is None:
                raise ValueError("NV_Schedule.Events[0].EndTime not present")
            test_value = self._schedule_test_time(original)

            _LOGGER.warning(
                "NEO %s Schedule EndTime SELF-TEST START original=%s test=%s",
                serial,
                original,
                test_value,
            )

            write_started = time.monotonic()
            write_corr = f"HA_DIAG/endtime-write/{uuid.uuid4()}"
            self._send_command(
                serial,
                user_id,
                {"command": {"type": "set-settings", path: test_value}},
                correlation_id=write_corr,
            )
            write_ack = self._diag_ack_matches(
                self._wait_diag_response(serial, write_corr), path, test_value
            )
            _LOGGER.warning(
                "NEO %s Schedule EndTime TEST write ACK: %s",
                serial,
                "PASS" if write_ack else "FAIL",
            )
            if not write_ack:
                failures.append("write_ack")

            status_ok = self._wait_diag_endtime(
                serial, test_value, full_status=False, since=write_started
            )
            _LOGGER.warning(
                "NEO %s Schedule EndTime TEST status-change: %s",
                serial,
                "PASS" if status_ok else "FAIL",
            )
            if not status_ok:
                failures.append("status_change")

            getall_started = time.monotonic()
            getall_corr = f"HA_DIAG/endtime-getall/{uuid.uuid4()}"
            self._send_command(
                serial,
                user_id,
                {"command": {"type": "getAll"}},
                correlation_id=getall_corr,
            )
            getall_ack = self._diag_getall_ack(
                self._wait_diag_response(serial, getall_corr)
            )
            persisted = self._wait_diag_endtime(
                serial, test_value, full_status=True, since=getall_started
            )
            _LOGGER.warning(
                "NEO %s Schedule EndTime TEST getAll ACK=%s persistence=%s",
                serial,
                "PASS" if getall_ack else "FAIL",
                "PASS" if persisted else "FAIL",
            )
            if not getall_ack:
                failures.append("getall_ack")
            if not persisted:
                failures.append("persistence")

        except Exception as exc:
            failures.append(f"test_error:{exc}")
            _LOGGER.exception("NEO %s Schedule EndTime self-test error", serial)

        finally:
            restore_ok = False
            if original is not None:
                try:
                    restore_started = time.monotonic()
                    restore_corr = f"HA_DIAG/endtime-restore/{uuid.uuid4()}"
                    self._send_command(
                        serial,
                        user_id,
                        {"command": {"type": "set-settings", path: original}},
                        correlation_id=restore_corr,
                    )
                    restore_ack = self._diag_ack_matches(
                        self._wait_diag_response(serial, restore_corr), path, original
                    )
                    restore_status = self._wait_diag_endtime(
                        serial, original, full_status=False, since=restore_started
                    )

                    restore_getall_started = time.monotonic()
                    restore_getall_corr = f"HA_DIAG/endtime-restore-getall/{uuid.uuid4()}"
                    self._send_command(
                        serial,
                        user_id,
                        {"command": {"type": "getAll"}},
                        correlation_id=restore_getall_corr,
                    )
                    restore_getall_ack = self._diag_getall_ack(
                        self._wait_diag_response(serial, restore_getall_corr)
                    )
                    restore_persisted = self._wait_diag_endtime(
                        serial,
                        original,
                        full_status=True,
                        since=restore_getall_started,
                    )
                    restore_ok = (
                        restore_ack
                        and restore_status
                        and restore_getall_ack
                        and restore_persisted
                    )
                    _LOGGER.warning(
                        "NEO %s Schedule EndTime RESTORE ACK=%s status-change=%s getAll_ACK=%s persistence=%s",
                        serial,
                        "PASS" if restore_ack else "FAIL",
                        "PASS" if restore_status else "FAIL",
                        "PASS" if restore_getall_ack else "FAIL",
                        "PASS" if restore_persisted else "FAIL",
                    )
                except Exception:
                    _LOGGER.exception(
                        "NEO %s Schedule EndTime RESTORE raised an exception", serial
                    )

            if not restore_ok:
                failures.append("RESTORE_FAILED")

            result = "PASS" if not failures else "FAIL: " + ",".join(failures)
            _LOGGER.warning(
                "NEO %s Schedule EndTime SELF-TEST RESULT: %s",
                serial,
                result,
            )
            with self._diag_condition:
                self._schedule_test_running.discard(serial)
            self._set_schedule_test_result(serial, result)

    def _begin_command_settle(self, serial: str, command: dict[str, Any]) -> None:
        """Publish the requested state optimistically and ignore stale echoes briefly."""
        state = self._states.get(serial)
        body = command.get("command")
        if state is None or not isinstance(body, dict):
            return

        changed_paths: list[str] = []
        schedule_enabled: bool | None = None
        for key, value in body.items():
            if key == "type":
                continue
            set_path(state, key, value)
            changed_paths.append(key)
            if re.fullmatch(r"NV_Schedule\.Events\[\d+\]\.Enabled", key):
                schedule_enabled = bool(value)

        # NEO Connect toggles schedule events individually. The controller then
        # derives NV_Schedule.Enabled, which is the value exposed to HA. Mirror
        # that derived master state during the settling window to prevent the
        # Schedule switch bouncing back to its stale pre-command state.
        if schedule_enabled is not None:
            set_path(state, "NV_Schedule.Enabled", schedule_enabled)
            changed_paths.append("NV_Schedule.Enabled")
            _LOGGER.debug(
                "NEO %s Schedule optimistic master state=%s",
                serial,
                schedule_enabled,
            )

        if not changed_paths:
            return

        expiry = time.monotonic() + _COMMAND_SETTLE_SECONDS
        with self._suppress_lock:
            self._suppress_until[serial] = expiry

        _LOGGER.debug(
            "NEO %s optimistic command state applied (%s); suppressing native state for %.1fs",
            serial,
            ", ".join(changed_paths),
            _COMMAND_SETTLE_SECONDS,
        )
        self._publish_device(serial)

        timer = threading.Timer(
            _COMMAND_SETTLE_SECONDS,
            self._finish_command_settle,
            args=(serial, expiry),
        )
        timer.daemon = True
        timer.start()

    def _is_command_settling(self, serial: str) -> bool:
        with self._suppress_lock:
            expiry = self._suppress_until.get(serial)
            return expiry is not None and expiry > time.monotonic()

    def _finish_command_settle(self, serial: str, expiry: float) -> None:
        with self._suppress_lock:
            current = self._suppress_until.get(serial)
            if current != expiry:
                return
            self._suppress_until.pop(serial, None)

        if not self._connection_state.get(serial, False):
            return

        _LOGGER.debug(
            "NEO %s command settling window expired; requesting canonical full state",
            serial,
        )
        self._request_get_all(serial)

    def _send_command(
        self,
        serial: str,
        user_id: str,
        command: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> str:
        command = deepcopy(command)
        correlation_id = correlation_id or f"HA_LOCAL/{uuid.uuid4()}"
        command["correlationId"] = correlation_id
        command["OptOutOfLogging"] = True
        topic = f"actron-cloud/{user_id}/neo/{serial}/app/cmd"
        payload = json.dumps(command, separators=(",", ":"))
        _LOGGER.debug(
            "Raw NEO MQTT TX topic=%s bytes=%d payload=%s",
            _safe_neo_topic(topic),
            len(payload.encode("utf-8")),
            _safe_mqtt_preview(payload.encode("utf-8")),
        )
        self._client.publish(topic, payload, qos=0)
        return correlation_id

    def _request_get_all(self, serial: str, *, periodic: bool = False) -> None:
        user_id = self._user_ids.get(serial)
        if user_id:
            self._last_getall_request[serial] = time.monotonic()
            if periodic:
                _LOGGER.debug("Periodic live-state refresh for NEO %s", serial)
            else:
                _LOGGER.info("Requesting full NEO state from %s with getAll", serial)
            self._send_command(serial, user_id, {"command": {"type": "getAll"}})

    def _telemetry_refresh_loop(self) -> None:
        """Bound live telemetry staleness while keeping idle traffic modest.

        NEO pushes many control changes immediately, but compressor telemetry is
        not guaranteed to be emitted on every status-change broadcast. Because
        this bridge is entirely local, periodically requesting getAll gives
        useful near-real-time power/speed data without involving Actron's cloud.
        """
        while True:
            time.sleep(_REFRESH_LOOP_SECONDS)
            now = time.monotonic()
            for serial, online in list(self._connection_state.items()):
                if not online or serial not in self._states:
                    continue
                if self._is_command_settling(serial):
                    continue

                raw = self._states[serial]
                settings = raw.get("UserAirconSettings") or {}
                live = raw.get("LiveAircon") or {}
                is_on = bool(settings.get("isOn", live.get("SystemOn", False)))
                interval = _ACTIVE_REFRESH_SECONDS if is_on else _IDLE_REFRESH_SECONDS
                last_status = self._last_full_status.get(serial, 0.0)
                last_request = self._last_getall_request.get(serial, 0.0)
                if now - max(last_status, last_request) >= interval:
                    self._request_get_all(serial, periodic=True)

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
        normalized["schedule_endtime_test_result"] = self._schedule_test_results.get(serial, "NOT RUN")
        _LOGGER.debug(
            "Publishing NEO %s state: power=%s mode=%s action=%s fan=%s power_w=%s speed=%s zones=%d",
            serial,
            normalized.get("power"),
            normalized.get("mode"),
            normalized.get("hvac_action"),
            normalized.get("fan_mode"),
            normalized.get("compressor_power"),
            normalized.get("compressor_speed"),
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
