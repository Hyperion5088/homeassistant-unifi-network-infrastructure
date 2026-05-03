# Entity And Attribute Contract

This document describes the Home Assistant entities created by UniFi Network Infrastructure and the attributes each entity exposes. It is intended for dashboard cards, automations, diagnostics, and future compatibility checks.

The integration only imports UniFi Network infrastructure hardware. It does not create `device_tracker` entities and does not import ordinary network clients as Home Assistant devices.

## Source Endpoints

| Source | Purpose |
| --- | --- |
| `POST /api/auth/login` | Local UniFi OS authentication. |
| `GET /proxy/network/api/s/<site>/stat/device` | Adopted infrastructure device inventory, gateway/switch/AP status, ports, WAN details, AP radios, AP VAPs, LLDP, traffic counters, and hardware telemetry. |
| `GET /proxy/network/api/s/<site>/rest/wlanconf` | WLAN/SSID configuration rows. |
| `PUT /proxy/network/api/s/<site>/rest/wlanconf/<wlan_id>` | Optional WLAN/SSID enable-disable writes. |
| `GET /proxy/network/api/s/<site>/rest/portforward` | Port-forward rules. |
| `PUT /proxy/network/api/s/<site>/rest/portforward/<rule_id>` | Optional port-forward enable-disable writes. |
| `GET /proxy/network/v2/api/site/<site>/trafficroutes` | Traffic routes / policy-based routes. |
| `PUT /proxy/network/v2/api/site/<site>/trafficroutes/<route_id>` | Optional traffic-route enable-disable writes. |
| Firewall policy endpoint | Optional user-editable firewall policy inventory and enable-disable writes. Generated, predefined, and IPS deny-list policies are excluded. |
| UniFi device command endpoints | Optional locate and guarded reboot actions. |
| UniFi port override endpoint | Optional port admin, bounce, PoE, and PoE reset controls. |

## Entity Categories

| Category | Integration rule |
| --- | --- |
| Normal sensors | Values useful on dashboards and device cards, such as client counts, inventory counts, port status, WAN IPs, and AP broadcast SSIDs. |
| Diagnostic sensors/buttons | Internal health or troubleshooting values, such as CPU, memory, temperature, firmware, update status, uptime, traffic counters, uplink, locate, and model/serial/MAC identity. |
| Configuration entities | User-editable settings and guard rails, such as protection locks, port-forward toggles, route-policy toggles, and firewall-policy toggles. |
| Control entities | Actions and toggles that directly affect hardware or wireless service, such as Wi-Fi toggles, port admin toggles, PoE toggles, bounce buttons, reset buttons, and guarded reboot buttons. |

## Device Sensors

These sensors are attached to the matching UniFi infrastructure device unless noted otherwise.

| Entity | Category | Default | State | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `System State` | Diagnostic | Disabled | Normalized enum: `online`, `offline`, `pending_adoption`, `adopting`, `provisioning`, `upgrading`, `disabled`, `isolated`, or `unknown`. | `kind`, `model`, `ip`, `mac`, `serial`, `firmware`, `raw_state`. | `stat/device` device row. |
| `IP LAN` | Normal | Enabled | Internal/controller-facing management IP. | None. | `lan_ip`, `ip`, `display_ip`, `last_ip`. |
| `System MAC Address` | Diagnostic | Enabled | Device MAC address. | None. | `mac`. |
| `System Serial Number` | Diagnostic | Enabled | Device serial number. | None. | `serial`. |
| `System Model` | Diagnostic | Enabled | UniFi model identifier. | None. | `model`, `model_in_eol`, `model_in_lts`. |
| `System CPU Usage` | Diagnostic | Enabled | CPU usage percent. | None. | `system-stats.cpu`, `cpu`. |
| `System Memory Usage` | Diagnostic | Enabled | Memory usage percent. | None. | `system-stats.mem`, `mem`. |
| `System Temperature` | Diagnostic | Enabled | Temperature in Celsius. If multiple probes exist, the highest value is used. | `probes`, `value_type`. | `general_temperature`, `temperature`, `system-stats.temperature`, `temperatures`. |
| `System Fan Level` | Normal | Enabled when present | Fan level percent. | None. | `fan_level` when `has_fan` is true. |
| `System Fan Summary` | Normal | Enabled when present | Concise fan state/speed summary. | None. | `fan`, `fan_table`. |
| `System Uptime` | Diagnostic | Enabled | Human-readable uptime, for example `22 days 16:53:41`. | None. | `uptime`. |
| `System Last Seen` | Diagnostic | Disabled | Timestamp of last controller observation. | None. | `last_seen`. |
| `System Load 1 min` | Diagnostic | Disabled | Linux-style unitless load average. | `window`, `unit`, `value_type`, `source`, `description`. | `sys_stats.loadavg_1`. |
| `System Load 5 min` | Diagnostic | Disabled | Linux-style unitless load average. | `window`, `unit`, `value_type`, `source`, `description`. | `sys_stats.loadavg_5`. |
| `System Load 15 min` | Diagnostic | Disabled | Linux-style unitless load average. | `window`, `unit`, `value_type`, `source`, `description`. | `sys_stats.loadavg_15`. |
| `System Firmware` | Diagnostic | Enabled | Firmware version. | None. | `version`, `firmwareVersion`. |
| `System Update Status` | Diagnostic | Enabled | `available` or `current`. | None. | `upgradable`. |
| `Port Count` | Normal | Disabled | Number of physical ports reported by switch/gateway devices. | None. | `port_table`; gateway fallback `ethernet_table`. |
| `Radio Count` | Normal | Disabled | Number of AP radios. | None. | `radio_table`. |
| `VAP Count` | Normal | Disabled | Number of virtual AP/BSSID rows. This can be higher than the number of SSIDs. | None. | `vap_table`. |
| `Broadcast SSIDs` | Normal | Enabled | Number of unique active SSID names currently broadcast by an AP. | `ssids`, `ssid_names`, `vap_instances`, `source`. Each `ssids` item can include `ssid`, `bands`, `radios`, `bssids`, `vap_interfaces`, `wlanconf_ids`, `states`, `is_guest`, `client_count`, and `broadcasting`. | `vap_table`, grouped by `essid` or `ssid`. |
| `Connected Clients` | Normal | Enabled | Aggregate connected client count only. | None. | `num_sta`, `user-num_sta`, `guest-num_sta`. |
| `Traffic Received` | Diagnostic | Enabled | Cumulative received traffic as readable B/KB/MB/GB/TB. | `direction`, `raw_bytes`, `raw_unit`, `value_type`, `counter_type`, `source`, `description`. | `rx_bytes`. |
| `Traffic Transmitted` | Diagnostic | Enabled | Cumulative transmitted traffic as readable B/KB/MB/GB/TB. | `direction`, `raw_bytes`, `raw_unit`, `value_type`, `counter_type`, `source`, `description`. | `tx_bytes`. |
| `Traffic Total` | Diagnostic | Enabled | Cumulative total traffic as readable B/KB/MB/GB/TB. | `direction`, `raw_bytes`, `raw_unit`, `value_type`, `counter_type`, `source`, `description`. | `bytes`. |
| `System Uplink` | Diagnostic | Enabled | Compact uplink summary. | `type`, `name`, `uplink_mac`, `uplink_device_name`, `uplink_remote_port`, `speed_mbps`, `tx_bytes`, `rx_bytes`. | `uplink`. |
| `Radio Details` | Normal | Disabled | Readable AP radio summary. | `radios`. Each radio can include `name`, `band`, `channel`, `channel_width_mhz`, `tx_power_mode`, `max_tx_power_dbm`, `min_tx_power_dbm`, and `spatial_streams`. | `radio_table`. |

## WAN Sensors

WAN sensors are attached to the gateway/router device and are created dynamically for each internet uplink that exposes an IP address.

| Entity | Category | Default | State | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `IP WAN <n>` | Normal | Enabled | WAN public IP address. | `wan`, `interface`, `port_idx`, `status`, `alive`. | `wan<n>`, `last_wan_status`, `last_wan_interfaces`. |

## Port Sensors

Port sensors are attached to the switch or gateway that owns the port. They are created dynamically from `port_table`.

| Entity | Category | Default | State | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `Port <label>` / `Port <connector> <label>` | Normal | Enabled | Negotiated speed, `Down`, or `Unknown`. | `device`, `port`, `port_idx`, `interface`, `enabled`, `link_up`, `speed_mbps`, `max_speed_mbps`, `speed_capability`, `poe_enabled`, `poe_capable`, `poe_power_w`, `poe_mode`, `poe_class`, `media`, `autoneg`, `full_duplex`, `flow_control_rx`, `flow_control_tx`, `is_uplink`, `protection_reasons`, `auto_protected`, `protected`, `admin_control_allowed`, `rx_bytes`, `tx_bytes`, `rx_rate_bps`, `tx_rate_bps`, `rx_rate_bytes_per_second`, `tx_rate_bytes_per_second`, `rx_errors`, `tx_errors`, `rx_dropped`, `tx_dropped`, `lldp_neighbors`. | `port_table`, `lldp_table`, local protection state. |

`lldp_neighbors` is a list of neighbor summaries for the port when UniFi exposes LLDP data. Each neighbor can include `name`, `port`, `chassis_id`, and `mac`.

## Wi-Fi Control Switches

Wi-Fi switches are attached to the router/controller device and are created only when the relevant options are enabled.

| Entity | Category | Default | State | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `WiFi <SSID>` | Control | Enabled when Wi-Fi controls are enabled | WLAN enabled state. | `wlan_id`, `ssid`, `security`, `band`, `is_guest`. | `rest/wlanconf`. |

Guest SSIDs are only created when guest Wi-Fi controls are enabled. Wired guest networks from network configuration rows are intentionally not controlled by this integration.

## Router Policy Switches

These switches are attached to the router/controller device. They are created only when their option family is enabled and are disabled by default in Home Assistant's entity registry.

| Entity | Category | Default | State | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `Port Forward <rule name>` | Configuration | Disabled | Port-forward rule enabled state. | `rule_id`, `name`, `protocol`, `source`, `destination`, `destination_port`, `forward_ip`, `forward_port`. | `rest/portforward`. |
| `Route Policy <policy name>` | Configuration | Disabled | Traffic route / policy-based route enabled state. | `route_id`, `name`, `matching_target`, `network_id`, `next_hop`, `kill_switch_enabled`, `domain_count`, `ip_address_count`, `ip_range_count`, `region_count`, `target_device_count`. | `trafficroutes`. |
| `Firewall Policy <policy name>` | Configuration | Disabled | Firewall policy enabled state. | `policy_id`, `name`, `action`, `index`, `logging`. | Firewall policy endpoint. |

## Port Protection Locks

Port protection locks are attached to the switch or gateway that owns the port. They are created only when port protection is enabled.

| Entity | Category | Default | State | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `Protection <port>` | Configuration | Enabled | Locked/unlocked protection state. | `device`, `port`, `port_idx`, `enabled`, `link_up`, `speed_mbps`, `poe_enabled`, `is_uplink`, `protection_reasons`, `auto_protected`, `protected_reason`, `manual_protection`, `temporarily_unlocked`, `auto_reprotect_seconds`. | `port_table`, `uplink`, `lldp_table`, WAN port mappings, local Home Assistant storage. |

Infrastructure-facing ports are auto-protected when UniFi marks them as uplinks, when they feed downstream UniFi devices, when LLDP identifies a wired neighbor, or when a gateway WAN mapping identifies an internet-facing port. Ordinary edge ports are unlocked by default but can be manually locked.

## Port Control Switches And Buttons

Port controls are attached to the switch or gateway that owns the port. They are created only when interface controls and the specific control family are enabled.

| Entity | Category | Default | State/Action | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `Admin <port>` | Control | Enabled when port admin controls are enabled | Port administrative enabled state. | `port`, `port_idx`, `link_up`, `protected`, `protection_reasons`, `control_allowed`. | `port_table`, port override writes, local protection state. |
| `PoE <port>` | Control | Enabled when PoE controls are enabled and port is PoE-capable | PoE enabled state. | `port`, `port_idx`, `link_up`, `protected`, `protection_reasons`, `control_allowed`. | `port_table`, port override writes, local protection state. |
| `Bounce <port>` | Control | Enabled when bounce controls are enabled | Temporarily disables and re-enables the port admin state. | None. | Port override writes. |
| `PoE Reset <port>` | Control | Enabled when PoE reset controls are enabled and port is PoE-capable | Temporarily disables and re-enables PoE power only. | None. | Port override writes. |

Protected ports make the admin, PoE, bounce, and PoE reset controls unavailable until the matching `Protection <port>` lock is temporarily unlocked.

## Device Maintenance Controls

Maintenance controls are attached to each UniFi infrastructure device and are created only when the relevant options are enabled.

| Entity | Category | Default | State/Action | Attributes | Source |
| --- | --- | --- | --- | --- | --- |
| `System Locate` | Diagnostic | Enabled when locate controls are enabled | Triggers the UniFi locate/identify action for a short time. | None. | Device command endpoint, using device MAC. |
| `Reboot` | Control | Disabled | Reboots the device only when the shared confirmation select is armed. | `confirmation`, `armed`. | Device command endpoint, using device MAC. |
| `Reboot Confirmation` | Control | Disabled | Shared select with `Cancel` and `Reboot`. | None. | Local Home Assistant state. |

## Stability Notes

- Attribute names are intended to be stable for dashboard cards and automations once V1 leaves beta.
- Raw UniFi field names can vary by controller version and hardware family; attributes are normalized where the integration has live evidence.
- Values that are missing, blank, or not exposed by the controller are omitted rather than filled with placeholder strings.
- Existing Home Assistant entity registry choices are respected. If a user disables an entity, migrations should not silently re-enable it.
