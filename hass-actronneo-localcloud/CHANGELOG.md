# Changelog

## 0.1.4

- Fixes Home Assistant warnings such as `Invalid fan_modes mode:` when a NEO status snapshot omits `UserAirconSettings.FanMode`.
- Normalizes an absent/blank NEO fan mode to `null` rather than an empty string.
- Publishes MQTT climate fan-mode discovery only after a real fan-mode value has been received; later status updates automatically add fan controls once available.
- Adds clearer NEO MQTT/status diagnostics, including INFO logs for full-status reception and `getAll` requests plus DEBUG summaries for status-change, heartbeat and published normalized state.

## 0.1.3

- Fixes Home Assistant MQTT Discovery rejecting NEO entities when the controller status does not contain a firmware version. `device.sw_version` is now omitted unless a non-empty string is available, matching Home Assistant's discovery schema.
- This resolves errors such as `string value is None at 'device.sw_version'` and allows the retained discovery configs to create the MQTT device and entities normally.

## 0.1.2

- Fixes NEO firmware 2.6.x repeatedly sending MQTT CONNECT on an already-established TLS/MQTT session. The compatibility proxy now absorbs repeated CONNECT packets and returns a successful CONNACK instead of forwarding them to Mosquitto, preventing `Bad client ... sending multiple CONNECT messages` protocol errors.
- Validates the real Mosquitto CONNACK before announcing a NEO as connected, so the add-on log now distinguishes TLS/CONNECT arrival from successful broker acceptance.
- Keeps normal MQTT packets flowing through the existing Mosquitto session after the duplicate CONNECT workaround.
- Expands README and installation documentation with the required host/container port mapping, `neo_mqtt_port` matching requirement, destination-port firewall rules, DNS override behaviour, UniFi/UDM notes, install order and troubleshooting guidance.
- Clarifies that Home Assistant MQTT Discovery creates NEO devices automatically after usable status is received; the manual **Add MQTT device** flow is not used.

## 0.1.1

- Avoids the standard Mosquitto Broker add-on's host TCP 8883 port conflict by mapping the NEO TLS MQTT listener to host port 28883 by default.
- Adds a `neo_mqtt_port` option and advertises that port through the local Nimbus messaging endpoint.
- The add-on Network host port for container port 8883 must match `neo_mqtt_port` if changed from the default.

## 0.1.0

- Initial experimental release.
- Emulates the Nimbus OAuth, account, messaging bootstrap and no-update OTA endpoints required by NEO controllers.
- Terminates the NEO TLS MQTT connection locally and rewrites the controller's password-only MQTT CONNECT into valid Home Assistant Mosquitto credentials.
- Supports multiple NEO controllers through a single add-on instance.
- Parses full-status, status-change, heartbeat and command-response MQTT traffic.
- Publishes normalized state and Home Assistant MQTT Discovery entities for the main climate system, zones, operating switches and common sensors.
- Translates Home Assistant MQTT climate/switch commands into native NEO `set-settings` commands.
- Persists the local Nimbus identity and TLS certificate across add-on restarts.
