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
