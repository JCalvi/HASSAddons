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
