# Actron NEO Local Cloud

## What this add-on does

The NEO controller normally boots through `nimbus.actronair.com.au`, receives an Actron MQTT endpoint, and then exchanges status and commands over TLS MQTT. This add-on replaces both parts locally:

```text
NEO controller
  |-- HTTPS 443 --> Actron NEO Local Cloud --> local Nimbus emulator
  `-- MQTT/TLS 8883 --> compatibility proxy --> Home Assistant Mosquitto
                                               |
                                               `--> MQTT Discovery entities
```

No separate Home Assistant custom integration is required. The standard Mosquitto Broker integration/add-on is required.

## Requirements

- Home Assistant OS/Supervised with the Mosquitto Broker available through the Supervisor MQTT service.
- The NEO controller must be able to reach the Home Assistant host on TCP 443 and TCP 8883.
- DNS or firewall/NAT control so `nimbus.actronair.com.au` traffic from the NEO can be directed to the Home Assistant host.

## Add-on configuration

Set **Home Assistant LAN IP** (`local_ip`) to the LAN address that the NEO controller can reach. Do not use the add-on container address.

Typical options:

```yaml
local_ip: 192.168.0.18
topic_prefix: hass-actronneo-localcloud
discovery_prefix: homeassistant
publish_raw_state: true
log_level: INFO
```

The add-on listens on host TCP 443 and 8883. These ports must not already be used by another add-on or host service.

## Network redirection

### Recommended: local DNS override

On the DNS server used by the NEO VLAN, create a local record:

```text
nimbus.actronair.com.au -> <Home Assistant LAN IP>
```

Then allow the NEO/VLAN to reach the Home Assistant LAN IP on:

- TCP 443 - local Nimbus HTTPS
- TCP 8883 - local NEO MQTT/TLS

The NEO itself does not need direct access to the Home Assistant Mosquitto port; the add-on proxies MQTT internally using Supervisor-provided credentials.

### Alternative: destination NAT

A firewall DNAT rule can redirect only NEO traffic destined for the real Nimbus HTTPS address to `<Home Assistant LAN IP>:443`. This was the method used during protocol development. A DNS override is preferable because the public Nimbus address can change.

## First connection

After installing and starting the add-on, reboot the NEO controller or wait for it to repeat its cloud bootstrap. Successful logs should show:

```text
Nimbus emulator listening on 127.0.0.1:8080
NEO MQTT TLS compatibility proxy listening on 0.0.0.0:8883
NEO MQTT TLS established ...
MQTT CONNECT <serial> ... -> local broker credentials
HA MQTT bridge connected
```

The controller then publishes `full-status`, `status-change` and `heart-beat` messages. The add-on creates Home Assistant MQTT Discovery entities automatically.

## Entities

The first release publishes:

- Main climate entity: power/mode, target temperature, current temperature and fan mode.
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
actron-cloud/<local-user-id>/neo/<serial>/app/cmd
```

The controller's command acknowledgements remain available on its native `mwc/cmd-response/...` topics.

## OTA behaviour

While connected to the local cloud, the add-on returns Nimbus' normal no-update response for OTA queries. This deliberately prevents an unexpected cloud firmware update through the emulator. To use Actron's normal OTA service, temporarily restore the controller's normal DNS/network path to Nimbus.

## TLS

On first start the add-on creates a persistent self-signed certificate for `nimbus.actronair.com.au` in the add-on data directory. NEO controllers tested during development accepted this certificate for both the local Nimbus HTTPS endpoint and the local MQTT/TLS endpoint. The certificate is retained across restarts.

## Troubleshooting

If Nimbus requests appear but MQTT does not connect, confirm the add-on's `local_ip` is reachable from the NEO VLAN on TCP 8883.

If no Nimbus requests appear, verify the DNS override or DNAT rule and confirm the NEO uses the expected DNS server.

If Home Assistant entities do not appear, verify the MQTT integration is enabled and that the discovery prefix is `homeassistant` unless you intentionally changed it.

For detailed diagnostics set `log_level` to `DEBUG` and leave `publish_raw_state` enabled.
