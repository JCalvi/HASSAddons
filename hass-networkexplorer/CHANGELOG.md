# Changelog

## 2026.6.07
- OpenWrt-safe SSH test now uses UCI or `/proc/sys/kernel/hostname` instead of `hostname`.
- Setup now uses a single Add Device button.
- Device type is detected after SSH install/test: Pi-hole, OpenWrt Wi-Fi, OpenWrt, Linux.
- OpenWrt Wi-Fi devices are used for Wi-Fi/AP polling; non-Wi-Fi OpenWrt devices are treated as normal network devices.

## 2026.6.06
- Detect remote OS during SSH key installation.
- Install OpenWrt keys to `/etc/dropbear/authorized_keys`.
