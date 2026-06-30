import json
from pathlib import Path

RUNTIME_CONFIG = Path("/data/networkexplorer_config.json")

DEFAULTS = {
    "piholes": ["192.168.1.2", "192.168.1.3"],
    "access_points": ["192.168.1.11", "192.168.1.12"],
    "ssh_user": "root",
    "ssh_key_path": "/config/ssh/id_ed25519",
    "ping_workers": 20,
    "ping_timeout": 1,
    "tcp_probe": False,
    "tcp_ports": [22, 53, 80, 443],
}


def load_config() -> dict:
    cfg = DEFAULTS.copy()
    for path in [Path("/data/options.json"), RUNTIME_CONFIG]:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for key, value in data.items():
                    if value is not None:
                        cfg[key] = value
            except Exception:
                pass
    cfg["piholes"] = [str(x).strip() for x in cfg.get("piholes", []) if str(x).strip()]
    cfg["access_points"] = [str(x).strip() for x in cfg.get("access_points", []) if str(x).strip()]
    cfg["ping_workers"] = max(1, int(cfg.get("ping_workers", 20)))
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
