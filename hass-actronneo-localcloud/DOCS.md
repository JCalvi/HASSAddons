# Actron NEO Local Cloud

## What this add-on does

The NEO controller normally bootstraps through `nimbus.actronair.com.au`, receives an Actron MQTT endpoint, and then exchanges status and commands over TLS MQTT. This add-on replaces both parts locally:

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

## Existing paired controllers: Nimbus UserId

An existing NEO is already paired to a Nimbus account and retains that account identity. For an already-paired controller, set `nimbus_user_id` to the original Nimbus `UserId` before redirecting the controller to the local emulator.

The UserId can be obtained from a capture of the real Nimbus response:

```text
GET /api/v0/messaging/connection/details
```

where it appears as:

```json
{"UserId":"<uuid>"}
```

The same UUID appears in the native MQTT topic path:

```text
actron-cloud/<UserId>/neo/<serial>/...
```

`nimbus_user_id` is only that UUID. It is **not** a bearer token, OAuth token, password, refresh token, pairing code or MQTT password. Do not store those credentials in the add-on configuration.

If this option is blank, the add-on generates and persists a random local UUID. That fallback is suitable for development/new pairing work, but an existing cloud-paired NEO may repeatedly re-initialize its MQTT session if Nimbus suddenly reports a different account ID. Version 0.1.5 adds this option specifically so the local emulator can preserve the identity used by the paired controller.

Multiple NEO controllers paired to the same Actron account normally share the same Nimbus UserId, so one add-on instance can serve them all.

## Important port distinction

The NEO does **not** connect to Home Assistant's Mosquitto Broker directly.

| Purpose | Add-on container port | Default HA host port | Notes |
| --- | ---: | ---: | --- |
| Local Nimbus HTTPS | 443 | 443 | NEO bootstrap HTTPS |
| NEO MQTT/TLS compatibility proxy | 8883 | **28883** | NEO connects here |
| Supervisor Mosquitto | internal service | normally 1883 internally | Used only by the add-on bridge/proxy |

The add-on intentionally maps container port `8883/tcp` to Home Assistant host port `28883`. This prevents a conflict with a normal Mosquitto Broker installation that may already expose host port `8883`.

The add-on option `neo_mqtt_port` is the **host-side port advertised to the NEO**. Therefore these values must match:

```text
Add-on Network mapping: 8883/tcp -> 28883
Add-on option:           neo_mqtt_port: 28883
```

If you change one, change the other to the same host port.

Host TCP 443 normally must remain available to this add-on because the NEO accesses `https://nimbus.actronair.com.au` on the standard HTTPS port. An advanced NAT design can translate NEO TCP 443 to another add-on host port, but that is outside the normal installation.

## Requirements

- Home Assistant OS/Supervised.
- The standard Mosquitto Broker add-on/integration available through the Supervisor MQTT service.
- A fixed or reserved Home Assistant LAN IP reachable from the NEO network.
- The original Nimbus UserId for already-paired controllers.
- The NEO controller(s) must be able to reach the Home Assistant host on destination TCP ports **443** and **28883** by default.
- DNS or firewall/NAT control so `nimbus.actronair.com.au` traffic from the NEO is directed to the Home Assistant host.

## Recommended installation order

1. Install and start the standard **Mosquitto Broker** add-on and make sure the Home Assistant MQTT integration is working.
2. Install **Actron NEO Local Cloud**.
3. Set `local_ip` to the Home Assistant LAN address reachable by the NEO controller(s).
4. For already-paired NEOs, set `nimbus_user_id` to the original Nimbus UserId used by those controllers.
5. Leave `neo_mqtt_port: 28883` unless you intentionally change the add-on host port mapping.
6. Confirm the add-on Network mappings are:

   ```text
   443/tcp  -> 443
   8883/tcp -> 28883
   ```

7. Start the add-on and confirm it remains running before changing DNS or reconnecting a NEO.
8. Create the firewall allow rule from the NEO controller IPs/network to the Home Assistant host.
9. Create the DNS override for `nimbus.actronair.com.au`.
10. Reconnect/reboot one NEO first and watch the add-on log. Once it is working, move the remaining NEOs across.

Starting the add-on before applying the DNS override avoids directing a controller to an HTTPS endpoint that is not yet listening.

## Add-on configuration

Set **Home Assistant LAN IP** (`local_ip`) to the LAN address that the NEO controller can reach. Do not use the add-on container address.

Typical options:

```yaml
local_ip: 192.168.0.18
nimbus_user_id: "<original Nimbus UserId>"
neo_mqtt_port: 28883
topic_prefix: hass-actronneo-localcloud
discovery_prefix: homeassistant
publish_raw_state: true
log_level: INFO
```

`neo_mqtt_port` must match the Home Assistant **host-side** port mapped from add-on container port `8883/tcp`.

When `nimbus_user_id` is non-empty, the add-on persists that value in its data directory. The value is deliberately not printed in normal logs.

## Firewall setup

A minimal firewall rule should look like:

```text
Action:            Allow
Protocol:          TCP
Source:            NEO controller IP(s), or the smallest suitable NEO group
Source port:       Any
Destination:       Home Assistant LAN IP
Destination ports: 443, 28883
```

Do not put `443,28883` in **Source Port**. They are destination ports on the Home Assistant host.

The NEO does not need access to Home Assistant host port `1883`, and it does not need access to the normal Mosquitto host port `8883`. The compatibility proxy uses Supervisor-provided Mosquitto credentials internally.

If an IoT/Untrusted-to-LAN/Trusted block rule exists, place the NEO allow rule above that block rule.

### Example with three NEOs

For controllers at `10.189.60.101`, `10.189.60.102` and `10.189.60.103` and Home Assistant at `192.168.0.18`:

```text
Source:            10.189.60.101-10.189.60.103
Destination:       192.168.0.18
Protocol:          TCP
Source port:       Any
Destination ports: 443, 28883
```

Using an explicit IP group/list is preferable to allowing an entire IoT subnet when only the NEO controllers require access.

## DNS redirection

### Recommended: local DNS override

On the DNS server actually used by the NEO network, create:

```text
nimbus.actronair.com.au -> <Home Assistant LAN IP>
```

For example:

```text
nimbus.actronair.com.au -> 192.168.0.18
```

If the NEO network receives the gateway/router as its DNS server by DHCP, create the record on that gateway/router rather than on a DNS server the NEO never queries.

### UniFi / UDM example

When the NEO VLAN uses **Auto DNS Server**, the UniFi gateway normally answers DNS for those clients. In current UniFi Network releases the record can be created as a Policy Engine DNS **Host (A)** record:

```text
Type:        Host (A)
Domain Name: nimbus.actronair.com.au
IP Address:  <Home Assistant LAN IP>
TTL:         Auto
```

A UniFi Host (A) record is generally available to clients using the gateway as DNS; the DNS record itself is not necessarily source-scoped to only the NEOs. This is usually acceptable when the firewall rule restricts access to Home Assistant TCP 443/28883 to the NEO IPs.

A gateway-wide DNS override can also affect Home Assistant itself. If the official Home Assistant **Actron Air** cloud integration is still enabled, it may resolve `nimbus.actronair.com.au` to the local emulator and fail TLS/API calls. Disable the old cloud integration while testing the local replacement, or use a source-scoped DNS/DNAT design if both services must coexist.

If strict source-specific redirection is required, use a source-restricted DNAT design instead of a global/local DNS record. A DNAT rule tied to Actron's current public Nimbus IP is less robust because that public IP can change.

## First connection

After the add-on is running and the network rules are in place, reboot the NEO, reconnect it to Wi-Fi from the network controller, or wait for it to repeat its cloud bootstrap.

Successful logs should progress through messages similar to:

```text
Nimbus emulator listening on 127.0.0.1:8080
NEO MQTT TLS compatibility proxy listening on 0.0.0.0:8883
HA MQTT bridge connected
...
GET /api/v0/messaging/connection/details ... 200
NEO MQTT TLS established from <NEO-IP> ...
MQTT CONNECT <serial> ... -> local broker credentials
Local MQTT broker accepted NEO <serial>
```

The controller should then publish `full-status`, `status-change` and `heart-beat` messages. The add-on creates Home Assistant MQTT Discovery entities automatically after usable state is received.

NEO firmware can issue another MQTT CONNECT during bootstrap. The proxy prevents that packet from being forwarded directly into Mosquitto, because standards-compliant Mosquitto rejects a second CONNECT on an already-established session. If a controller still loops immediately after the second CONNECT, verify `nimbus_user_id` first; an existing paired NEO should receive the same Nimbus account ID it used before the local cutover.

Do **not** use Home Assistant's manual **Add MQTT device** button for the NEO. The device/entities are created by MQTT Discovery.

## Entities

The add-on publishes:

- Main climate entity: power/mode, target temperature, current temperature and fan mode when a valid fan-mode value has been received.
- Per-zone climate entities for zones reported by the NEO.
- Quiet Mode, Turbo Mode, Away Mode and Continuous Fan switches.
- Outdoor temperature, humidity, compressor power and compressor speed sensors.
- Clean Filter and Defrosting binary sensors.
- Per-zone humidity sensors.

The normalized state is retained at:

```text
hass-actronneo-localcloud/<serial>/state
```

When `publish_raw_state` is enabled, the decoded raw NEO state is also retained at:

```text
hass-actronneo-localcloud/<serial>/raw
```

## Commands

Home Assistant commands are translated to the NEO's native `set-settings` payloads and published to:

```text
actron-cloud/<Nimbus-UserId>/neo/<serial>/app/cmd
```

The controller's command acknowledgements remain available on its native `mwc/cmd-response/...` topics.

## OTA behaviour

While connected to the local cloud, the add-on returns Nimbus' normal no-update response for OTA queries. This deliberately prevents an unexpected cloud firmware update through the emulator. To use Actron's normal OTA service, temporarily restore the controller's normal DNS/network path to Nimbus.

## TLS

On first start the add-on creates a persistent self-signed certificate for `nimbus.actronair.com.au` in the add-on data directory. NEO controllers tested during development accepted this certificate for both the local Nimbus HTTPS endpoint and the local MQTT/TLS endpoint. The certificate is retained across restarts.

If every ordinary add-on restart logs `Generating persistent local Nimbus TLS certificate...`, investigate add-on data persistence. Normally that line appears only when the certificate is first created.

## Troubleshooting

### Connects to MQTT, sends a second CONNECT, then immediately disconnects/retries

For an already cloud-paired NEO, first verify `nimbus_user_id` is set to the controller's original Nimbus UserId. The successful development path preserved the paired Nimbus UserId; replacing it with a generated UUID can cause the controller to re-initialize the session after `/api/v0/client/account` is returned.

### Nimbus works but MQTT never arrives

If `/api/v0/messaging/connection/details` appears in the add-on log but no MQTT TLS connection follows, confirm:

- the NEO can reach the Home Assistant host on destination TCP `28883`;
- the add-on Network mapping is `8883/tcp -> 28883`;
- `neo_mqtt_port` is also `28883`.

### Mosquitto says `Bad client ... sending multiple CONNECT messages`

Update Actron NEO Local Cloud to **0.1.2 or later**. Older versions transparently forwarded the NEO firmware's repeated CONNECT packet after the first handshake, which standards-compliant Mosquitto rejects as a protocol error.

### No Nimbus requests appear

Verify the DNS override/DNAT rule and confirm the NEO actually uses that DNS server. If the NEO already has an established cloud session, reconnecting it to Wi-Fi or rebooting it may be required to force a fresh bootstrap.

### No device appears in the MQTT integration

A successful TCP/TLS/MQTT connection alone is not enough. The add-on publishes discovery after it receives usable NEO state such as `full-status`. Do not manually add an MQTT device. Check the add-on log for status traffic first.

### Home Assistant entities still do not appear

Verify the MQTT integration is enabled and that `discovery_prefix` is `homeassistant` unless you intentionally changed it. For detailed diagnostics set `log_level` to `DEBUG` and leave `publish_raw_state` enabled.
