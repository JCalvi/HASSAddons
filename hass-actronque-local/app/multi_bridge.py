#!/usr/bin/env python3

"""Run one isolated Actron QUE Local bridge per configured QUE master.

Normal WallLink operation runs concurrently. First-time automatic secondary
setup is serialized across masters so UDP discovery/pairing cannot overlap.
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
DEFAULT_WALLLINK_PORT = 19296
SETUP_POLL_SECONDS = 1


def _options():
    try:
        with OPTIONS_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _list(value):
    result = []
    for item in re.split(r"[,;\s]+", str(value or "")):
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return result


def _parse_endpoint(value):
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
    return values[index] if index < len(values) else default


def _setup_state_file(index):
    return Path(f"/data/secondary_setup_{index}.json") if index else Path("/data/secondary_setup.json")


def _setup_complete(index):
    path = _setup_state_file(index)
    try:
        if not path.exists():
            return False
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        return isinstance(state, dict) and bool(state.get("completed"))
    except Exception:
        return False


CHILD_CODE = r'''
import os
from pathlib import Path
import main
import walllink_codec

# main.py briefly regressed from the proven QUE wire format to raw encrypted
# newline-delimited bytes.  Restore the original Base64 + padding codec before
# constructing either the normal bridge or the secondary-setup manager.  Both
# paths therefore share exactly the same safe framing implementation.
main.encrypt_walllink = walllink_codec.encrypt_walllink
main.decrypt_walllink = walllink_codec.decrypt_walllink

index = int(os.environ["ACTRONQUE_INSTANCE_INDEX"])
main.OPTIONS["master_ip"] = os.environ["ACTRONQUE_MASTER_IP"]
main.OPTIONS["master_port"] = int(os.environ["ACTRONQUE_MASTER_PORT"])
main.OPTIONS["topic_prefix"] = os.environ["ACTRONQUE_TOPIC_PREFIX"]
main.OPTIONS["serial"] = os.environ["ACTRONQUE_SYNTHETIC_SERIAL"]
main.OPTIONS["existing_secondary_serial"] = os.environ.get("ACTRONQUE_EXISTING_SECONDARY_SERIAL", "")
main.OPTIONS["auto_secondary_setup"] = os.environ.get("ACTRONQUE_SETUP_ENABLED", "0") == "1"

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


def _child_env(options, masters, synthetic_serials, existing_secondaries, index, setup_enabled):
    master_ip, master_port = masters[index]
    base_topic = str(options.get("topic_prefix", "hass-actronque-local")).rstrip("/")
    base_serial = synthetic_serials[0] if synthetic_serials else "FA000001"
    suffix = re.sub(r"[^A-Za-z0-9]", "", master_ip)[-8:] or str(index + 1)
    synthetic = _value_for(synthetic_serials, index)
    if not synthetic:
        synthetic = f"{base_serial[:6]}{index + 1:02d}"
    env = os.environ.copy()
    env["ACTRONQUE_MASTER_IP"] = master_ip
    env["ACTRONQUE_MASTER_PORT"] = str(master_port)
    env["ACTRONQUE_INSTANCE_INDEX"] = str(index)
    env["ACTRONQUE_DISCOVERY_MARKER"] = suffix.lower()
    env["ACTRONQUE_TOPIC_PREFIX"] = base_topic if index == 0 else f"{base_topic}/{suffix.lower()}"
    env["ACTRONQUE_SYNTHETIC_SERIAL"] = synthetic
    env["ACTRONQUE_EXISTING_SECONDARY_SERIAL"] = _value_for(existing_secondaries, index)
    env["ACTRONQUE_SETUP_ENABLED"] = "1" if setup_enabled else "0"
    return env, synthetic


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

    synthetic_serials = _list(options.get("serial", "FA000001"))
    existing_secondaries = _list(options.get("existing_secondary_serial", ""))
    auto_setup = bool(options.get("auto_secondary_setup", True))
    children = {}
    stopping = False

    if len(synthetic_serials) > len(masters):
        print("Warning: more synthetic secondary serials than QUE masters; extras will be ignored", flush=True)
    if len(existing_secondaries) > len(masters):
        print("Warning: more existing secondary serials than QUE masters; extras will be ignored", flush=True)

    pending = [i for i in range(len(masters)) if auto_setup and not _setup_complete(i)]
    active_setup = pending[0] if pending else None

    def start_child(index, setup_enabled=False):
        env, synthetic = _child_env(options, masters, synthetic_serials, existing_secondaries, index, setup_enabled)
        master_ip, master_port = masters[index]
        mode = "auto-setup active" if setup_enabled else "normal operation"
        print(f"Starting QUE instance {index + 1}: {master_ip}:{master_port} (synthetic secondary {synthetic}; {mode})", flush=True)
        children[index] = subprocess.Popen([sys.executable, "-c", CHILD_CODE], env=env)

    for index in range(len(masters)):
        start_child(index, setup_enabled=(index == active_setup))

    if active_setup is not None and len(pending) > 1:
        print(f"Multi-QUE setup coordinator: setup is serialized; QUE instance {active_setup + 1} is first", flush=True)

    def restart_for_setup(index):
        child = children[index]
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()
        start_child(index, setup_enabled=True)
        print(f"Multi-QUE setup coordinator: QUE instance {index + 1} may now perform automatic secondary setup", flush=True)

    def stop_children(*_):
        nonlocal stopping
        if stopping: return
        stopping = True
        for child in children.values():
            if child.poll() is None: child.terminate()

    signal.signal(signal.SIGTERM, stop_children); signal.signal(signal.SIGINT, stop_children)
    try:
        while not stopping:
            for index, child in list(children.items()):
                rc = child.poll()
                if rc is not None:
                    print(f"QUE bridge instance {index + 1} exited unexpectedly with code {rc}", flush=True)
                    stop_children(); return rc or 1

            if active_setup is not None and _setup_complete(active_setup):
                finished = active_setup
                pending = [i for i in pending if i != finished]
                active_setup = pending[0] if pending else None
                if active_setup is not None:
                    restart_for_setup(active_setup)
                else:
                    print("Multi-QUE setup coordinator: automatic secondary setup complete for all configured QUE units", flush=True)
            time.sleep(SETUP_POLL_SECONDS)
    finally:
        stop_children(); deadline = time.monotonic() + 10
        for child in children.values():
            remaining = max(0, deadline - time.monotonic())
            try: child.wait(timeout=remaining)
            except subprocess.TimeoutExpired: child.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main_entry())
