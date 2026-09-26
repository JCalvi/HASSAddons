#!/usr/bin/env python3

import json
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import main


STATE_FILE = Path("/data/secondary_setup.json")
UDP_PORT = 19295
FALLBACK_FIRMWARE = "1.456.1.598"


class SecondarySetupManager:
    """Automate the manual QUE secondary-controller bootstrap sequence."""

    def __init__(
        self,
        options,
        status_callback: Callable[[str], None],
        is_walllink_online: Callable[[], bool],
        set_max_on_live_link: Callable[[int], None],
    ):
        self.master_ip = str(options.get("master_ip", "")).strip()
        self.master_port = int(options.get("master_port", 19296))
        self.synthetic_serial = str(options.get("serial", "FA000001")).strip()
        self.configured_existing_serial = str(
            options.get("existing_secondary_serial", "")
        ).strip()
        self.target_max = max(2, int(options.get("max_secondary_controllers", 2)))
        self.auto_setup = bool(options.get("auto_secondary_setup", True))
        self.retry_delay = max(2, int(options.get("setup_retry_delay", 5)))

        self.status_callback = status_callback
        self.is_walllink_online = is_walllink_online
        self.set_max_on_live_link = set_max_on_live_link

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status = "Not started"
        self._state = self._load_state()
        self.firmware = str(
            self._state.get("firmware")
            or options.get("firmware")
            or main.OPTIONS.get("firmware")
            or FALLBACK_FIRMWARE
        ).strip()

    @property
    def status(self) -> str:
        return self._status

    @property
    def completed(self) -> bool:
        return bool(self._state.get("completed"))

    @property
    def existing_secondary_serial(self) -> str:
        return str(
            self._state.get("existing_secondary_serial")
            or self.configured_existing_serial
            or ""
        ).strip()

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._worker,
            name="secondary-setup",
            daemon=True,
        )
        self._thread.start()
        if self.auto_setup and not self.completed:
            self._wake.set()
        elif self.completed:
            self._set_status("Setup complete")
        else:
            self._set_status("Automatic setup disabled")

    def stop(self):
        self._stop.set()
        self._wake.set()

    def request_redo(self):
        self._state["completed"] = False
        self._save_state()
        self._set_status("Redo requested")
        self._wake.set()

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                with STATE_FILE.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            main.LOG.warning("Could not read secondary setup state: %s", exc)
        return {}

    def _save_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with STATE_FILE.open("w", encoding="utf-8") as handle:
                json.dump(self._state, handle, indent=2, sort_keys=True)
        except Exception as exc:
            main.LOG.warning("Could not save secondary setup state: %s", exc)

    def _set_status(self, status: str):
        if status == self._status:
            return
        self._status = status
        main.LOG.info("Secondary setup: %s", status)
        try:
            self.status_callback(status)
        except Exception:
            main.LOG.exception("Secondary setup status callback failed")

    def _worker(self):
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self._perform_setup()
            except Exception:
                main.LOG.exception("Secondary controller setup failed")
                self._set_status("Setup error; retrying")
                if not self._stop.wait(self.retry_delay):
                    self._wake.set()

    def _perform_setup(self):
        if self.is_walllink_online():
            self._set_status("Synthetic controller already paired; checking limit")
            self.set_max_on_live_link(self.target_max)
            self._mark_complete()
            return

        existing = self.existing_secondary_serial
        if not existing:
            self._set_status("Detecting existing secondary; leave it powered on")
            existing = self._detect_existing_secondary()
            if not existing:
                self._set_status("Waiting to detect existing secondary controller")
                if not self._stop.wait(self.retry_delay):
                    self._wake.set()
                return
            self._state["existing_secondary_serial"] = existing
            self._save_state()
            main.LOG.info("Detected existing secondary serial %s", existing)

        self._set_status(f"Power off secondary {existing}, then reboot the QUE master")

        if not self._set_limit_via_existing_secondary(existing):
            if not self._stop.wait(self.retry_delay):
                self._wake.set()
            return

        self._set_status("Limit raised. On the master select 'Connect another controller'")

        if self._pair_synthetic_controller():
            self._mark_complete()
            return

        self._set_status("Waiting for 'Connect another controller' on the QUE master")
        if not self._stop.wait(self.retry_delay):
            self._wake.set()

    def _mark_complete(self):
        self._state["completed"] = True
        self._state["synthetic_serial"] = self.synthetic_serial
        self._state["max_secondary_controllers"] = self.target_max
        self._state["firmware"] = self.firmware
        self._save_state()
        self._set_status("Setup complete; power the original secondary back on")

    def _connect_as(self, serial: str, timeout: float = 5.0) -> Tuple[socket.socket, dict]:
        sock = socket.create_connection((self.master_ip, self.master_port), timeout=timeout)
        sock.settimeout(timeout)

        hello = {
            "Data_Change": {},
            "Message": "Thank you for connecting me",
            "id": {
                "fw_version": self.firmware,
                "serial": serial,
            },
        }
        sock.sendall(main.encrypt_walllink(json.dumps(hello, separators=(",", ":")).encode()))

        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("Master closed connection during setup handshake")
            buffer += chunk

        frame, _ = buffer.split(b"\n", 1)
        reply = main.decrypt_walllink(frame + b"\n")
        message = str(reply.get("Message", ""))
        if not message.startswith("Connection is successful"):
            sock.close()
            raise ConnectionError(message or "QUE master rejected controller")
        return sock, reply

    def _set_limit_via_existing_secondary(self, serial: str) -> bool:
        try:
            sock, _ = self._connect_as(serial)
        except Exception as exc:
            main.LOG.debug(
                "Existing-secondary setup connection not ready for %s: %s",
                serial,
                exc,
            )
            return False

        try:
            change = {
                "Data_Change": {
                    "NV_SystemSettings.MaxSecondaryControllers": self.target_max,
                },
                "id": {
                    "fw_version": self.firmware,
                    "serial": serial,
                },
            }
            sock.sendall(
                main.encrypt_walllink(
                    json.dumps(change, separators=(",", ":")).encode()
                )
            )
            main.LOG.info(
                "Set NV_SystemSettings.MaxSecondaryControllers=%d via %s",
                self.target_max,
                serial,
            )
            time.sleep(1.0)
            return True
        except Exception as exc:
            main.LOG.warning("Could not raise MaxSecondaryControllers: %s", exc)
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _detect_existing_secondary(self) -> str:
        deadline = time.monotonic() + 20.0
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
            sock.bind(("", UDP_PORT))
            sock.settimeout(2.0)

            while time.monotonic() < deadline and not self._stop.is_set():
                try:
                    payload, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                try:
                    obj = json.loads(payload.decode("utf-8", "replace"))
                except Exception:
                    continue

                serial = str(obj.get("id", {}).get("serial", "")).strip()
                if (
                    obj.get("AvailableForJoining") is True
                    and obj.get("amMaster") is False
                    and serial
                    and serial != self.synthetic_serial
                ):
                    firmware = str(
                        obj.get("id", {}).get("fw_version")
                        or obj.get("wcFirmwareVer")
                        or ""
                    ).strip()
                    if firmware:
                        self.firmware = firmware
                        self._state["firmware"] = firmware
                        self._save_state()
                        main.LOG.info(
                            "Detected secondary firmware %s from %s",
                            firmware,
                            serial,
                        )
                    return serial
        except OSError as exc:
            main.LOG.warning("Could not listen for QUE UDP discovery: %s", exc)
        finally:
            sock.close()
        return ""

    def _pair_synthetic_controller(self) -> bool:
        announcement = {
            "AvailableForJoining": True,
            "amMaster": False,
            "id": {
                "fw_version": self.firmware,
                "serial": self.synthetic_serial,
            },
            "tWallLinkClassVer": "V0.01s",
            "wcFirmwareVer": self.firmware,
        }
        payload = json.dumps(announcement, separators=(",", ":")).encode("utf-8")

        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp.settimeout(0.5)

            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and not self._stop.is_set():
                for destination in (self.master_ip, "255.255.255.255"):
                    try:
                        udp.sendto(payload, (destination, UDP_PORT))
                    except OSError:
                        pass

                try:
                    response, address = udp.recvfrom(65535)
                    text = response.decode("utf-8", "replace")
                    if "InviteToJoinAsServantOnPort" in text:
                        main.LOG.info("QUE pairing invite received from %s", address[0])
                except socket.timeout:
                    pass

                try:
                    sock, _ = self._connect_as(self.synthetic_serial, timeout=3.0)
                    sock.close()
                    main.LOG.info(
                        "Synthetic secondary %s accepted by QUE master",
                        self.synthetic_serial,
                    )
                    return True
                except Exception:
                    pass

                if self._stop.wait(1.5):
                    break
        finally:
            udp.close()
        return False
