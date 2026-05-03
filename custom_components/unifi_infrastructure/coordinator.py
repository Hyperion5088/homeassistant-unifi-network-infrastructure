"""Coordinator for UniFi Infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniFiInfrastructureClient, UniFiInfrastructureError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class UniFiDevice:
    """Normalized UniFi infrastructure device."""

    key: str
    name: str
    kind: str
    model: str | None
    mac: str | None
    ip: str | None
    serial: str | None
    firmware: str | None
    state: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class UniFiInfrastructureData:
    """Coordinator data."""

    devices: dict[str, UniFiDevice]


class UniFiInfrastructureCoordinator(DataUpdateCoordinator[UniFiInfrastructureData]):
    """Fetch UniFi infrastructure device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: UniFiInfrastructureClient,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval) if scan_interval > 0 else DEFAULT_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> UniFiInfrastructureData:
        """Fetch data from UniFi Network."""
        try:
            devices = await self.client.async_get_devices()
        except UniFiInfrastructureError as err:
            raise UpdateFailed(str(err)) from err
        normalized = [_normalize_device(device) for device in devices]
        return UniFiInfrastructureData(devices={device.key: device for device in normalized})


def _normalize_device(device: dict[str, Any]) -> UniFiDevice:
    """Normalize a UniFi device row."""
    mac = _first_string(device, "mac")
    key = _first_string(device, "_id", "device_id", "serial", "mac") or "unknown"
    name = _first_string(device, "name", "display_name", "hostname", "model", "mac") or key
    return UniFiDevice(
        key=_clean_key(key),
        name=name,
        kind=str(device.get("type") or "device").lower(),
        model=_first_string(device, "model", "model_in_eol", "model_in_lts"),
        mac=mac,
        ip=_first_string(device, "ip", "display_ip", "last_ip"),
        serial=_first_string(device, "serial"),
        firmware=_first_string(device, "version", "firmwareVersion"),
        state=_device_state(device),
        raw=device,
    )


def _device_state(device: dict[str, Any]) -> str | None:
    """Return a readable device state."""
    state = _first_string(device, "state")
    if state is not None:
        return state
    if device.get("disabled"):
        return "disabled"
    if device.get("upgradable"):
        return "update_available"
    if device.get("adopted") is False:
        return "not_adopted"
    if device.get("connected") is False:
        return "offline"
    if device.get("online") is True or device.get("connected") is True:
        return "online"
    return None


def _first_string(device: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-empty string value."""
    for key in keys:
        value = device.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _clean_key(value: str) -> str:
    """Return a stable key safe for unique IDs."""
    return value.lower().replace(":", "").replace(" ", "_")
