#!/usr/bin/env python3

"""QUE WallLink wire codec.

WallLink frames are newline-delimited Base64.  The decoded payload contains a
12-byte cipher seed followed by encrypted non-zero padding, a zero padding
terminator, then the UTF-8 JSON message.  Keeping the encrypted bytes inside
Base64 is important: raw encrypted data can itself contain 0x0A and therefore
cannot safely be split on newline.
"""

import base64
import json
import os
from typing import Any, Dict

K0 = 0xFE2D85CD
K1 = 0x043E9190
K2 = 0x2E0EA4A4
MASK = 0xFFFFFFFF


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


def encrypt_walllink(data: bytes) -> bytes:
    seed = os.urandom(12)
    state = [
        K0 ^ extract32(seed[0:4]),
        K1 ^ extract32(seed[4:8]),
        K2 ^ extract32(seed[8:12]),
    ]

    # QUE expects a padded frame.  Padding bytes are deliberately non-zero;
    # the first zero byte marks the beginning of the JSON payload.
    pad_length = max(2, 512 - 12 - 1 - len(data))
    padding = bytearray()
    while len(padding) < pad_length:
        for b in os.urandom(pad_length - len(padding)):
            if b:
                padding.append(b)

    plain = bytes(padding) + b"\x00" + data
    encrypted = bytes(b ^ next_byte(state) for b in plain)
    return base64.b64encode(seed + encrypted) + b"\n"


def decrypt_walllink(encoded: bytes) -> Dict[str, Any]:
    raw = base64.b64decode(encoded.strip(), validate=True)
    if len(raw) <= 12:
        raise ValueError("WallLink frame too short")

    state = [
        K0 ^ extract32(raw[0:4]),
        K1 ^ extract32(raw[4:8]),
        K2 ^ extract32(raw[8:12]),
    ]

    output = bytearray()
    in_padding = True
    for encrypted_byte in raw[12:]:
        plain_byte = encrypted_byte ^ next_byte(state)
        if in_padding:
            if plain_byte == 0:
                in_padding = False
        else:
            output.append(plain_byte)

    if in_padding:
        raise ValueError("WallLink padding terminator not found")
    return json.loads(output.decode("utf-8"))
