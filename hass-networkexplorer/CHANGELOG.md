# 2026.6.20

- Default MQTT broker host is now `core-mosquitto`.
- Added MQTT connection/status logging and status reporting.
- MQTT command listener remains persistent while enabled and connected.
- Added Tailscale IP/hostname/FQDN fields to device details.
- Improved device details source display into primary/evidence chips.
- Preserves short hostname in the main table while keeping FQDN in details.

## 2026.6.19

- Stability release after MQTT introduction.
- Prevented MQTT reconnect failures from tight-looping and using high CPU.
- Automatic steering no longer runs an immediate full scan at add-on startup; it waits for the configured interval.
- Improved Home Assistant option display names and descriptions.
- MQTT listener remains optional and stays idle unless enabled with a broker host.

## 2026.6.18

- Preserve global Home Assistant add-on settings across add-on remove/reinstall by backing them up under `/config/networkexplorer/settings.json`.
- Default automatic Preferred AP steering settings are now enabled, 60 minute interval and 180 minute cooldown.
- Added MQTT command listener support using `mosquitto_sub`/`mosquitto_pub`.
- Added MQTT options: broker host, port, username, password and topic prefix.
- MQTT steering command topic: `<prefix>/command/steer` with payload such as `{"ip":"192.168.1.80"}` or `{"mac":"aa:bb:cc:dd:ee:ff"}`.
- MQTT status replies publish to `<prefix>/status/steer`.

## 2026.6.17

- Detect Tailscale/CGNAT addresses in `100.64.0.0/10` and show them as `Tailscale` instead of Ethernet.
- Display short hostnames in the main table while preserving FQDN in device details.
- Prefer higher-confidence hostnames: managed/SSH names, then Static DHCP, DHCP leases, Static DNS, then Pi-hole network names.
- Seed managed device names into inventory so configured infrastructure names win over lower-confidence sources.

## 2026.6.16

- Fixed global settings precedence: HA add-on Configuration values now override stale runtime data.
- Runtime device storage now only persists managed devices and per-client Preferred AP preferences.
- Removed legacy runtime shadowing of steering interval/cooldown settings.
- Added service-style steering API endpoints for Home Assistant automations: `/api/steer`, `/api/steer_device` and `/api/service/steer`.
- Backfilled missing changelog entries for 2026.6.13 and 2026.6.14.

## 2026.6.14

- Improved Buildx-based Docker build workflow for multi-architecture images.
- Continued Preferred AP steering testing and packaging updates.
- Improved Home Assistant add-on metadata/version handling.

## 2026.6.13

- Added Preferred AP steering refinements.
- Added OpenWrt client disassociation testing for manual move actions.
- Improved device detail controls for Preferred AP management.

## 2026.6.15

- Moved SSH key path to a per-device setting in Network Explorer setup.
- Removed the global SSH key path from the Home Assistant Configuration page.
- Kept all global settings in the Home Assistant Configuration page with descriptions.
- Added descriptions for Preferred AP steering settings.
- Preferred AP steering interval/cooldown are now global add-on options.
- Added OpenWrt neighbour collection for managed OpenWrt devices, including non-Wi-Fi gateways.


## 2026.6.12

- Added Preferred AP Steering.
- Preferred AP is set per Wi-Fi device from the expanded details panel.
- Added Move now to preferred AP action.
- Added optional scheduled steering interval and cooldown.

## 2026.6.11

- Persist managed devices under `/config/networkexplorer/devices.json` so they survive add-on removal/reinstall.
- Migrate existing runtime device config from the older `/data/networkexplorer_config.json` location during upgrades.
- Add Home Assistant option descriptions for SSH key path, ping workers, ping timeout, TCP probe and TCP ports.

## 2026.6.10

- Removed legacy Pi-hole/access point/SSH user fields from the Home Assistant add-on configuration page.
- Device management now lives solely in the Network Explorer UI.
- Ignored stale legacy HA options so old Pi-hole/AP values cannot reappear after update.
- Default ping worker count is now 50.

## 2026.6.09
- Moved refresh controls into the top header beside Theme and Settings.
- Refresh is now a combined immediate-refresh and auto-refresh control.
- Removed the separate auto-refresh row from the filter card.
- Summary chips are now clickable filters.
- Wi-Fi summary chip filters all live Wi-Fi connections; Devices clears filters.

# Changelog

## 2026.6.08
- Settings button now toggles to Hide Settings when open.
- Setup devices sort numerically by IP address.
- Added configurable auto-refresh with Off as the default.
- Remember search, filters, sorting, expanded row and refresh preference.
- Click IP to open HTTP, Ctrl+Click IP to open HTTPS.
- Click hostname or MAC to copy it.
- Added client-side first seen / last seen details.


## 2026.6.07
- OpenWrt-safe SSH test now uses UCI or `/proc/sys/kernel/hostname` instead of `hostname`.
- Setup now uses a single Add Device button.
- Device type is detected after SSH install/test: Pi-hole, OpenWrt Wi-Fi, OpenWrt, Linux.
- OpenWrt Wi-Fi devices are used for Wi-Fi/AP polling; non-Wi-Fi OpenWrt devices are treated as normal network devices.

## 2026.6.06
- Detect remote OS during SSH key installation.
- Install OpenWrt keys to `/etc/dropbear/authorized_keys`.
