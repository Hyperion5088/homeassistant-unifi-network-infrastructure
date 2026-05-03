"""Constants for the UniFi Network Infrastructure integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "unifi_network_infrastructure"

CONF_SITE = "site"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_PORT_PROTECTION = "enable_port_protection"
CONF_ENABLE_WIFI_CONTROLS = "enable_wifi_controls"
CONF_ENABLE_GUEST_WIFI_CONTROLS = "enable_guest_wifi_controls"
CONF_ENABLE_PORT_FORWARD_CONTROLS = "enable_port_forward_controls"
CONF_ENABLE_ROUTE_POLICY_CONTROLS = "enable_route_policy_controls"
CONF_ENABLE_FIREWALL_POLICY_CONTROLS = "enable_firewall_policy_controls"
CONF_ENABLE_INTERFACE_CONTROLS = "enable_interface_controls"
CONF_ENABLE_PORT_ADMIN_CONTROLS = "enable_port_admin_controls"
CONF_ENABLE_POE_CONTROLS = "enable_poe_controls"
CONF_ENABLE_PORT_BOUNCE = "enable_port_bounce"
CONF_ENABLE_POE_RESET = "enable_poe_reset"
CONF_ENABLE_LOCATE_CONTROL = "enable_locate_control"
CONF_ENABLE_REBOOT_CONTROL = "enable_reboot_control"

DEFAULT_PORT = 443
DEFAULT_SITE = "default"
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL_SECONDS = 60
DEFAULT_SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS)
DEFAULT_ENABLE_PORT_PROTECTION = True
DEFAULT_ENABLE_WIFI_CONTROLS = True
DEFAULT_ENABLE_GUEST_WIFI_CONTROLS = True
DEFAULT_ENABLE_PORT_FORWARD_CONTROLS = True
DEFAULT_ENABLE_ROUTE_POLICY_CONTROLS = True
DEFAULT_ENABLE_FIREWALL_POLICY_CONTROLS = False
DEFAULT_ENABLE_INTERFACE_CONTROLS = False
DEFAULT_ENABLE_PORT_ADMIN_CONTROLS = False
DEFAULT_ENABLE_POE_CONTROLS = False
DEFAULT_ENABLE_PORT_BOUNCE = False
DEFAULT_ENABLE_POE_RESET = False
DEFAULT_ENABLE_LOCATE_CONTROL = False
DEFAULT_ENABLE_REBOOT_CONTROL = False

UNIFI_HARDWARE_TYPES = {
    "udm",
    "ugw",
    "usw",
    "uap",
}
