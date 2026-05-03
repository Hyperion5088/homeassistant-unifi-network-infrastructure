"""Select controls for UniFi Network Infrastructure."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENABLE_REBOOT_CONTROL, DOMAIN
from .coordinator import UniFiInfrastructureCoordinator
from .options import option_enabled

REBOOT_OPTIONS = ["Cancel", "Reboot"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi select entities."""
    if not option_enabled(entry, CONF_ENABLE_REBOOT_CONTROL):
        return
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UniFiRebootConfirmationSelect(coordinator)])


class UniFiRebootConfirmationSelect(CoordinatorEntity[UniFiInfrastructureCoordinator], SelectEntity):
    """Shared reboot confirmation select."""

    _attr_has_entity_name = True
    _attr_name = "Reboot Confirmation"
    _attr_options = REBOOT_OPTIONS
    _attr_unique_id = "unifi_reboot_confirmation"
    _attr_entity_registry_enabled_default = False

    @property
    def current_option(self) -> str:
        """Return the current confirmation state."""
        return self.coordinator.reboot_confirmation

    async def async_select_option(self, option: str) -> None:
        """Arm or cancel reboot."""
        self.coordinator.set_reboot_confirmation(option)
