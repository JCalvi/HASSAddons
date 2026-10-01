"""TLS MQTT compatibility proxy for NEO controllers."""

from __future__ import annotations

import logging
import socket
import ssl
import struct
import threading
from typing import Callable

from config import CERT_FILE, KEY_FILE, MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_USERNAME

_LOGGER = logging.getLogger("actronneo-localcloud.mqtt_proxy")


def _recv_exact(sock: socket.socket | ssl.SSLSocket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise EOFError("connection closed")
        data.extend(part)
    return bytes(data)


def _read_remaining_length(sock: socket.socket | ssl.SSLSocket) -> int:
    value = 0
    multiplier = 1
    for _ in range(4):
        byte = _recv_exact(sock, 1)[0]
        value += (byte & 0x7F) * multiplier
        if not (byte & 0x80):
            return value
        multiplier *= 128
    raise ValueError("invalid MQTT remaining length")


def _encode_remaining_length(value: int) -> bytes:
    out = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value:
            digit |= 0x80
        out.append(digit)
        if not value:
            return bytes(out)


def _read_mqtt_field(buf: bytes | bytearray, pos: int) -> tuple[bytes, int]:
    if pos + 2 > len(buf):
        raise ValueError("truncated MQTT field")
    length = struct.unpack("!H", bytes(buf[pos : pos + 2]))[0]
    start = pos + 2
    end = start + length
    if end > len(buf):
        raise ValueError("truncated MQTT field payload")
    return bytes(buf[start:end]), end


def _pack_mqtt_field(value: bytes) -> bytes:
    if len(value) > 65535:
        raise ValueError("MQTT field too long")
    return struct.pack("!H", len(value)) + value


def patch_connect(first_byte: int, body: bytes) -> tuple[bytes, str]:
    """Replace NEO's password-only CONNECT with Supervisor MQTT credentials."""
    if first_byte != 0x10:
        raise ValueError(f"first MQTT packet is 0x{first_byte:02x}, expected CONNECT")

    b = bytes(body)
    proto_name, pos = _read_mqtt_field(b, 0)
    if pos + 4 > len(b):
        raise ValueError("truncated MQTT CONNECT variable header")

    protocol_level = b[pos]
    flags = b[pos + 1]
    keepalive = b[pos + 2 : pos + 4]
    payload_pos = pos + 4
    if protocol_level != 4:
        raise ValueError(f"unsupported MQTT protocol level {protocol_level}; expected 4")

    client_id, payload_pos = _read_mqtt_field(b, payload_pos)
    client_id_text = client_id.decode("utf-8", errors="replace")

    will_flag = bool(flags & 0x04)
    username_flag = bool(flags & 0x80)
    password_flag = bool(flags & 0x40)

    will_fields = b""
    if will_flag:
        will_topic, payload_pos = _read_mqtt_field(b, payload_pos)
        will_payload, payload_pos = _read_mqtt_field(b, payload_pos)
        will_fields = _pack_mqtt_field(will_topic) + _pack_mqtt_field(will_payload)

    if username_flag:
        _, payload_pos = _read_mqtt_field(b, payload_pos)
    if password_flag:
        _, payload_pos = _read_mqtt_field(b, payload_pos)
    if payload_pos != len(b):
        raise ValueError("unexpected bytes after MQTT CONNECT payload")

    user_bytes = MQTT_USERNAME.encode("utf-8")
    pass_bytes = MQTT_PASSWORD.encode("utf-8")
    if not user_bytes:
        raise ValueError("Supervisor MQTT service returned an empty username")

    new_flags = flags | 0x80
    if pass_bytes:
        new_flags |= 0x40
    else:
        new_flags &= ~0x40

    variable_header = _pack_mqtt_field(proto_name) + bytes([protocol_level, new_flags]) + keepalive
    payload = _pack_mqtt_field(client_id) + will_fields + _pack_mqtt_field(user_bytes)
    if pass_bytes:
        payload += _pack_mqtt_field(pass_bytes)

    patched_body = variable_header + payload
    packet = bytes([first_byte]) + _encode_remaining_length(len(patched_body)) + patched_body
    _LOGGER.info(
        "MQTT CONNECT %s: protocol=%s flags=0x%02x -> local broker credentials",
        client_id_text,
        protocol_level,
        flags,
    )
    return packet, client_id_text


def _pipe(src: socket.socket | ssl.SSLSocket, dst: socket.socket | ssl.SSLSocket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except (OSError, ssl.SSLError):
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class NeoMqttProxy:
    def __init__(self, connection_callback: Callable[[str, bool], None] | None = None) -> None:
        self._connection_callback = connection_callback
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.maximum_version = ssl.TLSVersion.TLSv1_2
        self._context.set_ciphers(
            "AES256-GCM-SHA384:AES128-GCM-SHA256:AES128-SHA256:AES128-SHA:@SECLEVEL=1"
        )
        self._context.load_cert_chain(CERT_FILE, KEY_FILE)

    def serve_forever(self) -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", 8883))
        server.listen(20)
        _LOGGER.info("NEO MQTT TLS compatibility proxy listening on 0.0.0.0:8883")
        while True:
            raw, addr = server.accept()
            threading.Thread(
                target=self._handle,
                args=(raw, addr),
                daemon=True,
                name=f"neo-mqtt-{addr[0]}:{addr[1]}",
            ).start()

    def _handle(self, raw: socket.socket, addr: tuple[str, int]) -> None:
        tls: ssl.SSLSocket | None = None
        backend: socket.socket | None = None
        client_id = ""
        online_announced = False
        try:
            tls = self._context.wrap_socket(raw, server_side=True)
            _LOGGER.info(
                "NEO MQTT TLS established from %s using %s %s",
                addr[0],
                tls.version(),
                tls.cipher()[0] if tls.cipher() else "unknown",
            )
            backend = socket.create_connection((MQTT_HOST, MQTT_PORT), timeout=10)
            backend.settimeout(None)

            first = _recv_exact(tls, 1)[0]
            remaining = _read_remaining_length(tls)
            body = _recv_exact(tls, remaining)
            packet, client_id = patch_connect(first, body)
            backend.sendall(packet)

            if self._connection_callback and client_id:
                self._connection_callback(client_id.lower(), True)
                online_announced = True

            t1 = threading.Thread(target=_pipe, args=(tls, backend), daemon=True)
            t2 = threading.Thread(target=_pipe, args=(backend, tls), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except EOFError:
            _LOGGER.debug("NEO %s closed after TLS before MQTT CONNECT", addr[0])
        except Exception as exc:
            _LOGGER.warning("NEO MQTT proxy connection from %s failed: %s", addr[0], exc)
        finally:
            if online_announced and self._connection_callback and client_id:
                self._connection_callback(client_id.lower(), False)
            for sock in (tls, backend, raw):
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if client_id:
                _LOGGER.info("NEO MQTT client %s disconnected", client_id)
