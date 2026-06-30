# Network Explorer

Home Assistant add-on for a live network inventory page.

Sources:
- Pi-hole static DHCP, static DNS, leases, network database and neighbour table via SSH
- OpenWrt live Wi-Fi associations and hostapd connect/disconnect history via SSH
- Parallel ping checks from the add-on container

Default network:
- Pi-hole: 192.168.1.2, 192.168.1.3
- OpenWrt APs: 192.168.1.11, 192.168.1.12

Put the SSH private key at the configured `ssh_key_path`, default:

```text
/config/ssh/id_ed25519
```

The matching public key must be authorised on the Pi-hole machines and OpenWrt APs.
