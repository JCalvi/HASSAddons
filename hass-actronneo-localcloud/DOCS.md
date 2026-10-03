# Actron NEO Local Cloud

## What this add-on does

The NEO controller normally bootstraps through `nimbus.actronair.com.au`, receives an Actron MQTT endpoint, and exchanges status/commands over TLS MQTT. This add-on replaces those paths locally:

```text
NEO controller
  |-- HTTPS 443 -----------------> HA host:443
  |                                  |
  |                                  `-> add-on container:443 -> nginx -> local Nimbus emulator
  |
  `-- MQTT/TLS 28883 -----------> HA host:28883
                                     |
                                     `-> add-on container:8883 -> compatibility proxy
                                                                        |
                                                                        `-> Supervisor Mosquitto:1883
                                                                                     |
                                                                                     `-> MQTT Discovery entities
```

No separate Home Assistant custom integration is required. The standard Mosquitto Broker add-on/integration is required.

## Nimbus bootstrap identity

Nimbus requires a `UserId` field during bootstrap, but the controller does not require that field to contain its real Actron/Nimbus UUID.

The add-on creates and persists a private local UUID automatically in its data directory and uses that only for the local Nimbus bootstrap response. There is no Nimbus User ID option to configure.

Once a NEO connects, it publishes native MQTT traffic under topics such as:

```text
actron-cloud/<UserId>/neo/<serial>/...
```

The add-on learns the controller's real Actron/Nimbus UserId from that topic and uses the learned value for commands. The bootstrap UUID and the learned MQTT UserId therefore serve separate purposes.

## Ports

The NEO does **not** connect directly to Home Assistant's normal Mosquitto listener.

| Purpose | Add-on container port | Default HA host port | Notes |
| --- | ---: | ---: | --- |
| Local Nimbus HTTPS | 443 | 443 | NEO bootstrap HTTPS |
| NEO MQTT/TLS compatibility proxy | 8883 | **28883** | NEO connects here |
| Supervisor Mosquitto | internal service | normally 1883 internally | Used only by the add-on bridge/proxy |

The default mapping is:

```text
443/tcp  -> 443
8883/tcp -> 28883
```

and the add-on option must match the host-side MQTT/TLS port:

```text
neo_mqtt_port: 28883
```

If you change one, change the other.

## Requirements

- Home Assistant OS/Supervised.
- Standard Mosquitto Broker add-on/integration available through the Supervisor MQTT service.
- Fixed/reserved Home Assistant LAN IP reachable from the NEO network.
- NEO controller(s) able to reach the HA host on destination TCP ports **443** and **28883**.
- DNS or source-specific NAT control so `nimbus.actronair.com.au` traffic from the NEO is directed to the HA host.

## Recommended installation order

1. Install/start the standard **Mosquitto Broker** add-on and confirm the HA MQTT integration is working.
2. Install **Actron NEO Local Cloud**.
3. Set `local_ip` to the Home Assistant LAN address reachable by the NEO controller(s).
4. Leave `neo_mqtt_port: 28883` unless you intentionally change the host port mapping.
5. Confirm the add-on Network mappings are `443/tcp -> 443` and `8883/tcp -> 28883`.
6. Start the add-on.
7. Add the firewall allow rule from the NEO controller IPs to the HA host.
8. Add the DNS override for `nimbus.actronair.com.au`.
9. Reconnect/reboot one NEO first and watch the add-on log. Move the remaining NEOs only after the first one is stable.

Typical options:

```yaml
local_ip: 192.168.0.18
neo_mqtt_port: 28883
topic_prefix: hass-actronneo-localcloud
discovery_prefix: homeassistant
publish_raw_state: true
log_level: INFO
```

## Firewall setup

A minimal rule should look like:

```text
Action:            Allow
Protocol:          TCP
Source:            NEO controller IP(s)
Source port:       Any
Destination:       Home Assistant LAN IP
Destination ports: 443, 28883
```

The NEO does not need HA host port `1883`, and it does not need the normal Mosquitto host port `8883`.

## DNS redirection

Create this record on the DNS server actually used by the NEO network:

```text
nimbus.actronair.com.au -> <Home Assistant LAN IP>
```

### UniFi / UDM

With **Auto DNS Server**, the UniFi gateway normally answers DNS for clients. A Policy Engine DNS **Host (A)** record can be used:

```text
Type:        Host (A)
Domain Name: nimbus.actronair.com.au
IP Address:  <Home Assistant LAN IP>
TTL:         Auto
```

A gateway-wide Host (A) record is generally visible to all clients using the gateway as DNS. Restrict access with the firewall rule above.

A gateway-wide DNS override can also affect Home Assistant itself. If the official HA **Actron Air** cloud integration remains enabled, it may resolve `nimbus.actronair.com.au` to the local emulator. Disable the old cloud integration while using the local replacement, or use source-scoped DNS/DNAT if both must coexist.

## First connection

Successful logs should progress through messages similar to:

```text
Nimbus emulator listening on 127.0.0.1:8080
NEO MQTT TLS compatibility proxy listening on 0.0.0.0:8883
HA MQTT bridge connected
GET /api/v0/messaging/connection/details ... 200
NEO MQTT TLS established from <NEO-IP> ...
MQTT CONNECT <serial> ... -> local broker credentials
Local MQTT broker accepted NEO <serial>
NEO <serial> full-status received (...)
NEO <serial> heart-beat received
```

NEO firmware 2.6.x can send a second MQTT CONNECT on an already-established TLS/MQTT stream. Standard Mosquitto rejects that as a protocol error, so the add-on absorbs the duplicate CONNECT and acknowledges it locally while keeping the existing broker session.

The controller also uses an approximately **30-second retry interval** after an established MQTT connection is lost. Controlled forced-disconnect testing against the real Actron MQTT service reproduced the same roughly 31-second first retry and also an occasional failed first reconnect followed by another firmware retry. This confirms that the retry behaviour is not unique to the local broker.

During a local add-on restart a controller may occasionally need more than one retry slot before reaching a stable session. Once `full-status` and heartbeats arrive, normal operation has remained stable.

Do **not** use Home Assistant's manual **Add MQTT device** flow. MQTT Discovery creates the NEO device automatically after usable state is received.

## MQTT state parsing

A native NEO full-status message is wrapped like:

```json
{
  "event": {
    "type": "full-status-broadcast",
    "UserAirconSettings": {},
    "RemoteZoneInfo": []
  }
}
```

Status changes use the same `event` wrapper with `type: status-change-broadcast` and may contain flat keys such as `UserAirconSettings.isOn` or `RemoteZoneInfo[1].ZonePosition`.

The bridge keeps the complete full-status tree and merges partial status-change paths into it before normalizing Home Assistant state.

## Live telemetry refresh

Moving the connection local removes Internet/cloud latency, but the NEO firmware still decides when it emits native status-change broadcasts. Compressor telemetry is not guaranteed to be pushed every time the underlying value changes.

The add-on therefore supplements native push traffic with a local `getAll` refresh:

```text
System ON:   about every 5 seconds
System OFF:  about every 30 seconds
```

Native status changes are still processed immediately. The periodic refresh bounds how stale compressor power, compressor speed and other engineering telemetry can become. The refresh is skipped during the 6-second command settling/anti-bounce window.

The NEO can retain the last non-zero compressor telemetry in `CompPower`, `CompSpeed` and `CompressorCapacity` even after the compressor has stopped. When `UserAirconSettings.isOn` or `OutdoorUnit.CompressorOn` says the compressor is stopped, the add-on reports those live values as zero.

### NTW / Inverter telemetry scaling

NTW/Inverter systems encode some engineering values with scale factors:

```text
LiveAircon.OutdoorUnit.CompPower         x 100 -> W
LiveAircon.OutdoorUnit.SupplyVoltage_Vac x 10  -> V
```

For example, a raw `CompPower` value of `40` is exposed as approximately `4000 W`.

`LiveAircon.OutdoorUnit.CompSpeed` is exposed as Compressor Speed in `%`.

## Entities

Enabled by default:

- Main climate entity with HVAC mode, target/current temperature, fan mode and live HVAC action.
- Quiet Mode, Turbo Mode, Away Mode and Continuous Fan switches.
- Outdoor Temperature.
- Humidity.
- Compressor Power.
- Compressor Speed (%).
- Clean Filter and Defrosting binary sensors.
- Per-zone climate/humidity entities when the NEO reports configured zones.

Additional engineering/information entities are published **disabled by default** and can be enabled individually from the Home Assistant device page. These include compressor capacity, fan RPM/PWM, compressor running state, multiple temperatures, Wi-Fi signal, controller/MQTT uptime, MQTT reconnect count, VSD status, AC error code, pressure faults, supply electrical values, EEV opening, superheat, firmware, outdoor unit family and rated capacity.

Normalized state is retained at:

```text
hass-actronneo-localcloud/<serial>/state
```

When `publish_raw_state` is enabled, decoded raw NEO state is retained at:

```text
hass-actronneo-localcloud/<serial>/raw
```

## Commands

Home Assistant commands are translated to native NEO `set-settings` payloads and published to:

```text
actron-cloud/<UserId>/neo/<serial>/app/cmd
```

The NEO replies on `mwc/cmd-response/...`. State changes are reflected back through `status-change` broadcasts and merged into the retained HA state.

The bridge uses a short 6-second optimistic settling window after commands to prevent stale NEO echoes from making HA controls bounce back. At the end of that window it requests canonical full state with `getAll`.

## OTA behaviour

While connected to the local cloud, the add-on returns Nimbus' no-update response for OTA queries. To use Actron's normal OTA service, temporarily restore the controller's normal DNS/network path to Nimbus.

## TLS

On first start the add-on creates a persistent self-signed certificate for `nimbus.actronair.com.au` in the add-on data directory. Tested NEO controllers accepted this certificate for both local Nimbus HTTPS and local MQTT/TLS. The certificate is retained across restarts.

If every ordinary add-on restart logs `Generating persistent local Nimbus TLS certificate...`, investigate add-on data persistence.

## Troubleshooting

### Connects, then retries

A NEO may take one or more approximately 30-second retry slots after an MQTT service interruption. The same first-retry interval and occasional second retry were observed against the real Actron MQTT service, so the add-on intentionally leaves the firmware retry timer alone.

If a later attempt reaches `full-status` and heartbeats continue, the local session is usable.

### Commands receive cmd-response but HA controls snap back

The bridge includes a 6-second optimistic settling window and canonical `getAll` refresh to prevent stale status echoes from immediately reversing a control in Home Assistant.

### Compressor power appears about 100x too small

Current releases apply the NTW/Inverter x100 engineering scale before publishing compressor power in watts.

### Compressor telemetry changes slowly or stays non-zero after shutdown

The add-on requests local full state approximately every 5 seconds while a system is on and every 30 seconds while off, in addition to native status-change pushes. It also reports compressor power/speed/capacity as zero when the compressor is not running.

### Nimbus works but MQTT never arrives

Confirm:

- NEO can reach HA destination TCP `28883`;
- add-on mapping is `8883/tcp -> 28883`;
- `neo_mqtt_port` is also `28883`.

### Mosquitto says `Bad client ... sending multiple CONNECT messages`

Use Actron NEO Local Cloud 1.1.0 or later. The compatibility proxy absorbs the NEO's duplicate CONNECT instead of forwarding it to Mosquitto.

### No Nimbus requests appear

Verify DNS/DNAT and confirm the NEO actually uses that DNS server. Reconnect Wi-Fi or reboot the NEO if necessary to force a fresh bootstrap.

### No device appears in MQTT

A TCP/TLS/MQTT connection alone is not enough. Discovery is published after usable NEO state such as `full-status` arrives.

For deeper logging set:

```yaml
log_level: DEBUG
publish_raw_state: true
```
