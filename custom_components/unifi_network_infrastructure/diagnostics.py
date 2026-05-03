"""Diagnostics for UniFi Network Infrastructure."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    "Authorization",
    "Cookie",
    "X-CSRF-Token",
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "csrf_token",
    "headers",
    "password",
    "refresh_token",
    "session",
    "session_cookie",
    "token",
    "username",
    "x_csrf_token",
}

KIND_LABELS = {
    "udm": "gateways",
    "ugw": "gateways",
    "usw": "switches",
    "uap": "access_points",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics with credentials redacted."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    hardware_counts = Counter(device.kind for device in data.devices.values())
    hardware_roles = Counter(
        KIND_LABELS.get(device.kind, "other_infrastructure")
        for device in data.devices.values()
    )
    port_counts = Counter(
        data.devices[port.device_key].kind
        for port in data.ports.values()
        if port.device_key in data.devices
    )
    infrastructure_port_count = sum(
        1 for port in data.ports.values() if port.protection_reasons
    )
    poe_capable_port_count = sum(
        1
        for port in data.ports.values()
        if port.raw.get("port_poe") is True
        or port.raw.get("poe_caps") not in (None, "", 0)
        or port.raw.get("poe_class") not in (None, "", 0)
    )
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "scope": {
            "integration_focus": "UniFi Network infrastructure hardware only",
            "client_tracking_platform": False,
            "device_tracker_platform_created": False,
            "ordinary_client_devices_imported": False,
            "ordinary_clients_imported_as_devices": False,
            "ordinary_client_endpoints_polled": False,
            "client_data_policy": (
                "Client endpoints are intentionally avoided. The integration only uses aggregate "
                "client counts exposed on infrastructure device rows."
            ),
        },
        "counts": {
            "devices_total": len(data.devices),
            "infrastructure_hardware_by_role": dict(sorted(hardware_roles.items())),
            "devices_by_kind": dict(sorted(hardware_counts.items())),
            "ports_total": len(data.ports),
            "ports_by_device_kind": dict(sorted(port_counts.items())),
            "ports_with_auto_protection_reason": infrastructure_port_count,
            "poe_capable_ports": poe_capable_port_count,
            "wan_uplinks": len(data.wans),
            "wlans": len(data.wlans),
            "port_forward_rules": len(data.port_forwards),
            "route_policies": len(data.traffic_routes),
            "firewall_policies": len(data.firewall_policies),
        },
        "entity_families": {
            "infrastructure_devices": True,
            "device_trackers": False,
            "ordinary_client_devices": False,
            "wlan_controls": bool(data.wlans),
            "port_forward_controls": bool(data.port_forwards),
            "route_policy_controls": bool(data.traffic_routes),
            "firewall_policy_controls": bool(data.firewall_policies),
            "port_sensors": bool(data.ports),
            "port_protection_locks": bool(data.ports),
            "wan_ip_sensors": bool(data.wans),
        },
        "repair_guidance": {
            "missing_infrastructure_devices": (
                "Confirm the UniFi service account can read Network application devices and "
                "that the devices are adopted in the controller."
            ),
            "missing_port_controls": (
                "Port controls are optional. Enable the port control family in integration "
                "options and use an account with Network write permissions."
            ),
            "protected_port_controls_unavailable": (
                "This is expected for ports protected by infrastructure, WAN, uplink, downlink, "
                "access point, or LLDP evidence. Temporarily unlock the port before making a "
                "maintenance change."
            ),
            "missing_policy_controls": (
                "Firewall, port-forward, and route-policy controls are optional and their "
                "entities are disabled by default. Enable the option first, then enable only "
                "the individual entities you want to control."
            ),
            "missing_clients_or_trackers": (
                "Expected behaviour. This integration does not create device trackers or import "
                "ordinary UniFi client devices."
            ),
        },
        "devices": [
            {
                "key": device.key,
                "name": device.name,
                "kind": device.kind,
                "hardware_role": KIND_LABELS.get(device.kind, "other_infrastructure"),
                "model": device.model,
                "ip": device.ip,
                "firmware": device.firmware,
                "state": device.state,
            }
            for device in sorted(data.devices.values(), key=lambda device: (device.kind, device.name))
        ],
    }
