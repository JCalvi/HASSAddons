#!/usr/bin/env python3

import copy
import json
import re

import main
from full_bridge import FullActronQueBridge, _as_bool, _as_number
from state_updates import affected_topics, wanted
from secondary_setup import SecondarySetupManager


class ActronQueLocalBridge(FullActronQueBridge):
    """Polished Home Assistant UI for the local QUE bridge."""

    _EXPOSED_EXACT = {
        "UserAirconSettings.isOn", "UserAirconSettings.Mode", "UserAirconSettings.FanMode",
        "UserAirconSettings.AwayMode", "UserAirconSettings.QuietMode",
        "UserAirconSettings.TemperatureSetpoint_Cool_oC", "UserAirconSettings.TemperatureSetpoint_Heat_oC",
        "MasterInfo.ControlAllZones", "MasterInfo.LiveTemp_oC", "MasterInfo.LiveOutdoorTemp_oC",
        "MasterInfo.LiveHumidity_pc", "LiveAircon.CompressorMode", "LiveAircon.CompressorCapacity",
        "LiveAircon.AmRunningFan", "LiveAircon.OutdoorUnit.CompressorOn",
        "LiveAircon.OutdoorUnit.CompPower", "LiveAircon.CoilInlet", "LiveAircon.FanPWM", "LiveAircon.FanRPM",
        "Alerts.CleanFilter", "ACStats.NV_FanRunTime_10m", "NV_SystemSettings.SystemName", "NV_SystemSettings.MaxSecondaryControllers",
    }
    _EXPOSED_PATTERNS = (
        re.compile(r"UserAirconSettings\.EnabledZones\[\d+\]$"), re.compile(r"RemoteZoneInfo\[\d+\]\.NV_Exists$"),
        re.compile(r"RemoteZoneInfo\[\d+\]\.NV_Title$"), re.compile(r"RemoteZoneInfo\[\d+\]\.LiveTemp_oC$"),
        re.compile(r"RemoteZoneInfo\[\d+\]\.TemperatureSetpoint_Cool_oC$"), re.compile(r"RemoteZoneInfo\[\d+\]\.TemperatureSetpoint_Heat_oC$"),
        re.compile(r"RemoteZoneInfo\[\d+\]\.ZonePosition$"), re.compile(r"RemoteZoneInfo\[\d+\]\.RemoteTemperatures_oC\..+$"),
        re.compile(r"RemoteZoneInfo\[\d+\]\.Sensors\..+\.Battery_pc$"), re.compile(r"RemoteZoneInfo\[\d+\]\.Sensors\..+\.lastRssi$"),
    )

    def __init__(self):
        super().__init__(); self._setup_started = False; self._unexposed_logged = False
        self.secondary_setup = SecondarySetupManager(main.OPTIONS, status_callback=self._publish_setup_status, is_walllink_online=lambda: self.walllink_online, set_max_on_live_link=self._set_max_secondary_controllers)

    def _publish_setup_status(self, status: str) -> None:
        self.mqtt_publish(f"{self.topic_prefix}/secondary_setup/status", status, retain=True)

    def _set_max_secondary_controllers(self, value: int) -> None:
        self._send_changes({"NV_SystemSettings.MaxSecondaryControllers": int(value)})

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            # Broker restart/reconnection requires a fresh retained discovery
            # snapshot even if nothing about the AC's configuration changed.
            self._last_discovery_signature = None
        super().on_mqtt_connect(client, userdata, flags, reason_code, properties)
        if reason_code != 0: return
        self.mqtt.subscribe(f"{self.topic_prefix}/zone/+/mode/set", qos=1)
        self.mqtt.subscribe(f"{self.topic_prefix}/secondary_setup/redo", qos=1)
        self._clear_separate_setpoint_numbers(); self._publish_setup_status(self.secondary_setup.status)
        if not self._setup_started: self._setup_started = True; self.secondary_setup.start()

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic; payload = msg.payload.decode("utf-8", "replace").strip().lower()
        if topic == f"{self.topic_prefix}/secondary_setup/redo":
            main.LOG.info("Redo Secondary Controller Setup requested from Home Assistant"); self.secondary_setup.request_redo(); return
        prefix = f"{self.topic_prefix}/zone/"
        if topic.startswith(prefix) and topic.endswith("/mode/set"):
            try:
                zone_number = int(topic[len(prefix):-len("/mode/set")])
                if zone_number < 1: raise ValueError("zone number must be >= 1")
                if payload == "off": enabled = False
                elif payload in ("auto", "cool", "heat", "fan_only", "on"): enabled = True
                else: main.LOG.warning("Ignoring invalid zone HVAC mode: %r", payload); return
                self._send_changes({f"UserAirconSettings.EnabledZones[{zone_number - 1}]": enabled}); return
            except Exception as exc:
                main.LOG.error("Zone mode command failed for %s: %s", topic, exc); return
        super().on_mqtt_message(client, userdata, msg)

    def _clear_discovery(self, domain: str, object_id: str) -> None:
        self.mqtt_publish(f"{self.discovery_prefix}/{domain}/hass_actronque_local/{object_id}/config", b"", retain=True)

    def _clear_separate_setpoint_numbers(self) -> None:
        self._clear_discovery("number", "heating_setpoint"); self._clear_discovery("number", "cooling_setpoint")
        for number in range(1, 9):
            self._clear_discovery("number", f"zone_{number}_heating_setpoint"); self._clear_discovery("number", f"zone_{number}_cooling_setpoint")

    def publish_discovery(self):
        if not self.mqtt_connected or not self.state:
            return
        # Data_All may be sent repeatedly without any actual change to the
        # entity schema. Skip rebuilding/publishing the complete discovery tree
        # unless its identity, settings or zone/sensor structure changed.
        signature = (
            self.master_serial,
            self.master_fw,
            self.system_name,
            self.separate_heat_cool_targets,
            self._zone_signature_value(),
        )
        if signature == getattr(self, "_last_discovery_signature", None):
            return
        super().publish_discovery()
        self._clear_separate_setpoint_numbers(); self._publish_zone_climates(); p = self.topic_prefix
        config = {
            "name": f"Actron QUE ({self.system_name})", "mode_command_topic": f"{p}/climate/mode/set", "mode_state_topic": f"{p}/climate/mode/state",
            "fan_mode_command_topic": f"{p}/climate/fan/set", "fan_mode_state_topic": f"{p}/climate/fan/state",
            "current_temperature_topic": f"{p}/indoor_temperature/state", "action_topic": f"{p}/climate/action/state",
            "modes": ["off", "auto", "cool", "heat", "fan_only"], "fan_modes": ["auto", "low", "medium", "high"],
            "min_temp": 10, "max_temp": 32, "temp_step": 0.5, "temperature_unit": "C", **self._availability(),
        }
        config.update(self._climate_temperature_config(f"{p}/climate/temperature"))
        self.publish_discovery_entity("climate", "climate", config)
        self.publish_discovery_entity("sensor", "secondary_setup_status", {"name": "Secondary Controller Setup Status", "state_topic": f"{p}/secondary_setup/status", "entity_category": "diagnostic", "icon": "mdi:link-variant", **self._availability()})
        self.publish_discovery_entity("button", "redo_secondary_controller_setup", {"name": "Redo Secondary Controller Setup", "command_topic": f"{p}/secondary_setup/redo", "payload_press": "PRESS", "entity_category": "config", "icon": "mdi:link-variant-plus", **self._availability()})
        self._publish_setup_status(self.secondary_setup.status)
        self._last_discovery_signature = signature

    def _publish_zone_climates(self) -> None:
        with self.state_lock: zones = copy.deepcopy(self.state.get("RemoteZoneInfo", []))
        if not isinstance(zones, list): return
        p = self.topic_prefix
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict) or not _as_bool(zone.get("NV_Exists")): continue
            number = index + 1; title = str(zone.get("NV_Title") or f"Zone {number}").strip()
            config = {
                "name": title, "mode_command_topic": f"{p}/zone/{number}/mode/set", "mode_state_topic": f"{p}/zone/{number}/mode/state",
                "current_temperature_topic": f"{p}/zone/{number}/temperature/state", "action_topic": f"{p}/zone/{number}/action/state",
                "modes": ["off", "auto", "cool", "heat", "fan_only"], "min_temp": 10, "max_temp": 32, "temp_step": 0.5,
                "temperature_unit": "C", **self._availability(),
            }
            config.update(self._climate_temperature_config(f"{p}/zone/{number}/temperature"))
            self.publish_discovery_entity("climate", f"zone_{number}_climate", config)

    def _publish_value(self, topic: str, value):
        number = _as_number(value)
        # Preserve the pre-10.3 UI sanitation for invalid sensor percentages.
        if number is not None and topic.endswith(("/compressor_capacity/state", "/fan_pwm/state")):
            if not 0.0 <= number <= 100.0:
                value = 0
                number = 0.0
        if number is not None:
            integer_topics = ("/fan_pwm/state", "/fan_rpm/state", "/battery/state", "/rssi/state")
            one_decimal_topics = ("/temperature/state", "/temperature/target/state", "/temperature/low/state", "/temperature/high/state", "/indoor_temperature/state", "/outdoor_temperature/state", "/compressor_capacity/state", "/compressor_power/state", "/filter_runtime/state", "/position/state")
            if topic.endswith("/humidity/state"):
                # Whole-percent RH with a 1% deadband avoids logging sensor jitter.
                # The full-precision value remains available in the WallLink state.
                with self._retained_state_lock:
                    last_published = self._retained_state_cache.get(topic)
                if last_published is not None and abs(number - float(last_published)) < 1.0:
                    return
                value = int(round(number))
            elif topic.endswith(integer_topics): value = int(round(number))
            elif topic.endswith("/coil_inlet_temperature/state"): value = round(number, 2)
            elif topic.endswith(one_decimal_topics): value = round(number, 1)
        super()._publish_value(topic, value)

    def handle_walllink_message(self, obj):
        super().handle_walllink_message(obj); data_all = obj.get("Data_All") if isinstance(obj, dict) else None
        if not self._unexposed_logged and isinstance(data_all, dict): self._unexposed_logged = True; self._log_unexposed_fields(data_all)

    def _log_unexposed_fields(self, state):
        leaves = []
        def walk(value, path=""):
            if isinstance(value, dict):
                for key, child in value.items(): walk(child, f"{path}.{key}" if path else str(key))
                return
            if isinstance(value, list):
                for index, child in enumerate(value): walk(child, f"{path}[{index}]")
                return
            leaves.append((path, value))
        walk(state); unexposed = []
        for path, value in leaves:
            if path in self._EXPOSED_EXACT or any(pattern.fullmatch(path) for pattern in self._EXPOSED_PATTERNS): continue
            unexposed.append((path, value))
        if not unexposed: main.LOG.debug("QUE field scan: no unexposed Data_All leaf fields found"); return
        main.LOG.debug("QUE field scan: %d unexposed Data_All leaf field(s) found", len(unexposed))
        for path, value in unexposed[:100]: main.LOG.debug("Unexposed QUE field: %s = %s", path, json.dumps(value, ensure_ascii=False, default=str))
        if len(unexposed) > 100: main.LOG.debug("QUE field scan: %d additional field(s) omitted", len(unexposed) - 100)

    @staticmethod
    def _actual_climate_action(system_on, live):
        if system_on is False:
            return "off"
        if not isinstance(live, dict):
            return "idle"

        raw_mode = str(live.get("CompressorMode") or "").upper()
        if raw_mode == "IDLE":
            return "idle"

        outdoor = live.get("OutdoorUnit", {})
        compressor_on = _as_bool(outdoor.get("CompressorOn")) if isinstance(outdoor, dict) else None
        fan_running = _as_bool(live.get("AmRunningFan"))

        # QUE can leave CompressorMode at COOL/HEAT while the plant is in
        # Standby. CompressorOn is the authoritative indication of active
        # compressor operation in the live QUE state.
        if compressor_on is True:
            if "COOL" in raw_mode: return "cooling"
            if "HEAT" in raw_mode: return "heating"
        elif compressor_on is False:
            return "fan" if fan_running is True else "idle"

        # Older/partial WallLink payloads may not contain CompressorOn.
        return FullActronQueBridge._climate_action(system_on, raw_mode)

    def _climate_action(self, system_on, compressor_mode):
        """Use live compressor/fan information for actual operating action."""
        live = self.state.get("LiveAircon", {}) if isinstance(self.state, dict) else {}
        return self._actual_climate_action(system_on, live)

    def publish_current_state(self, changed_paths=None):
        """Publish UI-only zone climate states after the selective base update."""
        super().publish_current_state(changed_paths)
        selected = affected_topics(changed_paths)
        if selected is not None and not any(
            wanted("zone/1/mode/state", selected) if topic == "zone/*/mode/state"
            else wanted("zone/1/action/state", selected) if topic == "zone/*/action/state"
            else topic.endswith(("/mode/state", "/action/state"))
            for topic in selected
        ):
            return

        messages = []
        p = self.topic_prefix
        with self.state_lock:
            state = self.state
            if not isinstance(state, dict) or not state:
                return
            settings = state.get("UserAirconSettings", {})
            live = state.get("LiveAircon", {})
            zones = state.get("RemoteZoneInfo", [])
            if not isinstance(settings, dict): settings = {}
            if not isinstance(live, dict): live = {}
            if not isinstance(zones, list): zones = []
            enabled = settings.get("EnabledZones", [])
            if not isinstance(enabled, list): enabled = []
            system_on = _as_bool(settings.get("isOn"))
            raw_mode = str(settings.get("Mode", "")).upper()
            active_mode = self.QUE_TO_MODE.get(raw_mode, "auto")
            action = self._actual_climate_action(system_on, live)
            if selected is None or "zone/*/mode/state" in selected or "zone/*/action/state" in selected:
                indices = range(len(zones))
            else:
                indices = sorted({
                    int(match.group(1)) - 1
                    for topic in selected
                    for match in (re.match(r"^zone/(\d+)/(?:mode|action)/state$", topic),)
                    if match
                })
            for index in indices:
                if not 0 <= index < len(zones):
                    continue
                zone = zones[index]
                if not isinstance(zone, dict) or not _as_bool(zone.get("NV_Exists")):
                    continue
                number = index + 1
                base = f"zone/{number}/"
                zone_enabled = _as_bool(enabled[index]) if index < len(enabled) else False
                if wanted(base + "mode/state", selected):
                    messages.append((f"{p}/{base}mode/state", active_mode if zone_enabled else "off"))
                if wanted(base + "action/state", selected):
                    messages.append((f"{p}/{base}action/state", action if zone_enabled else "off"))

        for topic, value in messages:
            self._publish_value(topic, value)

    def run(self):
        try: super().run()
        finally: self.secondary_setup.stop()


if __name__ == "__main__":
    ActronQueLocalBridge().run()
