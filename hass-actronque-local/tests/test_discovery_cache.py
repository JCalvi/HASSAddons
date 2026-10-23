"""MQTT discovery deduplication: production UI and base MQTT publisher."""
from types import SimpleNamespace
import unittest

import main
from ui_bridge import ActronQueLocalBridge
from test_state_updates import sample_state


class Recorder:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=1, retain=False):
        self.sent.append((topic, payload, qos, retain))
        return SimpleNamespace(rc=main.mqtt.MQTT_ERR_SUCCESS)

    def discovery(self):
        return [(t, p) for t, p, _, _ in self.sent
                if t.startswith("homeassistant/") and t.endswith("/config")]

    def clear(self):
        self.sent.clear()


class DiscoveryCacheTests(unittest.TestCase):
    def test_base_cache_suppresses_duplicate_config_and_empty_tombstones(self):
        bridge = main.ActronQueBridge()
        recorder = Recorder()
        bridge.mqtt.publish = recorder.publish

        topic = "homeassistant/sensor/hass_actronque_local/test/config"
        for payload in ({"name": "Test"}, {"name": "Test"}, b"", b"", {"name": "New"}):
            bridge.mqtt_publish(topic, payload, retain=True)
        self.assertEqual(len(recorder.discovery()), 3)

        # Availability and events must not be suppressed.
        for _ in range(2):
            bridge.mqtt_publish(bridge.topic_prefix + "/status", "online", retain=True)
            bridge.mqtt_publish(bridge.topic_prefix + "/event/change", {"x": 1})
        self.assertEqual(len(recorder.sent), 7)

        # Reconnect deliberately invalidates retained cache, forcing a resync.
        bridge.on_mqtt_disconnect(None, None, None, 0, None)
        bridge.mqtt_publish(topic, {"name": "New"}, retain=True)
        self.assertEqual(len(recorder.discovery()), 4)

    def test_actual_ui_skips_unchanged_data_all_and_telemetry(self):
        bridge = ActronQueLocalBridge()
        recorder = Recorder()
        bridge.mqtt.publish = recorder.publish
        bridge.mqtt_connected = True
        first = sample_state()

        bridge.handle_walllink_message({"Data_All": first})
        first_configs = recorder.discovery()
        self.assertGreater(len(first_configs), 10)
        self.assertTrue(any(p == b"" for _, p in first_configs))

        recorder.clear()
        again = sample_state()
        again["MasterInfo"]["LiveTemp_oC"] = 26.0
        bridge.handle_walllink_message({"Data_All": again})
        self.assertEqual(recorder.discovery(), [])

        bridge.handle_walllink_message({"Data_Change": {"LiveAircon.FanRPM": 250}})
        self.assertEqual(recorder.discovery(), [])

        # Repeated / identical zone metadata still must not cause discovery.
        bridge.handle_walllink_message({"Data_Change": {"RemoteZoneInfo[0].NV_Title": "Bedroom"}})
        self.assertEqual(recorder.discovery(), [])

        # A genuinely changed zone name updates its discovery configuration.
        bridge.handle_walllink_message({"Data_Change": {"RemoteZoneInfo[0].NV_Title": "Office"}})
        self.assertGreater(len(recorder.discovery()), 0)

    def test_new_rssi_sensor_field_refreshes_discovery(self):
        bridge = ActronQueLocalBridge()
        recorder = Recorder()
        bridge.mqtt.publish = recorder.publish
        bridge.mqtt_connected = True
        state = sample_state()
        del state["RemoteZoneInfo"][0]["Sensors"]["a"]["lastRssi"]
        bridge.handle_walllink_message({"Data_All": state})
        recorder.clear()
        bridge.handle_walllink_message({"Data_Change": {"RemoteZoneInfo[0].Sensors.a.lastRssi": -56}})
        topics = [t for t, _ in recorder.discovery()]
        self.assertTrue(any("zone_1_sensor_a_rssi/config" in t for t in topics))

    def test_mqtt_reconnect_forces_complete_discovery(self):
        bridge = ActronQueLocalBridge()
        recorder = Recorder()
        bridge.mqtt.publish = recorder.publish
        bridge.mqtt.subscribe = lambda *args, **kwargs: None
        bridge.secondary_setup.start = lambda: None
        bridge._setup_started = True
        bridge.mqtt_connected = True
        bridge.handle_walllink_message({"Data_All": sample_state()})

        recorder.clear()
        bridge.on_mqtt_connect(None, None, None, 0, None)
        self.assertGreater(len(recorder.discovery()), 10)


if __name__ == "__main__":
    unittest.main()
