import os
import subprocess
from pathlib import Path

from .config import load_config, save_runtime_config

KNOWN_HOSTS = "/dev/null"


def _run(cmd, timeout=15, input_text=None, env=None):
    try:
        p = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            env=env,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:
        return 999, "", str(exc)


def sh_quote(value: str) -> str:
    # POSIX-safe single-quote escaping for remote shell commands.
    return "'" + str(value).replace("'", "'\''") + "'"


def password_ssh(ip, user, password, remote_cmd, timeout=25):
    env = os.environ.copy()
    env["SSHPASS"] = password or ""
    cmd = [
        "sshpass", "-e",
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "NumberOfPasswordPrompts=1",
        "-o", "ConnectTimeout=5",
        f"{user}@{ip}",
        remote_cmd,
    ]
    return _run(cmd, timeout=timeout, env=env)


def detect_remote_os(ip, user, password):
    probe = (
        "if [ -f /etc/openwrt_release ]; then echo OPENWRT; cat /etc/openwrt_release; "
        "elif [ -f /etc/os-release ]; then cat /etc/os-release; "
        "elif [ -f /etc/debian_version ]; then echo DEBIAN; cat /etc/debian_version; "
        "else uname -a; fi"
    )
    rc, out, err = password_ssh(ip, user, password, probe, timeout=15)
    raw = (out or err or "").strip()
    low = raw.lower()
    if rc != 0:
        return {"ok": False, "os": "unknown", "profile": "unknown", "raw": raw, "error": err or out or "OS detection failed"}
    if "openwrt" in low:
        return {"ok": True, "os": "OpenWrt", "profile": "openwrt", "raw": raw, "error": ""}
    if "debian" in low or "raspbian" in low or "ubuntu" in low or "dietpi" in low:
        return {"ok": True, "os": "Linux", "profile": "linux", "raw": raw, "error": ""}
    return {"ok": True, "os": "Linux", "profile": "linux", "raw": raw, "error": ""}


def key_paths(cfg=None):
    cfg = cfg or load_config()
    private_key = Path(cfg.get("ssh_key_path") or "/config/ssh/id_ed25519")
    public_key = Path(str(private_key) + ".pub")
    return private_key, public_key


def ensure_key(cfg=None):
    private_key, public_key = key_paths(cfg)
    private_key.parent.mkdir(parents=True, exist_ok=True)
    if not private_key.exists() or not public_key.exists():
        rc, out, err = _run([
            "ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(private_key), "-C", "network-explorer"
        ], timeout=20)
        if rc != 0:
            raise RuntimeError(err or out or "ssh-keygen failed")
        private_key.chmod(0o600)
        public_key.chmod(0o644)
    return {
        "private_key": str(private_key),
        "public_key": str(public_key),
        "public_key_text": public_key.read_text().strip() if public_key.exists() else "",
        "exists": private_key.exists() and public_key.exists(),
    }


def key_status():
    cfg = load_config()
    private_key, public_key = key_paths(cfg)
    return {
        "private_key": str(private_key),
        "public_key": str(public_key),
        "exists": private_key.exists() and public_key.exists(),
        "public_key_text": public_key.read_text().strip() if public_key.exists() else "",
    }


def configured_devices(cfg=None):
    cfg = cfg or load_config()
    saved = cfg.get("devices") or []
    if saved:
        out = []
        for d in saved:
            ip = str(d.get("ip") or "").strip()
            if not ip:
                continue
            out.append({
                "type": d.get("type") or "Host",
                "ip": ip,
                "user": d.get("user") or cfg.get("ssh_user", "root"),
                "name": d.get("name") or "",
            })
        return out

    out = []
    for ip in cfg.get("piholes", []):
        out.append({"type": "Pi-hole", "ip": ip, "user": cfg.get("ssh_user", "root"), "name": ""})
    for ip in cfg.get("access_points", []):
        out.append({"type": "OpenWrt AP", "ip": ip, "user": cfg.get("ssh_user", "root"), "name": ""})
    return out


def save_devices_from_payload(payload):
    devices = []
    for d in payload.get("devices") or []:
        ip = str(d.get("ip") or "").strip()
        if not ip:
            continue
        devices.append({
            "type": d.get("type") or "Host",
            "ip": ip,
            "user": d.get("user") or payload.get("ssh_user") or "root",
            "name": d.get("name") or "",
        })

    if not devices:
        for ip in payload.get("piholes", []) or []:
            if str(ip).strip():
                devices.append({"type": "Pi-hole", "ip": str(ip).strip(), "user": payload.get("ssh_user") or "root", "name": ""})
        for ip in payload.get("access_points", []) or []:
            if str(ip).strip():
                devices.append({"type": "OpenWrt AP", "ip": str(ip).strip(), "user": payload.get("ssh_user") or "root", "name": ""})

    piholes = [d["ip"] for d in devices if d.get("type") == "Pi-hole"]
    aps = [d["ip"] for d in devices if d.get("type") == "OpenWrt AP"]
    updates = {
        "devices": devices,
        "piholes": piholes,
        "access_points": aps,
    }
    for key in ["ssh_user", "ssh_key_path", "ping_workers", "ping_timeout", "tcp_probe", "tcp_ports"]:
        if key in payload:
            updates[key] = payload[key]
    save_runtime_config(updates)
    return load_config()


def test_host(ip, user, key_path):
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "LogLevel=ERROR",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        "-o", "ConnectTimeout=4",
        "-o", "IdentitiesOnly=yes",
        "-i", key_path,
        f"{user}@{ip}",
        "echo OK && hostname",
    ]
    rc, out, err = _run(cmd, timeout=10)
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    ok = rc == 0 and lines and lines[0] == "OK"
    return {"ip": ip, "user": user, "ok": ok, "host": lines[1] if len(lines) > 1 else "", "error": "" if ok else (err or out or "SSH test failed")}


def test_connections(payload=None):
    cfg = load_config()
    if payload and (payload.get("devices") or payload.get("piholes") or payload.get("access_points")):
        cfg = save_devices_from_payload(payload)
    ensure_key(cfg)
    results = []
    for h in configured_devices(cfg):
        r = test_host(h["ip"], h.get("user") or cfg.get("ssh_user", "root"), cfg.get("ssh_key_path", ""))
        r["type"] = h["type"]
        r["name"] = h.get("name", "")
        results.append(r)
    return results


def install_key_on_host(ip, user, password, public_key_text):
    detected = detect_remote_os(ip, user, password)
    if not detected.get("ok"):
        return {
            "ip": ip,
            "user": user,
            "ok": False,
            "detected_os": detected.get("os", "unknown"),
            "profile": detected.get("profile", "unknown"),
            "install_path": "",
            "error": detected.get("error") or "Authentication failed",
            "os_detail": detected.get("raw", ""),
        }

    key = sh_quote(public_key_text)
    profile = detected.get("profile")

    if profile == "openwrt":
        install_path = "/etc/dropbear/authorized_keys"
        remote = (
            "umask 077; "
            "mkdir -p /etc/dropbear /root/.ssh; "
            "touch /etc/dropbear/authorized_keys /root/.ssh/authorized_keys; "
            "chmod 600 /etc/dropbear/authorized_keys /root/.ssh/authorized_keys; "
            "grep -qxF " + key + " /etc/dropbear/authorized_keys 2>/dev/null || printf '%s\n' " + key + " >> /etc/dropbear/authorized_keys; "
            "grep -qxF " + key + " /root/.ssh/authorized_keys 2>/dev/null || printf '%s\n' " + key + " >> /root/.ssh/authorized_keys; "
            "chmod 600 /etc/dropbear/authorized_keys /root/.ssh/authorized_keys; "
            "echo OK_OPENWRT"
        )
    else:
        install_path = "~/.ssh/authorized_keys"
        remote = (
            "umask 077; "
            "mkdir -p ~/.ssh; "
            "touch ~/.ssh/authorized_keys; "
            "chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; "
            "grep -qxF " + key + " ~/.ssh/authorized_keys 2>/dev/null || printf '%s\n' " + key + " >> ~/.ssh/authorized_keys; "
            "chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; "
            "echo OK_LINUX"
        )

    rc, out, err = password_ssh(ip, user, password, remote, timeout=25)
    ok = rc == 0 and ("OK_OPENWRT" in out or "OK_LINUX" in out or "OK" in out)
    return {
        "ip": ip,
        "user": user,
        "ok": ok,
        "detected_os": detected.get("os", "unknown"),
        "profile": profile,
        "install_path": install_path,
        "os_detail": detected.get("raw", ""),
        "error": "" if ok else (err or out or "Install failed"),
    }


def install_keys(payload):
    cfg = save_devices_from_payload(payload)
    key = ensure_key(cfg)
    public_key_text = key["public_key_text"]
    requested_ip = str(payload.get("ip") or "").strip()
    payload_devices = payload.get("devices") or []
    results = []

    for h in configured_devices(cfg):
        if requested_ip and h["ip"] != requested_ip:
            continue
        pdev = next((d for d in payload_devices if str(d.get("ip") or "").strip() == h["ip"]), {})
        password = pdev.get("password") or payload.get("password") or ""
        user = pdev.get("user") or h.get("user") or cfg.get("ssh_user", "root")
        r = {"ip": h["ip"], "type": h["type"], "name": h.get("name", ""), "user": user}
        if not password:
            r.update({"ok": False, "key_ok": False, "error": "Password required for this device"})
            results.append(r)
            continue
        installed = install_key_on_host(h["ip"], user, password, public_key_text)
        r.update(installed)
        if r["ok"]:
            t = test_host(h["ip"], user, cfg.get("ssh_key_path", ""))
            r["key_ok"] = t["ok"]
            r["host"] = t.get("host", "")
            if not t["ok"]:
                r["error"] = t["error"]
        else:
            r["key_ok"] = False
        results.append(r)
    return results
