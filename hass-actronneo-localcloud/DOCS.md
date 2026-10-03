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

## Nimbus UserId

`nimbus_user_id` is optional. Leave it blank for normal installations; the add-on generates and persists a local UUID automatically.

Version 0.1.5 introduced the option while investigating a reconnect loop. Later testing showed an already cloud-paired NEO successfully reached `full-status` and heartbeat with the generated local UUID, so the original Actron account UserId is **not** required for normal setup.

If you deliberately use the override, the value is the UUID returned by the real Nimbus `/api/v0/messaging/connection/details` response and used in topics such as:

```text
actron-cloud/<UserId>/neo/<serial>/...
```

It is not an email address, OAuth token, refresh token, password, pairing code or MQTT password.

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
4. Leave `nimbus_user_id` blank unless intentionally using the advanced override.
5. Leave `neo_mqtt_port: 28883` unless you intentionally change the host port mapping.
6. Confirm the add-on Network mappings are `443/tcp -> 443` and `8883/tcp -> 28883`.
7. Start the add-on.
8. Add the firewall allow rule from the NEO controller IPs to the HA host.
9. Add the DNS override for `nimbus.actronair.com.au`.
10. Reconnect/reboot one NEO first and watch the add-on log. Move the remaining NEOs only after the first one is stable.

Typical options:

```yaml
local_ip: 192.168.0.18
nimbus_user_id: ""
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

For example, with NEOs at `10.189.60.101`, `.102` and `.103` and HA at `192.168.0.18`:

```text
Source:            10.189.60.101-10.189.60.103
Destination:       192.168.0.18
Protocol:          TCP
Source port:       Any
Destination ports: 443, 28883
```

Do not put `443,28883` in **Source Port**. The NEO does not need HA host port `1883`, and it does not need the normal Mosquitto host port `8883`.

## DNS redirection

Create this record on the DNS server actually used by the NEO network:

```text
nimbus.actronair.com.au -> <Home Assistant LAN IP>
```

For example:

```text
nimbus.actronair.com.au -> 192.168.0.18
```

### UniFi / UDM

With **Auto DNS Server**, the UniFi gateway normally answers DNS for clients. A Policy Engine DNS **Host (A)** record can be used:

```text
Type:        Host (A)
Domain Name: nimbus.actronair.com.au
IP Address:  <Home Assistant LAN IP>
TTL:         Auto
```

A gateway-wide Host (A) record is generally visible to all clients using the gateway for DNS. Restrict access with the firewall rule above.

A gateway-wide DNS override can also affect Home Assistant itself. If the official HA **Actron Air** cloud integration remains enabled, it may resolve `nimbus.actronair.com.au` to the local emulator and fail TLS/API calls. Disable the old cloud integration while testing the local replacement, or use source-scoped DNS/DNAT if both must coexist.

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

NEO firmware may send a duplicate MQTT CONNECT during bootstrap. Version 0.1.2+ absorbs the duplicate instead of forwarding it to Mosquitto. A controller may also retry the bootstrap once before settling into a stable session.

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

Version 0.1.6 fixes event unwrapping so the complete event body is retained. Earlier versions could keep only the first nested dictionary, causing default/unknown values, zero zones and ignored command-driven status changes.

## Entities

The add-on publishes:

- Main climate entity: power/mode, target temperature, current temperature and fan mode when available.
- Per-zone climate entities.
- Quiet Mode, Turbo Mode, Away Mode and Continuous Fan switches.
- Outdoor temperature, humidity, compressor power and compressor speed sensors.
- Clean Filter and Defrosting binary sensors.
- Per-zone humidity sensors.

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

## OTA behaviour

While connected to the local cloud, the add-on returns Nimbus' no-update response for OTA queries. To use Actron's normal OTA service, temporarily restore the controller's normal DNS/network path to Nimbus.

## TLS

On first start the add-on creates a persistent self-signed certificate for `nimbus.actronair.com.au` in the add-on data directory. Tested NEO controllers accepted this certificate for both local Nimbus HTTPS and local MQTT/TLS. The certificate is retained across restarts.

If every ordinary add-on restart logs `Generating persistent local Nimbus TLS certificate...`, investigate add-on data persistence.

## Troubleshooting

### Connects, then retries once

A first-attempt duplicate CONNECT/disconnect followed by a successful retry has been observed on NEO firmware 2.6.x. If the second attempt reaches `full-status` and heartbeats continue, the local session is usable.

### Full-status arrives but values are Unknown/default or zones=0

Update to **0.1.6 or later**. Earlier versions incorrectly unwrapped the MQTT `event` object and could discard most of the NEO state.

### Commands receive cmd-response but HA controls snap back

Update to **0.1.6 or later**. Earlier versions could silently discard `status-change-broadcast` payloads, so the NEO could acknowledge a command while Home Assistant continued showing the previous retained state.

### Nimbus works but MQTT never arrives

Confirm:

- NEO can reach HA destination TCP `28883`;
- add-on mapping is `8883/tcp -> 28883`;
- `neo_mqtt_port` is `28883`.

### Mosquitto says `Bad client ... sending multiple CONNECT messages`

Update to **0.1.2 or later**.

### No Nimbus requests appear

Verify DNS/DNAT and confirm the NEO actually uses that DNS server. Reconnect Wi-Fi or reboot the NEO if necessary to force a fresh bootstrap.

### No device appears in MQTT

A TCP/TLS/MQTT connection alone is not enough. Discovery is published after usable NEO state such as `full-status` arrives.

For detailed diagnostics set:

```yaml
log_level: DEBUG
publish_raw_state: true
```
