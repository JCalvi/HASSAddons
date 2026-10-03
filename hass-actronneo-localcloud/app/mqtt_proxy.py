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

_SUCCESS_CONNACK = b"\x20\x02\x00\x00"
_MQTT_PACKET_NAMES = {
    1: "CONNECT",
    2: "CONNACK",
    3: "PUBLISH",
    4: "PUBACK",
    5: "PUBREC",
    6: "PUBREL",
    7: "PUBCOMP",
    8: "SUBSCRIBE",
    9: "SUBACK",
    10: "UNSUBSCRIBE",
    11: "UNSUBACK",
    12: "PINGREQ",
    13: "PINGRESP",
    14: "DISCONNECT",
}


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


def _read_packet(sock: socket.socket | ssl.SSLSocket) -> tuple[int, bytes, bytes]:
    """Read one complete MQTT packet and return header byte, body and full packet."""
    first_byte = _recv_exact(sock, 1)[0]
    remaining = _read_remaining_length(sock)
    body = _recv_exact(sock, remaining)
    packet = bytes([first_byte]) + _encode_remaining_length(remaining) + body
    return first_byte, body, packet


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


def _validate_connack(first_byte: int, body: bytes, client_id: str) -> None:
    if first_byte != 0x20 or len(body) != 2:
        raise ValueError(
            f"local broker returned invalid CONNACK for {client_id}: "
            f"header=0x{first_byte:02x} length={len(body)}"
        )
    if body[1] != 0:
        raise ValueError(f"local broker rejected {client_id} with CONNACK return code {body[1]}")


def _pipe(
    src: socket.socket | ssl.SSLSocket,
    dst: socket.socket | ssl.SSLSocket,
    write_lock: threading.Lock | None = None,
) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            if write_lock is None:
                dst.sendall(data)
            else:
                with write_lock:
                    dst.sendall(data)
    except (OSError, ssl.SSLError):
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _neo_to_broker(
    neo: ssl.SSLSocket,
    broker: socket.socket,
    neo_write_lock: threading.Lock,
    client_id: str,
) -> None:
    """Forward NEO MQTT packets while absorbing its duplicate CONNECT quirk.

    NEO firmware 2.6.x can send another CONNECT packet on the already-established
    TLS/MQTT stream after Nimbus account bootstrap. Mosquitto rejects a second
    CONNECT on the same MQTT session, so absorb it locally and acknowledge it.
    Testing showed that opening a replacement Mosquitto session and returning a
    real CONNACK/SUBACK does not stop the NEO from closing this bootstrap attempt,
    so the simpler compatibility path is retained here.
    """
    duplicate_connects = 0
    post_duplicate_packets = 0
    last_post_duplicate_packet = "none"
    try:
        while True:
            first_byte, body, packet = _read_packet(neo)
            packet_type = first_byte >> 4
            packet_name = _MQTT_PACKET_NAMES.get(packet_type, f"TYPE_{packet_type}")
            if packet_type == 1:  # CONNECT
                duplicate_connects += 1
                post_duplicate_packets = 0
                last_post_duplicate_packet = "none"
                _LOGGER.info(
                    "NEO %s sent duplicate MQTT CONNECT #%d; keeping existing local broker session",
                    client_id,
                    duplicate_connects,
                )
                with neo_write_lock:
                    neo.sendall(_SUCCESS_CONNACK)
                continue

            if duplicate_connects:
                post_duplicate_packets += 1
                last_post_duplicate_packet = packet_name
                if packet_type == 14:
                    _LOGGER.info(
                        "NEO %s sent MQTT DISCONNECT after duplicate CONNECT #%d",
                        client_id,
                        duplicate_connects,
                    )
                else:
                    _LOGGER.debug(
                        "NEO %s post-duplicate packet #%d: %s type=%d flags=0x%x body=%d bytes",
                        client_id,
                        post_duplicate_packets,
                        packet_name,
                        packet_type,
                        first_byte & 0x0F,
                        len(body),
                    )

            broker.sendall(packet)
    except EOFError:
        if duplicate_connects:
            _LOGGER.info(
                "NEO %s closed MQTT/TLS stream after duplicate CONNECT #%d; "
                "post-duplicate packets=%d last=%s",
                client_id,
                duplicate_connects,
                post_duplicate_packets,
                last_post_duplicate_packet,
            )
        else:
            _LOGGER.debug("NEO %s closed MQTT/TLS stream", client_id)
    except (OSError, ssl.SSLError) as exc:
        if duplicate_connects:
            _LOGGER.info(
                "NEO %s MQTT/TLS stream ended after duplicate CONNECT #%d: %s; "
                "post-duplicate packets=%d last=%s",
                client_id,
                duplicate_connects,
                exc,
                post_duplicate_packets,
                last_post_duplicate_packet,
            )
    except Exception as exc:
        _LOGGER.warning("NEO MQTT packet forwarding for %s failed: %s", client_id, exc)
    finally:
        try:
            broker.shutdown(socket.SHUT_WR)
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

            # Wait naturally for the NEO's first MQTT CONNECT. A 5-second
            # post-TLS timeout was tested and only closed idle sockets sooner;
            # it did not shorten the controller's own retry interval.
            first, body, _packet = _read_packet(tls)
            patched_connect, client_id = patch_connect(first, body)
            backend.sendall(patched_connect)

            connack_first, connack_body, connack_packet = _read_packet(backend)
            _validate_connack(connack_first, connack_body, client_id)
            tls.sendall(connack_packet)
            _LOGGER.info("Local MQTT broker accepted NEO %s", client_id)

            if self._connection_callback and client_id:
                self._connection_callback(client_id.lower(), True)
                online_announced = True

            neo_write_lock = threading.Lock()
            t1 = threading.Thread(
                target=_neo_to_broker,
                args=(tls, backend, neo_write_lock, client_id),
                daemon=True,
            )
            t2 = threading.Thread(
                target=_pipe,
                args=(backend, tls, neo_write_lock),
                daemon=True,
            )
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
