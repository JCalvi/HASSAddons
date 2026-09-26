# Actron QUE Local

Direct local Home Assistant control of an ActronAir QUE system using the native
WallLink protocol.

## Current controls

Version 0.1.0 intentionally starts conservatively.

### Writable
- Quiet Mode — verified against the real QUE master.

### Read-only
- WallLink connection
- Aircon on/off state
- Operating mode
- Fan mode
- System name
- Master serial

The full QUE state can also be published to the MQTT topic:

`hass-actronque-local/raw/state`

and each incoming `Data_Change` is published to:

`hass-actronque-local/event/change`

These will be used to add the remaining controls after their exact WallLink
variable paths have been verified.
