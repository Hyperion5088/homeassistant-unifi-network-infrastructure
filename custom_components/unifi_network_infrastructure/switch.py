"""Switch controls for UniFi Network Infrastructure."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLE_FIREWALL_POLICY_CONTROLS,
    CONF_ENABLE_POE_CONTROLS,
    CONF_ENABLE_GUEST_WIFI_CONTROLS,
    CONF_ENABLE_PORT_ADMIN_CONTROLS,
    CONF_ENABLE_PORT_FORWARD_CONTROLS,
    CONF_ENABLE_ROUTE_POLICY_CONTROLS,
    CONF_ENABLE_WIFI_CONTROLS,
    DOMAIN,
)
from .coordinator import (
    UniFiFirewallPolicy,
    UniFiInfrastructureCoordinator,
    UniFiPort,
    UniFiPortForward,
    UniFiTrafficRoute,
    UniFiWlan,
)
from .options import interface_controls_enabled, option_enabled


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Network Infrastructure switch controls."""
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_wlans: set[str] = set()
    known_port_forwards: set[str] = set()
    known_traffic_routes: set[str] = set()
    known_firewall_policies: set[str] = set()
    known_admin_ports: set[str] = set()
    known_poe_ports: set[str] = set()

    def add_wlan_entities() -> None:
        new_entities = [
            UniFiWlanEnabledSwitch(coordinator, wlan_id)
            for wlan_id, wlan in sorted(coordinator.data.wlans.items())
            if _wlan_control_enabled(entry, wlan)
            if wlan_id not in known_wlans
        ]
        if not new_entities:
            return
        known_wlans.update(entity.wlan_id for entity in new_entities)
        async_add_entities(new_entities)

    def add_port_forward_entities() -> None:
        if not option_enabled(entry, CONF_ENABLE_PORT_FORWARD_CONTROLS):
            return
        new_entities = [
            UniFiPortForwardEnabledSwitch(coordinator, rule_id)
            for rule_id in sorted(coordinator.data.port_forwards)
            if rule_id not in known_port_forwards
        ]
        if not new_entities:
            return
        known_port_forwards.update(entity.rule_id for entity in new_entities)
        async_add_entities(new_entities)

    def add_traffic_route_entities() -> None:
        if not option_enabled(entry, CONF_ENABLE_ROUTE_POLICY_CONTROLS):
            return
        new_entities = [
            UniFiTrafficRouteEnabledSwitch(coordinator, route_id)
            for route_id in sorted(coordinator.data.traffic_routes)
            if route_id not in known_traffic_routes
        ]
        if not new_entities:
            return
        known_traffic_routes.update(entity.route_id for entity in new_entities)
        async_add_entities(new_entities)

    def add_firewall_policy_entities() -> None:
        if not option_enabled(entry, CONF_ENABLE_FIREWALL_POLICY_CONTROLS):
            return
        new_entities = [
            UniFiFirewallPolicyEnabledSwitch(coordinator, policy_id)
            for policy_id in sorted(coordinator.data.firewall_policies)
            if policy_id not in known_firewall_policies
        ]
        if not new_entities:
            return
        known_firewall_policies.update(entity.policy_id for entity in new_entities)
        async_add_entities(new_entities)

    def add_port_admin_entities() -> None:
        if not (
            interface_controls_enabled(entry)
            and option_enabled(entry, CONF_ENABLE_PORT_ADMIN_CONTROLS)
        ):
            return
        new_entities = [
            UniFiPortAdminSwitch(coordinator, port_key)
            for port_key in sorted(coordinator.data.ports)
            if port_key not in known_admin_ports
        ]
        if not new_entities:
            return
        known_admin_ports.update(entity.port_key for entity in new_entities)
        async_add_entities(new_entities)

    def add_poe_entities() -> None:
        if not (
            interface_controls_enabled(entry)
            and option_enabled(entry, CONF_ENABLE_POE_CONTROLS)
        ):
            return
        new_entities = [
            UniFiPortPoeSwitch(coordinator, port_key)
            for port_key, port in sorted(coordinator.data.ports.items())
            if port_key not in known_poe_ports and _port_poe_capable(port)
        ]
        if not new_entities:
            return
        known_poe_ports.update(entity.port_key for entity in new_entities)
        async_add_entities(new_entities)

    add_wlan_entities()
    add_port_forward_entities()
    add_traffic_route_entities()
    add_firewall_policy_entities()
    add_port_admin_entities()
    add_poe_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_wlan_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_port_forward_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_traffic_route_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_firewall_policy_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_port_admin_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_poe_entities))


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
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
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


class UniFiTrafficRouteEnabledSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """Traffic route policy enabled switch."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:routes"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, route_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.route_id = route_id
        self._attr_unique_id = f"traffic_route_{route_id}_enabled"
        self._attr_name = f"Route Policy {self.route.name}" if self.route is not None else "Route Policy"

    @property
    def route(self) -> UniFiTrafficRoute | None:
        """Return the backing traffic route."""
        return self.coordinator.data.traffic_routes.get(self.route_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the traffic route is enabled."""
        return self.route.enabled if self.route is not None else None

    @property
    def available(self) -> bool:
        """Return whether the traffic route row is currently available."""
        return super().available and self.route is not None and self.route.enabled is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return traffic route context."""
        if self.route is None:
            return {}
        attrs = {
            "route_id": self.route.key,
            "name": self.route.name,
            "matching_target": self.route.matching_target,
            "network_id": self.route.network_id,
            "next_hop": self.route.next_hop,
            "kill_switch_enabled": self.route.kill_switch_enabled,
            "domain_count": self.route.domain_count,
            "ip_address_count": self.route.ip_address_count,
            "ip_range_count": self.route.ip_range_count,
            "region_count": self.route.region_count,
            "target_device_count": self.route.target_device_count,
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
        """Enable the traffic route."""
        await self.coordinator.async_set_traffic_route_enabled(self.route_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the traffic route."""
        await self.coordinator.async_set_traffic_route_enabled(self.route_id, False)


class UniFiFirewallPolicyEnabledSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """Firewall policy enabled switch."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:wall-fire"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, policy_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.policy_id = policy_id
        self._attr_unique_id = f"firewall_policy_{policy_id}_enabled"
        self._attr_name = f"Firewall Policy {self.policy.name}" if self.policy is not None else "Firewall Policy"

    @property
    def policy(self) -> UniFiFirewallPolicy | None:
        """Return the backing firewall policy."""
        return self.coordinator.data.firewall_policies.get(self.policy_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the firewall policy is enabled."""
        return self.policy.enabled if self.policy is not None else None

    @property
    def available(self) -> bool:
        """Return whether the firewall policy row is currently available."""
        return super().available and self.policy is not None and self.policy.enabled is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return firewall policy context."""
        if self.policy is None:
            return {}
        attrs = {
            "policy_id": self.policy.key,
            "name": self.policy.name,
            "action": self.policy.action,
            "index": self.policy.index,
            "logging": self.policy.logging,
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
        """Enable the firewall policy."""
        await self.coordinator.async_set_firewall_policy_enabled(self.policy_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the firewall policy."""
        await self.coordinator.async_set_firewall_policy_enabled(self.policy_id, False)


class UniFiPortAdminSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """Port administrative state switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:ethernet"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, port_key: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.port_key = port_key
        self._attr_unique_id = f"{port_key}_admin_enabled"
        self._attr_name = f"Admin {self.port.name}" if self.port is not None else "Admin"

    @property
    def port(self) -> UniFiPort | None:
        """Return the backing port."""
        return self.coordinator.data.ports.get(self.port_key)

    @property
    def is_on(self) -> bool | None:
        """Return whether the port is administratively enabled."""
        return self.port.enabled if self.port is not None else None

    @property
    def available(self) -> bool:
        """Return whether this switch can currently be used."""
        return (
            super().available
            and self.port is not None
            and self.port.enabled is not None
            and self.coordinator.can_change_port(self.port_key)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return port context."""
        return _port_control_attrs(self.coordinator, self.port)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        return _port_device_info(self.coordinator, self.port)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the port."""
        await self.coordinator.async_set_port_enabled(self.port_key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the port."""
        await self.coordinator.async_set_port_enabled(self.port_key, False)


class UniFiPortPoeSwitch(CoordinatorEntity[UniFiInfrastructureCoordinator], SwitchEntity):
    """Port PoE state switch."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:power-plug"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, port_key: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.port_key = port_key
        self._attr_unique_id = f"{port_key}_poe_enabled"
        self._attr_name = f"PoE {self.port.name}" if self.port is not None else "PoE"

    @property
    def port(self) -> UniFiPort | None:
        """Return the backing port."""
        return self.coordinator.data.ports.get(self.port_key)

    @property
    def is_on(self) -> bool | None:
        """Return whether PoE is enabled."""
        return self.port.poe_enabled if self.port is not None else None

    @property
    def available(self) -> bool:
        """Return whether this switch can currently be used."""
        return (
            super().available
            and self.port is not None
            and _port_poe_capable(self.port)
            and self.coordinator.can_change_port(self.port_key)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return port context."""
        return _port_control_attrs(self.coordinator, self.port)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        return _port_device_info(self.coordinator, self.port)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable PoE."""
        await self.coordinator.async_set_port_poe_enabled(self.port_key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable PoE."""
        await self.coordinator.async_set_port_poe_enabled(self.port_key, False)


def _wlan_switch_name(wlan: UniFiWlan | None) -> str:
    """Return a clear WLAN switch name."""
    if wlan is None:
        return "WiFi"
    return f"WiFi {wlan.name}"


def _wlan_control_enabled(entry: ConfigEntry, wlan: UniFiWlan) -> bool:
    """Return whether a WLAN should expose a control switch."""
    if wlan.is_guest is True:
        return option_enabled(entry, CONF_ENABLE_GUEST_WIFI_CONTROLS)
    return option_enabled(entry, CONF_ENABLE_WIFI_CONTROLS)


def _port_poe_capable(port: UniFiPort) -> bool:
    """Return whether a port should expose PoE controls."""
    value = port.raw.get("port_poe")
    if isinstance(value, bool):
        return value
    poe_caps = port.raw.get("poe_caps")
    return isinstance(poe_caps, int | float) and poe_caps > 0


def _port_control_attrs(
    coordinator: UniFiInfrastructureCoordinator,
    port: UniFiPort | None,
) -> dict[str, Any]:
    """Return common port control context."""
    if port is None:
        return {}
    attrs = {
        "port": port.name,
        "port_idx": port.port_idx,
        "link_up": port.up,
        "protected": coordinator.is_port_locked(port.key),
        "protection_reasons": list(port.protection_reasons),
        "control_allowed": coordinator.can_change_port(port.key),
    }
    return {key: value for key, value in attrs.items() if value not in (None, "", [])}


def _port_device_info(
    coordinator: UniFiInfrastructureCoordinator,
    port: UniFiPort | None,
) -> DeviceInfo | None:
    """Return device info for a port entity."""
    if port is None:
        return None
    device = coordinator.data.devices.get(port.device_key)
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
