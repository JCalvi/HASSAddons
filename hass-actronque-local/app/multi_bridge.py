#!/usr/bin/env python3

"""Run one isolated Actron QUE Local bridge per configured QUE master.

The first master keeps the historic MQTT topic namespace. Additional masters get
an IP-derived internal topic namespace; Home Assistant entity identity still
comes from each QUE master's real serial number.
"""

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


def main():
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
        env["ACTRONQUE_MASTER_IP"] = master_ip
        env["ACTRONQUE_INSTANCE_INDEX"] = str(index)
        env["ACTRONQUE_PRIMARY_INSTANCE"] = "1" if index == 0 else "0"
        if index == 0:
            env["ACTRONQUE_TOPIC_PREFIX"] = base_topic
            env["ACTRONQUE_SYNTHETIC_SERIAL"] = base_serial
        else:
            suffix = re.sub(r"[^A-Za-z0-9]", "", master_ip)[-8:] or str(index + 1)
            env["ACTRONQUE_TOPIC_PREFIX"] = f"{base_topic}/{suffix.lower()}"
            # Each QUE must see a distinct synthetic secondary controller.
            env["ACTRONQUE_SYNTHETIC_SERIAL"] = f"{base_serial[:6]}{index + 1:02d}"
        print(f"Starting QUE instance {index + 1}: {master_ip}", flush=True)
        children.append(subprocess.Popen([sys.executable, "/app/ui_bridge.py"], env=env))

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
    raise SystemExit(main())
