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

_INITIAL_CONNECT_TIMEOUT = 5.0
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


def _close_socket(sock: socket.socket | ssl.SSLSocket | None) -> None:
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _open_backend(patched_connect: bytes, client_id: str) -> tuple[socket.socket, bytes]:
    """Open a fresh Mosquitto session and return the socket plus its real CONNACK."""
    broker = socket.create_connection((MQTT_HOST, MQTT_PORT), timeout=10)
    try:
        broker.settimeout(None)
        broker.sendall(patched_connect)
        connack_first, connack_body, connack_packet = _read_packet(broker)
        _validate_connack(connack_first, connack_body, client_id)
        return broker, connack_packet
    except Exception:
        _close_socket(broker)
        raise


def _broker_to_neo(
    backend_state: dict[str, object],
    backend_lock: threading.Lock,
    broker: socket.socket,
    generation: int,
    neo: ssl.SSLSocket,
    neo_write_lock: threading.Lock,
    client_id: str,
) -> None:
    """Forward one broker generation to the NEO.

    A duplicate NEO CONNECT creates a new broker generation. When an old broker
    generation is deliberately closed, its reader must not tear down the NEO TLS
    stream that is being reused for the replacement session.
    """
    try:
        while True:
            data = broker.recv(65536)
            if not data:
                break
            with neo_write_lock:
                neo.sendall(data)
    except (OSError, ssl.SSLError):
        pass
    finally:
        with backend_lock:
            is_current = (
                backend_state.get("socket") is broker
                and backend_state.get("generation") == generation
            )
        if is_current:
            _LOGGER.debug("Local MQTT broker session for NEO %s ended", client_id)
            try:
                neo.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _start_broker_reader(
    backend_state: dict[str, object],
    backend_lock: threading.Lock,
    broker: socket.socket,
    generation: int,
    neo: ssl.SSLSocket,
    neo_write_lock: threading.Lock,
    client_id: str,
) -> None:
    threading.Thread(
        target=_broker_to_neo,
        args=(
            backend_state,
            backend_lock,
            broker,
            generation,
            neo,
            neo_write_lock,
            client_id,
        ),
        daemon=True,
        name=f"neo-broker-reader-{client_id}-{generation}",
    ).start()


def _neo_to_broker(
    neo: ssl.SSLSocket,
    backend_state: dict[str, object],
    backend_lock: threading.Lock,
    neo_write_lock: threading.Lock,
    client_id: str,
) -> None:
    """Forward NEO packets, replacing the broker session on duplicate CONNECT.

    NEO firmware 2.6.x can send another CONNECT on an already-established TLS
    stream after Nimbus account bootstrap. The CONNECT uses Clean Session, and
    observed controllers immediately SUBSCRIBE after receiving CONNACK. Treat the
    duplicate CONNECT as a genuine new MQTT session: retire the old Mosquitto
    connection, establish a fresh one with the rewritten credentials, and return
    Mosquitto's real CONNACK to the NEO before forwarding subsequent packets.
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

                patched_connect, duplicate_client_id = patch_connect(first_byte, body)
                if duplicate_client_id.lower() != client_id.lower():
                    raise ValueError(
                        f"duplicate CONNECT client id changed from {client_id} to {duplicate_client_id}"
                    )

                _LOGGER.info(
                    "NEO %s sent duplicate MQTT CONNECT #%d; replacing local broker session",
                    client_id,
                    duplicate_connects,
                )

                # Retire the old backend generation before opening the replacement.
                # This prevents its reader thread from interpreting the intentional
                # close as a reason to tear down the NEO TLS stream.
                with backend_lock:
                    old_backend = backend_state.get("socket")
                    new_generation = int(backend_state.get("generation", 0)) + 1
                    backend_state["generation"] = new_generation
                    backend_state["socket"] = None

                if isinstance(old_backend, socket.socket):
                    _close_socket(old_backend)

                try:
                    new_backend, connack_packet = _open_backend(patched_connect, client_id)
                except Exception as exc:
                    _LOGGER.warning(
                        "Failed to replace local MQTT broker session for NEO %s after duplicate CONNECT #%d: %s",
                        client_id,
                        duplicate_connects,
                        exc,
                    )
                    try:
                        neo.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return

                with backend_lock:
                    backend_state["socket"] = new_backend

                with neo_write_lock:
                    neo.sendall(connack_packet)

                _start_broker_reader(
                    backend_state,
                    backend_lock,
                    new_backend,
                    new_generation,
                    neo,
                    neo_write_lock,
                    client_id,
                )
                _LOGGER.info(
                    "Local MQTT broker replacement accepted NEO %s after duplicate CONNECT #%d",
                    client_id,
                    duplicate_connects,
                )
                continue

            if duplicate_connects:
                post_duplicate_packets += 1
                last_post_duplicate_packet = packet_name
                _LOGGER.debug(
                    "NEO %s post-replacement packet #%d: %s type=%d flags=0x%x body=%d bytes",
                    client_id,
                    post_duplicate_packets,
                    packet_name,
                    packet_type,
                    first_byte & 0x0F,
                    len(body),
                )

            with backend_lock:
                broker = backend_state.get("socket")
            if not isinstance(broker, socket.socket):
                raise ConnectionError(f"no active local MQTT broker session for NEO {client_id}")
            broker.sendall(packet)
    except EOFError:
        if duplicate_connects:
            _LOGGER.info(
                "NEO %s closed MQTT/TLS stream after %d broker-session replacement(s); "
                "post-replacement packets=%d last=%s",
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
                "NEO %s MQTT/TLS stream ended after %d broker-session replacement(s): %s; "
                "post-replacement packets=%d last=%s",
                client_id,
                duplicate_connects,
                exc,
                post_duplicate_packets,
                last_post_duplicate_packet,
            )
    except Exception as exc:
        _LOGGER.warning("NEO MQTT packet forwarding for %s failed: %s", client_id, exc)


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
        initial_backend: socket.socket | None = None
        backend_state: dict[str, object] | None = None
        backend_lock = threading.Lock()
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

            tls.settimeout(_INITIAL_CONNECT_TIMEOUT)
            try:
                first, body, _packet = _read_packet(tls)
            except socket.timeout:
                _LOGGER.info(
                    "NEO %s sent no MQTT CONNECT within %.1fs after TLS; closing stalled TLS session",
                    addr[0],
                    _INITIAL_CONNECT_TIMEOUT,
                )
                return
            finally:
                tls.settimeout(None)

            patched_connect, client_id = patch_connect(first, body)
            initial_backend, connack_packet = _open_backend(patched_connect, client_id)
            with threading.Lock():
                tls.sendall(connack_packet)
            _LOGGER.info("Local MQTT broker accepted NEO %s", client_id)

            if self._connection_callback and client_id:
                self._connection_callback(client_id.lower(), True)
                online_announced = True

            neo_write_lock = threading.Lock()
            backend_state = {"socket": initial_backend, "generation": 1}
            _start_broker_reader(
                backend_state,
                backend_lock,
                initial_backend,
                1,
                tls,
                neo_write_lock,
                client_id,
            )

            _neo_to_broker(
                tls,
                backend_state,
                backend_lock,
                neo_write_lock,
                client_id,
            )
        except EOFError:
            _LOGGER.debug("NEO %s closed after TLS before MQTT CONNECT", addr[0])
        except Exception as exc:
            _LOGGER.warning("NEO MQTT proxy connection from %s failed: %s", addr[0], exc)
        finally:
            if online_announced and self._connection_callback and client_id:
                self._connection_callback(client_id.lower(), False)

            current_backend: socket.socket | None = None
            if backend_state is not None:
                with backend_lock:
                    maybe_backend = backend_state.get("socket")
                    backend_state["generation"] = int(backend_state.get("generation", 0)) + 1
                    backend_state["socket"] = None
                if isinstance(maybe_backend, socket.socket):
                    current_backend = maybe_backend

            _close_socket(current_backend)
            if initial_backend is not current_backend:
                _close_socket(initial_backend)
            _close_socket(tls)
            if raw is not tls:
                _close_socket(raw)

            if client_id:
                _LOGGER.info("NEO MQTT client %s disconnected", client_id)
