#!/usr/bin/env python3

import re
from typing import Any, Dict

import main


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "_", str(value or "").lower()).strip("_")


class LocalActronQueBridge(main.ActronQueBridge):
    """Local QUE bridge presented as a drop-in replacement for hass-actronque."""

    ENTITY_ICONS = {
        ("switch", "quiet_mode"): "mdi:volume-off",
        ("sensor", "compressor_mode"): "mdi:engine-outline",
        ("sensor", "fan_mode"): "mdi:fan",
        ("sensor", "mode"): "mdi:thermostat",
        ("sensor", "master_serial"): "mdi:identifier",
        ("sensor", "system_name"): "mdi:home-outline",
        ("binary_sensor", "walllink_connected"): "mdi:lan-connect",
        ("binary_sensor", "aircon_on"): "mdi:air-conditioner",
    }

    def _serial_raw(self) -> str:
        return str(
            self.master_serial
            if self.master_serial != "unknown"
            else main.OPTIONS["serial"]
        )

    def _serial_entity(self) -> str:
        return self._serial_raw().lower()

    def device_info(self):
        serial = self._serial_raw()
        return {
            "identifiers": [f"actronque_{serial}"],
            "name": f"Actron QUE Local ({self.system_name})",
            "manufacturer": "Actron",
            "model": "Actron Que",
            "sw_version": self.master_fw,
        }

    def _default_entity_id(self, domain: str, object_id: str, config: Dict[str, Any]) -> str:
        """Canonical entity ID for every Local entity: <domain>.actronque_<serial>_..."""
        serial = self._serial_entity()
        base = f"{domain}.actronque_{serial}"

        if domain == "climate" and object_id == "climate":
            return base

        match = re.fullmatch(r"zone_(\d+)_climate", object_id)
        if match:
            return f"{base}_zone_{match.group(1)}_{_slug(config.get('name'))}"

        match = re.fullmatch(r"zone_(\d+)_enabled", object_id)
        if match:
            title = re.sub(r"\s+Enabled$", "", str(config.get("name", "")), flags=re.I)
            return f"{base}_zone_{match.group(1)}_{_slug(title)}"

        match = re.fullmatch(r"zone_(\d+)_temperature", object_id)
        if match:
            title = re.sub(r"\s+Temperature$", "", str(config.get("name", "")), flags=re.I)
            return f"{base}_zone_{match.group(1)}_{_slug(title)}_temperature"

        match = re.fullmatch(r"zone_(\d+)_position", object_id)
        if match:
            title = re.sub(r"\s+Damper Position$", "", str(config.get("name", "")), flags=re.I)
            return f"{base}_zone_{match.group(1)}_{_slug(title)}_damper_position"

        match = re.fullmatch(r"zone_(\d+)_sensor_(.+)_(temperature|battery|rssi)", object_id)
        if match:
            return f"{base}_zone_{match.group(1)}_sensor_{_slug(match.group(2))}_{match.group(3)}"

        aliases = {
            "indoor_temperature": "temperature",
            "outdoor_temperature": "outdoor_temperature",
            "compressor_mode": "compressor",
            "filter_runtime": "fan_time_since_filter_cleaned",
            "clean_filter": "clean_filter",
            "constant_fan": "constant_fan_mode",
        }
        suffix = aliases.get(object_id, object_id)
        return f"{base}_{suffix}"

    def _cloud_unique_id(self, domain: str, object_id: str) -> str:
        """Stable unique ID, matching hass-actronque where a cloud equivalent exists."""
        serial = self._serial_raw()

        fixed = {
            ("climate", "climate"): "AC",
            ("sensor", "humidity"): "Humidity",
            ("sensor", "indoor_temperature"): "Temperature",
            ("sensor", "outdoor_temperature"): "OutdoorTemperature",
            ("sensor", "compressor_capacity"): "CompressorCapacity",
            ("sensor", "compressor_power"): "CompressorPower",
            ("sensor", "coil_inlet_temperature"): "CoilInletTemperature",
            ("binary_sensor", "clean_filter"): "CleanFilter",
            ("sensor", "filter_runtime"): "FanTSFC",
            ("sensor", "fan_pwm"): "FanPWM",
            ("sensor", "fan_rpm"): "FanRPM",
            ("switch", "control_all_zones"): "ControlAllZones",
            ("switch", "away_mode"): "AwayMode",
            ("switch", "constant_fan"): "ConstantFanMode",
            ("switch", "quiet_mode"): "QuietMode",
        }
        suffix = fixed.get((domain, object_id))
        if suffix:
            return f"{serial}-{suffix}"

        match = re.fullmatch(r"zone_(\d+)_enabled", object_id)
        if domain == "switch" and match:
            return f"{serial}-z{match.group(1)}s"

        match = re.fullmatch(r"zone_(\d+)_temperature", object_id)
        if domain == "sensor" and match:
            return f"{serial}-z{match.group(1)}t"

        match = re.fullmatch(r"zone_(\d+)_position", object_id)
        if domain == "sensor" and match:
            return f"{serial}-z{match.group(1)}-position"

        match = re.fullmatch(r"zone_(\d+)_climate", object_id)
        if domain == "climate" and match:
            return f"{serial}-z{match.group(1)}-climate"

        return f"{serial}-local-{object_id}"

    def _battery_is_real(self, object_id: str) -> bool:
        match = re.fullmatch(r"zone_(\d+)_sensor_(.+)_battery", object_id)
        if not match:
            return True

        zone_index = int(match.group(1)) - 1
        sensor_slug = match.group(2)
        zones = self.state.get("RemoteZoneInfo", []) if isinstance(self.state, dict) else []
        if not isinstance(zones, list) or zone_index < 0 or zone_index >= len(zones):
            return False

        zone = zones[zone_index]
        sensors = zone.get("Sensors", {}) if isinstance(zone, dict) else {}
        if not isinstance(sensors, dict):
            return False

        for sensor_id, info in sensors.items():
            if _slug(sensor_id) != sensor_slug or not isinstance(info, dict):
                continue
            try:
                battery = float(info.get("Battery_pc"))
            except (TypeError, ValueError):
                return False
            return 0.0 <= battery <= 100.0

        return False

    def _identity_from_discovery_topic(self, topic: str):
        """Extract (domain, object_id) from per-entity HA MQTT discovery topics."""
        prefix = f"{self.discovery_prefix}/"
        if not topic.startswith(prefix) or not topic.endswith("/config"):
            return None
        parts = topic[len(prefix):].split("/")
        if len(parts) < 3:
            return None
        domain = parts[0]
        object_id = parts[-2]
        return domain, object_id

    def mqtt_publish(self, topic: str, payload: Any, retain: bool = False):
        """Enforce the serial identity scheme on every MQTT discovery payload.

        2026.9.1 routed the base entities through publish_discovery_entity().  The
        2026.9.2 base bridge briefly published seven entities directly, bypassing
        Local's identity/icon mapping.  Normalising at the MQTT discovery boundary
        makes both base and Full bridge discovery follow the same rules.
        """
        identity = self._identity_from_discovery_topic(topic)
        if identity and isinstance(payload, dict):
            domain, object_id = identity
            payload = dict(payload)
            payload["unique_id"] = self._cloud_unique_id(domain, object_id)
            payload["default_entity_id"] = self._default_entity_id(domain, object_id, payload)
            # object_id as a discovery payload option is deprecated in modern HA;
            # default_entity_id is the supported way to seed the entity registry ID.
            payload.pop("object_id", None)
            payload["device"] = self.device_info()
            icon = self.ENTITY_ICONS.get((domain, object_id))
            if icon:
                payload["icon"] = icon
        return super().mqtt_publish(topic, payload, retain=retain)

    def publish_discovery_entity(self, domain: str, object_id: str, config: Dict[str, Any]):
        config = dict(config)
        topic = f"{self.discovery_prefix}/{domain}/hass_actronque_local/{object_id}/config"

        if domain == "switch" and re.fullmatch(r"zone_\d+_enabled", object_id):
            self.mqtt_publish(topic, b"", retain=True)
            return

        if domain == "sensor" and (
            re.fullmatch(r"zone_\d+_temperature", object_id)
            or re.fullmatch(r"zone_\d+_sensor_.+_temperature", object_id)
        ):
            self.mqtt_publish(topic, b"", retain=True)
            return

        if domain == "sensor" and object_id.endswith("_battery") and not self._battery_is_real(object_id):
            self.mqtt_publish(topic, b"", retain=True)
            return

        config["unique_id"] = self._cloud_unique_id(domain, object_id)
        config["default_entity_id"] = self._default_entity_id(domain, object_id, config)

        icon = self.ENTITY_ICONS.get((domain, object_id))
        if icon:
            config["icon"] = icon

        config["device"] = self.device_info()
        self.mqtt_publish(topic, config, retain=True)


if __name__ == "__main__":
    LocalActronQueBridge().run()
