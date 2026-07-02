# Network Explorer

Home Assistant add-on for live network inventory, OpenWrt/Pi-hole discovery, Wi-Fi visibility and Preferred AP steering.

## What it collects

Network Explorer can collect information from:

- Managed Pi-hole/Linux devices over SSH: static DHCP, static DNS, leases, Pi-hole network database and neighbour table.
- Managed OpenWrt devices over SSH: neighbour tables, live Wi-Fi associations, hostapd connect/disconnect history and optional Tailscale status.
- The add-on container: parallel ping checks and optional TCP probes.

Devices are managed from the Network Explorer web UI, not from the Home Assistant add-on Configuration tab.

## Setup

Open the add-on web UI and use **Settings**.

1. Add each managed device by IP address.
2. Enter the SSH username and one-time password.
3. Use **Install Key** or **Install All Keys**.
4. The password is used once to install the public key and is not saved.

The private key stays inside the Home Assistant config folder. Each managed device can use its own SSH key path, defaulting to:

```text
/config/ssh/id_ed25519
```

## Advanced add-on options

The Home Assistant Configuration page contains global/runtime options only:

- `ping_workers`: number of concurrent pings to send during each refresh.
- `ping_timeout`: time in seconds to wait for each ping response.
- `tcp_probe`: also probe configured TCP ports when ping is not enough.
- `tcp_ports`: TCP ports to test when TCP probing is enabled.
- `steering_enabled`: enables automatic Preferred AP steering. Manual Move Now still works when off.
- `steering_interval_minutes`: time between automatic steering checks.
- `steering_cooldown_minutes`: minimum time before the same device can be automatically steered again.
- `mqtt_enabled`: enables the MQTT command listener.
- `mqtt_host`: MQTT broker hostname or IP address. For the Home Assistant Mosquitto add-on this is normally `core-mosquitto`.
- `mqtt_port`: MQTT broker port, usually `1883`.
- `mqtt_username` / `mqtt_password`: optional MQTT credentials, required when your broker requires authentication.
- `mqtt_topic_prefix`: topic prefix, default `network_explorer`.

## Preferred AP steering

For live Wi-Fi devices, set a Preferred AP from the expanded device details panel.

Manual steering:

- Use **Move now to preferred AP** in the details panel.
- Manual steering works even when automatic steering is disabled.

Automatic steering:

- Controlled by `steering_enabled`, `steering_interval_minutes` and `steering_cooldown_minutes` in the Home Assistant Configuration page.
- Network Explorer periodically checks live Wi-Fi clients and disconnects clients that are connected to the wrong AP so they can reconnect to their preferred AP.

## Home Assistant automation / `rest_command` steering

Network Explorer exposes a small HTTP API that Home Assistant can call from a `rest_command`, script, automation or dashboard button.

Endpoint:

```text
POST /api/steer_device
```

Payload by IP:

```json
{ "ip": "192.168.1.80" }
```

Payload by MAC:

```json
{ "mac": "aa:bb:cc:dd:ee:ff" }
```

The device must already have a Preferred AP set in Network Explorer.

Example Home Assistant `rest_command`:

```yaml
rest_command:
  network_explorer_steer_device:
    url: "http://<network-explorer-host>:8090/api/steer_device"
    method: POST
    content_type: "application/json"
    payload: '{"ip":"{{ ip }}"}'
```

## MQTT commands

MQTT is optional. When enabled, Network Explorer subscribes to:

```text
<prefix>/command/#
```

Default prefix:

```text
network_explorer
```

### Test command

```text
Topic: network_explorer/command/test
Payload: {"hello":"world"}
```

### Move one device to its Preferred AP

By IP address:

```text
Topic: network_explorer/command/steer
Payload: {"ip":"192.168.1.80"}
```

By MAC address:

```text
Topic: network_explorer/command/steer
Payload: {"mac":"aa:bb:cc:dd:ee:ff"}
```

### Move all eligible devices

This steers all currently live Wi-Fi devices that have a Preferred AP set and are not already on that AP:

```text
Topic: network_explorer/command/steer
Payload: {"all":true}
```

Result messages are published to:

```text
network_explorer/status/steer
```

MQTT steering works even when automatic steering is disabled.
