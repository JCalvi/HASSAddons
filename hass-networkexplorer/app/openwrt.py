from .models import norm_mac, merge_device, add_source
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


def collect_wifi_live(devices: dict, cfg: dict):
    for ap_ip in cfg.get("access_points", []):
        out = ssh_cmd(ap_ip, cfg["ssh_user"], cfg.get("ssh_key_path", ""), AP_CLIENTS, timeout=10)
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
        out = ssh_cmd(ap_ip, cfg["ssh_user"], cfg.get("ssh_key_path", ""), AP_HISTORY, timeout=10)
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
