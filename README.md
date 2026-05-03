# UniFi Infrastructure for Home Assistant

Home Assistant integration for UniFi Network hardware only.

This integration is intentionally narrower than the built-in UniFi Network integration. It is designed to expose adopted UniFi infrastructure devices without creating Home Assistant devices or entities for ordinary network clients.

## Status

This repository is an early V1 development build.

Current scope:

- local UniFi OS / UniFi Network login
- adopted UniFi gateway, switch, and access point inventory from the UniFi Network controller
- read-only device state, identity, firmware, uptime, CPU, memory, temperature, load average, traffic, uplink, and client-count summary sensors where the controller exposes them
- switch/gateway port count sensors where the controller exposes port inventory
- access point radio and VAP count sensors where the controller exposes radio inventory
- fan sensors only when the controller exposes concrete fan level or fan table data
- SSID enable/disable controls exposed as switch entities on the UniFi router/controller device
- switch and gateway port configuration protection locks, including router WAN uplinks when the controller exposes the WAN port mapping
- internal/controller-facing gateway IP sensors plus separate WAN IP sensors for each detected internet uplink
- no `device_tracker` platform
- no ordinary network-client devices
- diagnostics with credentials redacted

Sensor notes:

- `System Load` is a Linux-style unitless load average, not CPU percentage. Interpret it relative to the device CPU capacity.
- `Received Traffic`, `Transmitted Traffic`, and `Total Traffic` are cumulative byte counters from the controller payload, not live Mbps bandwidth rates. Their native values stay in bytes for Home Assistant, with a readable KB/MB/GB/TB display value in attributes.
- `Radio Count` is the number of physical AP radios.
- `VAP Count` is the number of virtual AP/BSSID instances, so it can be higher than the number of SSIDs.
- `State`, `Last Seen`, `System Load`, `Radio Count`, `VAP Count`, and `Radio Details` are disabled by default to keep new installs quieter. Existing early-development installs are migrated once so those entities are disabled by the integration unless the user enables them again afterwards.

Entity category rules:

- Normal sensors: operational values useful for dashboards and device cards, such as state, identity, firmware, temperature, clients, uplink, and port/radio inventory.
- Diagnostic sensors: internal health or troubleshooting values, such as CPU, memory, uptime, last seen, system load, and cumulative traffic counters.
- Configuration entities: user-editable settings and protection locks.
- Control entities: actions and toggles, such as SSID enable/disable switches.

Not included yet:

- UniFi port admin controls
- UniFi PoE controls
- per-AP WLAN controls
- reboot / locate controls
- firmware update actions
- dashboard card

## Installation

### HACS

Add this repository to HACS as an integration repository once it has been published:

- Repository: `https://github.com/Hyperion5088/homeassistant-unifi-infrastructure`
- Category: `Integration`

Then install `UniFi Infrastructure`, restart Home Assistant, and add the integration from Settings > Devices & services.

### Manual

Copy `custom_components/unifi_infrastructure` to your Home Assistant `custom_components` directory, restart Home Assistant, then add the integration from Settings > Devices & services.

## Configuration

Use a dedicated local UniFi OS / UniFi Network service account. Do not use a Ubiquiti cloud SSO account.

The first build asks for:

- UniFi host
- username
- password
- HTTPS port
- site ID, usually `default`
- TLS certificate verification setting
- polling interval

The integration uses the local UniFi OS login endpoint and then polls:

- `POST /api/auth/login`
- `GET /proxy/network/api/s/<site>/stat/device`

It deliberately avoids client/device-tracker endpoints.

SSID controls poll the UniFi WLAN configuration endpoint and create switch entities dynamically:

- `GET /proxy/network/api/s/<site>/rest/wlanconf`
- `PUT /proxy/network/api/s/<site>/rest/wlanconf/<wlan_id>`

If a new WLAN/SSID is added later, the integration creates the matching switch on a future poll without reinstalling the integration.

Per-AP SSID control is intentionally out of scope for now.

Port protection uses the UniFi controller's local `port_table[].is_uplink` flag, child-device uplink metadata, router WAN port mappings, and per-port LLDP rows where the controller exposes `lldp_table[].local_port_idx`. That means an uplink can still be protected when the upstream or downstream device is not UniFi hardware, and switch/router ports that feed downstream UniFi switches or access points can also be protected.

For UniFi gateways, the normal `IP Address` sensor uses the internal/controller-facing address where the controller exposes one, such as `lan_ip`. Public internet addresses are exposed separately as `WAN 1 IP Address`, `WAN 2 IP Address`, and so on, depending on how many active WAN rows the controller reports.

Port protection creates a lock for every switch/router port and uses short names such as `Protection Port 3` on the switch/router device. Infrastructure uplink/downlink ports and detected router WAN ports are locked by default; ordinary edge ports are unlocked by default and can be manually locked. Manual locks are stored locally by Home Assistant so they survive reloads and restarts. Unlocking an infrastructure port temporarily allows maintenance and it automatically locks again after 15 minutes.

## Design Boundary

This project should stay focused on UniFi-managed infrastructure:

- gateway/router
- UniFi switches
- UniFi access points

Phones, laptops, TVs, servers, media boxes, and other ordinary network clients should not be imported into Home Assistant by this integration.
