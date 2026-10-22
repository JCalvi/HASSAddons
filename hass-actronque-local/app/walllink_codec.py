#!/usr/bin/env python3
"""QUE WallLink wire codec with an optional native 32-bit stream cipher.

WallLink frames are newline-delimited Base64. Decoded payloads contain a
12-byte seed followed by encrypted non-zero padding, a zero terminator and
UTF-8 JSON. The native library accelerates only the XOR cipher; Base64,
framing, padding validation and JSON processing remain in Python.
"""

import base64
import ctypes
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

K0 = 0xFE2D85CD
K1 = 0x043E9190
K2 = 0x2E0EA4A4
MASK = 0xFFFFFFFF

LOG = logging.getLogger("actronque")


def _load_native_xor():
    path = Path(__file__).with_name("libwalllink_cipher.so")
    try:
        library = ctypes.CDLL(str(path))
        func = library.walllink_xor
        func.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t)
        func.restype = None
        return func
    except (OSError, AttributeError) as exc:
        LOG.warning("Native WallLink cipher unavailable (%s); using Python fallback", exc)
        return None


_NATIVE_XOR = _load_native_xor()


def extract32(data: bytes) -> int:
    value = 0
    for b in data:
        signed = b if b < 128 else b - 256
        value = (signed | ((value << 8) & MASK)) & MASK
    return value


def next_bit(state) -> int:
    x, y, z = state
    fb0 = ((x >> 6) ^ (x >> 31) ^ x ^ (x >> 4) ^ (x >> 2) ^ ((x << 1) & MASK)) & MASK
    x = ((x >> 1) | ((fb0 & 1) << 31)) & MASK
    fb1 = ((y >> 30) ^ (y >> 2)) & 1
    y = ((y >> 1) | (fb1 << 30)) & MASK
    zs = z >> 1
    fb2 = (zs ^ (z >> 28)) & 1
    z = (zs | (fb2 << 28)) & MASK
    state[:] = [x, y, z]
    return (x ^ y ^ z) & 1


def next_byte(state) -> int:
    value = 0
    for _ in range(8):
        value = ((value << 1) & 0xFE) | next_bit(state)
    return value


def _xor_python(seed: bytes, data: bytes) -> bytes:
    """Original bit-for-bit cipher retained as a portable fallback/reference."""
    state = [
        K0 ^ extract32(seed[0:4]),
        K1 ^ extract32(seed[4:8]),
        K2 ^ extract32(seed[8:12]),
    ]
    return bytes(value ^ next_byte(state) for value in data)


def _xor_stream(seed: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if _NATIVE_XOR is None:
        return _xor_python(seed, data)
    result = ctypes.create_string_buffer(len(data))
    _NATIVE_XOR(seed, data, result, len(data))
    return result.raw


def encrypt_walllink(data: bytes) -> bytes:
    seed = os.urandom(12)

    # QUE expects padded frames. Padding bytes must be non-zero; the first
    # zero byte marks the beginning of the JSON payload.
    pad_length = max(2, 512 - 12 - 1 - len(data))
    padding = bytearray()
    while len(padding) < pad_length:
        for b in os.urandom(pad_length - len(padding)):
            if b:
                padding.append(b)

    plain = bytes(padding) + b"\x00" + data
    return base64.b64encode(seed + _xor_stream(seed, plain)) + b"\n"


def decrypt_walllink(encoded: bytes) -> Dict[str, Any]:
    raw = base64.b64decode(encoded.strip(), validate=True)
    if len(raw) <= 12:
        raise ValueError("WallLink frame too short")

    plain = _xor_stream(raw[:12], raw[12:])
    terminator = plain.find(b"\x00")
    if terminator == -1:
        raise ValueError("WallLink padding terminator not found")
    return json.loads(plain[terminator + 1:].decode("utf-8"))
