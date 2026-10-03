# Actron NEO Local Cloud

Home Assistant add-on that replaces the cloud bootstrap and MQTT path used by ActronAir NEO wall controllers with a local service.

The add-on presents a local `nimbus.actronair.com.au` HTTPS endpoint, returns a local MQTT endpoint to the controller, accepts the controller's TLS MQTT connection, and bridges it into Home Assistant's Mosquitto broker. Home Assistant entities are created with MQTT Discovery, so no separate custom integration and no manual **Add MQTT device** step are required.

## Nimbus UserId

Normal installations should leave `nimbus_user_id` blank.

The NEO publishes its native MQTT traffic under topics such as:

```text
actron-cloud/<UserId>/neo/<serial>/...
```

Once the controller connects, the add-on learns the real Actron/Nimbus UserId automatically from the MQTT topic and uses it for commands. The user therefore does not need to know or enter the UUID.

Before MQTT is established, the local Nimbus bootstrap response still requires a UserId field. When `nimbus_user_id` is blank, the add-on creates and persists a private local UUID for that bootstrap response only. Testing with existing cloud-paired NEO controllers confirmed this generated bootstrap UUID does not prevent them reaching full-status and heartbeat.

`nimbus_user_id` remains only as an optional advanced/manual override. If deliberately set, it must be the Nimbus UUID returned by `/api/v0/messaging/connection/details`; it is not an email address, OAuth token, password or MQTT password. Clearing the field removes the override.

## Default ports

| Purpose | Add-on container port | Home Assistant host port | NEO connects to |
| --- | ---: | ---: | ---: |
| Local Nimbus HTTPS | 443 | 443 | `<HA-IP>:443` |
| NEO MQTT/TLS compatibility proxy | 8883 | **28883** | `<HA-IP>:28883` |
| Supervisor Mosquitto service | - | unchanged | NEO does **not** connect directly |

The add-on deliberately maps its internal MQTT/TLS port `8883` to host port `28883` by default. This avoids clashing with a normal Mosquitto Broker installation that may already expose host port `8883`.

If you change the host-side mapping for add-on container port `8883/tcp`, set `neo_mqtt_port` to the **same host port**. Nimbus advertises `neo_mqtt_port` to the NEO controller.

## Quick installation

1. Install and configure the standard Home Assistant **Mosquitto Broker** add-on/integration first.
2. Install **Actron NEO Local Cloud** and set `local_ip` to the Home Assistant LAN address reachable by the NEO controller(s).
3. Leave `nimbus_user_id` blank unless you deliberately want to override the generated bootstrap identity.
4. Leave `neo_mqtt_port: 28883` unless you intentionally change the host mapping.
5. Confirm the add-on Network mappings are `443/tcp -> 443` and `8883/tcp -> 28883`.
6. In the firewall, allow only the NEO controller IPs/VLAN as required to reach the Home Assistant host on **destination TCP ports 443 and 28883**. Source ports should remain `Any`.
7. On the DNS server used by the NEO network, create `nimbus.actronair.com.au -> <Home Assistant LAN IP>`.
8. Start the add-on **before** reconnecting/rebooting a NEO or applying a DNS change that sends Nimbus traffic to Home Assistant.
9. Reconnect or reboot one NEO first and watch the add-on log. Once `full-status` is received, Home Assistant MQTT Discovery creates the device/entities automatically.

## Home Assistant entities

The normal device page includes the main climate entity, Quiet/Turbo/Away/Continuous Fan controls, outdoor temperature, humidity, compressor power/speed, Clean Filter, Defrosting and any configured zones.

Version 1.0 reports the climate's live HVAC action (`off`, `idle`, `heating`, `cooling`, `drying` or `fan`). Compressor Speed is exposed as a percentage with a speedometer icon.

Additional engineering and diagnostic entities are published **disabled by default** so they do not clutter a normal installation. They include compressor capacity/running state, indoor fan RPM/PWM, coil/discharge/suction/VSD temperatures, Wi-Fi signal, controller/MQTT uptime, MQTT reconnect count, VSD communications state, current AC error code, LP/HP fault states, supply voltage/current/power, EEV opening, superheat, indoor/outdoor/Wi-Fi firmware, outdoor unit family and rated system capacity. Enable only the ones you want from the Home Assistant device entity list.

### Live telemetry refresh

The NEO itself decides when to publish native `status-change` broadcasts. Moving MQTT locally removes the Internet/cloud path, but it does not make the controller spontaneously publish compressor telemetry more frequently.

Version 1.0 therefore supplements native push updates with a lightweight local `getAll` refresh: approximately every **5 seconds while the system is on** and every **30 seconds while off**. Native status changes are still processed immediately, so the periodic refresh is only a maximum-staleness backstop for values such as compressor power and speed.

The NEO can retain its last non-zero compressor telemetry after the compressor stops. Version 1.0 therefore reports compressor power, speed and capacity as zero whenever the unit/compressor state says the compressor is not running, instead of displaying stale historical values.

NTW/Inverter controllers also use scaled telemetry values. In particular, raw `CompPower` is multiplied by 100 for the Home Assistant watt value, so a raw value of `40` is reported as approximately `4000 W`. Supply voltage uses the corresponding NTW x10 scaling.

### UniFi DNS note

A UniFi **Host (A)** DNS record is normally visible to clients that use the UniFi gateway as DNS; it is not inherently scoped to only the NEO devices. Restricting firewall access to the Home Assistant host on TCP 443/28883 to the NEO IPs provides the important access control. If you require the redirection itself to be source-specific, use a source-restricted DNAT design instead, understanding that DNAT to a public Nimbus IP can be less robust if that public IP changes.

A gateway-wide DNS override also affects Home Assistant itself if HA uses that gateway for DNS. If the official Home Assistant **Actron Air** cloud integration remains enabled, it may then try to connect to the local Nimbus emulator instead of Actron's public service. Disable the old cloud integration while using the local replacement, or use source-scoped DNS/DNAT if both must coexist.

See [DOCS.md](DOCS.md) for the full network setup, installation sequence, expected logs and troubleshooting information.
