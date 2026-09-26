#!/usr/bin/env python3

import copy

import main
from full_bridge import FullActronQueBridge, _as_bool, _as_number


class ActronQueLocalBridge(FullActronQueBridge):
    """Polished Home Assistant UI for the local QUE bridge."""

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        super().on_mqtt_connect(client, userdata, flags, reason_code, properties)
        if reason_code != 0:
            return

        self.mqtt.subscribe(f"{self.topic_prefix}/zone/+/mode/set", qos=1)
        self._clear_separate_setpoint_numbers()

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", "replace").strip().lower()

        prefix = f"{self.topic_prefix}/zone/"
        if topic.startswith(prefix) and topic.endswith("/mode/set"):
            try:
                middle = topic[len(prefix) : -len("/mode/set")]
                zone_number = int(middle)
                if zone_number < 1:
                    raise ValueError("zone number must be >= 1")

                if payload == "off":
                    enabled = False
                elif payload in ("auto", "cool", "heat", "fan_only", "on"):
                    # QUE zones follow the system HVAC mode. Selecting any active
                    # climate mode means enable this zone, exactly as the cloud add-on.
                    enabled = True
                else:
                    main.LOG.warning("Ignoring invalid zone HVAC mode: %r", payload)
                    return

                self._send_changes(
                    {f"UserAirconSettings.EnabledZones[{zone_number - 1}]": enabled}
                )
                return
            except Exception as exc:
                main.LOG.error("Zone mode command failed for %s: %s", topic, exc)
                return

        super().on_mqtt_message(client, userdata, msg)

    def _clear_discovery(self, domain: str, object_id: str) -> None:
        topic = (
            f"{self.discovery_prefix}/{domain}/"
            f"hass_actronque_local/{object_id}/config"
        )
        self.mqtt_publish(topic, b"", retain=True)

    def _clear_separate_setpoint_numbers(self) -> None:
        # v0.2.0 exposed heat/cool setpoints as separate Number entities.
        # The climate entity already supports a proper lower/upper target range,
        # so remove those retained discoveries to match the cloud add-on UI.
        self._clear_discovery("number", "heating_setpoint")
        self._clear_discovery("number", "cooling_setpoint")

        for number in range(1, 9):
            self._clear_discovery("number", f"zone_{number}_heating_setpoint")
            self._clear_discovery("number", f"zone_{number}_cooling_setpoint")

    def publish_discovery(self):
        super().publish_discovery()
        if not self.mqtt_connected or not self.state:
            return

        # Remove v0.2.0's standalone setpoint controls after the base discovery
        # has run, then expose one range-style climate entity per real zone.
        self._clear_separate_setpoint_numbers()
        self._publish_zone_climates()

        # Give the main climate entity the same useful display name as the device.
        p = self.topic_prefix
        self.publish_discovery_entity(
            "climate",
            "climate",
            {
                "name": f"Actron QUE Local ({self.system_name})",
                "mode_command_topic": f"{p}/climate/mode/set",
                "mode_state_topic": f"{p}/climate/mode/state",
                "fan_mode_command_topic": f"{p}/climate/fan/set",
                "fan_mode_state_topic": f"{p}/climate/fan/state",
                "temperature_high_command_topic": f"{p}/climate/temperature/high/set",
                "temperature_high_state_topic": f"{p}/climate/temperature/high/state",
                "temperature_low_command_topic": f"{p}/climate/temperature/low/set",
                "temperature_low_state_topic": f"{p}/climate/temperature/low/state",
                "current_temperature_topic": f"{p}/indoor_temperature/state",
                "action_topic": f"{p}/climate/action/state",
                "modes": ["off", "auto", "cool", "heat", "fan_only"],
                "fan_modes": ["auto", "low", "medium", "high"],
                "min_temp": 10,
                "max_temp": 32,
                "temp_step": 0.5,
                "temperature_unit": "C",
                **self._availability(),
            },
        )

    def _publish_zone_climates(self) -> None:
        with self.state_lock:
            zones = copy.deepcopy(self.state.get("RemoteZoneInfo", []))

        if not isinstance(zones, list):
            return

        p = self.topic_prefix
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict) or not _as_bool(zone.get("NV_Exists")):
                continue

            number = index + 1
            title = str(zone.get("NV_Title") or f"Zone {number}").strip()

            self.publish_discovery_entity(
                "climate",
                f"zone_{number}_climate",
                {
                    "name": title,
                    "mode_command_topic": f"{p}/zone/{number}/mode/set",
                    "mode_state_topic": f"{p}/zone/{number}/mode/state",
                    "temperature_high_command_topic": f"{p}/zone/{number}/temperature/high/set",
                    "temperature_high_state_topic": f"{p}/zone/{number}/temperature/high/state",
                    "temperature_low_command_topic": f"{p}/zone/{number}/temperature/low/set",
                    "temperature_low_state_topic": f"{p}/zone/{number}/temperature/low/state",
                    "current_temperature_topic": f"{p}/zone/{number}/temperature/state",
                    "action_topic": f"{p}/zone/{number}/action/state",
                    "modes": ["off", "auto", "cool", "heat", "fan_only"],
                    "min_temp": 10,
                    "max_temp": 32,
                    "temp_step": 0.5,
                    "temperature_unit": "C",
                    **self._availability(),
                },
            )

    def _publish_value(self, topic: str, value):
        """Round live numeric values to match the cloud add-on presentation."""
        number = _as_number(value)
        if number is not None:
            integer_topics = (
                "/fan_pwm/state",
                "/fan_rpm/state",
                "/battery/state",
                "/rssi/state",
            )
            one_decimal_topics = (
                "/temperature/state",
                "/temperature/low/state",
                "/temperature/high/state",
                "/indoor_temperature/state",
                "/outdoor_temperature/state",
                "/humidity/state",
                "/compressor_capacity/state",
                "/compressor_power/state",
                "/filter_runtime/state",
                "/position/state",
            )

            if topic.endswith(integer_topics):
                value = int(round(number))
            elif topic.endswith("/coil_inlet_temperature/state"):
                value = round(number, 2)
            elif topic.endswith(one_decimal_topics):
                value = round(number, 1)

        super()._publish_value(topic, value)

    def publish_current_state(self):
        super().publish_current_state()

        with self.state_lock:
            state = copy.deepcopy(self.state)

        if not state:
            return

        settings = state.get("UserAirconSettings", {})
        live = state.get("LiveAircon", {})
        zones = state.get("RemoteZoneInfo", [])

        if not isinstance(settings, dict):
            settings = {}
        if not isinstance(live, dict):
            live = {}
        if not isinstance(zones, list):
            zones = []

        enabled = settings.get("EnabledZones", [])
        if not isinstance(enabled, list):
            enabled = []

        system_on = _as_bool(settings.get("isOn"))
        raw_mode = str(settings.get("Mode", "")).upper()
        active_mode = self.QUE_TO_MODE.get(raw_mode, "auto")
        action = self._climate_action(system_on, live.get("CompressorMode"))

        p = self.topic_prefix
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict) or not _as_bool(zone.get("NV_Exists")):
                continue

            number = index + 1
            zone_enabled = _as_bool(enabled[index]) if index < len(enabled) else False
            zone_mode = active_mode if zone_enabled else "off"
            zone_action = action if zone_enabled else "off"

            self._publish_value(f"{p}/zone/{number}/mode/state", zone_mode)
            self._publish_value(f"{p}/zone/{number}/action/state", zone_action)


if __name__ == "__main__":
    ActronQueLocalBridge().run()
