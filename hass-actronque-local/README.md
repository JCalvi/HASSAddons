# Actron QUE Local

Direct local Home Assistant control of ActronAir QUE systems using the native WallLink protocol.

This add-on is designed as a local replacement for `hass-actronque`: it keeps the familiar Home Assistant entity IDs based on the real QUE master serial, but communicates directly with the wall controller instead of using the Actron cloud.

## Features

- Full local HVAC control over WallLink TCP.
- Main climate entity with heat/cool range, operating mode and fan mode.
- Zone climate entities with enable/disable and per-zone heat/cool targets.
- Away Mode, Control All Zones, Constant Fan and Quiet Mode controls.
- Indoor and outdoor temperature, humidity, compressor mode/capacity/power, coil inlet temperature, fan PWM/RPM and filter diagnostics.
- Wireless zone-sensor battery and RSSI where available.
- Automatic reconnect and MQTT Discovery.
- Guided synthetic-secondary setup for both master-only systems and systems that already have a physical secondary controller.
- Home Assistant setup-status sensor and **Redo Secondary Controller Setup** button.
- Optional raw WallLink state and Data_Change event topics for diagnostics.

## Home Assistant entity IDs

The add-on deliberately mirrors the entity naming used by `hass-actronque` so existing dashboards, automations and scripts can keep using the same IDs.

Examples:

- `climate.actronque_<master_serial>`
- `climate.actronque_<master_serial>_zone_4_alex_bed`
- `sensor.actronque_<master_serial>_temperature`
- `switch.actronque_<master_serial>_control_all_zones`

The serial is read from the actual QUE master, so multiple QUE systems remain distinct.

## Migrating from hass-actronque

Do not run both add-ons as active controllers at the same time.

Recommended migration:

1. Stop and disable `hass-actronque`.
2. Remove its MQTT-discovered device/entities from Home Assistant if they remain registered.
3. Install/configure `Actron QUE Local`.
4. Start the local add-on and allow MQTT Discovery to recreate the device.
5. Existing dashboards and automations should continue using the same entity IDs.

The local add-on uses its own MQTT discovery topics internally, but advertises cloud-compatible Home Assistant entity IDs and device identity.

## One-time secondary-controller setup

The QUE master treats the Home Assistant add-on as a synthetic secondary wall controller.

If the synthetic controller is already paired, the add-on connects normally and setup completes automatically.

### Master-only system — no physical secondary

If the installation has only the QUE master controller, leave `existing_secondary_serial` blank.

1. Start the add-on with **Automatic secondary setup** enabled.
2. The add-on checks for an existing physical secondary.
3. If none is detected, the setup status will ask you to select **Connect another controller** on the QUE master.
4. The add-on announces its synthetic secondary controller and pairs directly into the available secondary slot.
5. After pairing, the add-on raises `NV_SystemSettings.MaxSecondaryControllers` to the configured value (normally `2`) through the new local connection.
6. Setup is marked complete and normal local control starts.

No controller needs to be powered off or impersonated in a master-only installation.

### System with an existing physical secondary

For a typical system with one master and one physical secondary already paired:

1. Start the add-on with **Automatic secondary setup** enabled.
2. Leave the real secondary powered while the add-on detects its serial, or enter the serial manually in `existing_secondary_serial`.
3. When the setup-status sensor/log asks, power off the physical secondary and reboot the QUE master.
4. The add-on temporarily identifies as the known secondary and raises `NV_SystemSettings.MaxSecondaryControllers` to the configured value (normally `2`).
5. On the QUE master, select **Connect another controller**.
6. The add-on announces the synthetic controller and waits for the master to accept it.
7. When setup reports complete, power the original secondary back on.

The setup state is stored under `/data`, so normal add-on restarts do not repeat the pairing process.

If setup needs to be repeated later, press **Redo Secondary Controller Setup** in Home Assistant.

## Important options

- `master_ip` — IP address of the QUE master wall controller.
- `master_port` — WallLink TCP port, normally `19296`.
- `serial` — synthetic Home Assistant secondary-controller serial.
- `auto_secondary_setup` — enables the guided one-time setup workflow.
- `existing_secondary_serial` — optional known physical-secondary serial. Leave blank for automatic detection; if no physical secondary exists, the add-on uses the master-only direct-pairing path.
- `max_secondary_controllers` — controller limit used during setup; normally `2`, allowing Home Assistant and one physical secondary to coexist.
- `setup_retry_delay` — delay between setup retries while waiting for physical steps.
- `topic_prefix` — internal MQTT topic prefix.
- `publish_raw_state` — publishes the full current QUE state for diagnostics.

## MQTT diagnostics

With the default topic prefix:

- `hass-actronque-local/status` — WallLink online/offline status.
- `hass-actronque-local/bridge/status` — application/MQTT status.
- `hass-actronque-local/raw/state` — full current QUE state when enabled.
- `hass-actronque-local/event/change` — latest incoming WallLink `Data_Change`.
- `hass-actronque-local/secondary_setup/status` — secondary-controller setup state.
- `hass-actronque-local/secondary_setup/redo` — command topic used by the redo button.

## Requirements

- Home Assistant OS/Supervised add-on environment.
- MQTT service available to the add-on.
- Network access from Home Assistant to the QUE master.
- The QUE master IP should be stable, preferably via DHCP reservation.
