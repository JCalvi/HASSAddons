# Changelog

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
