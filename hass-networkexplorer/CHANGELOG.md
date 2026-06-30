# Changelog

## 2026.6.06
- Detect remote OS during SSH key installation.
- Install keys to `/etc/dropbear/authorized_keys` for OpenWrt/Dropbear.
- Install keys to `~/.ssh/authorized_keys` for normal Linux hosts.
- Preserve the user-facing device type separately from the detected OS.
- Add SSH diagnostic details for detected OS and installed key path.
- Add a default Docker BUILD_FROM to silence local Buildx warnings.
