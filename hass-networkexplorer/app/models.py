import re
import ipaddress

ONLINE_NEIGH_STATES = {"REACHABLE", "DELAY", "PROBE"}
IDLE_NEIGH_STATES = {"STALE"}
OFFLINE_NEIGH_STATES = {"FAILED", "INCOMPLETE"}


def is_ipv4(ip: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", ip or ""))


def is_tailscale_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10")
    except Exception:
        return False


def split_fqdn(host: str) -> tuple[str, str]:
    raw = (host or "").strip().strip(".")
    if not raw or raw == "*" or raw.lower() == "unknown":
        return "", ""
    # Display the short hostname in the table, but preserve the original FQDN
    # for the details panel. Avoid shortening IP-address-like values.
    if "." in raw and not is_ipv4(raw):
        return raw.split(".", 1)[0], raw
    return raw, ""


def host_rank(source: str) -> int:
    # Highest number wins. Managed/SSH-discovered names should beat DNS/PTR
    # names; static reservations should beat transient database names.
    return {
        "Managed Device": 100,
        "SSH": 95,
        "Static DHCP": 90,
        "DHCP Lease": 80,
        "Static DNS": 70,
        "Pi-hole Network": 60,
        "Name by MAC": 50,
    }.get(source or "", 10)


def norm_mac(mac: str) -> str:
    mac = (mac or "").strip().lower()
    return mac if re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", mac) else ""


def clean_host(host: str) -> str:
    short, _fqdn = split_fqdn(host)
    return short


def new_device(ip="", host="", mac="", source="") -> dict:
    short_host, fqdn = split_fqdn(host)
    return {
        "ip": ip or "",
        "host": short_host,
        "fqdn": fqdn,
        "tailscale_ip": ip if is_tailscale_ip(ip or "") else "",
        "tailscale_host": short_host if is_tailscale_ip(ip or "") else "",
        "tailscale_fqdn": fqdn if is_tailscale_ip(ip or "") else "",
        "_host_rank": host_rank(source) if short_host else 0,
        "mac": norm_mac(mac),
        "status": "offline",
        "connection": "Tailscale" if is_tailscale_ip(ip or "") else "Ethernet",
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
    raw_host = host
    short_host, fqdn = split_fqdn(host)
    host = short_host
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
        devices[key] = new_device(ip=ip if is_ipv4(ip) else "", host=raw_host, mac=mac, source=source)

    d = devices[key]
    if is_ipv4(ip):
        d["ip"] = ip
        if is_tailscale_ip(ip):
            d["connection"] = "Tailscale"
            d["tailscale_ip"] = ip
            add_source(d, "Tailscale")
    if host:
        rank = host_rank(source)
        if rank >= int(d.get("_host_rank") or 0) or not d.get("host"):
            d["host"] = host
            d["_host_rank"] = rank
        if fqdn and not d.get("fqdn"):
            d["fqdn"] = fqdn
        if is_tailscale_ip(d.get("ip") or ""):
            if host and not d.get("tailscale_host"):
                d["tailscale_host"] = host
            if fqdn and not d.get("tailscale_fqdn"):
                d["tailscale_fqdn"] = fqdn
    if mac and not d.get("mac"):
        d["mac"] = mac
    add_source(d, source)
    return d
