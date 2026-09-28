# Actron QUE Local — Configuration

Actron QUE Local connects directly to one or more QUE master wall controllers using the native WallLink protocol. It does not require the Actron cloud for operation.

The add-on includes guided one-time synthetic-secondary setup for both master-only systems and systems that already have a physical secondary controller.

## Requirements

- Home Assistant OS or Supervised with add-on support.
- MQTT service available to the add-on.
- Network access from Home Assistant to each QUE master.
- Stable QUE master IP addresses are recommended.

The add-on obtains MQTT credentials from Supervisor automatically.

## Main configuration

- `master_ip` — one QUE master endpoint or a comma-separated list. Use `IP:port`; the port may be omitted and defaults to `19296`.
- `serial` — synthetic Home Assistant secondary-controller serial. For multiple QUE systems, enter matching serials as a comma-separated positional list. Missing additional serials are generated automatically.
- `auto_secondary_setup` — enables guided secondary-controller setup. If multiple units need setup, the add-on serializes first-time discovery/pairing automatically.
- `existing_secondary_serial` — optional existing physical-secondary serial. For multiple QUE systems, enter matching serials in the same order as `master_ip`; leave blank where automatic detection should be used.
- `max_secondary_controllers` — target value for `NV_SystemSettings.MaxSecondaryControllers`; normally `2`, allowing Home Assistant and one physical secondary to coexist.
- `setup_retry_delay` — seconds between setup retries while waiting for physical actions.
- `separate_heat_cool_targets` — `false` (default) exposes one target temperature; `true` exposes independent heating and cooling targets on the same climate entities.
- `topic_prefix` — internal MQTT topic prefix.
- `discovery_prefix` — Home Assistant MQTT Discovery prefix.
- `reconnect_delay` — WallLink reconnect delay.
- `socket_timeout` — WallLink receive timeout.
- `log_data_changes` — log incoming `Data_Change` messages.
- `publish_raw_state` — publish complete current QUE state to MQTT.
- `log_level` — application logging level.

There is no separate `master_port` option. Existing host-only values such as `192.168.1.218` remain valid and use WallLink port `19296` automatically.

## Multiple QUE systems

For example:

```yaml
master_ip: 192.168.1.218:19296, 192.168.1.219:19296
serial: FA000001, FA000002
```

Each configured QUE gets an independent WallLink session, MQTT namespace, Home Assistant device identity and secondary-setup state. The actual QUE master serial remains the basis of Home Assistant entity identity, so multiple systems do not collide.

Normal operation is concurrent. When automatic secondary setup is required on multiple units, only one incomplete QUE is permitted to perform UDP discovery/pairing at a time. As soon as it records setup completion, the coordinator enables setup for the next incomplete QUE. Units that are already paired start normal operation immediately and do not wait for the setup queue.

## Temperature targets

The **Separate Heat/Cool Targets** option applies to the main climate and every zone climate without changing their entity IDs.

With the option disabled, Home Assistant shows a single target. A change writes the cooling target in Cool mode, heating target in Heat mode, and both targets in Auto mode. With the option enabled, Home Assistant exposes the QUE heating and cooling setpoints independently.

For the single target state, Cool reports the cooling target, Heat reports the heating target, and Auto/Off/Fan-only report the midpoint of the stored heat and cool targets. This mirrors the existing Actron QUE Cloud behaviour.

## Migrating from hass-actronque

Actron QUE Local deliberately advertises the same Home Assistant device/entity IDs as `hass-actronque`, derived from the actual master serial. This allows existing dashboards and automations to continue using their current entity IDs.

Do not operate the cloud and local add-ons as active controllers for the same QUE system at the same time.

## First start when the synthetic controller is already paired

If the configured synthetic serial is already accepted by the QUE master, startup is automatic. The setup-status entity settles on `Setup complete`.

## First start on a master-only system

If there is no physical secondary controller, leave the corresponding `existing_secondary_serial` entry blank.

With automatic setup enabled:

1. The add-on checks for an existing physical secondary.
2. If none is found, the setup status asks you to select **Connect another controller** on that QUE master.
3. The add-on sends the secondary-style UDP announcement on port `19295` and waits for that master to accept the synthetic controller on its configured WallLink endpoint.
4. Once accepted, the add-on raises `NV_SystemSettings.MaxSecondaryControllers` to the configured target value through the new synthetic-controller connection.
5. Setup is saved as complete and normal local operation begins.

No controller needs to be powered off or impersonated in a master-only system.

## First start when a physical secondary already occupies the available slot

1. Initially leave the physical secondary powered on. The add-on attempts to detect its serial automatically, or use `existing_secondary_serial` to supply it explicitly.
2. When the setup status asks, power off that physical secondary and reboot its QUE master.
3. The add-on temporarily identifies as the existing secondary and writes `NV_SystemSettings.MaxSecondaryControllers` to the configured target value.
4. On that QUE master choose **Connect another controller**.
5. The add-on announces the synthetic controller and waits for acceptance.
6. When setup reports complete, power the original physical secondary back on.

Each QUE's completion state is stored separately under `/data`, so normal restarts do not repeat completed setup.

## Re-running setup

Each QUE exposes a **Redo Secondary Controller Setup** button and a **Secondary Controller Setup Status** diagnostic sensor. Pressing the button clears that QUE's saved completion flag and reruns its guided setup sequence.

## Entity naming

Entity IDs follow the cloud add-on convention and include the actual QUE master serial, for example:

- `climate.actronque_<master_serial>`
- `climate.actronque_<master_serial>_zone_4_alex_bed`
- `sensor.actronque_<master_serial>_temperature`
- `switch.actronque_<master_serial>_control_all_zones`

This keeps systems with different master serials distinct and makes migration from `hass-actronque` straightforward.
