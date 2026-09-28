#!/usr/bin/env python3

"""Run one isolated Actron QUE Local bridge per configured QUE master."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

OPTIONS_FILE = Path("/data/options.json")
DEFAULT_WALLLINK_PORT = 19296


def _options():
    try:
        with OPTIONS_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _list(value):
    """Accept one value or a comma/semicolon/whitespace separated list."""
    result = []
    for item in re.split(r"[,;\s]+", str(value or "")):
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result


def _parse_endpoint(value):
    """Return (host, port); old host-only values remain valid on port 19296."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("empty QUE master address")
    if value.count(":") == 1:
        host, port_text = value.rsplit(":", 1)
        host = host.strip()
        if not host:
            raise ValueError(f"invalid QUE master address: {value!r}")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(f"invalid WallLink port in {value!r}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"WallLink port out of range in {value!r}")
        return host, port
    return value, DEFAULT_WALLLINK_PORT


def _masters(options):
    return [_parse_endpoint(value) for value in _list(options.get("master_ip", ""))]


def _value_for(values, index, default=""):
    if index < len(values):
        return values[index]
    return default


CHILD_CODE = r'''
import os
from pathlib import Path
import main

index = int(os.environ["ACTRONQUE_INSTANCE_INDEX"])
main.OPTIONS["master_ip"] = os.environ["ACTRONQUE_MASTER_IP"]
main.OPTIONS["master_port"] = int(os.environ["ACTRONQUE_MASTER_PORT"])
main.OPTIONS["topic_prefix"] = os.environ["ACTRONQUE_TOPIC_PREFIX"]
main.OPTIONS["serial"] = os.environ["ACTRONQUE_SYNTHETIC_SERIAL"]
main.OPTIONS["existing_secondary_serial"] = os.environ.get("ACTRONQUE_EXISTING_SECONDARY_SERIAL", "")

import secondary_setup
secondary_setup.STATE_FILE = Path(f"/data/secondary_setup_{index}.json") if index else Path("/data/secondary_setup.json")

from ui_bridge import ActronQueLocalBridge
bridge = ActronQueLocalBridge()

if index > 0:
    original_publish = bridge.mqtt_publish
    marker = os.environ["ACTRONQUE_DISCOVERY_MARKER"]
    discovery_prefix = bridge.discovery_prefix + "/"
    def isolated_publish(topic, payload, retain=False):
        if topic.startswith(discovery_prefix) and topic.endswith("/config"):
            parts = topic.split("/")
            if len(parts) >= 5:
                parts[-3] = parts[-3] + "_" + marker
                topic = "/".join(parts)
        return original_publish(topic, payload, retain)
    bridge.mqtt_publish = isolated_publish

bridge.run()
'''


def main_entry():
    options = _options()
    try:
        masters = _masters(options)
    except ValueError as exc:
        print(f"Invalid QUE master configuration: {exc}", flush=True)
        return 1
    if not masters:
        print("No QUE master IP configured", flush=True)
        return 1

    base_topic = str(options.get("topic_prefix", "hass-actronque-local")).rstrip("/")
    synthetic_serials = _list(options.get("serial", "FA000001"))
    existing_secondaries = _list(options.get("existing_secondary_serial", ""))
    base_serial = synthetic_serials[0] if synthetic_serials else "FA000001"
    children = []

    if len(synthetic_serials) > len(masters):
        print("Warning: more synthetic secondary serials than QUE masters; extras will be ignored", flush=True)
    if len(existing_secondaries) > len(masters):
        print("Warning: more existing secondary serials than QUE masters; extras will be ignored", flush=True)

    for index, (master_ip, master_port) in enumerate(masters):
        env = os.environ.copy()
        endpoint = f"{master_ip}:{master_port}"
        suffix = re.sub(r"[^A-Za-z0-9]", "", master_ip)[-8:] or str(index + 1)
        env["ACTRONQUE_MASTER_IP"] = master_ip
        env["ACTRONQUE_MASTER_PORT"] = str(master_port)
        env["ACTRONQUE_INSTANCE_INDEX"] = str(index)
        env["ACTRONQUE_DISCOVERY_MARKER"] = suffix.lower()
        env["ACTRONQUE_TOPIC_PREFIX"] = base_topic if index == 0 else f"{base_topic}/{suffix.lower()}"

        synthetic = _value_for(synthetic_serials, index)
        if not synthetic:
            synthetic = f"{base_serial[:6]}{index + 1:02d}"
        env["ACTRONQUE_SYNTHETIC_SERIAL"] = synthetic
        env["ACTRONQUE_EXISTING_SECONDARY_SERIAL"] = _value_for(existing_secondaries, index)

        print(f"Starting QUE instance {index + 1}: {endpoint} (synthetic secondary {synthetic})", flush=True)
        children.append(subprocess.Popen([sys.executable, "-c", CHILD_CODE], env=env))

    stopping = False

    def stop_children(*_):
        nonlocal stopping
        if stopping: return
        stopping = True
        for child in children:
            if child.poll() is None: child.terminate()

    signal.signal(signal.SIGTERM, stop_children); signal.signal(signal.SIGINT, stop_children)
    try:
        while not stopping:
            for child in children:
                rc = child.poll()
                if rc is not None:
                    print(f"QUE bridge process exited unexpectedly with code {rc}", flush=True); stop_children(); return rc or 1
            time.sleep(1)
    finally:
        stop_children(); deadline = time.monotonic() + 10
        for child in children:
            remaining = max(0, deadline - time.monotonic())
            try: child.wait(timeout=remaining)
            except subprocess.TimeoutExpired: child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
