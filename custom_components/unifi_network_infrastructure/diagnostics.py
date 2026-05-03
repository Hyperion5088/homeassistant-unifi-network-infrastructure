"""Diagnostics for UniFi Network Infrastructure."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics with credentials redacted."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return {
        "entry": {
            key: "REDACTED" if key == CONF_PASSWORD else value
            for key, value in entry.data.items()
        },
        "options": dict(entry.options),
        "devices": [
            {
                "key": device.key,
                "name": device.name,
                "kind": device.kind,
                "model": device.model,
                "ip": device.ip,
                "firmware": device.firmware,
                "state": device.state,
            }
            for device in data.devices.values()
        ],
    }
