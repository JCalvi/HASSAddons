import json
from pathlib import Path

# Persistent user-managed device/config store.
# /data is removed when an add-on is uninstalled; /config is Home Assistant's
# persistent configuration directory and survives add-on removal/reinstall.
RUNTIME_CONFIG = Path("/config/networkexplorer/devices.json")
LEGACY_RUNTIME_CONFIG = Path("/data/networkexplorer_config.json")

DEFAULT_SETTINGS = {
    "steering": {
        "enabled": False,
        "interval_minutes": 10,
        "cooldown_minutes": 30,
    }
}

DEFAULTS = {
    "devices": [],
    "ssh_key_path": "/config/ssh/id_ed25519",
    "ping_workers": 50,
    "ping_timeout": 1,
    "tcp_probe": False,
    "tcp_ports": [22, 53, 80, 443],
    "preferences": {},
    "settings": DEFAULT_SETTINGS.copy(),
}


def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _deep_merge_settings(existing: dict | None) -> dict:
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(existing, dict):
        for key, value in existing.items():
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value
    return settings


def _legacy_device_lists_to_devices(data: dict) -> list:
    devices = list(data.get("devices") or [])
    known_ips = {str(d.get("ip") or "").strip() for d in devices}
    for ip in data.get("piholes") or []:
        ip = str(ip).strip()
        if ip and ip not in known_ips:
            devices.append({"type": "Pi-hole", "ip": ip, "user": data.get("ssh_user") or "root", "name": ""})
            known_ips.add(ip)
    for ip in data.get("access_points") or []:
        ip = str(ip).strip()
        if ip and ip not in known_ips:
            devices.append({"type": "OpenWrt Wi-Fi", "ip": ip, "user": data.get("ssh_user") or "root", "name": ""})
            known_ips.add(ip)
    return devices


def normalise_runtime_data(data: dict) -> dict:
    """Normalise persistent config into the v2026.6.14 schema.

    The file should contain only true Network Explorer state:
      - managed devices
      - per-device preferences
      - UI-owned settings
      - ssh_key_path

    Pi-hole and AP lists are now derived from devices and are no longer stored.
    """
    data = dict(data or {})
    out = {}

    devices = _legacy_device_lists_to_devices(data)
    clean_devices = []
    for d in devices:
        ip = str(d.get("ip") or "").strip()
        if not ip:
            continue
        dtype = d.get("type") or "Auto"
        capabilities = d.get("capabilities")
        if not isinstance(capabilities, list):
            capabilities = []
        # Compatibility: OpenWrt Wi-Fi is still accepted in UI, but also gains
        # a wifi capability so future code can use capabilities instead of types.
        if dtype in {"OpenWrt Wi-Fi", "OpenWrt AP"} and "wifi" not in capabilities:
            capabilities.append("wifi")
        clean_devices.append({
            "type": dtype,
            "ip": ip,
            "user": d.get("user") or data.get("ssh_user") or "root",
            "name": d.get("name") or "",
            **({"capabilities": capabilities} if capabilities else {}),
        })
    out["devices"] = clean_devices

    prefs = data.get("preferences") if isinstance(data.get("preferences"), dict) else {}
    out["preferences"] = prefs

    settings = _deep_merge_settings(data.get("settings"))
    # Migrate old root steering keys into settings.steering.
    steering = settings.setdefault("steering", {})
    if "steering_enabled" in data:
        steering["enabled"] = bool(data.get("steering_enabled"))
    if "steering_interval_minutes" in data:
        steering["interval_minutes"] = data.get("steering_interval_minutes")
    if "steering_cooldown_minutes" in data:
        steering["cooldown_minutes"] = data.get("steering_cooldown_minutes")
    out["settings"] = settings

    if data.get("ssh_key_path"):
        out["ssh_key_path"] = data.get("ssh_key_path")

    return out


def migrate_legacy_runtime_config() -> None:
    """Copy old /data runtime config into /config once."""
    if RUNTIME_CONFIG.exists() or not LEGACY_RUNTIME_CONFIG.exists():
        return
    data = _read_json(LEGACY_RUNTIME_CONFIG)
    if data:
        _write_json(RUNTIME_CONFIG, normalise_runtime_data(data))


def _derive_lists_from_devices(cfg: dict) -> None:
    devices = cfg.get("devices") or []
    piholes = []
    access_points = []
    for d in devices:
        dtype = d.get("type") or ""
        caps = d.get("capabilities") or []
        ip = str(d.get("ip") or "").strip()
        if not ip:
            continue
        if dtype == "Pi-hole":
            piholes.append(ip)
        if dtype in {"OpenWrt Wi-Fi", "OpenWrt AP"} or "wifi" in caps:
            access_points.append(ip)
    # Derived values are for internal runtime use only. They are not written
    # back to devices.json.
    cfg["piholes"] = piholes
    cfg["access_points"] = access_points


def load_config() -> dict:
    migrate_legacy_runtime_config()
    cfg = json.loads(json.dumps(DEFAULTS))

    # Home Assistant add-on options contain runtime/performance settings only.
    # Device inventory and UI preferences are managed in the Network Explorer UI.
    options_path = Path("/data/options.json")
    if options_path.exists():
        try:
            data = json.loads(options_path.read_text())
            for key, value in data.items():
                if key in {"piholes", "access_points", "ssh_user", "devices", "preferences", "settings", "steering_enabled", "steering_interval_minutes", "steering_cooldown_minutes"}:
                    continue
                if value is not None:
                    cfg[key] = value
        except Exception:
            pass

    runtime = normalise_runtime_data(_read_json(RUNTIME_CONFIG))
    # Rewrite once if old schema was loaded, so the on-disk file is cleaned up.
    if runtime and _read_json(RUNTIME_CONFIG) != runtime:
        _write_json(RUNTIME_CONFIG, runtime)
    for key, value in runtime.items():
        if value is not None:
            cfg[key] = value

    cfg["ping_workers"] = max(1, int(cfg.get("ping_workers", 50)))
    cfg["ping_timeout"] = max(1, int(cfg.get("ping_timeout", 1)))
    cfg["tcp_ports"] = [int(x) for x in cfg.get("tcp_ports", [])]
    if not isinstance(cfg.get("preferences"), dict):
        cfg["preferences"] = {}
    cfg["settings"] = _deep_merge_settings(cfg.get("settings"))

    steering = cfg["settings"].setdefault("steering", {})
    steering["enabled"] = bool(steering.get("enabled", False))
    steering["interval_minutes"] = max(1, int(steering.get("interval_minutes", 10) or 10))
    steering["cooldown_minutes"] = max(1, int(steering.get("cooldown_minutes", 30) or 30))

    # Backwards-compatible aliases for existing collector/steering code.
    cfg["steering_enabled"] = steering["enabled"]
    cfg["steering_interval_minutes"] = steering["interval_minutes"]
    cfg["steering_cooldown_minutes"] = steering["cooldown_minutes"]
    cfg["ssh_user"] = "root"  # Default only; each managed device stores its own user.
    _derive_lists_from_devices(cfg)
    return cfg


def save_runtime_config(updates: dict) -> dict:
    migrate_legacy_runtime_config()
    cfg = normalise_runtime_data(_read_json(RUNTIME_CONFIG))

    updates = dict(updates or {})
    # Explicitly ignore old duplicated lists if a caller still sends them.
    updates.pop("piholes", None)
    updates.pop("access_points", None)
    updates.pop("ssh_user", None)

    # Support old root steering update keys, but save only new settings object.
    if any(k in updates for k in ("steering_enabled", "steering_interval_minutes", "steering_cooldown_minutes")):
        settings = _deep_merge_settings(cfg.get("settings"))
        steering = settings.setdefault("steering", {})
        if "steering_enabled" in updates:
            steering["enabled"] = bool(updates.pop("steering_enabled"))
        if "steering_interval_minutes" in updates:
            steering["interval_minutes"] = int(updates.pop("steering_interval_minutes") or 10)
        if "steering_cooldown_minutes" in updates:
            steering["cooldown_minutes"] = int(updates.pop("steering_cooldown_minutes") or 30)
        updates["settings"] = settings

    if "settings" in updates:
        updates["settings"] = _deep_merge_settings(updates["settings"])

    for key, value in updates.items():
        if value is not None:
            cfg[key] = value

    cfg = normalise_runtime_data(cfg)
    _write_json(RUNTIME_CONFIG, cfg)
    return cfg
