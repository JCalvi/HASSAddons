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


def _masters(options):
    return _list(options.get("master_ip", ""))


def _value_for(values, index, default=""):
    if index < len(values):
        return values[index]
    return default


# This wrapper deliberately imports main first, then overrides that process's
# in-memory OPTIONS before ui_bridge is imported. This keeps each bridge fully
# isolated without changing the proven single-unit bridge classes.
CHILD_CODE = r'''
import os
from pathlib import Path
import main

index = int(os.environ["ACTRONQUE_INSTANCE_INDEX"])
main.OPTIONS["master_ip"] = os.environ["ACTRONQUE_MASTER_IP"]
main.OPTIONS["topic_prefix"] = os.environ["ACTRONQUE_TOPIC_PREFIX"]
main.OPTIONS["serial"] = os.environ["ACTRONQUE_SYNTHETIC_SERIAL"]
main.OPTIONS["existing_secondary_serial"] = os.environ.get("ACTRONQUE_EXISTING_SECONDARY_SERIAL", "")

import secondary_setup
secondary_setup.STATE_FILE = Path(f"/data/secondary_setup_{index}.json") if index else Path("/data/secondary_setup.json")

from ui_bridge import ActronQueLocalBridge
bridge = ActronQueLocalBridge()

if index > 0:
    # MQTT Discovery config topics must be unique per QUE. Entity/device IDs
    # remain cloud-compatible because those are derived from the real master
    # serial after WallLink connects.
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
    masters = _masters(options)
    if not masters:
        print("No QUE master IP configured", flush=True)
        return 1

    base_topic = str(options.get("topic_prefix", "hass-actronque-local")).rstrip("/")
    synthetic_serials = _list(options.get("serial", "FA000001"))
    existing_secondaries = _list(options.get("existing_secondary_serial", ""))
    base_serial = synthetic_serials[0] if synthetic_serials else "FA000001"
    children = []

    if len(synthetic_serials) > len(masters):
        print("Warning: more synthetic secondary serials than QUE master IPs; extras will be ignored", flush=True)
    if len(existing_secondaries) > len(masters):
        print("Warning: more existing secondary serials than QUE master IPs; extras will be ignored", flush=True)

    for index, master_ip in enumerate(masters):
        env = os.environ.copy()
        suffix = re.sub(r"[^A-Za-z0-9]", "", master_ip)[-8:] or str(index + 1)
        env["ACTRONQUE_MASTER_IP"] = master_ip
        env["ACTRONQUE_INSTANCE_INDEX"] = str(index)
        env["ACTRONQUE_DISCOVERY_MARKER"] = suffix.lower()
        if index == 0:
            env["ACTRONQUE_TOPIC_PREFIX"] = base_topic
        else:
            env["ACTRONQUE_TOPIC_PREFIX"] = f"{base_topic}/{suffix.lower()}"

        # Serial lists map positionally to master_ip. For backwards
        # compatibility a single serial still works exactly as before. If a
        # multi-master installation supplies fewer synthetic serials than
        # masters, deterministic unique serials are generated for the rest.
        synthetic = _value_for(synthetic_serials, index)
        if not synthetic:
            synthetic = f"{base_serial[:6]}{index + 1:02d}"
        env["ACTRONQUE_SYNTHETIC_SERIAL"] = synthetic
        env["ACTRONQUE_EXISTING_SECONDARY_SERIAL"] = _value_for(existing_secondaries, index)

        print(
            f"Starting QUE instance {index + 1}: {master_ip} "
            f"(synthetic secondary {synthetic})",
            flush=True,
        )
        children.append(subprocess.Popen([sys.executable, "-c", CHILD_CODE], env=env))

    stopping = False

    def stop_children(*_):
        nonlocal stopping
        if stopping:
            return
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop_children)
    signal.signal(signal.SIGINT, stop_children)

    try:
        while not stopping:
            for child in children:
                rc = child.poll()
                if rc is not None:
                    print(f"QUE bridge process exited unexpectedly with code {rc}", flush=True)
                    stop_children()
                    return rc or 1
            time.sleep(1)
    finally:
        stop_children()
        deadline = time.monotonic() + 10
        for child in children:
            remaining = max(0, deadline - time.monotonic())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
