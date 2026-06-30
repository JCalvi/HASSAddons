import json
from pathlib import Path

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
    path = Path("/data/options.json")
    cfg = DEFAULTS.copy()
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
