"""Lock entities for UniFi Network Infrastructure guarded controls."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AUTO_PROTECT_SECONDS, UniFiInfrastructureCoordinator, UniFiPort
from .const import DOMAIN
from .options import port_protection_enabled


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Network Infrastructure lock entities."""
    if not port_protection_enabled(entry):
        return
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_ports: set[str] = set()

    def add_port_entities() -> None:
        new_entities = [
            UniFiPortConfigProtectionLock(coordinator, port_key)
            for port_key, port in sorted(
                coordinator.data.ports.items(),
                key=lambda item: (item[1].device_key, item[1].port_idx),
            )
            if port_key not in known_ports
        ]
        if not new_entities:
            return
        known_ports.update(entity.port_key for entity in new_entities)
        async_add_entities(new_entities)

    add_port_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_port_entities))


class UniFiPortConfigProtectionLock(CoordinatorEntity[UniFiInfrastructureCoordinator], LockEntity):
    """Protection lock for UniFi switch uplink configuration."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, port_key: str) -> None:
        """Initialize the lock."""
        super().__init__(coordinator)
        self.port_key = port_key
        self._attr_unique_id = f"{port_key}_config_protection"
        self._attr_name = f"Protection {self.port.name}" if self.port is not None else "Protection"

    @property
    def port(self) -> UniFiPort | None:
        """Return the backing port."""
        return self.coordinator.data.ports.get(self.port_key)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        if self.port is None:
            return None
        device = self.coordinator.data.devices.get(self.port.device_key)
        if device is None:
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

    @property
    def available(self) -> bool:
        """Return whether the port row is currently available."""
        return super().available and self.port is not None

    @property
    def is_locked(self) -> bool:
        """Return whether port configuration controls are protected."""
        return self.coordinator.is_port_locked(self.port_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return lock context."""
        if self.port is None:
            return {}
        device = self.coordinator.data.devices.get(self.port.device_key)
        reason = self.coordinator.port_protection_reason(self.port_key)
        attrs = {
            "device": device.name if device is not None else self.port.device_key,
            "port": self.port.name,
            "port_idx": self.port.port_idx,
            "enabled": self.port.enabled,
            "link_up": self.port.up,
            "speed_mbps": self.port.speed_mbps,
            "poe_enabled": self.port.poe_enabled,
            "is_uplink": self.port.is_uplink,
            "protection_reasons": list(self.port.protection_reasons),
            "auto_protected": reason is not None,
            "protected_reason": reason,
            "manual_protection": self.coordinator.is_port_manually_locked(self.port_key),
            "temporarily_unlocked": self.coordinator.is_port_temporarily_unlocked(self.port_key),
            "auto_reprotect_seconds": AUTO_PROTECT_SECONDS,
        }
        return {key: value for key, value in attrs.items() if value not in (None, "")}

    async def async_lock(self, **kwargs: Any) -> None:
        """Protect port configuration controls."""
        self.coordinator.lock_port(self.port_key)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Temporarily allow port configuration controls."""
        self.coordinator.unlock_port(self.port_key)
