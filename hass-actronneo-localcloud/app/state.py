"""NEO status merge and normalization helpers."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

_PATH_PART_RE = re.compile(r"^([^\[]+)(?:\[(\d+)\])?$")


def deep_merge(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def set_path(root: dict[str, Any], path: str, value: Any) -> None:
    """Set dotted paths such as RemoteZoneInfo[2].LiveTemp_oC."""
    parts = path.split(".")
    current: Any = root
    for index, part in enumerate(parts):
        match = _PATH_PART_RE.match(part)
        if not match:
            if isinstance(current, dict):
                current[part] = deepcopy(value)
            return
        name, array_index = match.groups()
        last = index == len(parts) - 1
        if array_index is None:
            if last:
                if isinstance(current, dict):
                    current[name] = deepcopy(value)
                return
            if not isinstance(current, dict):
                return
            child = current.get(name)
            if not isinstance(child, dict):
                child = {}
                current[name] = child
            current = child
            continue

        if not isinstance(current, dict):
            return
        arr = current.get(name)
        if not isinstance(arr, list):
            arr = []
            current[name] = arr
        idx = int(array_index)
        while len(arr) <= idx:
            arr.append({})
        if last:
            arr[idx] = deepcopy(value)
            return
        if not isinstance(arr[idx], dict):
            arr[idx] = {}
        current = arr[idx]


def extract_event(payload: Any) -> dict[str, Any] | None:
    """Return the state-bearing body of a NEO MQTT broadcast."""
    if not isinstance(payload, dict):
        return None

    event = payload.get("event")
    if isinstance(event, dict) and event:
        body = {key: deepcopy(value) for key, value in event.items() if key != "type"}
        return body or None

    if any(k in payload for k in ("AirconSystem", "UserAirconSettings", "LiveAircon")):
        return {key: deepcopy(value) for key, value in payload.items() if key != "type"}
    return None


def neo_to_ha_mode(is_on: bool, mode: str) -> str:
    if not is_on:
        return "off"
    return {
        "AUTO": "auto",
        "COOL": "cool",
        "HEAT": "heat",
        "FAN": "fan_only",
        "DRY": "dry",
    }.get(str(mode).upper(), "off")


def ha_to_neo_mode(mode: str) -> str:
    return {
        "auto": "AUTO",
        "cool": "COOL",
        "heat": "HEAT",
        "fan_only": "FAN",
        "dry": "DRY",
    }.get(mode.lower(), mode.upper())


def _neo_hvac_action(is_on: bool, neo_mode: str, live: dict[str, Any]) -> str:
    """Map live NEO operation to Home Assistant climate HVAC actions."""
    if not is_on:
        return "off"

    compressor_mode = str(live.get("CompressorMode") or "").upper()
    if "HEAT" in compressor_mode:
        return "heating"
    if "DRY" in compressor_mode:
        return "drying"
    if "COOL" in compressor_mode:
        return "drying" if neo_mode.upper() == "DRY" else "cooling"
    if bool(live.get("AmRunningFan", False)) or neo_mode.upper() == "FAN":
        return "fan"
    return "idle"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_error_code(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return f"E{int(value):02d}"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None


def normalize_state(serial: str, raw: dict[str, Any]) -> dict[str, Any]:
    settings = raw.get("UserAirconSettings") or {}
    master = raw.get("MasterInfo") or {}
    live = raw.get("LiveAircon") or {}
    outdoor = live.get("OutdoorUnit") or {}
    aircon = raw.get("AirconSystem") or {}
    indoor = aircon.get("IndoorUnit") or {}
    outdoor_config = aircon.get("OutdoorUnit") or {}
    nv = raw.get("NV_SystemSettings") or {}
    alerts = raw.get("Alerts") or {}
    cloud = raw.get("Cloud") or {}
    cloud_connection = cloud.get("Connection") or {}
    cloud_uptime = cloud_connection.get("UpTime") or {}
    cloud_sessions = cloud_connection.get("SessionCount") or {}
    system_local = raw.get("SystemStatus_Local") or {}
    wifi = system_local.get("WiFi") or {}
    eev = outdoor.get("EEV") or {}

    is_on = bool(settings.get("isOn", live.get("SystemOn", False)))
    neo_mode = str(settings.get("Mode", "AUTO"))
    mode = neo_to_ha_mode(is_on, neo_mode)
    target = (
        settings.get("TemperatureSetpoint_Heat_oC")
        if neo_mode.upper() == "HEAT"
        else settings.get("TemperatureSetpoint_Cool_oC")
    )

    fan_value = settings.get("FanMode")
    fan_raw = str(fan_value).strip() if fan_value is not None else ""
    fan_mode = fan_raw.replace("+CONT", "").replace("-CONT", "").lower() or None
    turbo_raw = settings.get("TurboMode", False)
    turbo = turbo_raw.get("Enabled", False) if isinstance(turbo_raw, dict) else bool(turbo_raw)

    system_name = str(
        nv.get("SystemName")
        or aircon.get("SystemName")
        or f"Actron NEO {serial.upper()}"
    )

    zones_raw = raw.get("RemoteZoneInfo") or []
    enabled_zones = settings.get("EnabledZones") or []
    zones: list[dict[str, Any]] = []
    for idx, zone in enumerate(zones_raw):
        if not isinstance(zone, dict):
            continue
        exists = bool(zone.get("NV_Exists", False))
        title = str(zone.get("NV_Title") or f"Zone {idx + 1}")
        if not exists and not zone.get("NV_Title"):
            continue
        enabled = bool(enabled_zones[idx]) if idx < len(enabled_zones) else False
        zone_mode = mode if is_on and enabled else "off"
        zone_target = (
            zone.get("TemperatureSetpoint_Heat_oC")
            if neo_mode.upper() == "HEAT"
            else zone.get("TemperatureSetpoint_Cool_oC")
        )
        zones.append(
            {
                "id": idx,
                "name": title,
                "enabled": enabled,
                "mode": zone_mode,
                "current_temperature": zone.get("LiveTemp_oC"),
                "target_temperature": zone_target,
                "humidity": zone.get("LiveHumidity_pc"),
                "position": zone.get("ZonePosition"),
                "itc": bool(zone.get("NV_ITC", False)),
                "vav": bool(zone.get("NV_VAV", False)),
            }
        )

    mode_support = settings.get("ModeSupport") or {}
    support_map = [
        ("Auto", "auto"),
        ("Cool", "cool"),
        ("Heat", "heat"),
        ("Fan", "fan_only"),
        ("Dry", "dry"),
    ]
    supported_modes = ["off"]
    if isinstance(mode_support, dict) and mode_support:
        supported_modes += [ha for neo, ha in support_map if mode_support.get(neo, False)]
    else:
        supported_modes += ["auto", "cool", "heat", "fan_only"]
    if mode not in supported_modes:
        supported_modes.append(mode)

    limits = (raw.get("NV_Limits") or {}).get("UserSetpoint_oC") or {}
    min_temp = min(float(limits.get("setCool_Min", 16.0)), float(limits.get("setHeat_Min", 16.0)))
    max_temp = max(float(limits.get("setCool_Max", 30.0)), float(limits.get("setHeat_Max", 30.0)))

    fan_modes = ["auto", "low", "med", "medium", "high"]
    if fan_mode and fan_mode not in fan_modes:
        fan_modes.append(fan_mode)

    session_count = _int_or_none(cloud_sessions.get("SinceLastMCUReset"))
    reconnect_count = max(session_count - 1, 0) if session_count is not None else None

    # NTW/Inverter telemetry uses scaled engineering values. Real NTW payloads
    # report values such as CompPower=40 for approximately 4.0 kW. The current
    # ActronAir NEO integration uses x100 for compressor power and x10 for
    # supply voltage on this hardware family.
    model = str(aircon.get("MasterWCModel", ""))
    family = str(outdoor_config.get("Family", ""))
    is_ntw_series = model.upper().startswith("NTW") or "INVERTER" in family.upper()
    raw_comp_power = _float_or_none(outdoor.get("CompPower"))
    compressor_power = (
        raw_comp_power * 100.0
        if is_ntw_series and raw_comp_power is not None
        else raw_comp_power
    )
    raw_supply_voltage = _float_or_none(outdoor.get("SupplyVoltage_Vac"))
    supply_voltage = (
        raw_supply_voltage * 10.0
        if is_ntw_series and raw_supply_voltage is not None
        else raw_supply_voltage
    )

    return {
        "serial": serial,
        "name": system_name,
        "firmware": str(aircon.get("MasterWCFirmwareVersion", "")),
        "model": str(aircon.get("MasterWCModel", "NEO")),
        "online": True,
        "power": is_on,
        "mode": mode,
        "hvac_action": _neo_hvac_action(is_on, neo_mode, live),
        "supported_modes": supported_modes,
        "current_temperature": master.get("LiveTemp_oC"),
        "target_temperature": target,
        "humidity": master.get("LiveHumidity_pc"),
        "outdoor_temperature": master.get("LiveOutdoorTemp_oC"),
        "fan_mode": fan_mode,
        "fan_modes": fan_modes,
        "continuous_fan": "+CONT" in fan_raw or "-CONT" in fan_raw,
        "quiet": bool(settings.get("QuietModeEnabled", False)),
        "turbo": turbo,
        "away": bool(settings.get("AwayMode", False)),
        "compressor_mode": live.get("CompressorMode"),
        "compressor_power": compressor_power,
        "compressor_speed": outdoor.get("CompSpeed"),
        "compressor_capacity": live.get("CompressorCapacity"),
        "indoor_fan_rpm": live.get("FanRPM"),
        "indoor_fan_pwm": live.get("FanPWM"),
        "compressor_running": bool(outdoor.get("CompressorOn", False)),
        "coil_inlet_temperature": live.get("CoilInlet"),
        "outdoor_coil_temperature": outdoor.get("CoilTemp"),
        "discharge_temperature": outdoor.get("DischargeTemp"),
        "suction_temperature": outdoor.get("SuctTemp"),
        "drive_temperature": outdoor.get("DriveTemp"),
        "wifi_signal": system_local.get("WifiStrength_of3"),
        "controller_uptime": system_local.get("Uptime_s"),
        "mqtt_session_uptime": cloud_uptime.get("CurrentSession_s"),
        "mqtt_reconnect_count": reconnect_count,
        "vsd_comms_status": outdoor.get("VSDODUCommsStatus"),
        "error_code": _format_error_code(live.get("ErrCode")),
        "lp_fault": bool(outdoor.get("LPErr", False)),
        "hp_fault": bool(outdoor.get("HPErr", False)),
        "supply_voltage": supply_voltage,
        "supply_current": outdoor.get("SupplyCurrentRMS_A"),
        "supply_power": outdoor.get("SupplyPowerRMS_W"),
        "eev_opening": eev.get("Opening_pc"),
        "superheat": eev.get("SuperHeat"),
        "indoor_firmware": indoor.get("IndoorFW"),
        "outdoor_firmware": outdoor_config.get("SoftwareVersion"),
        "outdoor_family": outdoor_config.get("Family"),
        "system_capacity_kw": outdoor_config.get("Capacity_kW"),
        "wifi_firmware": wifi.get("FirmwareVersion"),
        "clean_filter": bool(alerts.get("CleanFilter", False)),
        "defrosting": bool(alerts.get("Defrosting", live.get("Defrost", False))),
        "min_temp": min_temp,
        "max_temp": max_temp,
        "zones": zones,
    }
