# Changelog

## 2026.9.2

- Add **Separate Heat/Cool Targets** configuration, matching the Actron QUE Cloud behaviour.
- Default to a single target temperature for the main climate and all zone climate entities.
- In single-target mode, write the cooling setpoint in Cool mode, heating setpoint in Heat mode, and both setpoints in Auto mode; Off and Fan-only ignore target changes, matching the cloud add-on.
- Publish the cooling target in Cool mode, heating target in Heat mode, and the heat/cool midpoint for Auto, Off and Fan-only modes.
- When **Separate Heat/Cool Targets** is enabled, retain the existing independent high/low target controls.
- Preserve all existing climate entity IDs and cloud-compatible unique IDs when switching between target modes.
- Keep the separate Heating/Cooling Number entities suppressed; target control remains on the climate entities only.
- Add support for multiple independent QUE systems from one add-on instance.
- Allow `master_ip` to contain one `IP:port` endpoint or a comma-separated list of endpoints; host-only values remain backwards compatible and default to WallLink port `19296`.
- Remove the redundant user-facing `master_port` option.
- Allow `serial` and `existing_secondary_serial` to use matching positional lists for multi-QUE installations; missing additional synthetic serials are generated automatically.
- Give each QUE an independent WallLink session, MQTT namespace, Home Assistant device identity and persisted secondary-controller setup state.
- Serialize first-time multi-QUE automatic secondary setup so only one incomplete unit performs UDP discovery/pairing at a time, preventing setup traffic from overlapping between QUE masters.
- Allow already-paired QUE units to start and operate concurrently while another configured unit is completing first-time setup.
- Restore the proven QUE WallLink Base64/padded wire framing after a regression briefly sent raw encrypted bytes terminated by newline. Raw ciphertext can contain `0x0A`, causing false frame boundaries and repeated `UnicodeDecodeError` failures. Normal operation and secondary setup now share the same safe codec.
- Add semantic Home Assistant icons for **WallLink Connected** and **Air Conditioner**, complementing the existing Quiet Mode, Compressor Mode, Fan Mode, operating Mode, Master Serial and System Name icons.
- Update README, configuration documentation and Home Assistant option descriptions for multi-QUE operation and the endpoint-list format.

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

- Promote the add-on from experimental to production-ready status.
- Add guided synthetic-secondary controller setup and redo control.
- Add full local QUE climate, zone and diagnostic entity support.
