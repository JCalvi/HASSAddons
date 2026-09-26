#!/usr/bin/env python3

from typing import Any, Dict

import main


class LocalActronQueBridge(main.ActronQueBridge):
    """Local QUE bridge with a device identity distinct from the cloud add-on."""

    LEGACY_DISCOVERY_ENTITIES = (
        ("binary_sensor", "walllink_connected"),
        ("binary_sensor", "aircon_on"),
        ("sensor", "mode"),
        ("sensor", "fan_mode"),
        ("switch", "quiet_mode"),
        ("sensor", "system_name"),
        ("sensor", "master_serial"),
    )

    def device_info(self):
        identifier_serial = (
            self.master_serial
            if self.master_serial != "unknown"
            else str(main.OPTIONS["serial"])
        )

        return {
            "identifiers": [f"actronque_local_{identifier_serial.lower()}"],
            "name": f"Actron QUE Local {self.system_name}",
            "manufacturer": "ActronAir",
            "model": "QUE Local",
            "sw_version": self.master_fw,
        }

    def publish_discovery_entity(
        self,
        domain: str,
        object_id: str,
        config: Dict[str, Any],
    ):
        config = dict(config)
        config.setdefault(
            "unique_id",
            f"actronque_local_{self.master_serial.lower()}_{object_id}",
        )
        config.setdefault("device", self.device_info())

        topic = (
            f"{self.discovery_prefix}/{domain}/"
            f"hass_actronque_local/{object_id}/config"
        )

        self.mqtt_publish(topic, config, retain=True)

    def clear_legacy_discovery(self):
        """Remove v0.1.0 discovery configs that shared the cloud device ID."""
        for domain, object_id in self.LEGACY_DISCOVERY_ENTITIES:
            topic = (
                f"{self.discovery_prefix}/{domain}/"
                f"actronque_local/{object_id}/config"
            )
            self.mqtt_publish(topic, b"", retain=True)

        main.LOG.info("Cleared legacy local MQTT discovery entries")

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        super().on_mqtt_connect(
            client,
            userdata,
            flags,
            reason_code,
            properties,
        )

        if reason_code == 0:
            self.clear_legacy_discovery()


if __name__ == "__main__":
    LocalActronQueBridge().run()
