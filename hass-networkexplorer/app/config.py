import json
from pathlib import Path

RUNTIME_CONFIG = Path("/data/networkexplorer_config.json")

DEFAULTS = {
    # Devices are managed in the Network Explorer UI and persisted in
    # /data/networkexplorer_config.json. These legacy list fields are kept
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


def load_config() -> dict:
    cfg = DEFAULTS.copy()

    # Home Assistant add-on options now contain runtime/performance settings only.
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

    # Runtime config is owned by the Network Explorer UI and may include managed
    # devices plus the derived Pi-hole and OpenWrt Wi-Fi polling lists.
    if RUNTIME_CONFIG.exists():
        try:
            data = json.loads(RUNTIME_CONFIG.read_text())
            for key, value in data.items():
                if value is not None:
                    cfg[key] = value
        except Exception:
            pass

    cfg["piholes"] = [str(x).strip() for x in cfg.get("piholes", []) if str(x).strip()]
    cfg["access_points"] = [str(x).strip() for x in cfg.get("access_points", []) if str(x).strip()]
    cfg["ping_workers"] = max(1, int(cfg.get("ping_workers", 50)))
    cfg["ping_timeout"] = max(1, int(cfg.get("ping_timeout", 1)))
    cfg["tcp_ports"] = [int(x) for x in cfg.get("tcp_ports", [])]
    return cfg


def save_runtime_config(updates: dict) -> dict:
    cfg = {}
    if RUNTIME_CONFIG.exists():
        try:
            cfg = json.loads(RUNTIME_CONFIG.read_text())
        except Exception:
            cfg = {}
    for key, value in updates.items():
        if value is not None:
            cfg[key] = value
    RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG.write_text(json.dumps(cfg, indent=2))
    return cfg
