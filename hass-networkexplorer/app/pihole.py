import re
from .models import merge_device, is_ipv4, norm_mac
from .sshutil import ssh_cmd

REMOTE_COLLECT = r'''
for f in /etc/pihole/pihole.toml /etc/pihole/custom.list /etc/hosts /etc/pihole/dhcp.leases /var/lib/misc/dnsmasq.leases /etc/dnsmasq.d/04-pihole-static-dhcp.conf; do
  if [ -r "$f" ]; then
    echo "__FILE__$f"
    cat "$f" 2>/dev/null
    echo "__END_FILE__"
  fi
done

echo "__NEIGH__"
ip neigh show 2>/dev/null

echo "__DB__"
if command -v sqlite3 >/dev/null 2>&1 && [ -r /etc/pihole/pihole-FTL.db ]; then
  sqlite3 -separator '|' /etc/pihole/pihole-FTL.db "SELECT n.hwaddr, a.ip, n.name FROM network n LEFT JOIN network_addresses a ON n.id = a.network_id;" 2>/dev/null
fi
'''


def _split_sections(text: str) -> tuple[dict, str, str]:
    files = {}
    current = None
    neigh = []
    db = []
    mode = None
    for line in text.splitlines():
        if line.startswith("__FILE__"):
            current = line.replace("__FILE__", "", 1)
            files[current] = []
            mode = "file"
        elif line == "__END_FILE__":
            current = None
            mode = None
        elif line == "__NEIGH__":
            mode = "neigh"
        elif line == "__DB__":
            mode = "db"
        elif mode == "file" and current:
            files[current].append(line)
        elif mode == "neigh":
            neigh.append(line)
        elif mode == "db":
            db.append(line)
    return {k: "\n".join(v) for k, v in files.items()}, "\n".join(neigh), "\n".join(db)


def _parse_pihole_toml(devices, txt: str):
    for block in re.findall(r"hosts\s*=\s*\[(.*?)\]", txt or "", re.S):
        for entry in re.findall(r'"([^"]+)"', block):
            parts = [p.strip() for p in entry.split(",")]
            mac = ip = host = ""
            for p in parts:
                if norm_mac(p):
                    mac = p
                elif is_ipv4(p):
                    ip = p
                elif p and p != "*" and p.lower() not in {"infinite", "ignore"} and not p.startswith(("id:", "set:", "tag:")):
                    if not host:
                        host = p
            if mac and ip:
                merge_device(devices, ip=ip, host=host, mac=mac, source="Static DHCP")


def _parse_custom_list(devices, txt: str, source: str):
    for line in (txt or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and is_ipv4(parts[0]) and not parts[0].startswith("127."):
            merge_device(devices, ip=parts[0], host=parts[1], source=source)


def _parse_static_dhcp_conf(devices, txt: str):
    for line in (txt or "").splitlines():
        m = re.search(r"dhcp-host=([0-9a-fA-F:]{17}),([0-9.]+),?([^,]*)?", line)
        if m:
            merge_device(devices, ip=m.group(2), host=m.group(3) or "", mac=m.group(1), source="Static DHCP")


def _parse_leases(devices, txt: str):
    for line in (txt or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and is_ipv4(parts[2]):
            merge_device(devices, ip=parts[2], host=parts[3], mac=parts[1], source="DHCP Lease")


def _parse_neigh(devices, txt: str):
    for line in (txt or "").splitlines():
        parts = line.split()
        if not parts or not is_ipv4(parts[0]):
            continue
        ip = parts[0]
        mac = ""
        if "lladdr" in parts:
            i = parts.index("lladdr")
            if i + 1 < len(parts):
                mac = norm_mac(parts[i + 1])
        state = parts[-1] if parts else ""
        if ip and mac:
            d = None
            for existing in devices.values():
                if existing.get("mac") == mac or existing.get("ip") == ip:
                    d = existing
                    break
            if not d:
                d = merge_device(devices, ip=ip, mac=mac, source="Neighbour")
            if d:
                d["neighbour_state"] = state
                # Neighbour state is diagnostic only. Ping/Wi-Fi decides online.
                from .models import add_source
                add_source(d, "Neighbour")


def _parse_db(devices, txt: str):
    for line in (txt or "").splitlines():
        parts = line.split("|")
        if len(parts) >= 2:
            mac = parts[0] if len(parts) > 0 else ""
            ip = parts[1] if len(parts) > 1 else ""
            host = parts[2] if len(parts) > 2 else ""
            if ip and is_ipv4(ip):
                merge_device(devices, ip=ip, host=host, mac=mac, source="Pi-hole Network")



def _creds_for_ip(cfg: dict, ip: str):
    for d in cfg.get("devices") or []:
        if str(d.get("ip") or "").strip() == str(ip):
            return d.get("user") or cfg.get("ssh_user", "root"), d.get("ssh_key_path") or cfg.get("ssh_key_path", "")
    return cfg.get("ssh_user", "root"), cfg.get("ssh_key_path", "")

def collect_pihole(devices: dict, ip: str, cfg: dict):
    user, key_path = _creds_for_ip(cfg, ip)
    out = ssh_cmd(ip, user, key_path, REMOTE_COLLECT, timeout=10)
    files, neigh, db = _split_sections(out)
    _parse_pihole_toml(devices, files.get("/etc/pihole/pihole.toml", ""))
    _parse_custom_list(devices, files.get("/etc/pihole/custom.list", ""), "Static DNS")
    _parse_custom_list(devices, files.get("/etc/hosts", ""), "Static DNS")
    _parse_static_dhcp_conf(devices, files.get("/etc/dnsmasq.d/04-pihole-static-dhcp.conf", ""))
    _parse_leases(devices, files.get("/etc/pihole/dhcp.leases", ""))
    _parse_leases(devices, files.get("/var/lib/misc/dnsmasq.leases", ""))
    _parse_db(devices, db)
    _parse_neigh(devices, neigh)
