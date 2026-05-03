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
from .coordinator import UniFiInfrastructureCoordinator, UniFiPortForward, UniFiWlan


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Infrastructure switch controls."""
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_wlans: set[str] = set()
    known_port_forwards: set[str] = set()

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

    def add_port_forward_entities() -> None:
        new_entities = [
            UniFiPortForwardEnabledSwitch(coordinator, rule_id)
            for rule_id in sorted(coordinator.data.port_forwards)
            if rule_id not in known_port_forwards
        ]
        if not new_entities:
            return
        known_port_forwards.update(entity.rule_id for entity in new_entities)
        async_add_entities(new_entities)

    add_wlan_entities()
    add_port_forward_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_wlan_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_port_forward_entities))


class UniFiWlanEnabledSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """SSID/WLAN enabled switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:wifi"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, wlan_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.wlan_id = wlan_id
        self._attr_unique_id = f"wlan_{wlan_id}_enabled"
        self._attr_name = _wlan_switch_name(self.wlan)

    @property
    def wlan(self) -> UniFiWlan | None:
        """Return the backing WLAN."""
        return self.coordinator.data.wlans.get(self.wlan_id)

    @property
    def icon(self) -> str:
        """Return a guest-aware icon."""
        return "mdi:wifi-marker" if self.wlan is not None and self.wlan.is_guest is True else self._attr_icon

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


class UniFiPortForwardEnabledSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """Port-forward rule enabled switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:arrow-decision"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, rule_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.rule_id = rule_id
        self._attr_unique_id = f"port_forward_{rule_id}_enabled"
        self._attr_name = f"Port Forward {self.rule.name}" if self.rule is not None else "Port Forward"

    @property
    def rule(self) -> UniFiPortForward | None:
        """Return the backing port-forward rule."""
        return self.coordinator.data.port_forwards.get(self.rule_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the port-forward rule is enabled."""
        return self.rule.enabled if self.rule is not None else None

    @property
    def available(self) -> bool:
        """Return whether the port-forward row is currently available."""
        return super().available and self.rule is not None and self.rule.enabled is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return port-forward context."""
        if self.rule is None:
            return {}
        attrs = {
            "rule_id": self.rule.key,
            "name": self.rule.name,
            "protocol": self.rule.protocol,
            "source": self.rule.source,
            "destination": self.rule.destination,
            "destination_port": self.rule.destination_port,
            "forward_ip": self.rule.forward_ip,
            "forward_port": self.rule.forward_port,
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
        """Enable the port-forward rule."""
        await self.coordinator.async_set_port_forward_enabled(self.rule_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the port-forward rule."""
        await self.coordinator.async_set_port_forward_enabled(self.rule_id, False)


def _wlan_switch_name(wlan: UniFiWlan | None) -> str:
    """Return a clear WLAN switch name."""
    if wlan is None:
        return "SSID"
    return f"Guest Network {wlan.name}" if wlan.is_guest is True else f"SSID {wlan.name}"
