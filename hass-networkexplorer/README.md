# Network Explorer

Home Assistant add-on for a live network inventory page.

Sources:

- Pi-hole static DHCP, static DNS, leases, network database and neighbour table via SSH
- OpenWrt live Wi-Fi associations and hostapd connect/disconnect history via SSH
- Parallel ping checks from the add-on container

Default network:

- Pi-hole: `192.168.1.2`, `192.168.1.3`
- OpenWrt APs: `192.168.1.11`, `192.168.1.12`

## Setup

Open the add-on web UI, enter each device IP/user/password, then use **Install Key** or **Install All Keys**. Passwords are used once to install the public key and are not saved.

The private key stays inside the Home Assistant config folder. Each managed device can use its own SSH key path, defaulting to `/config/ssh/id_ed25519`.

## Advanced add-on options

Devices are managed from the Network Explorer web UI, not from the Home Assistant add-on Configuration tab.

- `ping_workers`: Number of concurrent pings to send during each refresh. Higher values complete scans faster but create a larger short burst of traffic.
- `ping_timeout`: Time in seconds to wait for each ping response.
- `tcp_probe`: Also probe configured TCP ports when ping is not enough.
- `tcp_ports`: TCP ports to test when TCP probing is enabled.
- `steering_enabled`: Enables automatic Preferred AP steering. Manual Move Now still works when off.
- `steering_interval_minutes`: Time between automatic steering checks.
- `steering_cooldown_minutes`: Minimum time before the same device can be automatically steered again.
- `mqtt_enabled`: Enables the MQTT command listener.
- `mqtt_host`: MQTT broker hostname or IP address.
- `mqtt_port`: MQTT broker port, usually `1883`.
- `mqtt_username` / `mqtt_password`: Optional MQTT credentials.
- `mqtt_topic_prefix`: Topic prefix, default `network_explorer`.



## Home Assistant automation / service-style steering

Network Explorer exposes a small HTTP API that Home Assistant can call from a `rest_command`, script, automation, or dashboard button.

Example payloads:

```json
{ "ip": "192.168.1.80" }
```

```json
{ "mac": "aa:bb:cc:dd:ee:ff" }
```

Endpoint:

```text
POST /api/steer_device
```

The device must already have a Preferred AP set in Network Explorer. Manual steering works even when automatic steering is disabled.

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

Move a device to its Preferred AP using an IP address:

```text
Topic: network_explorer/command/steer
Payload: {"ip":"192.168.1.80"}
```

Or using a MAC address:

```text
Topic: network_explorer/command/steer
Payload: {"mac":"aa:bb:cc:dd:ee:ff"}
```

Result messages are published to:

```text
network_explorer/status/steer
```

The device must already have a Preferred AP set in Network Explorer. MQTT steering works even when automatic steering is disabled.


## 2026.6.19 Notes

This release keeps MQTT optional and prevents MQTT connection failures from using CPU. Automatic Preferred AP steering waits for the configured interval rather than running a full scan immediately at add-on startup.


## MQTT command listener

When enabled, Network Explorer connects to the configured MQTT broker and subscribes to `<prefix>/command/#`. The default broker host is `core-mosquitto`, suitable for the Home Assistant Mosquitto add-on. If your broker requires authentication, create or use an MQTT account and enter its username/password in the add-on Configuration page.

Example steering command topic: `<prefix>/command/steer` with payload `{"mac":"aa:bb:cc:dd:ee:ff"}` or `{"ip":"192.168.1.80"}`. Results are published under `<prefix>/status/steer`.
