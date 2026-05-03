"""Constants for the UniFi Network Infrastructure integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "unifi_network_infrastructure"

CONF_SITE = "site"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 443
DEFAULT_SITE = "default"
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL_SECONDS = 60
DEFAULT_SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS)

UNIFI_HARDWARE_TYPES = {
    "udm",
    "ugw",
    "usw",
    "uap",
}
