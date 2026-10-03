"""Home Assistant MQTT Discovery publishing."""

from __future__ import annotations

import json
from typing import Any

import paho.mqtt.client as mqtt

from config import DISCOVERY_PREFIX, TOPIC_PREFIX


def _publish(client: mqtt.Client, component: str, object_id: str, payload: dict[str, Any]) -> None:
    topic = f"{DISCOVERY_PREFIX}/{component}/{object_id}/config"
    client.publish(topic, json.dumps(payload, separators=(",", ":"), allow_nan=False), retain=True)


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
        "temperature_state_topic": state_topic,
        "temperature_state_template": "{{ value_json.target_temperature }}",
        "temperature_command_topic": f"{base}/set/temperature",
        "current_temperature_topic": state_topic,
        "current_temperature_template": "{{ value_json.current_temperature }}",
        "fan_mode_state_topic": state_topic,
        "fan_mode_state_template": "{{ value_json.fan_mode }}",
        "fan_mode_command_topic": f"{base}/set/fan_mode",
        "modes": state["supported_modes"],
        "fan_modes": state["fan_modes"],
        "min_temp": state["min_temp"],
        "max_temp": state["max_temp"],
        "temp_step": 0.5,
        "temperature_unit": "C",
    }
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

    sensors = {
        "outdoor_temperature": ("Outdoor Temperature", "°C", "temperature"),
        "humidity": ("Humidity", "%", "humidity"),
        "compressor_power": ("Compressor Power", "W", "power"),
        "compressor_speed": ("Compressor Speed", None, None),
    }
    for key, (name, unit, device_class) in sensors.items():
        payload = {
            "name": name,
            "unique_id": f"actronneo_{serial}_{key}",
            "device": device,
            "availability_topic": availability,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.{key} }}}}",
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if device_class:
            payload["device_class"] = device_class
        _publish(client, "sensor", f"actronneo_{serial}_{key}", payload)

    binaries = {
        "clean_filter": ("Clean Filter", "problem"),
        "defrosting": ("Defrosting", None),
    }
    for key, (name, device_class) in binaries.items():
        payload = {
            "name": name,
            "unique_id": f"actronneo_{serial}_{key}",
            "device": device,
            "availability_topic": availability,
            "state_topic": state_topic,
            "value_template": f"{{{{ 'ON' if value_json.{key} else 'OFF' }}}}",
            "payload_on": "ON",
            "payload_off": "OFF",
        }
        if device_class:
            payload["device_class"] = device_class
        _publish(client, "binary_sensor", f"actronneo_{serial}_{key}", payload)

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
