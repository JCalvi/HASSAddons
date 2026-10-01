# Changelog

## 0.1.0

- Initial experimental release.
- Emulates the Nimbus OAuth, account, messaging bootstrap and no-update OTA endpoints required by NEO controllers.
- Terminates the NEO TLS MQTT connection locally and rewrites the controller's password-only MQTT CONNECT into valid Home Assistant Mosquitto credentials.
- Supports multiple NEO controllers through a single add-on instance.
- Parses full-status, status-change, heartbeat and command-response MQTT traffic.
- Publishes normalized state and Home Assistant MQTT Discovery entities for the main climate system, zones, operating switches and common sensors.
- Translates Home Assistant MQTT climate/switch commands into native NEO `set-settings` commands.
- Persists the local Nimbus identity and TLS certificate across add-on restarts.
