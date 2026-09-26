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

    def _serial(self) -> str:
        return str(self.master_serial if self.master_serial != "unknown" else main.OPTIONS["serial"]).lower()

    def device_info(self):
        serial = self._serial()
        return {
            # Deliberately identical to hass-actronque so the local add-on can
            # replace it without requiring dashboard/automation entity changes.
            "identifiers": [f"actronque_{serial}"],
            "name": f"Actron QUE ({self.system_name})",
            "manufacturer": "Actron",
            "model": "Actron Que",
            "sw_version": self.master_fw,
        }

    def _default_entity_id(self, domain: str, object_id: str, config: Dict[str, Any]) -> str:
        serial = self._serial()
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

        match = re.fullmatch(r"zone_(\d+)_sensor_(.+)_(temperature|battery|rssi)", object_id)
        if match:
            return f"{base}_zone_{match.group(1)}_sensor_{_slug(match.group(2))}_{match.group(3)}"

        aliases = {
            "indoor_temperature": "temperature",
            "outdoor_temperature": "outdoor_temperature",
            "compressor_mode": "compressor",
            "filter_runtime": "fan_time_since_filter_cleaned",
            "clean_filter": "clean_filter",
        }
        suffix = aliases.get(object_id, object_id)
        return f"{base}_{suffix}"

    def publish_discovery_entity(self, domain: str, object_id: str, config: Dict[str, Any]):
        config = dict(config)
        config.setdefault("unique_id", f"{self._serial()}-local-{object_id}")
        config.setdefault("default_entity_id", self._default_entity_id(domain, object_id, config))
        config.setdefault("device", self.device_info())

        topic = f"{self.discovery_prefix}/{domain}/hass_actronque_local/{object_id}/config"
        self.mqtt_publish(topic, config, retain=True)

    def clear_legacy_discovery(self):
        # Remove discovery retained by earlier local versions. The new payloads
        # use cloud-compatible entity IDs, but their discovery topics remain
        # local so two publishers cannot overwrite each other's configs.
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
