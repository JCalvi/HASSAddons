import json
from pathlib import Path

# Persistent user-managed device/config store.
# /data is removed when an add-on is uninstalled; /config is Home Assistant's
# persistent configuration directory and survives add-on removal/reinstall.
RUNTIME_CONFIG = Path("/config/networkexplorer/devices.json")
LEGACY_RUNTIME_CONFIG = Path("/data/networkexplorer_config.json")

DEFAULTS = {
    # Devices are managed in the Network Explorer UI and persisted in
    # /config/networkexplorer/devices.json. The legacy list fields are kept
    # internally for backwards compatibility only.
    "piholes": [],
    "access_points": [],
    "ssh_user": "root",
    "ssh_key_path": "/config/ssh/id_ed25519",
    "ping_workers": 50,
    "ping_timeout": 1,
    "tcp_probe": False,
    "tcp_ports": [22, 53, 80, 443],
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

    # Home Assistant add-on options contain runtime/performance settings only.
    # Device lists are managed from the Network Explorer UI. Ignore legacy device
    # options here so stale HA options cannot re-add old Pi-hole/AP lists.
    options_path = Path("/data/options.json")
    if options_path.exists():
        try:
            data = json.loads(options_path.read_text())
            for key, value in data.items():
                if key in {"piholes", "access_points", "ssh_user", "devices"}:
                    continue
                if value is not None:
                    cfg[key] = value
        except Exception:
            pass

    # Runtime config is owned by the Network Explorer UI and includes managed
    # devices plus derived Pi-hole/OpenWrt Wi-Fi polling lists.
    data = _read_json(RUNTIME_CONFIG)
    for key, value in data.items():
        if value is not None:
            cfg[key] = value

    cfg["piholes"] = [str(x).strip() for x in cfg.get("piholes", []) if str(x).strip()]
    cfg["access_points"] = [str(x).strip() for x in cfg.get("access_points", []) if str(x).strip()]
    cfg["ping_workers"] = max(1, int(cfg.get("ping_workers", 50)))
    cfg["ping_timeout"] = max(1, int(cfg.get("ping_timeout", 1)))
    cfg["tcp_ports"] = [int(x) for x in cfg.get("tcp_ports", [])]
    return cfg


def save_runtime_config(updates: dict) -> dict:
    migrate_legacy_runtime_config()
    cfg = _read_json(RUNTIME_CONFIG)
    for key, value in updates.items():
        if value is not None:
            cfg[key] = value
    _write_json(RUNTIME_CONFIG, cfg)
    return cfg
