"""Home Assistant MQTT Discovery publishing."""

from __future__ import annotations

import json
from typing import Any

import paho.mqtt.client as mqtt

from config import DISCOVERY_PREFIX, TOPIC_PREFIX


def _publish(client: mqtt.Client, component: str, object_id: str, payload: dict[str, Any]) -> None:
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

    # Home Assistant's MQTT discovery schema requires device.sw_version to be
    # a string when present. Some NEO full-status payloads do not expose the
    # wall-controller firmware field used by normalize_state(), so omit the
    # key entirely until a non-empty firmware value is available.
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

    # Some NEO status snapshots omit UserAirconSettings.FanMode entirely. Do
    # not publish fan-mode discovery until a real current value exists; Home
    # Assistant otherwise rejects the empty state as an invalid fan mode. A
    # later status containing FanMode republishes discovery with fan controls.
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
        _publish(client, "switch", f"actronneo_{serial}_{key}", payload)

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
        ("compressor_capacity", "Compressor Capacity", "%", None),
        ("indoor_fan_rpm", "Indoor Fan RPM", "rpm", None),
        ("indoor_fan_pwm", "Indoor Fan PWM", "%", None),
        ("coil_inlet_temperature", "Coil Inlet Temperature", "°C", "temperature"),
        ("outdoor_coil_temperature", "Outdoor Coil Temperature", "°C", "temperature"),
        ("discharge_temperature", "Discharge Temperature", "°C", "temperature"),
        ("suction_temperature", "Suction Temperature", "°C", "temperature"),
        ("drive_temperature", "Drive / VSD Temperature", "°C", "temperature"),
        ("wifi_signal", "Wi-Fi Signal", "dBm", "signal_strength"),
        ("controller_uptime", "Controller Uptime", "s", "duration"),
        ("mqtt_session_uptime", "MQTT Session Uptime", "s", "duration"),
        ("mqtt_reconnect_count", "MQTT Reconnect Count", None, None),
        ("vsd_comms_status", "VSD Communications Status", None, None),
        ("error_code", "AC Error Code", None, None),
        ("supply_voltage", "Supply Voltage", "V", "voltage"),
        ("supply_current", "Supply Current", "A", "current"),
        ("supply_power", "Supply Power", "W", "power"),
        ("eev_opening", "EEV Opening", "%", None),
        ("superheat", "Superheat", "°C", "temperature"),
        ("indoor_firmware", "Indoor Unit Firmware", None, None),
        ("outdoor_firmware", "Outdoor Unit Firmware", None, None),
        ("outdoor_family", "Outdoor Unit Family", None, None),
        ("system_capacity_kw", "System Capacity", "kW", None),
        ("wifi_firmware", "Wi-Fi Firmware", None, None),
    ]
    for key, name, unit, device_class in diagnostic_sensors:
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
            enabled_by_default=False,
            diagnostic=True,
        )

    for key, name, device_class in [
        ("compressor_running", "Compressor Running", "running"),
        ("lp_fault", "Low Pressure Fault", "problem"),
        ("hp_fault", "High Pressure Fault", "problem"),
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
