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


def _masters(options):
    result = []
    primary = str(options.get("master_ip", "")).strip()
    if primary:
        result.append(primary)
    raw = str(options.get("additional_master_ips", "") or "")
    for item in re.split(r"[,;\s]+", raw):
        ip = item.strip()
        if ip and ip not in result:
            result.append(ip)
    return result


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
if index > 0:
    # A manually supplied existing-secondary serial belongs to the primary.
    # Additional masters perform their own physical-secondary detection.
    main.OPTIONS["existing_secondary_serial"] = ""

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
    base_serial = str(options.get("serial", "FA000001")).strip() or "FA000001"
    children = []

    for index, master_ip in enumerate(masters):
        env = os.environ.copy()
        suffix = re.sub(r"[^A-Za-z0-9]", "", master_ip)[-8:] or str(index + 1)
        env["ACTRONQUE_MASTER_IP"] = master_ip
        env["ACTRONQUE_INSTANCE_INDEX"] = str(index)
        env["ACTRONQUE_DISCOVERY_MARKER"] = suffix.lower()
        if index == 0:
            env["ACTRONQUE_TOPIC_PREFIX"] = base_topic
            env["ACTRONQUE_SYNTHETIC_SERIAL"] = base_serial
        else:
            env["ACTRONQUE_TOPIC_PREFIX"] = f"{base_topic}/{suffix.lower()}"
            # Deterministic but distinct synthetic controller serial per master.
            env["ACTRONQUE_SYNTHETIC_SERIAL"] = f"{base_serial[:6]}{index + 1:02d}"
        print(f"Starting QUE instance {index + 1}: {master_ip}", flush=True)
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
