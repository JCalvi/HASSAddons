import json
from pathlib import Path

# Persistent user-managed device/config store.
# /data is removed when an add-on is uninstalled; /config is Home Assistant's
# persistent configuration directory and survives add-on removal/reinstall.
RUNTIME_CONFIG = Path("/config/networkexplorer/devices.json")
LEGACY_RUNTIME_CONFIG = Path("/data/networkexplorer_config.json")

DEFAULTS = {
    # Devices/preferences are managed in the Network Explorer UI and persisted
    # in /config/networkexplorer/devices.json.
    # Runtime/performance/steering settings come from HA add-on options.
    "devices": [],
    "preferences": {},
    "piholes": [],
    "access_points": [],
    "ssh_user": "root",
    "ssh_key_path": "/config/ssh/id_ed25519",
    "ping_workers": 50,
    "ping_timeout": 1,
    "tcp_probe": False,
    "tcp_ports": [22, 53, 80, 443],
    "steering_enabled": False,
    "steering_interval_minutes": 10,
    "steering_cooldown_minutes": 30,
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


def migrate_legacy_runtime_config() -> None:
    """Copy old /data runtime config into /config once.

    Earlier builds stored managed devices in /data, which is removed when the
    add-on is uninstalled. New builds store this in /config so device setup
    survives remove/reinstall. During normal upgrades, copy the old file if the
    new persistent file does not already exist.
    """
    if RUNTIME_CONFIG.exists() or not LEGACY_RUNTIME_CONFIG.exists():
        return
    data = _read_json(LEGACY_RUNTIME_CONFIG)
    if data:
        _write_json(RUNTIME_CONFIG, data)


def load_config() -> dict:
    migrate_legacy_runtime_config()

    cfg = DEFAULTS.copy()

    # 1) Read persistent Network Explorer UI data. Only device inventory and
    #    per-client preferences are accepted from this file. Older releases also
    #    stored global settings here; those are intentionally ignored so stale
    #    values in /config/networkexplorer/devices.json cannot override the HA
    #    Configuration page.
    runtime = _read_json(RUNTIME_CONFIG)
    devices = runtime.get("devices") if isinstance(runtime.get("devices"), list) else []
    prefs = runtime.get("preferences") if isinstance(runtime.get("preferences"), dict) else {}

    # Backwards compatibility: if an old runtime file only has piholes/APs,
    # convert them to managed devices once in memory. The next UI save will
    # persist them in the new devices list.
    if not devices:
        for ip in runtime.get("piholes", []) or []:
            if str(ip).strip():
                devices.append({"type": "Pi-hole", "ip": str(ip).strip(), "user": runtime.get("ssh_user") or "root", "name": "", "ssh_key_path": runtime.get("ssh_key_path") or "/config/ssh/id_ed25519"})
        for ip in runtime.get("access_points", []) or []:
            if str(ip).strip():
                devices.append({"type": "OpenWrt Wi-Fi", "ip": str(ip).strip(), "user": runtime.get("ssh_user") or "root", "name": "", "ssh_key_path": runtime.get("ssh_key_path") or "/config/ssh/id_ed25519"})

    cfg["devices"] = devices
    cfg["preferences"] = prefs

    # Derived lists used internally by collectors. These are no longer source
    # settings and are rebuilt from managed devices every load.
    cfg["piholes"] = [str(d.get("ip") or "").strip() for d in devices if d.get("type") == "Pi-hole" and str(d.get("ip") or "").strip()]
    cfg["access_points"] = [str(d.get("ip") or "").strip() for d in devices if d.get("type") in {"OpenWrt Wi-Fi", "OpenWrt AP"} and str(d.get("ip") or "").strip()]

    # 2) Read Home Assistant add-on options. These are the source of truth for
    #    global runtime/performance/steering settings.
    options_path = Path("/data/options.json")
    if options_path.exists():
        try:
            data = json.loads(options_path.read_text())
            allowed = {"ping_workers", "ping_timeout", "tcp_probe", "tcp_ports", "steering_enabled", "steering_interval_minutes", "steering_cooldown_minutes"}
            for key, value in data.items():
                if key in allowed and value is not None:
                    cfg[key] = value
        except Exception:
            pass

    cfg["ping_workers"] = max(1, int(cfg.get("ping_workers", 50)))
    cfg["ping_timeout"] = max(1, int(cfg.get("ping_timeout", 1)))
    cfg["tcp_probe"] = bool(cfg.get("tcp_probe", False))
    cfg["tcp_ports"] = [int(x) for x in cfg.get("tcp_ports", [])]
    cfg["steering_enabled"] = bool(cfg.get("steering_enabled", False))
    cfg["steering_interval_minutes"] = max(1, int(cfg.get("steering_interval_minutes", 10)))
    cfg["steering_cooldown_minutes"] = max(1, int(cfg.get("steering_cooldown_minutes", 30)))
    if not isinstance(cfg.get("preferences"), dict):
        cfg["preferences"] = {}
    return cfg

def save_runtime_config(updates: dict) -> dict:
    migrate_legacy_runtime_config()
    cfg = _read_json(RUNTIME_CONFIG)

    # Only persist UI-owned state here. Global add-on settings live in
    # /data/options.json and must not be shadowed by stale runtime values.
    allowed = {"devices", "preferences"}
    for key, value in updates.items():
        if key in allowed and value is not None:
            cfg[key] = value

    # Clean legacy keys when writing so the file no longer appears to contain
    # active global settings.
    for key in ["ssh_key_path", "ssh_user", "piholes", "access_points", "settings", "steering_enabled", "steering_interval_minutes", "steering_cooldown_minutes", "ping_workers", "ping_timeout", "tcp_probe", "tcp_ports"]:
        cfg.pop(key, None)

    _write_json(RUNTIME_CONFIG, cfg)
    return cfg
