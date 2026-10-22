"""Selective QUE state publishing tests without an MQTT broker."""
import copy
import unittest

from full_bridge import FullActronQueBridge
from state_updates import affected_topics, discovery_might_change


def sample_state():
    return {
        "UserAirconSettings": {
            "isOn": True, "Mode": "COOL", "FanMode": "AUTO",
            "QuietMode": False, "AwayMode": False, "EnabledZones": [True, True],
            "TemperatureSetpoint_Heat_oC": 20.0,
            "TemperatureSetpoint_Cool_oC": 26.0,
        },
        "MasterInfo": {"LiveTemp_oC": 23, "LiveOutdoorTemp_oC": 20,
                       "LiveHumidity_pc": 48, "ControlAllZones": False},
        "NV_SystemSettings": {"SystemName": "Workshop"},
        "LiveAircon": {
            "CompressorMode": "COOL", "CompressorCapacity": 50,
            "OutdoorUnit": {"CompPower": 1400}, "CoilInlet": 15,
            "FanPWM": 25, "FanRPM": 200,
        },
        "Alerts": {"CleanFilter": False},
        "ACStats": {"NV_FanRunTime_10m": 60},
        "RemoteZoneInfo": [
            {
                "NV_Exists": True, "NV_Title": "Bedroom",
                "LiveTemp_oC": 23, "ZonePosition": 10,
                "TemperatureSetpoint_Heat_oC": 20,
                "TemperatureSetpoint_Cool_oC": 26,
                "RemoteTemperatures_oC": {"a": 23},
                "Sensors": {"a": {"Battery_pc": 70, "lastRssi": -55}},
            },
            {
                "NV_Exists": True, "NV_Title": "Kitchen",
                "LiveTemp_oC": 24, "ZonePosition": 8,
                "TemperatureSetpoint_Heat_oC": 20,
                "TemperatureSetpoint_Cool_oC": 26,
                "RemoteTemperatures_oC": {"b": 24},
                "Sensors": {"b": {"Battery_pc": 60, "lastRssi": -60}},
            },
        ],
    }


class StateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FullActronQueBridge()
        self.bridge.state = sample_state()
        self.bridge.mqtt_connected = True
        self.messages = []
        self.discoveries = 0
        self.bridge.mqtt_publish = self.record
        self.bridge.publish_discovery = self.discover
        self.bridge._zone_signature = self.bridge._zone_signature_value()

    def record(self, topic, payload, retain=False):
        self.messages.append((topic.rsplit("hass-actronque-local/", 1)[-1], payload, retain))

    def discover(self):
        self.discoveries += 1

    def update(self, changes):
        self.messages.clear()
        self.bridge.handle_walllink_message({"Data_Change": changes})
        return {t: v for t, v, _ in self.messages if t != "event/change"}

    def test_zone_temperature_does_not_rebuild_unrelated_entities(self):
        published = self.update({"RemoteZoneInfo[0].LiveTemp_oC": 25.5})
        self.assertEqual(published, {"zone/1/temperature/state": 25.5})
        self.assertEqual(self.discoveries, 0)

    def test_mode_dependent_target_uses_actual_mode(self):
        published = self.update({"RemoteZoneInfo[0].TemperatureSetpoint_Cool_oC": 28.0})
        self.assertEqual(published, {
            "zone/1/temperature/high/state": 28.0,
            "zone/1/temperature/target/state": 28.0,
        })
        published = self.update({"UserAirconSettings.Mode": "HEAT"})
        self.assertEqual(published["climate/temperature/target/state"], 20.0)
        self.assertEqual(published["zone/1/temperature/target/state"], 20.0)
        self.assertEqual(published["zone/2/temperature/target/state"], 20.0)

    def test_compressor_and_on_changes_update_derived_action(self):
        published = self.update({"LiveAircon.CompressorMode": "HEAT"})
        self.assertEqual(published, {
            "compressor_mode/state": "HEAT", "climate/action/state": "heating",
        })
        published = self.update({"UserAirconSettings.isOn": False})
        self.assertEqual(published["aircon/state"], "OFF")
        self.assertEqual(published["climate/mode/state"], "off")
        self.assertEqual(published["climate/action/state"], "off")

    def test_one_sensor_update_and_structure_discovery(self):
        published = self.update({"RemoteZoneInfo[0].Sensors.a.lastRssi": -45})
        self.assertEqual(published, {"zone/1/sensor/a/rssi/state": -45})
        self.assertEqual(self.discoveries, 0)
        published = self.update({"RemoteZoneInfo[0].RemoteTemperatures_oC.new": 22})
        self.assertEqual(published, {"zone/1/sensor/new/temperature/state": 22})
        self.assertEqual(self.discoveries, 1)
        self.update({"RemoteZoneInfo[0].Sensors.a.Battery_pc": 255})
        self.assertEqual(self.discoveries, 2)

    def test_master_temperature_and_zone_enable(self):
        published = self.update({"MasterInfo.LiveTemp_oC": 25})
        self.assertEqual(published, {"temperature/state": 25, "indoor_temperature/state": 25})
        published = self.update({"UserAirconSettings.EnabledZones[1]": False})
        self.assertEqual(published, {"zone/2/enabled/state": "OFF"})

    def test_unknown_leaf_is_ignored_but_event_still_emitted(self):
        published = self.update({"LiveAircon.UnusedTelemetry": 12})
        self.assertEqual(published, {})
        self.assertTrue(any(t == "event/change" for t, _, _ in self.messages))
        self.assertIsNone(affected_topics(["RemoteZoneInfo[0].Sensors"]))
        self.assertTrue(discovery_might_change(["RemoteZoneInfo[0].Sensors"]))

    def test_full_refresh_and_whole_object_replacement(self):
        self.messages.clear()
        self.bridge.handle_walllink_message({"Data_All": copy.deepcopy(sample_state())})
        self.assertEqual(self.discoveries, 1)
        full = {t for t, _, _ in self.messages}
        self.assertIn("zone/1/temperature/state", full)
        self.assertIn("zone/2/sensor/b/rssi/state", full)
        self.assertIn("climate/temperature/target/state", full)
        published = self.update({"MasterInfo": {"LiveTemp_oC": 28}})
        self.assertEqual(published["temperature/state"], 28)
        self.assertEqual(published["indoor_temperature/state"], 28)
        self.assertIn("zone/1/temperature/state", published)

    def test_local_optimistic_write_selective_update(self):
        self.bridge.walllink._send_json = lambda payload: None
        self.messages.clear()
        self.bridge._write_temp("UserAirconSettings.TemperatureSetpoint_Cool_oC", "27")
        published = {t: v for t, v, _ in self.messages}
        self.assertEqual(published, {
            "climate/temperature/high/state": 27.0,
            "climate/temperature/target/state": 27.0,
        })


if __name__ == "__main__":
    unittest.main()
