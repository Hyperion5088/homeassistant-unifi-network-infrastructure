"""Button controls for UniFi Network Infrastructure."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLE_LOCATE_CONTROL,
    CONF_ENABLE_POE_RESET,
    CONF_ENABLE_PORT_BOUNCE,
    CONF_ENABLE_REBOOT_CONTROL,
    DOMAIN,
)
from .coordinator import UniFiDevice, UniFiInfrastructureCoordinator, UniFiPort
from .options import interface_controls_enabled, option_enabled


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Network Infrastructure buttons."""
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []
    if option_enabled(entry, CONF_ENABLE_LOCATE_CONTROL):
        entities.extend(
            UniFiLocateButton(coordinator, device_key)
            for device_key, device in sorted(coordinator.data.devices.items())
            if device.mac is not None
        )
    if option_enabled(entry, CONF_ENABLE_REBOOT_CONTROL):
        entities.extend(
            UniFiRebootButton(coordinator, device_key)
            for device_key, device in sorted(coordinator.data.devices.items())
            if device.mac is not None
        )
    if interface_controls_enabled(entry):
        if option_enabled(entry, CONF_ENABLE_PORT_BOUNCE):
            entities.extend(
                UniFiPortBounceButton(coordinator, port_key)
                for port_key in sorted(coordinator.data.ports)
            )
        if option_enabled(entry, CONF_ENABLE_POE_RESET):
            entities.extend(
                UniFiPortPoeResetButton(coordinator, port_key)
                for port_key, port in sorted(coordinator.data.ports.items())
                if _port_poe_capable(port)
            )
    async_add_entities(entities)


class UniFiLocateButton(CoordinatorEntity[UniFiInfrastructureCoordinator], ButtonEntity):
    """Temporarily enable the UniFi locate LED."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:led-on"
    _attr_name = "System Locate"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, device_key: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.device_key = device_key
        self._attr_unique_id = f"{device_key}_locate"

    @property
    def device(self) -> UniFiDevice | None:
        """Return the backing device."""
        return self.coordinator.data.devices.get(self.device_key)

    @property
    def available(self) -> bool:
        """Return whether the device is available."""
        return super().available and self.device is not None and self.device.mac is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        return _device_info(self.coordinator, self.device)

    async def async_press(self) -> None:
        """Flash locate LED briefly."""
        await self.coordinator.async_locate_device(self.device_key)


class UniFiRebootButton(CoordinatorEntity[UniFiInfrastructureCoordinator], ButtonEntity):
    """Guarded UniFi device reboot button."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:restart"
    _attr_name = "Reboot"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, device_key: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.device_key = device_key
        self._attr_unique_id = f"{device_key}_reboot"

    @property
    def device(self) -> UniFiDevice | None:
        """Return the backing device."""
        return self.coordinator.data.devices.get(self.device_key)

    @property
    def available(self) -> bool:
        """Return whether reboot is armed and target device exists."""
        return (
            super().available
            and self.device is not None
            and self.device.mac is not None
            and self.coordinator.reboot_armed()
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return reboot guard context."""
        return {
            "confirmation": self.coordinator.reboot_confirmation,
            "armed": self.coordinator.reboot_armed(),
        }

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        return _device_info(self.coordinator, self.device)

    async def async_press(self) -> None:
        """Reboot the device."""
        await self.coordinator.async_reboot_device(self.device_key)


class UniFiPortBounceButton(CoordinatorEntity[UniFiInfrastructureCoordinator], ButtonEntity):
    """Disable and re-enable one port."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:ethernet-cable-off"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, port_key: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.port_key = port_key
        self._attr_unique_id = f"{port_key}_bounce"
        self._attr_name = f"Bounce {self.port.name}" if self.port is not None else "Bounce"

    @property
    def port(self) -> UniFiPort | None:
        """Return the backing port."""
        return self.coordinator.data.ports.get(self.port_key)

    @property
    def available(self) -> bool:
        """Return whether the port can be bounced."""
        return (
            super().available
            and self.port is not None
            and self.coordinator.can_change_port(self.port_key)
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        return _port_device_info(self.coordinator, self.port)

    async def async_press(self) -> None:
        """Bounce the port."""
        await self.coordinator.async_bounce_port(self.port_key)


class UniFiPortPoeResetButton(CoordinatorEntity[UniFiInfrastructureCoordinator], ButtonEntity):
    """Power-cycle PoE on one port."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:power-cycle"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, port_key: str) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.port_key = port_key
        self._attr_unique_id = f"{port_key}_poe_reset"
        self._attr_name = f"PoE Reset {self.port.name}" if self.port is not None else "PoE Reset"

    @property
    def port(self) -> UniFiPort | None:
        """Return the backing port."""
        return self.coordinator.data.ports.get(self.port_key)

    @property
    def available(self) -> bool:
        """Return whether PoE can be reset."""
        return (
            super().available
            and self.port is not None
            and _port_poe_capable(self.port)
            and self.coordinator.can_change_port(self.port_key)
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        return _port_device_info(self.coordinator, self.port)

    async def async_press(self) -> None:
        """Reset PoE."""
        await self.coordinator.async_reset_port_poe(self.port_key)


def _port_poe_capable(port: UniFiPort) -> bool:
    """Return whether a port reports PoE capability."""
    value = port.raw.get("port_poe")
    if isinstance(value, bool):
        return value
    poe_caps = port.raw.get("poe_caps")
    return isinstance(poe_caps, int | float) and poe_caps > 0


def _device_info(
    coordinator: UniFiInfrastructureCoordinator,
    device: UniFiDevice | None,
) -> DeviceInfo | None:
    """Return HA device info for a UniFi device."""
    if device is None:
        return None
    return DeviceInfo(
        identifiers={(DOMAIN, device.key)},
        manufacturer="Ubiquiti",
        name=device.name,
        model=device.model,
        sw_version=device.firmware,
        serial_number=device.serial,
        configuration_url=coordinator.client.base_url,
    )


def _port_device_info(
    coordinator: UniFiInfrastructureCoordinator,
    port: UniFiPort | None,
) -> DeviceInfo | None:
    """Return HA device info for a port."""
    if port is None:
        return None
    return _device_info(coordinator, coordinator.data.devices.get(port.device_key))
