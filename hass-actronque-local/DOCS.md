# Actron QUE Local — Configuration

Actron QUE Local connects directly to the QUE master wall controller using the native WallLink protocol. It does not require the Actron cloud for operation.

The add-on includes a guided one-time synthetic-secondary setup for both master-only systems and systems that already have a physical secondary controller.

## Requirements

- Home Assistant OS or Supervised with add-on support.
- MQTT service available to the add-on.
- Network access from Home Assistant to the QUE master.
- A stable IP address for the QUE master is recommended.

The add-on obtains MQTT credentials from Supervisor automatically.

## Main configuration

- `master_ip` — IP address of the QUE master wall controller.
- `master_port` — native WallLink TCP port; normally `19296`.
- `serial` — serial presented by the synthetic Home Assistant secondary controller.
- `auto_secondary_setup` — enables the guided secondary-controller setup workflow.
- `existing_secondary_serial` — optional serial of an existing physical secondary. Leave blank to detect one automatically; if none exists, the add-on uses the master-only direct-pairing path.
- `max_secondary_controllers` — target value for `NV_SystemSettings.MaxSecondaryControllers`; normally `2`, allowing Home Assistant and one physical secondary to coexist.
- `setup_retry_delay` — seconds between setup retries while waiting for physical actions.
- `topic_prefix` — internal MQTT topic prefix.
- `discovery_prefix` — Home Assistant MQTT Discovery prefix.
- `reconnect_delay` — WallLink reconnect delay.
- `socket_timeout` — WallLink receive timeout.
- `log_data_changes` — log incoming `Data_Change` messages.
- `publish_raw_state` — publish complete current QUE state to MQTT.
- `log_level` — application logging level.

## Migrating from hass-actronque

Actron QUE Local deliberately advertises the same Home Assistant device/entity IDs as `hass-actronque`, derived from the actual master serial. This allows existing dashboards and automations to continue using their current entity IDs.

Recommended migration:

1. Stop and disable `hass-actronque`.
2. Remove its MQTT device/entities from Home Assistant if they remain registered.
3. Configure and start Actron QUE Local.
4. Allow MQTT Discovery to recreate the device and entities.

Do not operate both add-ons as active controllers at the same time.

## First start when the synthetic controller is already paired

If the configured synthetic serial is already accepted by the QUE master, startup is automatic. Logs should show the WallLink connection being accepted and the initial `Data_All` state being received.

The setup-status entity will settle on `Setup complete`.

## First start on a master-only system

If there is no physical secondary controller, leave `existing_secondary_serial` blank.

With automatic setup enabled:

1. The add-on briefly checks for an existing physical secondary.
2. If none is found, the setup status asks you to select **Connect another controller** on the QUE master.
3. The add-on sends the secondary-style UDP announcement on port `19295` and waits for the master to accept the synthetic controller on WallLink TCP port `19296`.
4. Once accepted, the add-on raises `NV_SystemSettings.MaxSecondaryControllers` to the configured target value through the new synthetic-controller connection.
5. Setup is saved as complete and normal local operation begins.

No controller needs to be powered off, and no existing-secondary impersonation is required on a master-only system.

## First start when a physical secondary already occupies the available slot

A common QUE installation has one master and one physical secondary, with the existing slot already occupied.

With automatic setup enabled:

1. Initially leave the physical secondary powered on. The add-on attempts to detect its serial automatically. Alternatively enter it in `existing_secondary_serial`.
2. When the setup status asks, power off the physical secondary and reboot the QUE master.
3. The add-on temporarily identifies as the existing secondary and writes `NV_SystemSettings.MaxSecondaryControllers` to the configured target value, normally `2`.
4. On the QUE master choose **Connect another controller**.
5. The add-on sends the secondary-style UDP announcement on port `19295` and waits for the master to accept the synthetic controller on WallLink TCP port `19296`.
6. When setup reports complete, power the original physical secondary back on.

The completion state is saved under `/data`, so normal restarts do not repeat setup.

## Re-running setup

Home Assistant exposes a **Redo Secondary Controller Setup** button. Pressing it clears the saved completion flag and reruns the guided setup sequence.

The corresponding diagnostic sensor is **Secondary Controller Setup Status**.

## MQTT diagnostic topics

Default prefix: `hass-actronque-local`

- `hass-actronque-local/status` — WallLink `online` / `offline`.
- `hass-actronque-local/bridge/status` — application MQTT status.
- `hass-actronque-local/raw/state` — complete current QUE state when enabled.
- `hass-actronque-local/event/change` — latest incoming WallLink `Data_Change`.
- `hass-actronque-local/secondary_setup/status` — guided setup status.
- `hass-actronque-local/secondary_setup/redo` — command used by the redo button.

## Entity naming

Entity IDs follow the cloud add-on convention and include the actual QUE master serial, for example:

- `climate.actronque_<master_serial>`
- `climate.actronque_<master_serial>_zone_4_alex_bed`
- `sensor.actronque_<master_serial>_temperature`
- `switch.actronque_<master_serial>_control_all_zones`

This keeps systems with different master serials distinct and makes migration from `hass-actronque` straightforward.
