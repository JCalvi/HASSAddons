#!/usr/bin/env python3

import copy
import json
import re
from typing import Any, Dict, Optional

import main
from local_identity import LocalActronQueBridge


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    return text or "unknown"


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        value = value.strip().upper()
        if value in ("ON", "TRUE", "1", "YES"):
            return True
        if value in ("OFF", "FALSE", "0", "NO"):
            return False
    return None


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class FullActronQueBridge(LocalActronQueBridge):
    """Full local QUE bridge using the native WallLink state/command schema."""

    MODE_TO_QUE = {"auto": "AUTO", "cool": "COOL", "heat": "HEAT", "fan_only": "FAN"}
    QUE_TO_MODE = {"AUTO": "auto", "COOL": "cool", "HEAT": "heat", "FAN": "fan_only"}
    FAN_TO_QUE = {"auto": "AUTO", "low": "LOW", "medium": "MED", "high": "HIGH"}
    QUE_TO_FAN = {"AUTO": "auto", "LOW": "low", "MED": "medium", "HIGH": "high"}

    def __init__(self):
        self._zone_signature = None
        self.separate_heat_cool_targets = bool(main.OPTIONS.get("separate_heat_cool_targets", False))
        super().__init__()

    # ----- Writes -------------------------------------------------------

    def _send_changes(self, changes: Dict[str, Any]) -> None:
        if not changes:
            return
        main.LOG.info("WallLink write: %s", json.dumps(changes, separators=(",", ":")))
        self.walllink._send_json({"Data_Change": changes, "id": {"fw_version": self.walllink.firmware, "serial": self.walllink.serial}})
        with self.state_lock:
            for path, value in changes.items():
                main.set_state_path(self.state, path, value)
        self.publish_current_state()

    def _write_bool(self, path: str, payload: str) -> None:
        value = _as_bool(payload)
        if value is None:
            main.LOG.warning("Ignoring invalid boolean command for %s: %r", path, payload)
            return
        self._send_changes({path: value})

    def _validated_temp(self, payload: str) -> Optional[float]:
        value = _as_number(payload)
        if value is None or not 10.0 <= value <= 32.0:
            main.LOG.warning("Ignoring invalid temperature: %r", payload)
            return None
        return round(value * 2.0) / 2.0

    def _write_temp(self, path: str, payload: str) -> None:
        value = self._validated_temp(payload)
        if value is not None:
            self._send_changes({path: value})

    def _write_single_temp(self, payload: str, zone_index: Optional[int] = None) -> None:
        """Match the cloud add-on's TemperatureSetType.Default behaviour."""
        value = self._validated_temp(payload)
        if value is None:
            return
        with self.state_lock:
            settings = self.state.get("UserAirconSettings", {})
            mode = str(settings.get("Mode", "")).upper() if isinstance(settings, dict) else ""
        prefix = "UserAirconSettings" if zone_index is None else f"RemoteZoneInfo[{zone_index}]"
        if mode == "COOL":
            changes = {f"{prefix}.TemperatureSetpoint_Cool_oC": value}
        elif mode == "HEAT":
            changes = {f"{prefix}.TemperatureSetpoint_Heat_oC": value}
        elif mode == "AUTO":
            changes = {
                f"{prefix}.TemperatureSetpoint_Heat_oC": value,
                f"{prefix}.TemperatureSetpoint_Cool_oC": value,
            }
        else:
            main.LOG.debug("Ignoring single temperature command while QUE mode is %s", mode or "unknown")
            return
        self._send_changes(changes)

    @staticmethod
    def _single_target(mode: str, heating: Any, cooling: Any) -> Optional[float]:
        heat = _as_number(heating)
        cool = _as_number(cooling)
        mode = str(mode or "").upper()
        if mode == "COOL":
            return cool
        if mode == "HEAT":
            return heat
        if heat is not None and cool is not None:
            return (heat + cool) / 2.0
        return heat if heat is not None else cool

    # ----- MQTT commands ------------------------------------------------

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        super().on_mqtt_connect(client, userdata, flags, reason_code, properties)
        if reason_code != 0:
            return
        for topic in (
            f"{self.topic_prefix}/climate/+/set",
            f"{self.topic_prefix}/climate/temperature/+/set",
            f"{self.topic_prefix}/away_mode/set",
            f"{self.topic_prefix}/control_all_zones/set",
            f"{self.topic_prefix}/constant_fan/set",
            f"{self.topic_prefix}/zone/+/enabled/set",
            f"{self.topic_prefix}/zone/+/temperature/set",
            f"{self.topic_prefix}/zone/+/temperature/+/set",
        ):
            self.mqtt.subscribe(topic, qos=1)

    def on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", "replace").strip()
        if topic == f"{self.topic_prefix}/quiet_mode/set":
            super().on_mqtt_message(client, userdata, msg)
            return
        try:
            rel = topic[len(self.topic_prefix) + 1 :]
            parts = rel.split("/")
            if rel == "away_mode/set":
                self._write_bool("UserAirconSettings.AwayMode", payload); return
            if rel == "control_all_zones/set":
                self._write_bool("MasterInfo.ControlAllZones", payload); return
            if rel == "constant_fan/set":
                requested = _as_bool(payload)
                if requested is None:
                    main.LOG.warning("Ignoring invalid Constant Fan command: %r", payload); return
                with self.state_lock:
                    current = self.state.get("UserAirconSettings", {}).get("FanMode", "AUTO")
                base = str(current).upper().replace("+CONT", "")
                if base not in ("AUTO", "LOW", "MED", "HIGH"): base = "AUTO"
                self._send_changes({"UserAirconSettings.FanMode": base + ("+CONT" if requested else "")}); return
            if parts == ["climate", "mode", "set"]:
                mode = payload.lower()
                if mode == "off": self._send_changes({"UserAirconSettings.isOn": False})
                elif mode in self.MODE_TO_QUE: self._send_changes({"UserAirconSettings.isOn": True, "UserAirconSettings.Mode": self.MODE_TO_QUE[mode]})
                else: main.LOG.warning("Ignoring invalid HVAC mode: %r", payload)
                return
            if parts == ["climate", "fan", "set"]:
                fan = payload.lower()
                if fan not in self.FAN_TO_QUE:
                    main.LOG.warning("Ignoring invalid fan mode: %r", payload); return
                with self.state_lock: current = self.state.get("UserAirconSettings", {}).get("FanMode", "")
                self._send_changes({"UserAirconSettings.FanMode": self.FAN_TO_QUE[fan] + ("+CONT" if "+CONT" in str(current).upper() else "")}); return
            if parts == ["climate", "temperature", "set"]:
                self._write_single_temp(payload); return
            if parts == ["climate", "temperature", "high", "set"]:
                self._write_temp("UserAirconSettings.TemperatureSetpoint_Cool_oC", payload); return
            if parts == ["climate", "temperature", "low", "set"]:
                self._write_temp("UserAirconSettings.TemperatureSetpoint_Heat_oC", payload); return
            if len(parts) == 4 and parts[0] == "zone" and parts[2:] == ["enabled", "set"]:
                zone_index = int(parts[1]) - 1
                if zone_index < 0: raise ValueError("zone number must be >= 1")
                value = _as_bool(payload)
                if value is None: main.LOG.warning("Ignoring invalid zone enable command: %r", payload); return
                self._send_changes({f"UserAirconSettings.EnabledZones[{zone_index}]": value}); return
            if len(parts) == 4 and parts[0] == "zone" and parts[2:] == ["temperature", "set"]:
                zone_index = int(parts[1]) - 1
                if zone_index < 0: raise ValueError("zone number must be >= 1")
                self._write_single_temp(payload, zone_index); return
            if len(parts) == 5 and parts[0] == "zone" and parts[2] == "temperature" and parts[4] == "set":
                zone_index = int(parts[1]) - 1
                if zone_index < 0: raise ValueError("zone number must be >= 1")
                suffix = "TemperatureSetpoint_Cool_oC" if parts[3] == "high" else "TemperatureSetpoint_Heat_oC" if parts[3] == "low" else None
                if suffix: self._write_temp(f"RemoteZoneInfo[{zone_index}].{suffix}", payload)
                return
        except Exception as exc:
            main.LOG.error("Command failed for %s payload %r: %s", topic, payload, exc)

    # ----- Discovery helpers -------------------------------------------

    def _availability(self):
        return {"availability_topic": f"{self.topic_prefix}/status", "payload_available": "online", "payload_not_available": "offline"}

    def _sensor(self, object_id, name, topic, device_class=None, unit=None, icon=None, category=None):
        config = {"name": name, "state_topic": topic, **self._availability()}
        if device_class: config["device_class"] = device_class
        if unit: config["unit_of_measurement"] = unit
        if icon: config["icon"] = icon
        if category: config["entity_category"] = category
        self.publish_discovery_entity("sensor", object_id, config)

    def _switch(self, object_id, name, state_topic, command_topic, icon=None):
        config = {"name": name, "state_topic": state_topic, "command_topic": command_topic, "payload_on": "ON", "payload_off": "OFF", "state_on": "ON", "state_off": "OFF", **self._availability()}
        if icon: config["icon"] = icon
        self.publish_discovery_entity("switch", object_id, config)

    def _number(self, object_id, name, state_topic, command_topic):
        self.publish_discovery_entity("number", object_id, {"name": name, "state_topic": state_topic, "command_topic": command_topic, "min": 10, "max": 32, "step": 0.5, "unit_of_measurement": "°C", "device_class": "temperature", "mode": "box", **self._availability()})

    def _climate_temperature_config(self, prefix: str, state_prefix: Optional[str] = None) -> Dict[str, Any]:
        state_prefix = state_prefix or prefix
        if self.separate_heat_cool_targets:
            return {
                "temperature_high_command_topic": f"{prefix}/high/set",
                "temperature_high_state_topic": f"{state_prefix}/high/state",
                "temperature_low_command_topic": f"{prefix}/low/set",
                "temperature_low_state_topic": f"{state_prefix}/low/state",
            }
        return {"temperature_command_topic": f"{prefix}/set", "temperature_state_topic": f"{state_prefix}/target/state"}

    def publish_discovery(self):
        super().publish_discovery()
        if not self.mqtt_connected or not self.state: return
        p = self.topic_prefix
        config = {
            "name": "Climate", "mode_command_topic": f"{p}/climate/mode/set", "mode_state_topic": f"{p}/climate/mode/state",
            "fan_mode_command_topic": f"{p}/climate/fan/set", "fan_mode_state_topic": f"{p}/climate/fan/state",
            "current_temperature_topic": f"{p}/indoor_temperature/state", "action_topic": f"{p}/climate/action/state",
            "modes": ["off", "auto", "cool", "heat", "fan_only"], "fan_modes": ["auto", "low", "medium", "high"],
            "min_temp": 10, "max_temp": 32, "temp_step": 0.5, "temperature_unit": "C", **self._availability(),
        }
        config.update(self._climate_temperature_config(f"{p}/climate/temperature"))
        self.publish_discovery_entity("climate", "climate", config)
        self._switch("away_mode", "Away Mode", f"{p}/away_mode/state", f"{p}/away_mode/set", "mdi:home-export-outline")
        self._switch("control_all_zones", "Control All Zones", f"{p}/control_all_zones/state", f"{p}/control_all_zones/set", "mdi:home-thermometer")
        self._switch("constant_fan", "Constant Fan", f"{p}/constant_fan/state", f"{p}/constant_fan/set", "mdi:fan")
        self._number("heating_setpoint", "Heating Setpoint", f"{p}/climate/temperature/low/state", f"{p}/climate/temperature/low/set")
        self._number("cooling_setpoint", "Cooling Setpoint", f"{p}/climate/temperature/high/state", f"{p}/climate/temperature/high/set")
        self._sensor("indoor_temperature", "Indoor Temperature", f"{p}/indoor_temperature/state", "temperature", "°C")
        self._sensor("outdoor_temperature", "Outdoor Temperature", f"{p}/outdoor_temperature/state", "temperature", "°C")
        self._sensor("humidity", "Humidity", f"{p}/humidity/state", "humidity", "%")
        self._sensor("compressor_mode", "Compressor Mode", f"{p}/compressor_mode/state")
        self._sensor("compressor_capacity", "Compressor Capacity", f"{p}/compressor_capacity/state", unit="%", icon="mdi:gauge")
        self._sensor("compressor_power", "Compressor Power", f"{p}/compressor_power/state", "power", "W")
        self._sensor("coil_inlet_temperature", "Coil Inlet Temperature", f"{p}/coil_inlet_temperature/state", "temperature", "°C")
        self._sensor("fan_pwm", "Fan PWM", f"{p}/fan_pwm/state", unit="%", icon="mdi:fan")
        self._sensor("fan_rpm", "Fan RPM", f"{p}/fan_rpm/state", unit="RPM", icon="mdi:fan")
        self._sensor("filter_runtime", "Fan Time Since Filter Cleaned", f"{p}/filter_runtime/state", "duration", "h", "mdi:clock-outline")
        self.publish_discovery_entity("binary_sensor", "clean_filter", {"name": "Clean Filter", "state_topic": f"{p}/clean_filter/state", "payload_on": "ON", "payload_off": "OFF", "device_class": "problem", "icon": "mdi:air-filter", **self._availability()})
        self._publish_zone_discovery()

    def _zone_signature_value(self):
        with self.state_lock: zones = copy.deepcopy(self.state.get("RemoteZoneInfo", []))
        if not isinstance(zones, list): return ()
        result = []
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict): continue
            sensor_ids = set()
            for key in ("Sensors", "RemoteTemperatures_oC"):
                value = zone.get(key, {})
                if isinstance(value, dict): sensor_ids.update(str(x) for x in value.keys())
            result.append((index, bool(zone.get("NV_Exists")), str(zone.get("NV_Title", "")), tuple(sorted(sensor_ids))))
        return tuple(result)

    def _publish_zone_discovery(self):
        with self.state_lock: zones = copy.deepcopy(self.state.get("RemoteZoneInfo", []))
        if not isinstance(zones, list): return
        p = self.topic_prefix
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict) or not _as_bool(zone.get("NV_Exists")): continue
            number = index + 1; title = str(zone.get("NV_Title") or f"Zone {number}").strip(); zid = f"zone_{number}"
            self._switch(f"{zid}_enabled", f"{title} Enabled", f"{p}/zone/{number}/enabled/state", f"{p}/zone/{number}/enabled/set", "mdi:air-conditioner")
            self._sensor(f"{zid}_temperature", f"{title} Temperature", f"{p}/zone/{number}/temperature/state", "temperature", "°C")
            self._number(f"{zid}_heating_setpoint", f"{title} Heating Setpoint", f"{p}/zone/{number}/temperature/low/state", f"{p}/zone/{number}/temperature/low/set")
            self._number(f"{zid}_cooling_setpoint", f"{title} Cooling Setpoint", f"{p}/zone/{number}/temperature/high/state", f"{p}/zone/{number}/temperature/high/set")
            self._sensor(f"{zid}_position", f"{title} Damper Position", f"{p}/zone/{number}/position/state", unit="%", icon="mdi:valve")
            sensors = zone.get("Sensors", {}) if isinstance(zone.get("Sensors", {}), dict) else {}; temps = zone.get("RemoteTemperatures_oC", {}) if isinstance(zone.get("RemoteTemperatures_oC", {}), dict) else {}
            for sensor_id in sorted(set(map(str, sensors.keys())) | set(map(str, temps.keys()))):
                sid = _slug(sensor_id); base = f"{zid}_sensor_{sid}"; display = f"{title} Sensor {sensor_id}"
                self._sensor(f"{base}_temperature", f"{display} Temperature", f"{p}/zone/{number}/sensor/{sensor_id}/temperature/state", "temperature", "°C")
                info = sensors.get(sensor_id, {})
                if not isinstance(info, dict): info = {}
                if "Battery_pc" in info: self._sensor(f"{base}_battery", f"{display} Battery", f"{p}/zone/{number}/sensor/{sensor_id}/battery/state", "battery", "%")
                if "lastRssi" in info: self._sensor(f"{base}_rssi", f"{display} RSSI", f"{p}/zone/{number}/sensor/{sensor_id}/rssi/state", "signal_strength", "dBm", category="diagnostic")

    # ----- State ---------------------------------------------------------

    def handle_walllink_message(self, obj: Dict[str, Any]):
        before = self._zone_signature; super().handle_walllink_message(obj); after = self._zone_signature_value(); self._zone_signature = after
        if self.mqtt_connected and after != before: self.publish_discovery()

    def _publish_value(self, topic: str, value: Any):
        if value is not None: self.mqtt_publish(topic, value, retain=True)

    def publish_current_state(self):
        super().publish_current_state()
        with self.state_lock: state = copy.deepcopy(self.state)
        if not state: return
        p = self.topic_prefix; settings = state.get("UserAirconSettings", {}); master_info = state.get("MasterInfo", {}); live = state.get("LiveAircon", {}); alerts = state.get("Alerts", {}); stats = state.get("ACStats", {})
        for name, value in (("settings", settings), ("master", master_info), ("live", live), ("alerts", alerts), ("stats", stats)):
            if not isinstance(value, dict):
                if name == "settings": settings = {}
                elif name == "master": master_info = {}
                elif name == "live": live = {}
                elif name == "alerts": alerts = {}
                else: stats = {}
        is_on = _as_bool(settings.get("isOn")); raw_mode = str(settings.get("Mode", "")).upper()
        self._publish_value(f"{p}/climate/mode/state", "off" if is_on is False else self.QUE_TO_MODE.get(raw_mode))
        raw_fan = str(settings.get("FanMode", "")).upper(); fan_base = raw_fan.replace("+CONT", "")
        self._publish_value(f"{p}/climate/fan/state", self.QUE_TO_FAN.get(fan_base))
        if raw_fan: self._publish_value(f"{p}/constant_fan/state", "ON" if "+CONT" in raw_fan else "OFF")
        heat = settings.get("TemperatureSetpoint_Heat_oC"); cool = settings.get("TemperatureSetpoint_Cool_oC")
        self._publish_value(f"{p}/climate/temperature/low/state", heat); self._publish_value(f"{p}/climate/temperature/high/state", cool)
        self._publish_value(f"{p}/climate/temperature/target/state", self._single_target(raw_mode, heat, cool))
        away = _as_bool(settings.get("AwayMode")); control_all = _as_bool(master_info.get("ControlAllZones"))
        if away is not None: self._publish_value(f"{p}/away_mode/state", "ON" if away else "OFF")
        if control_all is not None: self._publish_value(f"{p}/control_all_zones/state", "ON" if control_all else "OFF")
        self._publish_value(f"{p}/indoor_temperature/state", master_info.get("LiveTemp_oC")); self._publish_value(f"{p}/outdoor_temperature/state", master_info.get("LiveOutdoorTemp_oC")); self._publish_value(f"{p}/humidity/state", master_info.get("LiveHumidity_pc")); self._publish_value(f"{p}/compressor_mode/state", live.get("CompressorMode")); self._publish_value(f"{p}/compressor_capacity/state", live.get("CompressorCapacity"))
        outdoor_unit = live.get("OutdoorUnit", {})
        if isinstance(outdoor_unit, dict): self._publish_value(f"{p}/compressor_power/state", outdoor_unit.get("CompPower"))
        self._publish_value(f"{p}/coil_inlet_temperature/state", live.get("CoilInlet")); self._publish_value(f"{p}/fan_pwm/state", live.get("FanPWM")); self._publish_value(f"{p}/fan_rpm/state", live.get("FanRPM"))
        clean_filter = _as_bool(alerts.get("CleanFilter"))
        if clean_filter is not None: self._publish_value(f"{p}/clean_filter/state", "ON" if clean_filter else "OFF")
        runtime = _as_number(stats.get("NV_FanRunTime_10m"))
        if runtime is not None: self._publish_value(f"{p}/filter_runtime/state", round(runtime / 6.0, 1))
        self._publish_value(f"{p}/climate/action/state", self._climate_action(is_on, live.get("CompressorMode")))
        zones = state.get("RemoteZoneInfo", []); enabled = settings.get("EnabledZones", [])
        if not isinstance(zones, list): zones = []
        if not isinstance(enabled, list): enabled = []
        for index, zone in enumerate(zones):
            if not isinstance(zone, dict) or not _as_bool(zone.get("NV_Exists")): continue
            number = index + 1
            if index < len(enabled):
                zone_on = _as_bool(enabled[index])
                if zone_on is not None: self._publish_value(f"{p}/zone/{number}/enabled/state", "ON" if zone_on else "OFF")
            self._publish_value(f"{p}/zone/{number}/temperature/state", zone.get("LiveTemp_oC"))
            zheat = zone.get("TemperatureSetpoint_Heat_oC"); zcool = zone.get("TemperatureSetpoint_Cool_oC")
            self._publish_value(f"{p}/zone/{number}/temperature/low/state", zheat); self._publish_value(f"{p}/zone/{number}/temperature/high/state", zcool)
            self._publish_value(f"{p}/zone/{number}/temperature/target/state", self._single_target(raw_mode, zheat, zcool))
            position = _as_number(zone.get("ZonePosition"))
            if position is not None: self._publish_value(f"{p}/zone/{number}/position/state", round(position * 5.0, 1))
            temps = zone.get("RemoteTemperatures_oC", {}) if isinstance(zone.get("RemoteTemperatures_oC", {}), dict) else {}; sensors = zone.get("Sensors", {}) if isinstance(zone.get("Sensors", {}), dict) else {}
            for sensor_id in set(map(str, temps.keys())) | set(map(str, sensors.keys())):
                if sensor_id in temps: self._publish_value(f"{p}/zone/{number}/sensor/{sensor_id}/temperature/state", temps.get(sensor_id))
                info = sensors.get(sensor_id, {})
                if isinstance(info, dict):
                    self._publish_value(f"{p}/zone/{number}/sensor/{sensor_id}/battery/state", info.get("Battery_pc")); self._publish_value(f"{p}/zone/{number}/sensor/{sensor_id}/rssi/state", info.get("lastRssi"))

    @staticmethod
    def _climate_action(is_on: Optional[bool], compressor_mode: Any) -> str:
        if is_on is False: return "off"
        raw = str(compressor_mode or "").upper()
        if "COOL" in raw: return "cooling"
        if "HEAT" in raw: return "heating"
        if "FAN" in raw: return "fan"
        return "idle"


if __name__ == "__main__":
    FullActronQueBridge().run()
