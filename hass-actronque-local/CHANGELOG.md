# Changelog

## 0.2.2

- Round Home Assistant sensor values for cleaner display.
- Temperature, humidity, capacity, power, damper position and runtime values now publish with sensible precision.
- Coil inlet temperature publishes to 2 decimal places.
- Fan PWM/RPM, battery and RSSI publish as whole numbers.

## 0.2.1

- Present master and zone heat/cool targets as combined lower/upper climate ranges, matching the cloud add-on UI.
- Remove the separate heating/cooling Number entities introduced in v0.2.0.
- Add a proper climate entity for each existing zone.
- Rename the device to `Actron QUE Local (<SystemName>)` for consistency with the cloud add-on.

## 0.2.0

- Add full local HVAC climate control using native WallLink writes.
- Add main HVAC mode, fan mode, heating and cooling setpoint controls.
- Add Away Mode, Control All Zones and Constant Fan switches.
- Add indoor temperature, outdoor temperature, humidity, compressor mode/capacity/power, coil inlet temperature, fan PWM/RPM and filter status/runtime sensors.
- Dynamically discover existing zones from `RemoteZoneInfo`.
- Add per-zone enable control, live temperature, heating/cooling setpoints and damper position.
- Add per-zone wireless sensor temperature, battery and RSSI entities when present.
- Keep v0.1.x Quiet Mode control and diagnostics.

## 0.1.1

- Give the local integration its own Home Assistant MQTT device identity.
- Rename the MQTT device to `Actron QUE Local <SystemName>`.
- Use device identifier prefix `actronque_local_` so it cannot merge with the cloud add-on.
- Use distinct MQTT Discovery object IDs for the local integration.
- Remove retained v0.1.0 local discovery entries on startup so Home Assistant can separate the devices cleanly.

## 0.1.0

- Initial experimental release.
- Direct local WallLink connection.
- Automatic reconnect.
- Live `Data_All` / `Data_Change` state handling.
- MQTT Discovery.
- Verified Quiet Mode control.
- Read-only power, mode and fan state.
- Optional raw state and change topics.
