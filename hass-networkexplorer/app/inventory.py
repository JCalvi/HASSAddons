from .models import add_source, merge_device, is_tailscale_ip
from .pihole import collect_pihole
from .openwrt import collect_wifi_live, collect_wifi_history, collect_openwrt_neighbours
from .probe import apply_active_probes


def fill_missing_hosts_by_mac(devices: dict):
    mac_to_host = {}
    for d in devices.values():
        if d.get("mac") and d.get("host"):
            mac_to_host[d["mac"]] = d["host"]
    for d in devices.values():
        if d.get("mac") and not d.get("host") and d["mac"] in mac_to_host:
            d["host"] = mac_to_host[d["mac"]]
            d["_host_rank"] = max(int(d.get("_host_rank") or 0), 50)
            add_source(d, "Name by MAC")


def seed_managed_devices(devices: dict, cfg: dict):
    for m in cfg.get("devices") or []:
        ip = str(m.get("ip") or "").strip()
        name = str(m.get("name") or "").strip()
        if ip or name:
            merge_device(devices, ip=ip, host=name, source="Managed Device")


def apply_tailscale_classification(devices: dict):
    for d in devices.values():
        ip = d.get("ip") or ""
        if is_tailscale_ip(ip):
            d["connection"] = "Tailscale"
            d["tailscale_ip"] = ip
            if d.get("host") and not d.get("tailscale_host"):
                d["tailscale_host"] = d.get("host")
            if d.get("fqdn") and not d.get("tailscale_fqdn"):
                d["tailscale_fqdn"] = d.get("fqdn")
            add_source(d, "Tailscale")


def strip_internal_fields(devices: list[dict]):
    for d in devices:
        for k in list(d.keys()):
            if k.startswith("_"):
                d.pop(k, None)


def ip_sort_key(row):
    parts = (row.get("ip") or "999.999.999.999").split(".")
    return tuple(int(p) if p.isdigit() else 999 for p in parts)


def apply_preferences(devices: dict, cfg: dict):
    prefs = cfg.get("preferences") or {}
    for d in devices.values():
        key = d.get("mac") or d.get("ip") or d.get("host") or ""
        pref = (prefs.get(key) or {}).get("preferred_ap") if key else None
        d["preferred_ap"] = pref or "Auto"


def collect_inventory(cfg: dict) -> list[dict]:
    devices = {}

    seed_managed_devices(devices, cfg)

    for ip in cfg.get("piholes", []):
        collect_pihole(devices, ip, cfg)

    collect_openwrt_neighbours(devices, cfg)
    collect_wifi_live(devices, cfg)
    apply_active_probes(devices, cfg)
    collect_wifi_history(devices, cfg)
    apply_preferences(devices, cfg)
    fill_missing_hosts_by_mac(devices)
    apply_tailscale_classification(devices)

    rows = list(devices.values())
    rows.sort(key=ip_sort_key)
    strip_internal_fields(rows)
    return rows
