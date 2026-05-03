"""Sensors for UniFi Infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UniFiDevice, UniFiInfrastructureCoordinator, UniFiWan


@dataclass(frozen=True, kw_only=True)
class UniFiSensorDescription(SensorEntityDescription):
    """UniFi sensor description."""

    value_fn: Callable[[UniFiDevice], Any]
    attr_fn: Callable[[UniFiDevice], dict[str, Any]] | None = None
    device_kinds: frozenset[str] | None = None


SWITCH_KINDS = frozenset({"usw"})
AP_KINDS = frozenset({"uap"})
GATEWAY_KINDS = frozenset({"udm", "ugw"})
STATE_OPTIONS = [
    "offline",
    "online",
    "pending_adoption",
    "adopting",
    "provisioning",
    "upgrading",
    "disabled",
    "isolated",
    "unknown",
]


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


def _int(device: UniFiDevice, *keys: str) -> int | None:
    """Return an integer raw device value."""
    value = _number(device, *keys)
    return int(value) if value is not None else None


def _uptime_seconds(device: UniFiDevice) -> int | None:
    """Return uptime seconds."""
    return _int(device, "uptime")


def _uptime_display(device: UniFiDevice) -> str | None:
    """Return uptime as a friendly days plus clock string."""
    seconds = _uptime_seconds(device)
    if seconds is None:
        return None
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    day_label = "day" if days == 1 else "days"
    return f"{days} {day_label} {hours:02}:{minutes:02}:{seconds:02}"


def _temperature(device: UniFiDevice) -> int | float | None:
    """Return device temperature."""
    if (value := _number(device, "general_temperature", "temperature", "system-stats.temperature")) is not None:
        return value
    probes = _temperature_probe_details(device)
    values = [probe["value"] for probe in probes if isinstance(probe.get("value"), (int, float))]
    return max(values) if values else None


def _temperature_probe_details(device: UniFiDevice) -> list[dict[str, Any]]:
    """Return individual temperature probes when exposed by UniFi."""
    temperatures = device.raw.get("temperatures")
    if not isinstance(temperatures, list):
        return []
    probes: list[dict[str, Any]] = []
    for index, row in enumerate(temperatures, start=1):
        if not isinstance(row, dict):
            continue
        value = row.get("value")
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                value = None
        detail = {
            "name": row.get("name") or f"probe_{index}",
            "type": row.get("type"),
            "value": value,
            "unit": UnitOfTemperature.CELSIUS,
        }
        probes.append({key: value for key, value in detail.items() if value not in (None, "")})
    return probes


def _temperature_attrs(device: UniFiDevice) -> dict[str, Any] | None:
    """Return temperature probe details."""
    probes = _temperature_probe_details(device)
    return {"probes": probes, "value_type": "highest reported probe"} if probes else None


def _client_count(device: UniFiDevice) -> int | None:
    """Return aggregate connected client count only."""
    return _int(device, "num_sta", "user-num_sta", "guest-num_sta")


def _port_count(device: UniFiDevice) -> int | None:
    """Return the number of physical ports reported by the controller."""
    ports = device.raw.get("port_table")
    if isinstance(ports, list) and ports:
        return len(ports)
    ethernet = device.raw.get("ethernet_table")
    if isinstance(ethernet, list) and device.kind in GATEWAY_KINDS:
        return len(ethernet)
    return None


def _ap_radio_count(device: UniFiDevice) -> int | None:
    """Return access point radio count."""
    radios = device.raw.get("radio_table")
    if isinstance(radios, list):
        return len(radios)
    return None


def _ap_vap_count(device: UniFiDevice) -> int | None:
    """Return access point VAP count."""
    vaps = device.raw.get("vap_table")
    if isinstance(vaps, list):
        return len(vaps)
    return None


def _last_seen(device: UniFiDevice) -> datetime | None:
    """Return last seen timestamp."""
    value = _int(device, "last_seen")
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC)


def _fan_level(device: UniFiDevice) -> int | float | None:
    """Return fan level when UniFi exposes a concrete value."""
    if device.raw.get("has_fan") is not True:
        return None
    return _number(device, "fan_level")


def _fan_summary(device: UniFiDevice) -> str | None:
    """Return fan status/speed summary when concrete data is available."""
    fan = device.raw.get("fan")
    if isinstance(fan, str) and fan:
        return fan
    table = device.raw.get("fan_table")
    if not isinstance(table, list) or not table:
        return None
    parts: list[str] = []
    for index, row in enumerate(table, start=1):
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("id") or index
        speed = row.get("rpm") or row.get("speed") or row.get("value")
        state = row.get("state") or row.get("status")
        if speed not in (None, ""):
            parts.append(f"{name}: {speed} rpm")
        elif state not in (None, ""):
            parts.append(f"{name}: {state}")
    return " | ".join(parts) if parts else None


def _device_state(device: UniFiDevice) -> str:
    """Return normalized device state for an enum sensor."""
    raw_state = device.raw.get("state")
    if device.raw.get("disabled") is True:
        return "disabled"
    if device.raw.get("connected") is False:
        return "offline"
    if raw_state in (1, "1"):
        return "online"
    if raw_state in (0, "0"):
        return "offline"
    if raw_state in (2, "2"):
        return "pending_adoption"
    if raw_state in (3, "3"):
        return "adopting"
    if raw_state in (4, "4"):
        return "provisioning"
    if raw_state in (5, "5"):
        return "upgrading"
    if raw_state in (6, "6"):
        return "isolated"
    if device.state in STATE_OPTIONS:
        return device.state
    return "unknown"


def _state_attrs(device: UniFiDevice) -> dict[str, Any]:
    """Return state attributes with raw controller state retained."""
    attrs = _device_attrs(device)
    attrs["raw_state"] = device.raw.get("state")
    return {key: value for key, value in attrs.items() if value not in (None, "")}


def _uplink_summary(device: UniFiDevice) -> str | None:
    """Return a compact uplink summary."""
    uplink = device.raw.get("uplink")
    if not isinstance(uplink, dict):
        return None
    parts = [
        uplink.get("uplink_device_name"),
        uplink.get("name"),
        f"port {uplink['uplink_remote_port']}" if uplink.get("uplink_remote_port") is not None else None,
    ]
    return " / ".join(str(part) for part in parts if part not in (None, ""))


def _uplink_attrs(device: UniFiDevice) -> dict[str, Any] | None:
    """Return useful uplink details."""
    uplink = device.raw.get("uplink")
    if not isinstance(uplink, dict):
        return None
    attrs = {
        "type": uplink.get("type"),
        "name": uplink.get("name"),
        "uplink_mac": uplink.get("uplink_mac"),
        "uplink_device_name": uplink.get("uplink_device_name"),
        "uplink_remote_port": uplink.get("uplink_remote_port"),
        "speed_mbps": uplink.get("speed"),
        "tx_bytes": uplink.get("tx_bytes"),
        "rx_bytes": uplink.get("rx_bytes"),
    }
    return {key: value for key, value in attrs.items() if value not in (None, "")}


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


def _radio_attrs(device: UniFiDevice) -> dict[str, Any] | None:
    """Return access point radio details."""
    radios = device.raw.get("radio_table")
    if not isinstance(radios, list):
        return None
    details: list[dict[str, Any]] = []
    for index, radio in enumerate(radios, start=1):
        if not isinstance(radio, dict):
            continue
        detail = {
            "name": radio.get("name") or radio.get("radio_name") or f"radio_{index}",
            "band": _radio_band(radio.get("radio")),
            "channel": radio.get("channel"),
            "channel_width_mhz": radio.get("ht"),
            "tx_power_mode": radio.get("tx_power_mode"),
            "max_tx_power_dbm": radio.get("max_txpower"),
            "min_tx_power_dbm": radio.get("min_txpower"),
            "spatial_streams": radio.get("nss"),
        }
        details.append({key: value for key, value in detail.items() if value not in (None, "")})
    return {"radios": details} if details else None


def _radio_band(value: Any) -> str:
    """Return a friendly Wi-Fi band from UniFi's radio code."""
    return {
        "ng": "2.4 GHz",
        "na": "5 GHz",
        "6e": "6 GHz",
        "6g": "6 GHz",
    }.get(str(value), str(value) if value not in (None, "") else "unknown")


def _radio_details_state(device: UniFiDevice) -> str | None:
    """Return a readable access point radio summary."""
    radios = device.raw.get("radio_table")
    if not isinstance(radios, list) or not radios:
        return None
    bands = [_radio_band(radio.get("radio")) for radio in radios if isinstance(radio, dict)]
    count = len(radios)
    radio_label = "radio" if count == 1 else "radios"
    return f"{count} {radio_label}: {', '.join(bands)}" if bands else f"{count} {radio_label}"


def _load_attrs(window: str) -> dict[str, Any]:
    """Return explanatory load average attributes."""
    return {
        "window": window,
        "unit": "unitless",
        "value_type": "load average",
        "source": "sys_stats load average",
        "description": "Linux-style system load, not CPU percentage.",
    }


def _format_bytes(value: int | float | None) -> str | None:
    """Return bytes as the most appropriate binary unit."""
    if value is None:
        return None
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    unit_index = 0
    while abs(size) >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def _traffic_value(device: UniFiDevice, *keys: str) -> str | None:
    """Return a readable cumulative traffic counter."""
    return _format_bytes(_number(device, *keys))


def _traffic_attrs(device: UniFiDevice, direction: str, *keys: str) -> dict[str, Any]:
    """Return explanatory traffic counter attributes."""
    value = _number(device, *keys)
    return {
        "direction": direction,
        "raw_bytes": value,
        "raw_unit": "B",
        "value_type": "cumulative traffic counter",
        "counter_type": "cumulative",
        "source": "UniFi device traffic counter",
        "description": "Counter value from the controller payload, not live bandwidth.",
    }


SENSOR_DESCRIPTIONS: tuple[UniFiSensorDescription, ...] = (
    UniFiSensorDescription(
        key="state",
        name="State",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        icon="mdi:state-machine",
        value_fn=_device_state,
        attr_fn=_state_attrs,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="ip_address",
        name="IP Address",
        translation_key="ip_address",
        icon="mdi:ip-network",
        value_fn=lambda device: device.ip,
    ),
    UniFiSensorDescription(
        key="mac_address",
        name="MAC Address",
        translation_key="mac_address",
        icon="mdi:identifier",
        value_fn=lambda device: device.mac,
    ),
    UniFiSensorDescription(
        key="serial_number",
        name="Serial Number",
        translation_key="serial_number",
        icon="mdi:barcode",
        value_fn=lambda device: device.serial,
    ),
    UniFiSensorDescription(
        key="model",
        name="Model",
        translation_key="model",
        icon="mdi:router-network",
        value_fn=lambda device: device.model,
    ),
    UniFiSensorDescription(
        key="cpu_usage",
        name="CPU Usage",
        translation_key="cpu_usage",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: _number(device, "system-stats.cpu", "cpu"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="memory_usage",
        name="Memory Usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: _number(device, "system-stats.mem", "mem"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="temperature",
        name="Temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_temperature,
        attr_fn=_temperature_attrs,
    ),
    UniFiSensorDescription(
        key="fan_level",
        name="Fan Level",
        translation_key="fan_level",
        icon="mdi:fan",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_fan_level,
    ),
    UniFiSensorDescription(
        key="fan_summary",
        name="Fan Summary",
        translation_key="fan_summary",
        icon="mdi:fan",
        value_fn=_fan_summary,
    ),
    UniFiSensorDescription(
        key="uptime",
        name="Uptime",
        translation_key="uptime",
        icon="mdi:timer-outline",
        value_fn=_uptime_display,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="last_seen",
        name="Last Seen",
        translation_key="last_seen",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_seen,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="load_average_1_min",
        name="System Load 1 min",
        translation_key="load_average_1_min",
        icon="mdi:speedometer",
        value_fn=lambda device: _number(device, "sys_stats.loadavg_1"),
        attr_fn=lambda device: _load_attrs("1 minute"),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="load_average_5_min",
        name="System Load 5 min",
        translation_key="load_average_5_min",
        icon="mdi:speedometer",
        value_fn=lambda device: _number(device, "sys_stats.loadavg_5"),
        attr_fn=lambda device: _load_attrs("5 minutes"),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="load_average_15_min",
        name="System Load 15 min",
        translation_key="load_average_15_min",
        icon="mdi:speedometer",
        value_fn=lambda device: _number(device, "sys_stats.loadavg_15"),
        attr_fn=lambda device: _load_attrs("15 minutes"),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="firmware",
        name="Firmware",
        translation_key="firmware",
        icon="mdi:chip",
        value_fn=lambda device: device.firmware,
    ),
    UniFiSensorDescription(
        key="update_status",
        name="Update Status",
        translation_key="update_status",
        icon="mdi:update",
        value_fn=_update_state,
    ),
    UniFiSensorDescription(
        key="port_count",
        name="Port Count",
        translation_key="port_count",
        icon="mdi:ethernet",
        value_fn=_port_count,
        device_kinds=SWITCH_KINDS | GATEWAY_KINDS,
    ),
    UniFiSensorDescription(
        key="radio_count",
        name="Radio Count",
        translation_key="radio_count",
        icon="mdi:wifi",
        value_fn=_ap_radio_count,
        device_kinds=AP_KINDS,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="vap_count",
        name="VAP Count",
        translation_key="vap_count",
        icon="mdi:wifi-settings",
        value_fn=_ap_vap_count,
        device_kinds=AP_KINDS,
        entity_registry_enabled_default=False,
    ),
    UniFiSensorDescription(
        key="connected_clients",
        name="Connected Clients",
        translation_key="connected_clients",
        icon="mdi:account-network",
        value_fn=_client_count,
    ),
    UniFiSensorDescription(
        key="rx_bytes",
        name="Received Traffic",
        translation_key="rx_bytes",
        icon="mdi:download-network",
        value_fn=lambda device: _traffic_value(device, "rx_bytes"),
        attr_fn=lambda device: _traffic_attrs(device, "received", "rx_bytes"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="tx_bytes",
        name="Transmitted Traffic",
        translation_key="tx_bytes",
        icon="mdi:upload-network",
        value_fn=lambda device: _traffic_value(device, "tx_bytes"),
        attr_fn=lambda device: _traffic_attrs(device, "transmitted", "tx_bytes"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="total_bytes",
        name="Total Traffic",
        translation_key="total_bytes",
        icon="mdi:swap-horizontal-bold",
        value_fn=lambda device: _traffic_value(device, "bytes"),
        attr_fn=lambda device: _traffic_attrs(device, "total", "bytes"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="uplink",
        name="Uplink",
        translation_key="uplink",
        icon="mdi:lan-connect",
        value_fn=_uplink_summary,
        attr_fn=_uplink_attrs,
    ),
    UniFiSensorDescription(
        key="radio_summary",
        name="Radio Details",
        translation_key="radio_summary",
        icon="mdi:wifi-cog",
        value_fn=_radio_details_state,
        attr_fn=lambda device: _radio_attrs(device) or {},
        device_kinds=AP_KINDS,
        entity_registry_enabled_default=False,
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
            if (description.device_kinds is None or device.kind in description.device_kinds)
            and description.value_fn(device) is not None
        )
    known_wans: set[str] = set()

    def add_wan_entities() -> None:
        new_entities = [
            UniFiWanIpSensor(coordinator, wan_key)
            for wan_key in sorted(coordinator.data.wans)
            if wan_key not in known_wans
        ]
        if not new_entities:
            return
        known_wans.update(entity.wan_key for entity in new_entities)
        async_add_entities(new_entities)

    async_add_entities(entities)
    add_wan_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_wan_entities))


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


class UniFiWanIpSensor(CoordinatorEntity[UniFiInfrastructureCoordinator], SensorEntity):
    """UniFi router WAN IP address sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:wan"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, wan_key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.wan_key = wan_key
        self._attr_unique_id = f"{wan_key}_ip_address"
        self._attr_name = f"{self.wan.name} IP Address" if self.wan is not None else "WAN IP Address"

    @property
    def wan(self) -> UniFiWan | None:
        """Return the backing WAN uplink."""
        return self.coordinator.data.wans.get(self.wan_key)

    @property
    def native_value(self) -> str | None:
        """Return the WAN IP address."""
        return self.wan.ip if self.wan is not None else None

    @property
    def available(self) -> bool:
        """Return whether the WAN row is currently available."""
        return super().available and self.wan is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return WAN context."""
        if self.wan is None:
            return {}
        attrs = {
            "wan": self.wan.name,
            "interface": self.wan.ifname,
            "port_idx": self.wan.port_idx,
            "status": self.wan.status,
            "alive": self.wan.alive,
        }
        return {key: value for key, value in attrs.items() if value not in (None, "")}

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant device info."""
        if self.wan is None:
            return None
        device = self.coordinator.data.devices.get(self.wan.device_key)
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
