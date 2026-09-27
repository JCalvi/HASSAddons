# Changelog

## 2026.9.1

- Promote Actron QUE Local to the final calendar-versioned release line.
- Add a complete master-only setup path for systems with no physical secondary controller: when none is detected, Home Assistant pairs directly into the available secondary slot after **Connect another controller** is selected on the QUE master.
- After master-only pairing, automatically raise `NV_SystemSettings.MaxSecondaryControllers` through the new synthetic-controller connection so a physical secondary can still be added later if required.
- Keep the existing physical-secondary workflow for systems where the available secondary slot is already occupied.
- Rename the MQTT device to `Actron QUE Local (<SystemName>)` while keeping the main climate entity name neutral as `Actron QUE (<SystemName>)`.
- Preserve existing Home Assistant entity IDs and cloud-compatible unique IDs for seamless migration from the cloud add-on.
- Remove redundant standalone zone temperature sensors, duplicate hardware-sensor temperatures and per-zone Enabled switches when the zone climate entity already provides the same function.
- Suppress invalid battery readings such as `255%` and clear stale retained MQTT discovery for entities that are no longer exposed.
- Refresh README and configuration documentation for both master-only and physical-secondary installations.

## 0.3.6

- Rename the MQTT device to `Actron QUE Local (<SystemName>)` so the local and cloud add-ons are clearly differentiated at the device level.
- Keep the main climate entity name neutral as `Actron QUE (<SystemName>)` for seamless dashboards and entity presentation between Local and Cloud.
- Preserve existing entity IDs and unique IDs while changing only the displayed MQTT device name.

## 0.3.5

- Remove standalone per-zone temperature sensor entities because each zone climate entity already exposes the same `LiveTemp_oC` reading as `current_temperature`.
- Clear retained MQTT discovery for the old `sensor.actronque_<serial>_zone_<n>_<zone>_temperature` entities so they disappear automatically after upgrade/restart.
- Keep zone climate entities as the single place for zone temperature, enable/disable state and heat/cool target control.

## 0.3.4

- Remove duplicate hardware-sensor temperature entities such as `sensor.actronque_<serial>_zone_4_sensor_<sensor-id>_temperature` when the same physical reading is already exposed as the zone temperature.
- Clear retained MQTT discovery for those duplicate sensor-ID temperature entities so they disappear automatically after upgrade/restart.
- Remove redundant per-zone **Enabled** switches because the zone climate entity already controls the same `EnabledZones[]` state (`Off` disables the zone; an active HVAC mode enables it).
- Clear retained MQTT discovery for the old zone Enabled switches so they disappear automatically after upgrade/restart.
- Keep the raw per-sensor temperature data internally available for future diagnostics without cluttering the Home Assistant device.

## 0.3.3

- Treat QUE wireless-sensor `Battery_pc=255` as “battery not applicable” rather than a real 255% battery reading.
- Do not create battery entities for sensors whose battery value is outside the valid 0-100% range, and clear any retained MQTT discovery from earlier versions so bogus battery entities disappear automatically.
- Restore cloud-compatible damper-position entity IDs and matching cloud `unique_id` values so existing dashboards and automations continue to work after migration.
- Normalize out-of-range QUE percentage sentinels so invalid compressor-capacity and Fan PWM values are not exposed as 255%.
- Automatically learn and persist controller firmware during secondary-controller discovery; keep only an internal fallback for recovery rather than exposing firmware as a normal add-on option.
- Improve Home Assistant icons for Quiet Mode, Compressor Mode, Fan Mode, operating Mode, Master Serial and System Name.
- Keep the one-time unexposed `Data_All` field scan available for troubleshooting, but move it to DEBUG logging after confirming the additional telemetry is mostly low-value controller diagnostics.

## 0.3.2

- Remove the firmware field from normal add-on options and automatically learn/persist the controller firmware during secondary-controller discovery, with an internal fallback retained for recovery.
- Improve Home Assistant icons for Quiet Mode, Compressor Mode, Fan Mode, operating Mode, Master Serial and System Name.
- Restore cloud-compatible damper-position entity IDs such as `sensor.actronque_<serial>_zone_6_downstairs_damper_position` and the matching cloud `unique_id` values.
- Normalize QUE out-of-range percentage sentinels so values such as compressor capacity `255` are not exposed as `255%`; inactive compressor capacity and invalid Fan PWM now publish as `0`.
- Add a one-time first-connection scan that logs unexposed `Data_All` leaf fields to help identify useful QUE telemetry for future entities without repeatedly spamming logs.

## 0.3.1

- Fix duplicate MQTT devices when migrating from `hass-actronque`.
- Reuse the cloud add-on's MQTT device identifier exactly, including the master serial's original case.
- Reuse cloud-compatible MQTT `unique_id` values for the main climate, zones, switches and common sensors so Home Assistant can recreate or adopt the expected entities cleanly.
- Keep local MQTT transport/discovery topics separate while preserving the established Home Assistant device and entity identities.

## 0.3.0

- Promote Actron QUE Local to stable/production status.
- Add guided one-time synthetic secondary-controller setup.
- Detect an existing physical secondary automatically when possible, or allow its serial to be entered manually.
- Raise `NV_SystemSettings.MaxSecondaryControllers` during setup so a physical secondary and Home Assistant can coexist.
- Add secondary-style UDP pairing announcements on port `19295` and WallLink acceptance on TCP `19296`.
- Persist setup completion under `/data` so normal restarts do not repeat pairing.
- Add a **Secondary Controller Setup Status** diagnostic entity.
- Add a **Redo Secondary Controller Setup** Home Assistant button.
- Make Home Assistant device/entity IDs compatible with `hass-actronque`, using the actual QUE master serial so existing dashboards and automations can be retained during migration.
- Keep local MQTT discovery topics separate from the cloud add-on while advertising cloud-compatible entity IDs.
- Keep Paho MQTT 2.1.0 and reduce the runtime image by moving pip into a builder stage.
- Rewrite README and configuration documentation for the current full local-control feature set and migration workflow.

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
