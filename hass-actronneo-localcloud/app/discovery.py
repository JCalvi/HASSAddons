"""Home Assistant MQTT Discovery publishing."""

from __future__ import annotations

import json
import re
from typing import Any

import paho.mqtt.client as mqtt

from config import DISCOVERY_PREFIX, TOPIC_PREFIX


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "_", str(value or "").lower()).strip("_")


def _default_entity_id(component: str, object_id: str, payload: dict[str, Any]) -> str | None:
    """Build a deterministic entity ID from NEO serial and system name."""
    device = payload.get("device") or {}
    identifiers = device.get("identifiers") or []
    serial = ""
    for identifier in identifiers:
        text = str(identifier)
        if text.startswith("actronneo_"):
            serial = text[len("actronneo_") :]
            break
    if not serial:
        return None

    system_name = _slug(device.get("name"))
    serial_slug = _slug(serial)
    if not system_name or not serial_slug:
        return None

    base = f"{component}.actron_neo_{serial_slug}_{system_name}"
    prefix = f"actronneo_{serial}"
    if object_id == prefix:
        return base

    suffix = object_id
    if suffix.startswith(prefix + "_"):
        suffix = suffix[len(prefix) + 1 :]
    suffix = _slug(suffix)
    if not suffix:
        return base

    if component == "climate" and re.fullmatch(r"zone_\d+", suffix):
        zone_name = _slug(payload.get("name"))
        if zone_name:
            return f"{base}_{suffix}_{zone_name}"

    return f"{base}_{suffix}"


def _publish(client: mqtt.Client, component: str, object_id: str, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    default_entity_id = _default_entity_id(component, object_id, payload)
    if default_entity_id:
        payload["default_entity_id"] = default_entity_id
    topic = f"{DISCOVERY_PREFIX}/{component}/{object_id}/config"
    client.publish(topic, json.dumps(payload, separators=(",", ":"), allow_nan=False), retain=True)


def _state_sensor(
    client: mqtt.Client,
    *,
    serial: str,
    state_topic: str,
    availability: str,
    device: dict[str, Any],
    key: str,
    name: str,
    unit: str | None = None,
    device_class: str | None = None,
    icon: str | None = None,
    enabled_by_default: bool = True,
    diagnostic: bool = False,
) -> None:
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": f"actronneo_{serial}_{key}",
        "device": device,
        "availability_topic": availability,
        "state_topic": state_topic,
        "value_template": f"{{{{ value_json.{key} }}}}",
        "enabled_by_default": enabled_by_default,
    }
    if unit:
        payload["unit_of_measurement"] = unit
    if device_class:
        payload["device_class"] = device_class
    if icon:
        payload["icon"] = icon
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    _publish(client, "sensor", f"actronneo_{serial}_{key}", payload)


def _state_binary_sensor(
    client: mqtt.Client,
    *,
    serial: str,
    state_topic: str,
    availability: str,
    device: dict[str, Any],
    key: str,
    name: str,
    device_class: str | None = None,
    icon: str | None = None,
    enabled_by_default: bool = True,
    diagnostic: bool = False,
) -> None:
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": f"actronneo_{serial}_{key}",
        "device": device,
        "availability_topic": availability,
        "state_topic": state_topic,
        "value_template": f"{{{{ 'ON' if value_json.{key} else 'OFF' }}}}",
        "payload_on": "ON",
        "payload_off": "OFF",
        "enabled_by_default": enabled_by_default,
    }
    if device_class:
        payload["device_class"] = device_class
    if icon:
        payload["icon"] = icon
    if diagnostic:
        payload["entity_category"] = "diagnostic"
    _publish(client, "binary_sensor", f"actronneo_{serial}_{key}", payload)


def publish_discovery(client: mqtt.Client, serial: str, state: dict[str, Any]) -> None:
    base = f"{TOPIC_PREFIX}/{serial}"
    availability = f"{base}/availability"
    state_topic = f"{base}/state"
    device: dict[str, Any] = {
        "identifiers": [f"actronneo_{serial}"],
        "name": state["name"],
        "manufacturer": "ActronAir",
        "model": state.get("model") or "NEO",
    }

    firmware = str(state.get("firmware") or "").strip()
    if firmware:
        device["sw_version"] = firmware

    climate = {
        "name": state["name"],
        "unique_id": f"actronneo_{serial}_climate",
        "device": device,
        "availability_topic": availability,
        "payload_available": "online",
        "payload_not_available": "offline",
        "mode_state_topic": state_topic,
        "mode_state_template": "{{ value_json.mode }}",
        "mode_command_topic": f"{base}/set/mode",
        "action_topic": state_topic,
        "action_template": "{{ value_json.hvac_action }}",
        "temperature_state_topic": state_topic,
        "temperature_state_template": "{{ value_json.target_temperature }}",
        "temperature_command_topic": f"{base}/set/temperature",
        "current_temperature_topic": state_topic,
        "current_temperature_template": "{{ value_json.current_temperature }}",
        "modes": state["supported_modes"],
        "min_temp": state["min_temp"],
        "max_temp": state["max_temp"],
        "temp_step": 0.5,
        "temperature_unit": "C",
    }

    fan_mode = str(state.get("fan_mode") or "").strip()
    fan_modes = [str(item).strip() for item in state.get("fan_modes", []) if str(item).strip()]
    if fan_mode and fan_modes:
        climate.update(
            {
                "fan_mode_state_topic": state_topic,
                "fan_mode_state_template": "{{ value_json.fan_mode }}",
                "fan_mode_command_topic": f"{base}/set/fan_mode",
                "fan_modes": fan_modes,
            }
        )

    _publish(client, "climate", f"actronneo_{serial}", climate)

    switches = {
        "quiet": ("Quiet Mode", "quiet"),
        "turbo": ("Turbo Mode", "turbo"),
        "away": ("Away Mode", "away"),
        "continuous_fan": ("Continuous Fan", "continuous_fan"),
        "schedule": ("Schedule", "schedule"),
    }
    for key, (name, value_key) in switches.items():
        payload = {
            "name": name,
            "unique_id": f"actronneo_{serial}_{key}",
            "device": device,
            "availability_topic": availability,
            "state_topic": state_topic,
            "value_template": f"{{{{ 'ON' if value_json.{value_key} else 'OFF' }}}}",
            "command_topic": f"{base}/set/{key}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
        }
        if key == "schedule":
            payload["icon"] = "mdi:calendar-clock"
        _publish(client, "switch", f"actronneo_{serial}_{key}", payload)

    schedule_test_button = {
        "name": "Schedule Write Probe",
        "unique_id": f"actronneo_{serial}_schedule_endtime_test",
        "device": device,
        "availability_topic": availability,
        "command_topic": f"{base}/set/schedule_endtime_test",
        "payload_press": "PRESS",
        "icon": "mdi:test-tube",
        "entity_category": "diagnostic",
        "enabled_by_default": True,
    }
    _publish(
        client,
        "button",
        f"actronneo_{serial}_schedule_endtime_test",
        schedule_test_button,
    )

    _state_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="schedule_endtime_test_result",
        name="Schedule Write Probe Result",
        icon="mdi:test-tube",
        enabled_by_default=True,
        diagnostic=True,
    )

    for key, name in (
        ("away_heat_setpoint", "Away Heating Setpoint"),
        ("away_cool_setpoint", "Away Cooling Setpoint"),
    ):
        if state.get(key) is not None:
            payload = {
                "name": name,
                "unique_id": f"actronneo_{serial}_{key}",
                "device": device,
                "availability_topic": availability,
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "command_topic": f"{base}/set/{key}",
                "min": state["min_temp"],
                "max": state["max_temp"],
                "step": 0.5,
                "unit_of_measurement": "°C",
                "device_class": "temperature",
                "mode": "box",
            }
            _publish(client, "number", f"actronneo_{serial}_{key}", payload)

    # Everyday sensors remain enabled by default.
    _state_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="outdoor_temperature",
        name="Outdoor Temperature",
        unit="°C",
        device_class="temperature",
    )
    _state_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="humidity",
        name="Humidity",
        unit="%",
        device_class="humidity",
    )
    _state_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="compressor_power",
        name="Compressor Power",
        unit="W",
        device_class="power",
    )
    _state_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="compressor_speed",
        name="Compressor Speed",
        unit="%",
        icon="mdi:speedometer",
    )

    _state_binary_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="clean_filter",
        name="Clean Filter",
        device_class="problem",
    )
    _state_binary_sensor(
        client,
        serial=serial,
        state_topic=state_topic,
        availability=availability,
        device=device,
        key="defrosting",
        name="Defrosting",
    )

    # Engineering/diagnostic entities are intentionally disabled by default so
    # the normal device page stays compact. Users can enable whichever values
    # they want from the Home Assistant device/entity page.
    diagnostic_sensors = [
        ("compressor_capacity", "Compressor Capacity", "%", None, "mdi:gauge"),
        ("indoor_fan_rpm", "Indoor Fan RPM", "rpm", None, "mdi:fan"),
        ("indoor_fan_pwm", "Indoor Fan PWM", "%", None, "mdi:fan"),
        ("coil_inlet_temperature", "Coil Inlet Temperature", "°C", "temperature", "mdi:thermometer"),
        ("outdoor_coil_temperature", "Outdoor Coil Temperature", "°C", "temperature", "mdi:thermometer"),
        ("discharge_temperature", "Discharge Temperature", "°C", "temperature", "mdi:thermometer"),
        ("suction_temperature", "Suction Temperature", "°C", "temperature", "mdi:thermometer"),
        ("drive_temperature", "Drive / VSD Temperature", "°C", "temperature", "mdi:thermometer"),
        ("wifi_signal", "Wi-Fi Signal", "dBm", "signal_strength", "mdi:wifi"),
        ("controller_uptime", "Controller Uptime", "s", "duration", "mdi:timer-outline"),
        ("mqtt_session_uptime", "MQTT Session Uptime", "s", "duration", "mdi:timer-outline"),
        ("mqtt_reconnect_count", "MQTT Reconnect Count", None, None, "mdi:connection"),
        ("vsd_comms_status", "VSD Communications Status", None, None, "mdi:connection"),
        ("error_code", "AC Error Code", None, None, "mdi:alert-circle-outline"),
        ("supply_voltage", "Supply Voltage", "V", "voltage", "mdi:flash"),
        ("supply_current", "Supply Current", "A", "current", "mdi:flash"),
        ("supply_power", "Supply Power", "W", "power", "mdi:flash"),
        ("eev_opening", "EEV Opening", "%", None, "mdi:valve"),
        ("superheat", "Superheat", "°C", "temperature", "mdi:thermometer"),
        ("indoor_firmware", "Indoor Unit Firmware", None, None, "mdi:chip"),
        ("outdoor_firmware", "Outdoor Unit Firmware", None, None, "mdi:chip"),
        ("outdoor_family", "Outdoor Unit Family", None, None, "mdi:air-conditioner"),
        ("system_capacity_kw", "System Capacity", "kW", None, "mdi:gauge"),
        ("wifi_firmware", "Wi-Fi Firmware", None, None, "mdi:chip"),
    ]
    for key, name, unit, device_class, icon in diagnostic_sensors:
        _state_sensor(
            client,
            serial=serial,
            state_topic=state_topic,
            availability=availability,
            device=device,
            key=key,
            name=name,
            unit=unit,
            device_class=device_class,
            icon=icon,
            enabled_by_default=False,
            diagnostic=True,
        )

    for key, name, device_class, icon in [
        ("compressor_running", "Compressor Running", "running", "mdi:engine"),
        ("lp_fault", "Low Pressure Fault", "problem", "mdi:alert"),
        ("hp_fault", "High Pressure Fault", "problem", "mdi:alert"),
    ]:
        _state_binary_sensor(
            client,
            serial=serial,
            state_topic=state_topic,
            availability=availability,
            device=device,
            key=key,
            name=name,
            device_class=device_class,
            icon=icon,
            enabled_by_default=False,
            diagnostic=True,
        )

    for zone in state["zones"]:
        idx = int(zone["id"])
        zone_base = f"{base}/zone/{idx}"
        zone_name = str(zone["name"])
        zone_climate = {
            "name": zone_name,
            "unique_id": f"actronneo_{serial}_zone_{idx}_climate",
            "device": device,
            "availability_topic": availability,
            "mode_state_topic": state_topic,
            "mode_state_template": f"{{{{ value_json.zones | selectattr('id','eq',{idx}) | map(attribute='mode') | first }}}}",
            "mode_command_topic": f"{zone_base}/set/mode",
            "temperature_state_topic": state_topic,
            "temperature_state_template": f"{{{{ value_json.zones | selectattr('id','eq',{idx}) | map(attribute='target_temperature') | first }}}}",
            "temperature_command_topic": f"{zone_base}/set/temperature",
            "current_temperature_topic": state_topic,
            "current_temperature_template": f"{{{{ value_json.zones | selectattr('id','eq',{idx}) | map(attribute='current_temperature') | first }}}}",
            "modes": state["supported_modes"],
            "min_temp": state["min_temp"],
            "max_temp": state["max_temp"],
            "temp_step": 0.5,
            "temperature_unit": "C",
        }
        _publish(client, "climate", f"actronneo_{serial}_zone_{idx}", zone_climate)

        if zone.get("airflow_setpoint") is not None:
            airflow = {
                "name": f"{zone_name} Airflow",
                "unique_id": f"actronneo_{serial}_zone_{idx}_airflow",
                "device": device,
                "availability_topic": availability,
                "state_topic": state_topic,
                "value_template": f"{{{{ value_json.zones | selectattr('id','eq',{idx}) | map(attribute='airflow_setpoint') | first }}}}",
                "command_topic": f"{zone_base}/set/airflow",
                "min": 0,
                "max": 100,
                "step": 5,
                "unit_of_measurement": "%",
                "mode": "slider",
                "enabled_by_default": not bool(zone.get("airflow_locked", False)),
            }
            _publish(client, "number", f"actronneo_{serial}_zone_{idx}_airflow", airflow)

        zone_name_control = {
            "name": f"{zone_name} Name",
            "unique_id": f"actronneo_{serial}_zone_{idx}_name",
            "device": device,
            "availability_topic": availability,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.zones | selectattr('id','eq',{idx}) | map(attribute='name') | first }}}}",
            "command_topic": f"{zone_base}/set/name",
            "icon": "mdi:rename-box",
        }
        _publish(client, "text", f"actronneo_{serial}_zone_{idx}_name", zone_name_control)

        humidity = {
            "name": f"{zone_name} Humidity",
            "unique_id": f"actronneo_{serial}_zone_{idx}_humidity",
            "device": device,
            "availability_topic": availability,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.zones | selectattr('id','eq',{idx}) | map(attribute='humidity') | first }}}}",
            "unit_of_measurement": "%",
            "device_class": "humidity",
        }
        _publish(client, "sensor", f"actronneo_{serial}_zone_{idx}_humidity", humidity)
