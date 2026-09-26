#!/usr/bin/env python3

import re
from typing import Any, Dict

import main


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]", "_", str(value or "").lower()).strip("_")


class LocalActronQueBridge(main.ActronQueBridge):
    """Local QUE bridge presented as a drop-in replacement for hass-actronque."""

    LEGACY_LOCAL_DISCOVERY_ENTITIES = (
        ("binary_sensor", "walllink_connected"),
        ("binary_sensor", "aircon_on"),
        ("sensor", "mode"),
        ("sensor", "fan_mode"),
        ("switch", "quiet_mode"),
        ("sensor", "system_name"),
        ("sensor", "master_serial"),
    )

    ENTITY_ICONS = {
        ("switch", "quiet_mode"): "mdi:volume-off",
        ("sensor", "compressor_mode"): "mdi:engine-outline",
        ("sensor", "fan_mode"): "mdi:fan",
        ("sensor", "mode"): "mdi:thermostat",
        ("sensor", "master_serial"): "mdi:identifier",
        ("sensor", "system_name"): "mdi:home-outline",
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
            "name": f"Actron QUE ({self.system_name})",
            "manufacturer": "Actron",
            "model": "Actron Que",
            "sw_version": self.master_fw,
        }

    def _default_entity_id(self, domain: str, object_id: str, config: Dict[str, Any]) -> str:
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
        """Return hass-actronque's unique_id where a cloud equivalent exists."""
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

    def publish_discovery_entity(self, domain: str, object_id: str, config: Dict[str, Any]):
        config = dict(config)
        config.setdefault("unique_id", self._cloud_unique_id(domain, object_id))
        config.setdefault("default_entity_id", self._default_entity_id(domain, object_id, config))

        icon = self.ENTITY_ICONS.get((domain, object_id))
        if icon:
            config.setdefault("icon", icon)

        # QUE uses 255 as an invalid/unknown sentinel for some wireless sensor
        # battery values. Keep the raw MQTT state intact, but present only valid
        # 0-100 percentages to Home Assistant so 255% cannot appear in the
        # device header.
        if domain == "sensor" and config.get("device_class") == "battery":
            config.setdefault(
                "value_template",
                "{% set v = value | float(-1) %}{{ v | round(0) | int if 0 <= v <= 100 else 'unknown' }}",
            )

        config.setdefault("device", self.device_info())

        topic = f"{self.discovery_prefix}/{domain}/hass_actronque_local/{object_id}/config"
        self.mqtt_publish(topic, config, retain=True)

    def clear_legacy_discovery(self):
        for domain, object_id in self.LEGACY_LOCAL_DISCOVERY_ENTITIES:
            for prefix in ("actronque_local", "hass_actronque_local"):
                topic = f"{self.discovery_prefix}/{domain}/{prefix}/{object_id}/config"
                self.mqtt_publish(topic, b"", retain=True)
        main.LOG.info("Cleared legacy local MQTT discovery entries")

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        super().on_mqtt_connect(client, userdata, flags, reason_code, properties)
        if reason_code == 0:
            self.clear_legacy_discovery()


if __name__ == "__main__":
    LocalActronQueBridge().run()
