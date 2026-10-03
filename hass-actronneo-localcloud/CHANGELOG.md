# Changelog

## 1.0.3

- Adds a 5-second timeout between successful NEO TLS establishment and receipt of the initial MQTT `CONNECT` packet.
- If a controller opens TLS but then stalls before MQTT, the proxy now closes that dead session early instead of waiting for the NEO's observed ~30-second timeout.
- Logs stalled pre-CONNECT sessions at INFO so restart tests can show whether early closure causes the controller to retry sooner.
- The timeout applies only before the first MQTT packet; normal established MQTT sessions are returned to blocking operation and are otherwise unchanged.

## 1.0.2

- Adds MQTT reconnect diagnostics around the NEO 2.6.x duplicate-CONNECT sequence so restart delays can be characterised without logging sensitive payload contents.
- Logs whether a NEO explicitly sends MQTT `DISCONNECT` after the duplicate CONNECT or simply closes the MQTT/TLS stream.
- At DEBUG level, records the MQTT packet type/flags/length of post-duplicate traffic, while INFO summarizes the final close reason and last packet type.
- No reconnect behaviour is changed yet; this release is intentionally diagnostic so the real Actron broker behaviour can be emulated more accurately in a follow-up fix.

## 1.0.1

- Gives disabled-by-default engineering/diagnostic entities meaningful icons for their enabled state, including compressor/fan, temperatures, Wi-Fi, uptime, communications, electrical values, EEV, firmware and fault indicators.
- Note: Home Assistant shows its generic disabled-entity eye icon while an entity remains disabled; the entity's own icon appears after it is enabled.

## 1.0

- Promotes Actron NEO Local Cloud from experimental to stable status.
- Adds live HVAC action to the main climate entity so Home Assistant can show `off`, `idle`, `heating`, `cooling`, `drying` and `fan` independently of the selected HVAC mode.
- Adds disabled-by-default engineering diagnostics for compressor capacity, indoor fan RPM/PWM, compressor running state, coil inlet/outdoor coil/discharge/suction/VSD temperatures, Wi-Fi signal, controller/MQTT uptime, MQTT reconnect count, VSD communications status, AC error code, LP/HP faults, supply voltage/current/power, EEV opening and superheat.
- Adds disabled-by-default equipment information entities for indoor unit firmware, outdoor unit firmware/family/capacity and Wi-Fi firmware.
- Keeps the normal device page compact; all new engineering/information entities are published as Home Assistant diagnostic entities and can be enabled individually when wanted.
- Corrects NTW/Inverter compressor power telemetry scaling: raw `CompPower` is converted to watts using the NEO/NTW x100 scale. NTW supply voltage receives the corresponding x10 scale.
- Exposes `CompSpeed` as Compressor Speed in `%` and gives it a speedometer icon.
- Adds local telemetry refreshes with `getAll` approximately every 5 seconds while a system is on and every 30 seconds while off. Native push/status-change updates are still processed immediately.
- Forces compressor power, speed and capacity to zero whenever the system/compressor state says the compressor is stopped, preventing stale retained compressor telemetry from lingering after shutdown.
- Updates the local Nimbus service identifier to 1.0 and expands README/DOCS for the stable release.

## 0.1.7

- Adds optimistic command state plus a 6-second per-NEO settling/suppression window to prevent Home Assistant controls from bouncing back to stale values immediately after commands.
- Mirrors the proven anti-bounce approach used by the Actron QUE bridge: the requested command state is published immediately, stale NEO `status-change`/`full-status` echoes are ignored briefly, then a canonical `getAll` refresh is requested when the settling window expires.
- Command settling is tracked independently per NEO, so simultaneous control of multiple locally connected units does not interfere across systems.
- Clears command suppression if a NEO disconnects, ensuring reconnect/full-status data is accepted normally.
- Marks `nimbus_user_id` as genuinely optional in the Home Assistant add-on schema and adds a clear UI description explaining that normal installations should leave it blank.
- Documents that the bridge learns each controller's real Actron/Nimbus UserId automatically from the native MQTT topic after connection and uses that learned value for commands.
- Keeps a private persistent generated UUID only for the local Nimbus bootstrap response when no override is supplied.
- Fixes clearing `nimbus_user_id` so a previously persisted override is no longer silently reused; blank now really means no manual override.

## 0.1.6

- Fixes NEO MQTT `full-status-broadcast` and `status-change-broadcast` event unwrapping. The previous parser incorrectly returned only the first nested dictionary from `event`, which commonly discarded `UserAirconSettings`, `RemoteZoneInfo`, temperatures and other state.
- Fixes status-change broadcasts being silently ignored when the event `type` field appeared first. This prevented Home Assistant from reflecting command-driven state changes even though the NEO returned command responses.
- Restores complete normalized state so power/mode, fan state, temperatures and zones can be populated from the actual NEO broadcast instead of fallback/default values.
- Corrects the 0.1.5 Nimbus UserId guidance: testing confirmed an already cloud-paired NEO can reach full-status/heartbeat using the generated local UUID, so `nimbus_user_id` is now documented as an optional advanced override rather than a normal setup requirement.

## 0.1.5

- Adds a `nimbus_user_id` option so an already cloud-paired NEO can be presented with the same Nimbus account/UserId it used before the local cutover.
- Persists a configured Nimbus UserId in the add-on data directory without printing it in normal logs.
- Retains the generated local UUID fallback for development/new-pairing scenarios.
- Expands the README and installation/troubleshooting documentation around Nimbus identity and DNS behaviour.
- Documents that a gateway-wide DNS override for `nimbus.actronair.com.au` can also redirect Home Assistant's official Actron Air cloud integration to the local emulator.

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
