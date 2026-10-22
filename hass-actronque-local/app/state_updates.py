"""Map incoming QUE Data_Change paths to affected retained MQTT state topics.

Unknown individual leaf fields are deliberately ignored (they are still cached
and forwarded as Data_Change events). Whole-object/array replacements trigger
a conservative full state refresh.
"""
import re

PATH_TOPICS = {
    "UserAirconSettings.isOn": ("aircon/state", "climate/mode/state", "climate/action/state",
                                   "zone/*/mode/state", "zone/*/action/state"),
    "UserAirconSettings.Mode": ("mode/state", "climate/mode/state",
                                "climate/temperature/target/state", "zone/*/temperature/target/state",
                                "zone/*/mode/state"),
    "UserAirconSettings.FanMode": ("fan_mode/state", "climate/fan/state", "constant_fan/state"),
    "UserAirconSettings.QuietMode": ("quiet_mode/state",),
    "UserAirconSettings.AwayMode": ("away_mode/state",),
    "UserAirconSettings.TemperatureSetpoint_Heat_oC":
        ("climate/temperature/low/state", "climate/temperature/target/state"),
    "UserAirconSettings.TemperatureSetpoint_Cool_oC":
        ("climate/temperature/high/state", "climate/temperature/target/state"),
    "MasterInfo.LiveTemp_oC": ("temperature/state", "indoor_temperature/state"),
    "MasterInfo.LiveOutdoorTemp_oC": ("outdoor_temperature/state",),
    "MasterInfo.LiveHumidity_pc": ("humidity/state",),
    "MasterInfo.ControlAllZones": ("control_all_zones/state",),
    "NV_SystemSettings.SystemName": ("system/name",),
    "LiveAircon.CompressorMode": ("compressor_mode/state", "climate/action/state",
                                      "zone/*/action/state"),
    "LiveAircon.CompressorCapacity": ("compressor_capacity/state",),
    "LiveAircon.OutdoorUnit.CompressorOn": ("climate/action/state", "zone/*/action/state"),
    "LiveAircon.AmRunningFan": ("climate/action/state", "zone/*/action/state"),
    "LiveAircon.OutdoorUnit.CompPower": ("compressor_power/state",),
    "LiveAircon.CoilInlet": ("coil_inlet_temperature/state",),
    "LiveAircon.FanPWM": ("fan_pwm/state",),
    "LiveAircon.FanRPM": ("fan_rpm/state",),
    "Alerts.CleanFilter": ("clean_filter/state",),
    "ACStats.NV_FanRunTime_10m": ("filter_runtime/state",),
}
_ZONE = re.compile(r"^RemoteZoneInfo\[(\d+)\]\.(.+)$")
_ENABLED = re.compile(r"^UserAirconSettings\.EnabledZones\[(\d+)\]$")
_SENSOR = re.compile(r"^Sensors\.(.+)\.(Battery_pc|lastRssi)$")
_ZONE_TOPICS = {
    "LiveTemp_oC": ("temperature/state",),
    "TemperatureSetpoint_Heat_oC": ("temperature/low/state", "temperature/target/state"),
    "TemperatureSetpoint_Cool_oC": ("temperature/high/state", "temperature/target/state"),
    "ZonePosition": ("position/state",),
}
_KNOWN_PATHS = tuple(PATH_TOPICS) + ("UserAirconSettings.EnabledZones", "RemoteZoneInfo")
_ROOTS = frozenset(("UserAirconSettings", "MasterInfo", "NV_SystemSettings",
                    "LiveAircon", "Alerts", "ACStats", "RemoteZoneInfo"))


def affected_topics(paths):
    """Return relative MQTT topics, or None to request a full refresh."""
    if paths is None:
        return None
    result = set()
    for path in paths:
        if not isinstance(path, str):
            return None
        if path in PATH_TOPICS:
            result.update(PATH_TOPICS[path])
            continue
        match = _ENABLED.fullmatch(path)
        if match:
            result.update((f"zone/{int(match[1]) + 1}/enabled/state",
                           f"zone/{int(match[1]) + 1}/mode/state",
                           f"zone/{int(match[1]) + 1}/action/state"))
            continue
        match = _ZONE.fullmatch(path)
        if match:
            zone = int(match[1]) + 1
            field = match[2]
            if field in _ZONE_TOPICS:
                result.update(f"zone/{zone}/{suffix}" for suffix in _ZONE_TOPICS[field])
                continue
            if field.startswith("RemoteTemperatures_oC."):
                result.add(f"zone/{zone}/sensor/{field[len('RemoteTemperatures_oC.'): ]}/temperature/state")
                continue
            sensor = _SENSOR.fullmatch(field)
            if sensor:
                suffix = "battery" if sensor[2] == "Battery_pc" else "rssi"
                result.add(f"zone/{zone}/sensor/{sensor[1]}/{suffix}/state")
                continue
            # Whole-zone replacements, zone membership changes and unknown
            # nested structures may alter discovery or multiple MQTT values.
            if (field in ("NV_Exists", "NV_Title", "Sensors", "RemoteTemperatures_oC")
                    or field.startswith(("Sensors.", "RemoteTemperatures_oC."))
                    or "." not in field):
                return None
            continue
        if path in _ROOTS or any(key.startswith(path + ".") or key.startswith(path + "[")
                                 for key in _KNOWN_PATHS):
            return None
        # Indexed EnabledZones and RemoteZoneInfo aggregate replacements.
        if path.startswith("UserAirconSettings.EnabledZones"):
            return None
        if path.startswith("RemoteZoneInfo[") and "." not in path:
            return None
        if path == "LiveAircon.OutdoorUnit":
            return None
        # Unrelated telemetry has no exposed entity.
    return result


def wanted(topic, selected):
    """Match exact topics and the mode-dependent all-zone target wildcard."""
    if selected is None or topic in selected:
        return True
    match = re.fullmatch(r"zone/\d+/(.+)", topic)
    return bool(match and f"zone/*/{match[1]}" in selected)


def discovery_might_change(paths):
    """Only investigate zone identity on changed structure/sensor membership."""
    for path in paths or ():
        if not isinstance(path, str):
            return True
        if path == "RemoteZoneInfo" or path.startswith("RemoteZoneInfo["):
            match = _ZONE.fullmatch(path)
            if not match:
                return True
            field = match[2]
            if (field in ("NV_Exists", "NV_Title", "Sensors", "RemoteTemperatures_oC")
                    or field.startswith(("Sensors.", "RemoteTemperatures_oC."))):
                return True
    return False
