from .models import add_source
from .pihole import collect_pihole
from .openwrt import collect_wifi_live, collect_wifi_history
from .probe import apply_active_probes


def fill_missing_hosts_by_mac(devices: dict):
    mac_to_host = {}
    for d in devices.values():
        if d.get("mac") and d.get("host"):
            mac_to_host[d["mac"]] = d["host"]
    for d in devices.values():
        if d.get("mac") and not d.get("host") and d["mac"] in mac_to_host:
            d["host"] = mac_to_host[d["mac"]]
            add_source(d, "Name by MAC")


def ip_sort_key(row):
    parts = (row.get("ip") or "999.999.999.999").split(".")
    return tuple(int(p) if p.isdigit() else 999 for p in parts)


def collect_inventory(cfg: dict) -> list[dict]:
    devices = {}

    for ip in cfg.get("piholes", []):
        collect_pihole(devices, ip, cfg)

    collect_wifi_live(devices, cfg)
    apply_active_probes(devices, cfg)
    collect_wifi_history(devices, cfg)
    fill_missing_hosts_by_mac(devices)

    rows = list(devices.values())
    rows.sort(key=ip_sort_key)
    return rows
