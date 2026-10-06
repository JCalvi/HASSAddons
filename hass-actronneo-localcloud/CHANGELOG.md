## 1.3.1

- Corrects the add-on startup status messages so they report the configured log level and whether retained raw NEO state publishing is enabled or disabled.
- Raw NEO MQTT RX/TX diagnostics are now described as enabled only when the configured log level is `DEBUG`; at INFO/WARNING/ERROR startup explicitly says those DEBUG payload diagnostics are disabled.
- No runtime control, MQTT, discovery, Schedule, HVAC or telemetry behaviour changes.

## 1.3.0

- Removes the temporary Schedule EndTime Self-Test / Schedule Write Probe button, result sensor, probe state tracking, response-correlation capture, and all associated schedule-edit diagnostic code.
- Retains the proven native Schedule ON/OFF control using indexed `NV_Schedule.Events[n].Enabled` writes and the 1.2.9 optimistic master-state debounce fix.
- Records the schedule-edit investigation as closed for the known local `set-settings` interface: the 1.2.11 guarded probe tested nine plausible write representations and none produced canonical `getAll` persistence for an Event 0 EndTime change.
- Promotes **Indoor Fan RPM** from a disabled engineering diagnostic to a normal enabled-by-default sensor on the NEO device page.
- Leaves Indoor Fan PWM and the remaining engineering/information telemetry as disabled-by-default diagnostic entities.

## 1.2.11

- Replaces the single-format Schedule EndTime test with a comprehensive guarded **Schedule Write Probe**.
- Tests nine plausible NEO `set-settings` representations for changing only Event 0 `EndTime`: scalar EndTime; scalar EndTime plus the current Enabled flag; all Event 0 fields flattened to indexed scalar paths; the flattened event plus the current master Enabled flag; a complete indexed Event 0 object; the indexed event object without ID; the complete Events array; master Enabled plus the complete Events array; and the complete NV_Schedule object.
- Uses canonical `getAll` persistence as the authoritative success criterion. ACK/status-change behavior is logged for diagnosis but does not override canonical state.
- Captures diagnostic command responses from the MQTT response topic even when the NEO returns malformed JSON, allowing the known truncated/empty ACK-like response for unsupported schedule properties to be distinguished from a timeout.
- Starts with a canonical baseline check, verifies the original EndTime remains intact after each failed candidate, and stops immediately when a confirmed writable representation is found.
- If any candidate changes the schedule, the probe restores the exact original schedule before reporting success. Restore first uses the working method and then falls back through every probe representation if required.
- Final restore safety is judged by canonical `getAll`: an unchanged/original schedule is accepted as safe even if a no-op restore command receives an empty or malformed ACK-like response.
- Stops further probing and reports a CRITICAL result if a mutation is detected but the original EndTime cannot be restored.
- Keeps normal periodic telemetry polling suspended for the tested NEO while the probe runs to make the result unambiguous.
- This is intended as the final broad schedule-write investigation: if all nine representations fail while the original state remains confirmed, schedule editing will be considered unsupported through the known local `set-settings` interface.

## 1.2.10

- Adds a temporary Home Assistant diagnostic button, **Schedule EndTime Self-Test**, to prove whether `NV_Schedule.Events[0].EndTime` is writable before implementing schedule editing.
- The test reads and preserves the exact current Event 0 `EndTime`, writes a temporary value five minutes later, verifies the command ACK, waits for a matching native status-change, requests `getAll`, and verifies canonical persistence.
- The original EndTime is restored in a `finally` path even when an earlier test stage fails. Restore success is verified by command ACK plus canonical `getAll` persistence; a restore status-change is logged but is not required when the test write was ignored and the original value never changed.
- Adds an enabled diagnostic result sensor showing `RUNNING`, `PASS`, or a concise `FAIL: ...` reason, while the add-on log records each stage independently.
- Suppresses normal periodic telemetry refreshes for the tested controller while the self-test is running to reduce ambiguity in the diagnostic capture.
- This is diagnostic-only functionality intended to be removed once the NEO schedule write format is confirmed.

## 1.2.9

- Fixes the Schedule optimistic-state matcher introduced in 1.2.8. The regular expression was double-escaped and therefore did not recognize indexed `NV_Schedule.Events[n].Enabled` command paths.
- Schedule ON/OFF now immediately mirrors the controller-derived `NV_Schedule.Enabled` master state during the existing six-second command settling window, preventing the Home Assistant Schedule switch from bouncing to its previous state.
- Adds an explicit DEBUG log entry when the optimistic Schedule master state is mirrored, making this debounce path directly verifiable.
- No changes to the other 1.2.8 controls.

## 1.2.8

- Fixes the Home Assistant Schedule switch bounce after a successful NEO Connect-style schedule command. During the existing six-second command settling window, indexed `NV_Schedule.Events[n].Enabled` writes now also mirror the controller-derived `NV_Schedule.Enabled` master state used by the HA switch.
- Changes zone ON/OFF writes to the official NEO Connect indexed `UserAirconSettings.EnabledZones[n]` property instead of rewriting the complete EnabledZones array. Zone enable no longer implicitly powers on the complete system or changes its operating mode.
- Adds capability-driven Away heating and cooling setpoint controls using the APK-confirmed `NV_SystemSettings.AwayMode.TemperatureSetpoint_Heat_oC` and `TemperatureSetpoint_Cool_oC` paths when those settings are present in controller state.
- Adds per-zone airflow setpoint controls when `RemoteZoneInfo[n].AirflowSetpoint` is present, using the APK-confirmed indexed property path.
- Adds per-zone name controls using the APK-confirmed `RemoteZoneInfo[n].NV_Title` property.
- Quick Timer is intentionally not exposed yet: NEO Connect confirms `NV_QuickTimer` / `NV_QuickTimer.Master[0]`, but the complete serialized timer write shape has not yet been proven and the add-on will not guess it.
- Retains the raw MQTT TX/RX DEBUG diagnostics for first-use verification of the new controls.

## 1.2.7

- Fixes Schedule ON/OFF commands to match the command serialization used by the official NEO Connect 2.0.1 (1526) Android app.
- Sends each learned schedule event as an individual `NV_Schedule.Events[index].Enabled` setting inside the native `set-settings` command.
- Removes the unsuccessful 1.2.6 write of `NV_Schedule.Enabled` and the complete `NV_Schedule.Events` array; schedule times, days, zones, modes, fan modes and temperature setpoints are no longer transmitted when toggling Schedule.
- Retains fail-closed validation against the currently learned `NV_Schedule.Events` state and keeps raw MQTT TX/RX DEBUG diagnostics for verification.

# Changelog

## 1.2.6

- Adds explicit startup logging of the running Home Assistant add-on version.
- Adds an explicit startup confirmation that raw NEO MQTT RX/TX diagnostic instrumentation is present and is emitted when the add-on log level is DEBUG.
- Re-enables the Home Assistant Schedule switch as a guarded protocol test based on the captured native NEO schedule representation.
- Schedule writes preserve the complete learned `NV_Schedule.Events` array and change only `NV_Schedule.Enabled` plus each existing event's `Enabled` field.
- Refuses Schedule writes if a valid learned `NV_Schedule.Events` array is unavailable or an event lacks its native `Enabled` field; no schedule times, days, zones, modes, fan modes or setpoints are invented.
- Raw MQTT TX/RX diagnostics remain enabled at DEBUG so the test command, ACK/rejection and resulting native state can be verified.

## 1.2.5

- Adds DEBUG logging of the raw native NEO MQTT `status-change` payload before parsing, preserving the complete schedule event structure needed to investigate `NV_Schedule.Enabled` writes.
- Logs the redacted native MQTT topic, payload byte count and up to 16 KiB of payload data; Nimbus user IDs, UUIDs, email addresses, JWTs and obvious credential/token fields are redacted.
- Adds equivalent DEBUG logging for commands transmitted by the bridge to the NEO so command payloads and native responses can be compared directly.
- Retains raw `cmd-response` diagnostics using the same expanded safe payload logger.
- Schedule writes remain disabled while this diagnostic capture establishes the firmware's accepted schedule representation.

## 1.2.4

- Disables Home Assistant Schedule writes pending confirmation of the NEO firmware's accepted schedule command format.
- Schedule ON/OFF requests are now safely ignored and the current device state is republished instead of sending the unconfirmed `NV_Schedule` write that could be rejected by the controller.
- Keeps Schedule state reporting/readback available while preventing unsafe writes; the 1.2.3 DEBUG command-response diagnostics remain available for further protocol investigation.

## 1.2.3

- Captures native NEO `cmd-response` payloads at DEBUG level before attempting JSON decoding, so firmware command rejections can be inspected instead of appearing only as `Invalid JSON` warnings.
- Command-response diagnostics are bounded to 512 characters and redact obvious tokens, passwords/secrets, email addresses, JWTs and UUIDs before logging.
- Leaves the 1.2.2 schedule write behaviour unchanged while gathering the exact controller response needed to determine the accepted schedule command format.

## 1.2.2

- Fixes the Home Assistant Schedule switch write path. Native NEO testing showed schedule ON/OFF changes are emitted as the compound `NV_Schedule` object (`Enabled` together with `Events`), rather than as an independently writable `NV_Schedule.Enabled` setting.
- Schedule commands now send the controller's complete current `NV_Schedule` object with only the master `Enabled` value changed, preserving all existing schedule events, times, days, modes, setpoints and zone selections.
- Keeps the 1.2.1 DEBUG field-path diagnostics available for further protocol work.

## 1.2.1

- Adds DEBUG-only NEO `status-change` field-path logging to identify undocumented controller settings such as the native schedule enable control.
- Boolean changes include their `true`/`false` value so ON/OFF transitions can be distinguished; arbitrary string and numeric payload values are intentionally not logged.
- Field diagnostics are emitted before the command-settling suppression check, allowing native controller responses during the 6-second anti-bounce window to be inspected without changing normal state handling.

## 1.2

- Adds an enabled-by-default Schedule switch that controls the NEO master `NV_Schedule.Enabled` flag without altering stored schedule events.
- Adds deterministic MQTT Discovery `default_entity_id` values for all NEO entities using the controller serial and system name, for example `climate.actron_neo_26d03211_north_end_pac`.
- Keeps existing MQTT `unique_id` values unchanged; Home Assistant may retain already-registered entity IDs until they are renamed or recreated once.
- Updates README and full installation documentation to describe schedule control and the canonical entity ID format.

## 1.1.1

- Removes the `nimbus_user_id` add-on option from the Home Assistant schema, options UI, translation metadata and startup path.
- Always creates and persists a private local UUID for the Nimbus bootstrap `UserId`; no real Actron/Nimbus account UUID needs to be entered or retained.
- Keeps command routing unchanged: once a NEO connects, the bridge learns the controller's real Actron/Nimbus UserId from its native MQTT topic and uses that learned value for commands.
- Existing configured `nimbus_user_id` values are no longer read after upgrading to 1.1.1 and can be discarded.
- Updates README and full installation documentation to describe the automatic bootstrap identity and removes obsolete Nimbus ID setup steps/examples.
- Expands reconnect documentation with the completed real-cloud test result: the production Actron service also showed an occasional failed first reconnect followed by another firmware retry slot.

## 1.1.0

- Promotes the tested local-cloud implementation to a clean production release after the reconnect investigation.
- Removes the temporary `/client/account` delay experiment and the synthetic Nimbus JWT experiment, including their add-on options, environment wiring and diagnostic code.
- Returns OAuth handling to the simple local bearer token required by the local MQTT compatibility path; no real Actron token, refresh token or signing key is required.
- Simplifies duplicate-CONNECT handling to the minimum required compatibility behaviour: acknowledge the repeated CONNECT locally and keep the existing Supervisor Mosquitto session.
- Removes the detailed post-duplicate packet tracing used during reconnect diagnosis while retaining normal connection/disconnection logging.
- Documents that NEO firmware 2.6.x uses an approximately 30-second MQTT reconnect interval. A controlled forced disconnect against the real Actron MQTT service showed the same roughly 31-second wait before the first replacement connection.
- Keeps the real Nimbus `/client/account` HAL-style `_links` structure, local `getAll` refresh, command anti-bounce, live HVAC action, diagnostics/entities and all normal 1.0 functionality.

## 1.0.9

- Adds an opt-in `nimbus_synthetic_jwt` diagnostic for the NEO OAuth refresh path. It is disabled by default and does not change normal 1.0.8 behaviour unless explicitly enabled.
- When enabled, `/api/v0/oauth/token` returns a locally signed RS256 JWT instead of the simple `LOCAL-NEO-TOKEN`, matching the claim names/types observed in a real Nimbus refresh-token response.
- Mirrors the real Nimbus issuer/audience, paired-controller roles, `nxgen` pairing/session/serial/no-log claims, 72-hour token lifetime and four-entry MQTT ACL structure while keeping all identity values local/synthetic.
- Uses the incoming NEO refresh token only as the local synthetic `nxgen/pairing-id` claim and never logs it. The JWT is signed with the add-on's persistent local RSA key; no Actron signing key or cloud token is stored.
- Resolves the NEO serial from its User-Agent and reuses the cached controller name where available, allowing each controller to receive a controller-specific synthetic token.
- Intended to test whether NEO 2.6.x parses the real Nimbus JWT during OAuth bootstrap and whether that token structure affects the later TLS-without-CONNECT or duplicate-CONNECT reconnect states.

## 1.0.8

- Mirrors the HAL-style `_links` object observed in a real Nimbus `/api/v0/client/account` response while keeping all account values local/synthetic.
- Adds the real `self`, `change-email`, `change-password`, `update-details`, `register-account`, `forgot-password`, and `reset-password` link relations and titles.
- Leaves the top-level account fields, MQTT handling, response timing, and optional 1.0.7 delay diagnostic unchanged so this is a controlled response-structure experiment.
- Intended to test whether the previously empty local `_links` object contributes to NEO 2.6.x duplicate-CONNECT/retry behaviour after `/client/account` is processed.

## 1.0.7

- Adds a controlled Nimbus bootstrap timing diagnostic to test whether the NEO's `/api/v0/client/account` response triggers or resets its MQTT reconnect state machine.
- Adds `nimbus_account_delay_ip` and `nimbus_account_delay_seconds` options. With both set, only `/client/account` responses from the selected NEO source IP are delayed; all other controllers and Nimbus endpoints are unchanged.
- Passes the real NEO source address from nginx to the local Nimbus emulator using `X-Real-IP`, allowing one controller to be isolated while the others remain live controls.
- Logs the exact start and end of a targeted delay so the subsequent duplicate MQTT CONNECT can be timed against release of the unchanged account response.
- Defaults to disabled (`nimbus_account_delay_ip` blank and delay `0`), so normal behaviour remains the same as 1.0.6 unless the diagnostic is explicitly enabled.

## 1.0.6

- Confirms from 1.0.5 packet tracing that a duplicate-CONNECT attempt can receive a valid, matching Mosquitto `SUBACK` (`0x00`) before the NEO voluntarily closes the TLS session, so the broker response is not the cause of the restart delay.
- Removes the experimental 5-second pre-CONNECT timeout from 1.0.3. It shortened the lifetime of an idle TLS socket but did not shorten the NEO firmware's own retry interval.
- Simplifies duplicate-CONNECT compatibility back to the proven lightweight path: keep the existing Mosquitto backend session, absorb the repeated NEO `CONNECT`, and return a local successful CONNACK.
- Removes the 1.0.4/1.0.5 replacement-Mosquitto-session and SUBACK tracing machinery because testing showed it did not change controller reconnect behaviour.
- Retains safe packet-type diagnostics for duplicate-CONNECT attempts and documents that NEO 2.6.x may require one or more roughly 30-second retry slots after a local service restart before a stable session is established.

## 1.0.5

- Adds packet-level diagnostics for the broker-to-NEO side of duplicate-CONNECT recovery without logging MQTT topics, payloads, credentials or account identifiers.
- Packetises Mosquitto responses so the replacement-session `SUBACK` can be observed directly instead of being hidden inside arbitrary TCP reads.
- Logs the NEO `SUBSCRIBE` packet identifier, the matching Mosquitto `SUBACK` identifier/result codes, whether the IDs match, and the broker response latency.
- Includes the last observed SUBSCRIBE/SUBACK identifiers and SUBACK result codes in the duplicate-session close summary so an immediate NEO disconnect can be distinguished from a missing or rejected SUBACK.
- Keeps the 1.0.4 replacement-session behaviour and the 1.0.3 pre-CONNECT timeout unchanged; this release is diagnostic only apart from packet-aware forwarding of the same MQTT bytes.

## 1.0.4

- Changes duplicate NEO MQTT `CONNECT` handling from a synthetic local CONNACK to a genuine fresh Mosquitto session.
- When firmware 2.6.x sends a second `CONNECT` on the existing TLS stream, the proxy now retires the old backend MQTT session, opens a new one, rewrites credentials, and returns the new broker's real CONNACK to the NEO.
- Subsequent NEO `SUBSCRIBE` packets are therefore handled by the replacement Mosquitto session and receive a real SUBACK, matching the controller's observed Clean Session behaviour more closely.
- Keeps the outer NEO TLS connection and Home Assistant logical device connection alive while the backend MQTT session is replaced.
- Retains the 5-second pre-CONNECT timeout from 1.0.3 for controllers that establish TLS but stall before sending the first MQTT packet.
- Adds INFO/DEBUG logging for broker-session replacement and post-replacement MQTT packet flow so restart behaviour can be verified safely without payload logging.

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
- Adds disabled-by-default engineering diagnostics for compressor capacity, indoor fan RPM/PWM, compressor running state, coil inlet/outdoor coil/discharge/suction/VSD temperatures, Wi-Fi signal, controller/MQTT uptime, MQTT reconnect count, VSD communications status, current AC error code, LP/HP faults, supply voltage/current/power, EEV opening and superheat.
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
- Clarifies that Home Assistant MQTT Discovery creates the NEO device automatically after usable state is received; the manual **Add MQTT device** flow is not used.

## 0.1.1

- Avoids the standard Mosquitto Broker add-on's host TCP 8883 port conflict by mapping the NEO TLS MQTT listener to host port 28883 by default.
- Adds a `neo_mqtt_port` option and advertises that port through the local Nimbus messaging endpoint.
- The add-on Network host port for container port 8883/tcp must match `neo_mqtt_port` if changed from the default.

## 0.1.0

- Initial experimental release.
- Emulates the Nimbus OAuth, account, messaging bootstrap and no-update OTA endpoints required by NEO controllers.
- Terminates the NEO TLS MQTT connection locally and rewrites the controller's password-only MQTT CONNECT into valid Home Assistant Mosquitto credentials.
- Supports multiple NEO controllers through a single add-on instance.
- Parses full-status, status-change, heartbeat and command-response MQTT traffic.
- Publishes normalized state and Home Assistant MQTT Discovery entities for the main climate system, zones, operating switches and common sensors.
- Translates Home Assistant MQTT climate/switch commands into native NEO `set-settings` commands.
- Persists the local Nimbus identity and TLS certificate across add-on restarts.