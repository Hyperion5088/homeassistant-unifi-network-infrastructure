"""Sensors for UniFi Infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UniFiDevice, UniFiInfrastructureCoordinator


@dataclass(frozen=True, kw_only=True)
class UniFiSensorDescription(SensorEntityDescription):
    """UniFi sensor description."""

    value_fn: Callable[[UniFiDevice], Any]
    attr_fn: Callable[[UniFiDevice], dict[str, Any]] | None = None


def _raw_value(device: UniFiDevice, *keys: str) -> Any:
    """Return the first available raw device value."""
    for key in keys:
        value = _raw_path(device.raw, key)
        if value not in (None, ""):
            return value
    return None


def _raw_path(data: dict[str, Any], key: str) -> Any:
    """Return a raw value, supporting simple dotted paths."""
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _number(device: UniFiDevice, *keys: str) -> int | float | None:
    """Return a numeric raw device value."""
    value = _raw_value(device, *keys)
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _uptime(device: UniFiDevice) -> int | None:
    """Return uptime seconds."""
    value = _number(device, "uptime")
    return int(value) if value is not None else None


def _temperature(device: UniFiDevice) -> int | float | None:
    """Return device temperature."""
    return _number(device, "general_temperature", "temperature", "system-stats.temperature")


def _client_count(device: UniFiDevice) -> int | None:
    """Return aggregate connected client count only."""
    value = _number(device, "num_sta", "user-num_sta", "guest-num_sta")
    return int(value) if value is not None else None


def _update_state(device: UniFiDevice) -> str:
    """Return update availability as a simple state."""
    if device.raw.get("upgradable") is True:
        return "available"
    return "current"


def _device_attrs(device: UniFiDevice) -> dict[str, Any]:
    """Return safe device attributes."""
    attrs = {
        "kind": device.kind,
        "model": device.model,
        "ip": device.ip,
        "mac": device.mac,
        "serial": device.serial,
        "firmware": device.firmware,
    }
    return {key: value for key, value in attrs.items() if value not in (None, "")}


SENSOR_DESCRIPTIONS: tuple[UniFiSensorDescription, ...] = (
    UniFiSensorDescription(
        key="state",
        translation_key="state",
        value_fn=lambda device: device.state,
        attr_fn=_device_attrs,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: _number(device, "system-stats.cpu", "cpu"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="memory_usage",
        translation_key="memory_usage",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: _number(device, "system-stats.mem", "mem"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_temperature,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=_uptime,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="firmware",
        translation_key="firmware",
        value_fn=lambda device: device.firmware,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="update_status",
        translation_key="update_status",
        value_fn=_update_state,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="connected_clients",
        translation_key="connected_clients",
        value_fn=_client_count,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up UniFi Infrastructure sensors."""
    coordinator: UniFiInfrastructureCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[UniFiInfrastructureSensor] = []
    for device in coordinator.data.devices.values():
        entities.extend(
            UniFiInfrastructureSensor(coordinator, device.key, description)
            for description in SENSOR_DESCRIPTIONS
            if description.value_fn(device) is not None
        )
    async_add_entities(entities)


class UniFiInfrastructureSensor(CoordinatorEntity[UniFiInfrastructureCoordinator], SensorEntity):
    """UniFi infrastructure sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: UniFiInfrastructureCoordinator,
        device_key: str,
        description: UniFiSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_key = device_key
        self.entity_description = description
        self._attr_unique_id = f"{device_key}_{description.key}"

    @property
    def device(self) -> UniFiDevice | None:
        """Return the backing device."""
        return self.coordinator.data.devices.get(self.device_key)

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if (device := self.device) is None:
            return None
        return self.entity_description.value_fn(device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return sensor attributes."""
        if (device := self.device) is None or self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(device)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        if (device := self.device) is None:
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
