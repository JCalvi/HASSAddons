"""Offline native/Python cipher compatibility and WallLink frame tests."""
import base64
import json
import random
import unittest
from unittest.mock import patch

import walllink_codec as codec


class WallLinkCodecTests(unittest.TestCase):
    def test_native_available(self):
        self.assertIsNotNone(codec._NATIVE_XOR, "Docker build must include native cipher")

    def test_native_matches_python(self):
        randomizer = random.Random(1456)
        for n in (0, 1, 2, 7, 12, 128, 256, 512, 1024, 4096, 8192):
            for repeat in range(8):
                seed = bytes(randomizer.randrange(256) for _ in range(12))
                data = bytes(randomizer.randrange(256) for _ in range(n))
                with self.subTest(length=n, repeat=repeat):
                    self.assertEqual(codec._xor_stream(seed, data), codec._xor_python(seed, data))
                    self.assertEqual(codec._xor_stream(seed, codec._xor_stream(seed, data)), data)

    def test_roundtrip_native_and_fallback(self):
        for obj in ({}, {"Data_Change": {"LiveAircon.FanRPM": 44}},
                    {"Data_All": {"RemoteZoneInfo": [{"LiveTemp_oC": 24.5}] * 50}}):
            encoded = codec.encrypt_walllink(json.dumps(obj).encode())
            self.assertEqual(codec.decrypt_walllink(encoded), obj)
            with patch.object(codec, "_NATIVE_XOR", None):
                self.assertEqual(codec.decrypt_walllink(encoded), obj)
                self.assertEqual(codec.decrypt_walllink(codec.encrypt_walllink(json.dumps(obj).encode())), obj)

    def test_malformed_frames(self):
        with self.assertRaises(ValueError):
            codec.decrypt_walllink(b"not base64%")
        with self.assertRaisesRegex(ValueError, "too short"):
            codec.decrypt_walllink(base64.b64encode(b"short"))
        seed = bytes(range(12))
        without_terminator = base64.b64encode(seed + codec._xor_stream(seed, b"abc123"))
        with self.assertRaisesRegex(ValueError, "padding terminator"):
            codec.decrypt_walllink(without_terminator)
        malformed_json = base64.b64encode(seed + codec._xor_stream(seed, b"test\x00NOTJSON"))
        with self.assertRaises(json.JSONDecodeError):
            codec.decrypt_walllink(malformed_json)


if __name__ == "__main__":
    unittest.main()
