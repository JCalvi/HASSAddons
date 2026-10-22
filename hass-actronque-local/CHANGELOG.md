# Changelog

## 2026.10.4

- Fix 2026.10.3 selective-state publication errors caused by the production UI bridge still using the old no-argument method signature and a removed numeric publishing hook.
- Restore the overridable value formatting/validation hook and retain sensor percentage sanitisation.
- Extend selective dependency mapping to UI zone climate modes/actions and live compressor/fan changes so the actual climate action stays correct.
- Add end-to-end regression coverage against the actual `ActronQueLocalBridge` used by the running add-on, including initial snapshots, zone controls, action updates and numeric formatting.

## 2026.10.3

- Process only the MQTT entities affected by incoming WallLink `Data_Change` paths, including linked climate actions, target temperatures, zone enabled states and individual sensors.
- Avoid repeated whole-state deep copies during normal state publication; only snapshot the complete state when raw diagnostics are explicitly enabled.
- Skip zone discovery comparisons for ordinary telemetry, but detect zone structure, sensor membership and sensor battery-availability changes.
- Preserve full initialisation, `Data_All` and MQTT reconnect synchronisation; retain the established MQTT deduplication and native C WallLink decoder.
- Add regression tests covering selective updates, dependent topic mapping, full refreshes, sensor discovery and unknown structural updates; validate mode-dependent zone targets during partial updates.

## 2026.10.2

- Replace the high-CPU Python bitwise WallLink stream-cipher loop with an optimised native C implementation using precise 32-bit unsigned arithmetic; Python retains Base64 framing, padding checks and JSON parsing.
- Accelerate both received frame decryption and outgoing command encryption, with the original Python cipher automatically used if the native shared library cannot load.
- Compile the shared library for the selected CPU architecture in the add-on Docker image (amd64 and aarch64), without a compiler in the runtime image.
- Run a compatibility test suite as part of image builds: native/Python parity on varied binary frames, encrypt/decrypt round trips, fallback and malformed-message handling.
- No changes to MQTT entities, connection behaviour, sampling frequency or temperature control.

## 2026.10.1

- Default verbose WallLink `Data_Change` logging and full raw MQTT state publication to off; keep normal INFO-level operational logging enabled. Existing saved add-on options are not overwritten.

- Fix single-temperature Auto targets snapping back: shift the existing heat/cool band together around the requested midpoint (thanks to @dragonspy00 for identifying the issue in PR #52).
- Preserve independent Heat-only and Cool-only setpoint writes, and support both whole-system and per-zone Auto targets.
- Clamp Auto-mode band shifts to the configured 10–32°C control range while preserving the existing deadband; refuse updates when the existing band is unavailable or invalid instead of requesting equal setpoints.
- Reduce ongoing CPU and MQTT traffic by suppressing unchanged retained `/state` publications from the QUE WallLink bridge, including per-zone and sensor state.
- Keep change events, availability messages, MQTT discovery and commands unaffected by state deduplication.
- Clear the retained-state comparison cache on MQTT disconnect/reconnect and republish the full current state on reconnection.
- Cache only publications accepted by the MQTT client for QoS 1 delivery; unsuccessful publish attempts remain eligible for retry.


## 2026.9.3

- Fix Home Assistant climate action reporting so a QUE system that is on but not actively heating or cooling reports **Idle** rather than inheriting a stale compressor mode.
- Use the live outdoor-unit `CompressorOn` state, together with the active compressor mode and fan state, to distinguish **Heating**, **Cooling**, **Fan** and **Idle**; retain the legacy compressor-mode mapping as a fallback for partial/older WallLink payloads.

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
