import json
import subprocess
import threading
import time
from typing import Any

from .config import load_config
from .inventory import collect_inventory
from .steering import run_steering_once

MQTT_STATUS = {"enabled": False, "connected": False, "message": "Not started", "topic": "", "last_command": ""}

def _log(msg: str) -> None:
    print(f"MQTT: {msg}", flush=True)

def get_mqtt_status() -> dict:
    return dict(MQTT_STATUS)


def _base_cmd(cfg: dict) -> list[str]:
    cmd = ["-h", cfg.get("mqtt_host") or "", "-p", str(cfg.get("mqtt_port") or 1883)]
    user = cfg.get("mqtt_username") or ""
    pwd = cfg.get("mqtt_password") or ""
    if user:
        cmd += ["-u", user]
    if pwd:
        cmd += ["-P", pwd]
    return cmd


def _pub(cfg: dict, topic: str, payload: Any, retain: bool = False) -> None:
    try:
        full_topic = f"{cfg.get('mqtt_topic_prefix','network_explorer').strip('/')}/{topic.lstrip('/')}"
        data = payload if isinstance(payload, str) else json.dumps(payload)
        cmd = ["mosquitto_pub", *_base_cmd(cfg), "-t", full_topic, "-m", data]
        if retain:
            cmd.append("-r")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass


def _find_row(selector: dict) -> dict | None:
    rows = collect_inventory(load_config())
    ip = str(selector.get("ip") or "").strip().lower()
    mac = str(selector.get("mac") or "").strip().lower()
    host = str(selector.get("host") or selector.get("name") or "").strip().lower()
    for row in rows:
        if ip and str(row.get("ip") or "").lower() == ip:
            return row
        if mac and str(row.get("mac") or "").lower() == mac:
            return row
        if host and str(row.get("host") or "").lower() == host:
            return row
    return None


def _handle_message(cfg: dict, topic: str, message: str) -> None:
    MQTT_STATUS["last_command"] = topic
    _log(f"Command received on {topic}: {message[:200]}")
    prefix = cfg.get("mqtt_topic_prefix", "network_explorer").strip("/")
    rel = topic[len(prefix):].strip("/") if topic.startswith(prefix) else topic
    try:
        payload = json.loads(message) if message.strip().startswith(("{", "[")) else {"value": message.strip()}
    except Exception:
        payload = {"value": message.strip()}

    if rel in {"command/steer", "steer", "service/steer"}:
        row = _find_row(payload if isinstance(payload, dict) else {})
        if not row:
            _pub(cfg, "status/steer", {"ok": False, "error": "Device not found", "request": payload})
            return
        result = run_steering_once(row)
        _pub(cfg, "status/steer", {"ok": True, "request": payload, "results": result})
        return

    if rel in {"command/refresh", "refresh"}:
        rows = collect_inventory(load_config())
        _pub(cfg, "status/refresh", {"ok": True, "count": len(rows)})
        return

    _pub(cfg, "status/error", {"ok": False, "error": "Unknown MQTT command", "topic": topic})


def mqtt_loop() -> None:
    backoff = 30
    while True:
        cfg = load_config()
        if not cfg.get("mqtt_enabled") or not cfg.get("mqtt_host"):
            MQTT_STATUS.update({"enabled": bool(cfg.get("mqtt_enabled")), "connected": False, "message": "Disabled" if not cfg.get("mqtt_enabled") else "No broker host configured", "topic": ""})
            # Disabled means genuinely idle. Check occasionally in case the
            # user enables MQTT from the add-on Configuration page.
            time.sleep(60)
            continue

        prefix = cfg.get("mqtt_topic_prefix", "network_explorer").strip("/")
        topic = f"{prefix}/command/#"
        MQTT_STATUS.update({"enabled": True, "connected": False, "message": f"Connecting to {cfg.get('mqtt_host')}:{cfg.get('mqtt_port')}", "topic": topic})
        _log(MQTT_STATUS["message"])
        _pub(cfg, "status", {"online": True}, retain=True)
        cmd = ["mosquitto_sub", *_base_cmd(cfg), "-t", topic, "-v"]
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            MQTT_STATUS.update({"connected": True, "message": "Connected", "topic": topic})
            _log(f"Connected and subscribed to {topic}")
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split(" ", 1)
                msg_topic = parts[0]
                msg = parts[1] if len(parts) > 1 else ""
                _handle_message(load_config(), msg_topic, msg)
                new_cfg = load_config()
                if (not new_cfg.get("mqtt_enabled") or
                    new_cfg.get("mqtt_host") != cfg.get("mqtt_host") or
                    new_cfg.get("mqtt_topic_prefix") != cfg.get("mqtt_topic_prefix")):
                    break
            backoff = 30
        except Exception as exc:
            MQTT_STATUS.update({"connected": False, "message": str(exc) or "MQTT error"})
            _log(f"Error: {MQTT_STATUS['message']}")
        finally:
            try:
                if proc is not None:
                    proc.terminate()
            except Exception:
                pass

        # If mosquitto_sub exits immediately because the broker is down or the
        # credentials are wrong, do not tight-loop and burn CPU.
        MQTT_STATUS.update({"connected": False, "message": f"Disconnected. Retrying in {backoff} seconds", "topic": topic if 'topic' in locals() else ""})
        _log(MQTT_STATUS["message"])
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def start_mqtt_loop() -> None:
    t = threading.Thread(target=mqtt_loop, daemon=True)
    t.start()
