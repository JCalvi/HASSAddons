from .models import norm_mac, merge_device, add_source, is_ipv4
from .sshutil import ssh_cmd

AP_CLIENTS = r'''
AP="$(uci -q get system.@system[0].hostname)"
[ -z "$AP" ] && AP="$(cat /proc/sys/kernel/hostname 2>/dev/null)"
for dev in $(iw dev | awk '/Interface/ {print $2}'); do
  info="$(iw dev "$dev" info 2>/dev/null)"
  ssid="$(echo "$info" | awk -F'ssid ' '/ssid/ {print $2; exit}')"
  channel="$(echo "$info" | awk '/channel/ {print $2; exit}')"
  band=""
  [ "$channel" -lt 15 ] 2>/dev/null && band="2.4 GHz"
  [ "$channel" -ge 15 ] 2>/dev/null && band="5 GHz"
  [ -z "$ssid" ] && continue
  iw dev "$dev" station dump 2>/dev/null | awk -v ssid="$ssid" -v ap="$AP" -v band="$band" -v dev="$dev" '
    /^Station / {mac=$2}
    /^[[:space:]]*signal:/ {sig=$2}
    /^$/ { if(mac!="") print mac "|" ssid "|" ap "|" sig "|" band "|" dev; mac=""; sig="" }
    END { if(mac!="") print mac "|" ssid "|" ap "|" sig "|" band "|" dev }
  '
done
'''

AP_HISTORY = r'''
AP="$(uci -q get system.@system[0].hostname)"
[ -z "$AP" ] && AP="$(cat /proc/sys/kernel/hostname 2>/dev/null)"
for dev in $(iw dev | awk '/Interface/ {print $2}'); do
  ssid="$(iw dev "$dev" info 2>/dev/null | awk -F'ssid ' '/ssid/ {print $2; exit}')"
  [ -z "$ssid" ] && continue
  logread | grep "hostapd: $dev:" | grep -Ei "AP-STA-CONNECTED|AP-STA-DISCONNECTED" | while read line; do
    event="$(echo "$line" | grep -oE "AP-STA-CONNECTED|AP-STA-DISCONNECTED")"
    mac="$(echo "$line" | grep -oE "([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}" | tail -1 | tr A-F a-f)"
    when="$(echo "$line" | awk '{print $1" "$2" "$3" "$4" "$5}')"
    [ -n "$mac" ] && echo "$mac|$event|$ssid|$AP|$when"
  done
done
'''



def _creds_for_ip(cfg: dict, ip: str):
    for d in cfg.get("devices") or []:
        if str(d.get("ip") or "").strip() == str(ip):
            return d.get("user") or cfg.get("ssh_user", "root"), d.get("ssh_key_path") or cfg.get("ssh_key_path", "")
    return cfg.get("ssh_user", "root"), cfg.get("ssh_key_path", "")

def collect_wifi_live(devices: dict, cfg: dict):
    for ap_ip in cfg.get("access_points", []):
        user, key_path = _creds_for_ip(cfg, ap_ip)
        out = ssh_cmd(ap_ip, user, key_path, AP_CLIENTS, timeout=10)
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            mac, ssid, ap_name, sig, band = parts[:5]
            iface = parts[5] if len(parts) >= 6 else ""
            mac = norm_mac(mac)
            if not mac:
                continue
            d = None
            for existing in devices.values():
                if existing.get("mac") == mac:
                    d = existing
                    break
            if not d:
                d = merge_device(devices, mac=mac, source="Wi-Fi Live")
            if d:
                d["status"] = "online"
                d["connection"] = ssid
                d["ap"] = ap_name
                d["band"] = band
                d["rssi"] = sig
                d["wifi_ap_ip"] = ap_ip
                d["wifi_interface"] = iface
                d["wifi_last_event"] = "Connected"
                d["wifi_last_seen"] = "Now"
                add_source(d, "Wi-Fi Live")


def collect_wifi_history(devices: dict, cfg: dict):
    history = {}
    for ap_ip in cfg.get("access_points", []):
        user, key_path = _creds_for_ip(cfg, ap_ip)
        out = ssh_cmd(ap_ip, user, key_path, AP_HISTORY, timeout=10)
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            mac, event, ssid, ap_name, when = parts[:5]
            mac = norm_mac(mac)
            if mac:
                history[mac] = {"event": event, "ssid": ssid, "ap": ap_name, "when": when}

    for d in devices.values():
        mac = d.get("mac")
        if not mac or mac not in history or "Wi-Fi Live" in d.get("source", ""):
            continue
        h = history[mac]
        if d.get("status") != "online":
            d["status"] = "idle"
        d["connection"] = h["ssid"]
        d["ap"] = h["ap"]
        d["band"] = ""
        d["rssi"] = ""
        d["wifi_last_event"] = "Disconnected" if h["event"] == "AP-STA-DISCONNECTED" else "Connected"
        d["wifi_last_seen"] = h["when"]
        add_source(d, "Wi-Fi Last Seen")


OPENWRT_NEIGHBOURS = """
echo "__NEIGH__"
ip neigh show 2>/dev/null
"""


def _parse_openwrt_neigh(devices: dict, txt: str):
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
                d = merge_device(devices, ip=ip, mac=mac, source="OpenWrt Neighbour")
            if d:
                d["neighbour_state"] = state
                add_source(d, "OpenWrt Neighbour")


def collect_openwrt_neighbours(devices: dict, cfg: dict):
    for dev in cfg.get("devices") or []:
        dtype = dev.get("type") or ""
        if not str(dtype).startswith("OpenWrt"):
            continue
        ip = str(dev.get("ip") or "").strip()
        if not ip:
            continue
        user, key_path = _creds_for_ip(cfg, ip)
        out = ssh_cmd(ip, user, key_path, OPENWRT_NEIGHBOURS, timeout=8)
        _parse_openwrt_neigh(devices, out)

TAILSCALE_STATUS = """
if command -v tailscale >/dev/null 2>&1; then
  tailscale status --json 2>/dev/null
fi
"""


def collect_tailscale_status(devices: dict, cfg: dict):
    """Collect Tailscale peer names from any managed device with tailscale installed."""
    import json
    from .models import is_tailscale_ip
    for dev in cfg.get("devices") or []:
        ip = str(dev.get("ip") or "").strip()
        if not ip:
            continue
        user, key_path = _creds_for_ip(cfg, ip)
        out = ssh_cmd(ip, user, key_path, TAILSCALE_STATUS, timeout=8)
        if not out.strip().startswith("{"):
            continue
        try:
            data = json.loads(out)
        except Exception:
            continue
        items = []
        if isinstance(data.get("Self"), dict):
            items.append(data.get("Self"))
        peers = data.get("Peer") or {}
        if isinstance(peers, dict):
            items.extend([v for v in peers.values() if isinstance(v, dict)])
        for item in items:
            ips = item.get("TailscaleIPs") or []
            host = item.get("HostName") or ""
            dns = item.get("DNSName") or ""
            for ts_ip in ips:
                if not is_tailscale_ip(str(ts_ip)):
                    continue
                d = merge_device(devices, ip=str(ts_ip), host=dns or host, source="Tailscale")
                if d:
                    d["connection"] = "Tailscale"
                    d["tailscale_ip"] = str(ts_ip)
                    if host:
                        d["tailscale_host"] = host
                    if dns:
                        d["tailscale_fqdn"] = dns.strip('.')
                    add_source(d, "Tailscale")
