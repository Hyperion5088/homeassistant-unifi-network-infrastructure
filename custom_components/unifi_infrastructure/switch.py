"""Switch controls for UniFi Infrastructure."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UniFiInfrastructureCoordinator, UniFiWlan


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Infrastructure switch controls."""
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_wlans: set[str] = set()

    def add_wlan_entities() -> None:
        new_entities = [
            UniFiWlanEnabledSwitch(coordinator, wlan_id)
            for wlan_id in sorted(coordinator.data.wlans)
            if wlan_id not in known_wlans
        ]
        if not new_entities:
            return
        known_wlans.update(entity.wlan_id for entity in new_entities)
        async_add_entities(new_entities)

    add_wlan_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_wlan_entities))


class UniFiWlanEnabledSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """SSID/WLAN enabled switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:wifi"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, wlan_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.wlan_id = wlan_id
        self._attr_unique_id = f"wlan_{wlan_id}_enabled"
        self._attr_name = f"SSID {self.wlan.name}" if self.wlan is not None else "SSID"

    @property
    def wlan(self) -> UniFiWlan | None:
        """Return the backing WLAN."""
        return self.coordinator.data.wlans.get(self.wlan_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the SSID is enabled."""
        return self.wlan.enabled if self.wlan is not None else None

    @property
    def available(self) -> bool:
        """Return whether the WLAN row is currently available."""
        return super().available and self.wlan is not None and self.wlan.enabled is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return SSID context."""
        if self.wlan is None:
            return {}
        attrs = {
            "wlan_id": self.wlan.key,
            "ssid": self.wlan.name,
            "security": self.wlan.security,
            "band": self.wlan.band,
            "is_guest": self.wlan.is_guest,
        }
        return {key: value for key, value in attrs.items() if value not in (None, "")}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        router_key = self.coordinator.data.router_device_key
        if router_key is None or (device := self.coordinator.data.devices.get(router_key)) is None:
            return None
        return DeviceInfo(
            identifiers={(DOMAIN, device.key)},
            manufacturer="Ubiquiti",
            name=device.name,
            model=device.model,
            sw_version=device.firmware,
            serial_number=device.serial,
            configuration_url=self.coordinator.client.base_url,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the SSID."""
        await self.coordinator.async_set_wlan_enabled(self.wlan_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the SSID."""
        await self.coordinator.async_set_wlan_enabled(self.wlan_id, False)
