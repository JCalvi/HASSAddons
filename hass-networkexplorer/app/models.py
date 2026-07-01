import re

ONLINE_NEIGH_STATES = {"REACHABLE", "DELAY", "PROBE"}
IDLE_NEIGH_STATES = {"STALE"}
OFFLINE_NEIGH_STATES = {"FAILED", "INCOMPLETE"}


def is_ipv4(ip: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", ip or ""))


def norm_mac(mac: str) -> str:
    mac = (mac or "").strip().lower()
    return mac if re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", mac) else ""


def clean_host(host: str) -> str:
    host = (host or "").strip().strip(".")
    if host == "*" or host.lower() == "unknown":
        return ""
    return host


def new_device(ip="", host="", mac="", source="") -> dict:
    return {
        "ip": ip or "",
        "host": clean_host(host),
        "mac": norm_mac(mac),
        "status": "offline",
        "connection": "Ethernet",
        "ap": "",
        "band": "",
        "rssi": "",
        "neighbour_state": "",
        "ping": "",
        "tcp": "",
        "wifi_last_event": "",
        "wifi_last_seen": "",
        "wifi_ap_ip": "",
        "wifi_interface": "",
        "preferred_ap": "Auto",
        "source": source or "",
    }


def add_source(device: dict, source: str) -> None:
    if source and source not in device.get("source", ""):
        device["source"] = (device.get("source", "") + " + " + source).strip(" +")


def merge_device(devices: dict, ip="", host="", mac="", source="") -> dict | None:
    ip = (ip or "").strip()
    host = clean_host(host)
    mac = norm_mac(mac)
    if ip.startswith("127.") or ip.startswith("fe80:"):
        return None
    if not ip and not mac:
        return None

    key = ip if is_ipv4(ip) else None
    if not key and mac:
        for existing_key, d in devices.items():
            if d.get("mac") == mac:
                key = existing_key
                break
    if not key:
        key = mac or ip

    if key not in devices:
        devices[key] = new_device(ip=ip if is_ipv4(ip) else "", host=host, mac=mac, source=source)

    d = devices[key]
    if is_ipv4(ip):
        d["ip"] = ip
    if host:
        if source in {"Static DHCP", "Static DNS"}:
            d["host"] = host
        elif not d.get("host"):
            d["host"] = host
    if mac and not d.get("mac"):
        d["mac"] = mac
    add_source(d, source)
    return d
