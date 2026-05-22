# UniFi Network Infrastructure for Home Assistant

Home Assistant integration for UniFi Network hardware only.

This integration is intentionally limited to UniFi Network. It does not integrate UniFi Protect, UniFi Access, UniFi Talk, UniFi Connect, or other UniFi applications. It is designed to expose adopted UniFi Network infrastructure devices without creating Home Assistant devices or entities for ordinary network clients.

## Status

This repository is a beta V1 development build. It is usable for testing, but entity names and optional controls may still change before a stable release.

Current scope:

- local UniFi OS / UniFi Network login
- adopted UniFi gateway, switch, and access point inventory from the UniFi Network controller
- read-only device state, identity, firmware, uptime, CPU, memory, temperature, load average, traffic, uplink, and client-count summary sensors where the controller exposes them
- switch/gateway port count sensors where the controller exposes port inventory
- per-port sensors for UniFi switches and gateways, with negotiated speed as the state and link/admin/PoE/LLDP/protection details exposed as attributes
- access point radio, VAP/BSSID count, and broadcast SSID summary sensors where the controller exposes radio inventory
- fan sensors only when the controller exposes concrete fan level or fan table data
- SSID enable/disable controls exposed as switch entities on the UniFi router/controller device, with guest WLAN rows labelled as guest networks when UniFi marks them that way
- port-forward rule enable/disable controls exposed as switch entities on the UniFi router/controller device
- conditional route / traffic route policy enable-disable controls exposed as switch entities on the UniFi router/controller device
- switch and gateway port configuration protection locks, including router WAN uplinks when the controller exposes the WAN port mapping
- optional switch/gateway port admin, PoE, bounce, and PoE reset controls
- optional device locate and guarded reboot controls
- internal/controller-facing gateway IP sensors plus separate WAN IP, ISP, and last speed-test sensors for each detected internet uplink where UniFi exposes them
- no `device_tracker` platform
- no ordinary network-client devices
- diagnostics with credentials redacted

Sensor notes:

- `System Load` is a Linux-style unitless load average, not CPU percentage. Interpret it relative to the device CPU capacity.
- `Traffic Received`, `Traffic Transmitted`, and `Traffic Total` are cumulative counters from the controller payload, not live Mbps bandwidth rates. Their state is shown as a readable B/KB/MB/GB/TB value, with the raw byte counter retained in attributes.
- WAN speed-test sensors report the last UniFi ISP speed-test result for the matching WAN connection. They are not live bandwidth sensors and only appear when the controller exposes stored results for that connection.
- When a device reports multiple temperature probes, the `Temperature` sensor uses the highest reported probe as its state and includes the individual probe values as attributes.
- `Radio Count` is the number of physical AP radios.
- `VAP Count` is the number of virtual AP/BSSID instances, so it can be higher than the number of SSIDs.
- `Broadcast SSIDs` is the number of unique active SSID names reported by an AP. Its attributes include the SSID names, bands, radios, BSSIDs, VAP interfaces, WLAN configuration IDs, guest marker, client count, and raw VAP state where UniFi exposes them.
- `State`, `Last Seen`, `System Load`, `Radio Count`, `VAP Count`, and `Radio Details` are disabled by default to keep new installs quieter. Existing early-development installs are migrated once so those entities are disabled by the integration unless the user enables them again afterwards.

Entity naming rules:

- Wi-Fi controls use `WiFi <SSID>`.
- Port-forward controls use `Port Forward <rule name>`.
- Conditional route policies use `Route Policy <policy name>`.
- LAN/WAN addresses use `IP LAN`, `IP WAN 1`, `IP WAN 2`, and so on. ISP and speed-test entities follow the same WAN numbering.
- System/diagnostic sensors use `System <sensor>`, for example `System CPU Usage`, `System Firmware`, and `System MAC Address`.
- Port protection locks use `Protection <port>`.
- Port status sensors use `Port <label>` for copper ports and `Port <connector> <label>` for fibre ports, for example `Port SFP 1`, `Port SFP+ 1`, or `Port QSFP 1`.

Entity category rules:

- Normal sensors: operational values useful for dashboards and device cards, such as client counts and port/radio inventory.
- Diagnostic sensors: internal health or troubleshooting values, such as MAC address, model, firmware, temperature, update status, uplink, CPU, memory, uptime, last seen, system load, and cumulative traffic counters.
- Configuration entities: user-editable settings and protection locks.
- Control entities: actions and toggles, such as SSID enable/disable switches, port admin switches, PoE switches, bounce buttons, reset buttons, locate buttons, and guarded reboot buttons.

The full entity and attribute contract is documented in [`docs/entity-attribute-contract.md`](docs/entity-attribute-contract.md).

Not included yet:

- per-AP WLAN controls
- firmware update actions
- dashboard card

## Installation

### HACS

Add this repository to HACS as an integration repository once it has been published:

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hyperion5088&repository=homeassistant-unifi-network-infrastructure&category=integration)

- Repository: `https://github.com/Hyperion5088/homeassistant-unifi-network-infrastructure`
- Category: `Integration`

Then install `UniFi Network Infrastructure`, restart Home Assistant, and add the integration from Settings > Devices & services.

### Manual

Copy `custom_components/unifi_network_infrastructure` to your Home Assistant `custom_components` directory, restart Home Assistant, then add the integration from Settings > Devices & services.

## Configuration

Use a dedicated local UniFi OS / UniFi Network service account. Do not use a Ubiquiti cloud SSO account or your personal administrator account.

Recommended service account setup:

1. Open the UniFi OS console directly in a browser.
2. Go to `Admins & Users`.
3. Add a new local admin/user for Home Assistant, for example `homeassistant` or `integration-sa`.
4. Give the account only the UniFi Network permissions needed for the entity families you enable:
   - read-only access is enough for monitoring-only installs
   - network/application admin permissions are required if you enable SSID, port-forward, route-policy, port, locate, or reboot controls
5. Store the password in your normal secrets manager and use that account in the Home Assistant config flow.
6. Avoid sharing this account with the UniFi web UI, mobile app, or other automations so sessions and CSRF tokens do not collide.

The integration checks the configured account permissions during setup and in the options flow. If the account appears to be read-only, write/control entity options are hidden and the integration stays in monitoring mode.

The first build asks for:

- UniFi host
- username
- password
- HTTPS port
- TLS certificate verification setting
- polling interval

The UniFi Network site is fixed internally to `default`. For local UniFi OS consoles this is the only site this integration targets, so new installs do not ask for a site ID.

The integration uses the local UniFi OS login endpoint and then polls:

- `POST /api/auth/login`
- `GET /proxy/network/api/s/<site>/stat/device`
- `GET /proxy/network/api/s/<site>/stat/health`
- `GET /proxy/network/v2/api/site/<site>/aggregated-dashboard?historySeconds=86400`

It deliberately avoids client/device-tracker endpoints.

Device display names are shortened during import by removing DNS suffixes from hostname-like values. For example, `gateway-01.example.com` is shown as `gateway-01`. Unique IDs still come from stable controller identifiers such as `_id`, serial, or MAC address.

SSID controls poll the UniFi WLAN configuration endpoint and create switch entities dynamically:

- `GET /proxy/network/api/s/<site>/rest/wlanconf`
- `PUT /proxy/network/api/s/<site>/rest/wlanconf/<wlan_id>`

If a new WLAN/SSID is added later, the integration creates the matching switch on a future poll without reinstalling the integration.
When UniFi marks a WLAN row as guest, the switch is named as a guest network rather than a generic SSID.

The integration does not expose UniFi network configuration rows from `/rest/networkconf` as guest-network controls, because toggling those rows can disable the wired VLAN/network as well as Wi-Fi. Guest access control should use the WLAN/SSID switch path above.

Port-forward controls poll the UniFi port-forward endpoint and create switch entities dynamically:

- `GET /proxy/network/api/s/<site>/rest/portforward`
- `PUT /proxy/network/api/s/<site>/rest/portforward/<rule_id>`

Port-forward writes preserve the existing rule payload and only change the `enabled` field.

Conditional route policy controls poll UniFi Network's v2 traffic routes endpoint and create switch entities dynamically:

- `GET /proxy/network/v2/api/site/<site>/trafficroutes`
- `PUT /proxy/network/v2/api/site/<site>/trafficroutes/<route_id>`

Traffic route writes preserve the existing route payload and only change the `enabled` field.

Per-AP SSID control is intentionally out of scope for now.

Port admin and PoE controls are optional and disabled by default. They update the device `port_overrides` payload for the selected port and should be tested on known-safe ports before being enabled broadly.

Admin controls change whether the switch or gateway port itself is administratively enabled. Turning a port admin switch off can drop link, VLAN forwarding, LLDP, and any device connected to that port.

PoE controls only change power delivery on PoE-capable ports. They are intentionally separate because they can power-cycle or depower a PoE device while keeping the port configuration and admin state intact for diagnostics. PoE reset briefly turns PoE off and then back on without intentionally disabling the data port.

Locate and reboot controls are optional and disabled by default. Reboot controls use a two-step guard: set the reboot confirmation select to `Reboot`, then press the reboot button. The confirmation resets after the command or if `Cancel` is selected.

Port protection uses the UniFi controller's local `port_table[].is_uplink` flag, child-device uplink metadata, router WAN port mappings, and per-port LLDP rows where the controller exposes `lldp_table[].local_port_idx`. That means an uplink can still be protected when the upstream or downstream device is not UniFi hardware, and switch/router ports that feed downstream UniFi switches or access points can also be protected.

For UniFi gateways, the normal `IP LAN` sensor uses the internal/controller-facing address where the controller exposes one, such as `lan_ip`. Public internet addresses are exposed separately as `IP WAN 1`, `IP WAN 2`, and so on, depending on how many active WAN rows the controller reports. ISP and last speed-test result sensors are also created per WAN connection when UniFi exposes those values.

Port protection creates a lock for every switch/router port and uses short names such as `Protection Port 3` on the switch/router device. Infrastructure uplink/downlink ports and detected router WAN ports are locked by default; ordinary edge ports are unlocked by default and can be manually locked. Manual locks are stored locally by Home Assistant so they survive reloads and restarts. Unlocking an infrastructure port temporarily allows maintenance and it automatically locks again after 15 minutes.

Diagnostics are intended to be safe to share when troubleshooting. The diagnostics payload redacts credentials, cookies, headers, sessions, and token-like values. It does not include raw UniFi API payloads.

The diagnostics payload includes:

- confirmation that `device_tracker` and ordinary client-device import are intentionally absent
- aggregate hardware counts by role, such as gateways, switches, access points, and other infrastructure
- raw UniFi hardware kind counts where useful for support
- port, WAN, WLAN, port-forward, route-policy, and firewall-policy counts
- counts for ports with automatic protection evidence and PoE-capable ports
- concise repair guidance for missing infrastructure devices, missing optional controls, protected-port controls, and intentionally absent clients

If clients, phones, laptops, TVs, or other ordinary network devices are missing from diagnostics, that is expected. This integration only imports UniFi Network infrastructure hardware.

## Design Boundary

This project should stay focused on UniFi-managed infrastructure:

- gateway/router
- UniFi switches
- UniFi access points

Phones, laptops, TVs, servers, media boxes, and other ordinary network clients should not be imported into Home Assistant by this integration.
