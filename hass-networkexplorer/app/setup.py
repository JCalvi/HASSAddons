import json
import os
import shlex
import subprocess
from pathlib import Path

from .config import load_config, save_runtime_config

KNOWN_HOSTS = "/tmp/network_explorer_known_hosts"


def _run(cmd, timeout=15, input_text=None):
    try:
        p = subprocess.run(
            cmd,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:
        return 999, "", str(exc)


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


def all_hosts(cfg=None):
    cfg = cfg or load_config()
    hosts = []
    for ip in cfg.get("piholes", []):
        hosts.append({"type": "Pi-hole", "ip": ip})
    for ip in cfg.get("access_points", []):
        hosts.append({"type": "OpenWrt AP", "ip": ip})
    return hosts


def test_host(ip, user, key_path):
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        "-o", "ConnectTimeout=4",
        "-i", key_path,
        f"{user}@{ip}",
        "echo OK && hostname",
    ]
    rc, out, err = _run(cmd, timeout=10)
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    ok = rc == 0 and lines and lines[0] == "OK"
    return {"ip": ip, "ok": ok, "host": lines[1] if len(lines) > 1 else "", "error": "" if ok else (err or out or "SSH test failed")}


def test_connections():
    cfg = load_config()
    ensure_key(cfg)
    results = []
    for h in all_hosts(cfg):
        r = test_host(h["ip"], cfg.get("ssh_user", "root"), cfg.get("ssh_key_path", ""))
        r["type"] = h["type"]
        results.append(r)
    return results


def install_key_on_host(ip, user, password, public_key_text):
    escaped_key = public_key_text.replace("'", "'\\''")
    remote = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qxF '{escaped_key}' ~/.ssh/authorized_keys 2>/dev/null || echo '{escaped_key}' >> ~/.ssh/authorized_keys; "
        "chmod 600 ~/.ssh/authorized_keys && echo OK"
    )
    cmd = [
        "sshpass", "-p", password,
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        "-o", "ConnectTimeout=5",
        f"{user}@{ip}",
        remote,
    ]
    rc, out, err = _run(cmd, timeout=20)
    ok = rc == 0 and "OK" in out
    return {"ip": ip, "ok": ok, "error": "" if ok else (err or out or "Install failed")}


def install_keys(payload):
    cfg = load_config()
    # Allow the setup form to save IPs/user before installing.
    updates = {}
    for key in ["piholes", "access_points", "ssh_user", "ssh_key_path", "ping_workers", "ping_timeout", "tcp_probe", "tcp_ports"]:
        if key in payload:
            updates[key] = payload[key]
    if updates:
        save_runtime_config(updates)
        cfg = load_config()

    password = payload.get("password") or ""
    user = payload.get("ssh_user") or cfg.get("ssh_user", "root")
    if not password:
        raise RuntimeError("Password is required to install keys")

    key = ensure_key(cfg)
    public_key_text = key["public_key_text"]
    results = []
    for h in all_hosts(cfg):
        r = install_key_on_host(h["ip"], user, password, public_key_text)
        r["type"] = h["type"]
        if r["ok"]:
            t = test_host(h["ip"], user, cfg.get("ssh_key_path", ""))
            r["key_ok"] = t["ok"]
            if not t["ok"]:
                r["error"] = t["error"]
        else:
            r["key_ok"] = False
        results.append(r)
    return results
