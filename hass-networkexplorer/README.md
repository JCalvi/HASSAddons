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

The private key stays inside the Home Assistant config folder at the configured SSH key path.
