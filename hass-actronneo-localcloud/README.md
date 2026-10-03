# Actron NEO Local Cloud

Home Assistant add-on that replaces the cloud bootstrap and MQTT path used by ActronAir NEO wall controllers with a local service.

The add-on presents a local `nimbus.actronair.com.au` HTTPS endpoint, returns a local MQTT endpoint to the controller, accepts the controller's TLS MQTT connection, and bridges it into Home Assistant's Mosquitto broker. Home Assistant entities are created with MQTT Discovery, so no separate custom integration and no manual **Add MQTT device** step are required.

## Nimbus UserId

Normal installations should leave `nimbus_user_id` blank.

The NEO publishes native MQTT traffic under topics such as:

```text
actron-cloud/<UserId>/neo/<serial>/...
```

Once the controller connects, the add-on learns the real Actron/Nimbus UserId automatically from the MQTT topic and uses it for commands. Before MQTT is established the local Nimbus bootstrap still requires a UserId field, so a private persistent local UUID is used when no override is configured.

`nimbus_user_id` remains available only as an optional advanced/manual override. It is not an email address, OAuth token, password or MQTT password.

## Default ports

| Purpose | Add-on container port | Home Assistant host port | NEO connects to |
| --- | ---: | ---: | ---: |
| Local Nimbus HTTPS | 443 | 443 | `<HA-IP>:443` |
| NEO MQTT/TLS compatibility proxy | 8883 | **28883** | `<HA-IP>:28883` |
| Supervisor Mosquitto service | - | unchanged | NEO does **not** connect directly |

The add-on maps its internal MQTT/TLS port `8883` to host port `28883` by default to avoid clashing with a normal Mosquitto Broker installation. If you change the host-side mapping for add-on container port `8883/tcp`, set `neo_mqtt_port` to the same host port.

## Quick installation

1. Install and configure the standard Home Assistant **Mosquitto Broker** add-on/integration first.
2. Install **Actron NEO Local Cloud** and set `local_ip` to the Home Assistant LAN address reachable by the NEO controller(s).
3. Leave `nimbus_user_id` blank unless you deliberately want to override the generated bootstrap identity.
4. Leave `neo_mqtt_port: 28883` unless you intentionally change the host mapping.
5. Confirm the add-on Network mappings are `443/tcp -> 443` and `8883/tcp -> 28883`.
6. Allow the NEO controller IPs/VLAN to reach the Home Assistant host on destination TCP ports **443 and 28883**.
7. On the DNS server used by the NEO network, create `nimbus.actronair.com.au -> <Home Assistant LAN IP>`.
8. Start the add-on before reconnecting/rebooting a NEO or applying the DNS change.
9. Reconnect or reboot one NEO first and watch the add-on log. Once `full-status` is received, Home Assistant MQTT Discovery creates the device/entities automatically.

## Home Assistant entities

The normal device page includes the main climate entity, Quiet/Turbo/Away/Continuous Fan controls, outdoor temperature, humidity, compressor power/speed, Clean Filter, Defrosting and any configured zones.

The main climate entity reports live HVAC action (`off`, `idle`, `heating`, `cooling`, `drying` or `fan`) separately from the selected HVAC mode.

Additional engineering entities are published **disabled by default** so they do not clutter a normal installation. They include compressor capacity/running state, indoor fan RPM/PWM, coil/discharge/suction/VSD temperatures, Wi-Fi signal, controller/MQTT uptime, MQTT reconnect count, VSD communications state, AC error code, LP/HP fault states, supply voltage/current/power, EEV opening, superheat, indoor/outdoor/Wi-Fi firmware, outdoor unit family and rated system capacity.

## Live telemetry refresh

Native NEO `status-change` broadcasts are processed immediately. The add-on also requests a local `getAll` refresh approximately every **5 seconds while the system is on** and every **30 seconds while off** so compressor and engineering telemetry cannot remain stale for long.

The NEO can retain its last non-zero compressor telemetry after the compressor stops. The add-on therefore reports compressor power, speed and capacity as zero whenever the unit/compressor state says the compressor is not running.

NTW/Inverter controllers use scaled telemetry values. Raw `CompPower` is multiplied by 100 for watts, and supply voltage uses the corresponding x10 scaling.

## NEO reconnect behaviour

NEO firmware 2.6.x uses an approximately **30-second MQTT retry interval** after an established broker connection is lost. A controlled forced disconnect against the real Actron MQTT service showed the same roughly 31-second wait before the controller opened its first replacement connection, so this timer is controller behaviour rather than a Home Assistant delay.

During local service restarts a NEO can occasionally require more than one retry slot before reaching a stable session. The add-on keeps the minimal duplicate-CONNECT compatibility handling needed for Mosquitto, but otherwise leaves the NEO's own retry state machine alone. Once `full-status` and heartbeats arrive, normal local operation has remained stable.

## UniFi DNS note

A UniFi **Host (A)** DNS record is normally visible to clients that use the UniFi gateway as DNS; it is not inherently scoped only to the NEO devices. Restricting firewall access to the Home Assistant host on TCP 443/28883 to the NEO IPs provides the important access control.

A gateway-wide DNS override can also affect Home Assistant itself. If the official Home Assistant **Actron Air** cloud integration remains enabled, it may resolve `nimbus.actronair.com.au` to the local emulator. Disable the old cloud integration while using the local replacement, or use source-scoped DNS/DNAT if both must coexist.

See [DOCS.md](DOCS.md) for the full network setup, installation sequence, expected logs and troubleshooting information.
