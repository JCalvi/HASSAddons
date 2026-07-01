import json
import threading
import time
from pathlib import Path

from .config import load_config, save_runtime_config
from .inventory import collect_inventory
from .sshutil import ssh_cmd

STATE_FILE = Path('/config/networkexplorer/steering_state.json')


def _read_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return {}


def _write_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def device_key(row):
    return row.get('mac') or row.get('ip') or row.get('host') or ''


def get_preferences(cfg=None):
    cfg = cfg or load_config()
    prefs = cfg.get('preferences') or {}
    if not isinstance(prefs, dict):
        prefs = {}
    return prefs


def save_preferences(payload):
    cfg = load_config()
    prefs = get_preferences(cfg)
    updates = payload.get('preferences') or {}
    for k, v in updates.items():
        if not k:
            continue
        if not v or v == 'Auto':
            prefs.pop(k, None)
        else:
            prefs[k] = {'preferred_ap': str(v)}
    steering = payload.get('steering') or {}
    save_runtime_config({
        'preferences': prefs,
        'steering_enabled': bool(steering.get('enabled', cfg.get('steering_enabled', False))),
        'steering_interval_minutes': int(steering.get('interval_minutes', cfg.get('steering_interval_minutes', 10)) or 10),
        'steering_cooldown_minutes': int(steering.get('cooldown_minutes', cfg.get('steering_cooldown_minutes', 30)) or 30),
    })
    return load_config()


def managed_user_for_ip(cfg, ip):
    for d in cfg.get('devices') or []:
        if str(d.get('ip') or '').strip() == str(ip):
            return d.get('user') or cfg.get('ssh_user', 'root')
    return cfg.get('ssh_user', 'root')


def disassociate(row, reason='manual'):
    cfg = load_config()
    ap_ip = row.get('wifi_ap_ip') or ''
    iface = row.get('wifi_interface') or ''
    mac = row.get('mac') or ''
    if not ap_ip or not iface or not mac:
        return {'ok': False, 'error': 'Current Wi-Fi AP/interface is not known for this device.', 'row': row}
    user = managed_user_for_ip(cfg, ap_ip)
    key = cfg.get('ssh_key_path', '')
    remote = """MAC='%s'
IFACE='%s'
if command -v hostapd_cli >/dev/null 2>&1; then
  hostapd_cli -i \"$IFACE\" disassociate \"$MAC\" >/dev/null 2>&1 && echo OK_HOSTAPD && exit 0
fi
if command -v iw >/dev/null 2>&1; then
  iw dev \"$IFACE\" station del \"$MAC\" >/dev/null 2>&1 && echo OK_IW && exit 0
fi
echo FAILED
exit 1
""" % (mac, iface)
    out = ssh_cmd(ap_ip, user, key, remote, timeout=10)
    ok = 'OK_HOSTAPD' in out or 'OK_IW' in out
    return {'ok': ok, 'output': out, 'ap_ip': ap_ip, 'interface': iface, 'mac': mac, 'reason': reason, 'error': '' if ok else (out or 'Disassociate failed')}


def run_steering_once(manual_row=None):
    cfg = load_config()
    prefs = get_preferences(cfg)
    state = _read_state()
    now = time.time()
    cooldown = int(cfg.get('steering_cooldown_minutes', 30)) * 60
    results = []
    rows = [manual_row] if manual_row else collect_inventory(cfg)
    for row in rows:
        if not row:
            continue
        k = device_key(row)
        pref = row.get('preferred_ap') or (prefs.get(k) or {}).get('preferred_ap') or 'Auto'
        if not pref or pref == 'Auto':
            if manual_row:
                results.append({'ok': False, 'error': 'Preferred AP is Auto.', 'device': k})
            continue
        if row.get('status') != 'online' or not row.get('mac') or not row.get('ap'):
            if manual_row:
                results.append({'ok': False, 'error': 'Device is not currently visible as a live Wi-Fi client.', 'device': k})
            continue
        if row.get('ap') == pref:
            if manual_row:
                results.append({'ok': True, 'skipped': True, 'message': 'Already on preferred AP.', 'device': k})
            continue
        if not manual_row and now - float(state.get(k, 0) or 0) < cooldown:
            continue
        r = disassociate(row, reason='manual' if manual_row else 'scheduled')
        r['device'] = k
        r['preferred_ap'] = pref
        r['current_ap'] = row.get('ap')
        if r.get('ok'):
            state[k] = now
        results.append(r)
    _write_state(state)
    return results


def steering_loop():
    while True:
        try:
            cfg = load_config()
            interval = max(1, int(cfg.get('steering_interval_minutes', 10))) * 60
            if cfg.get('steering_enabled'):
                run_steering_once()
            time.sleep(interval)
        except Exception:
            time.sleep(60)


def start_steering_loop():
    t = threading.Thread(target=steering_loop, daemon=True)
    t.start()
