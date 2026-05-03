"""Sensors for UniFi Network Infrastructure."""

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
from .coordinator import UniFiDevice, UniFiInfrastructureCoordinator, UniFiPort, UniFiWan


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


def _ap_broadcast_ssid_count(device: UniFiDevice) -> int | None:
    """Return the number of unique SSIDs currently broadcast by an AP."""
    ssids = _ap_broadcast_ssids(device)
    if ssids is None:
        return None
    return len(ssids)


def _ap_broadcast_ssid_attrs(device: UniFiDevice) -> dict[str, Any] | None:
    """Return SSID broadcast details grouped from AP VAP rows."""
    ssids = _ap_broadcast_ssids(device)
    if ssids is None:
        return None
    return {
        "ssids": ssids,
        "ssid_names": [ssid["ssid"] for ssid in ssids],
        "vap_instances": sum(len(ssid.get("vap_interfaces", ())) for ssid in ssids),
        "source": "vap_table grouped by essid",
    }


def _ap_broadcast_ssids(device: UniFiDevice) -> list[dict[str, Any]] | None:
    """Return active VAP rows grouped by unique SSID."""
    vaps = device.raw.get("vap_table")
    if not isinstance(vaps, list):
        return None
    grouped: dict[str, dict[str, Any]] = {}
    for vap in vaps:
        if not isinstance(vap, dict) or not _vap_is_broadcasting(vap):
            continue
        ssid = vap.get("essid") or vap.get("ssid")
        if not isinstance(ssid, str) or not ssid:
            continue
        detail = grouped.setdefault(
            ssid,
            {
                "ssid": ssid,
                "bands": set(),
                "radios": set(),
                "bssids": set(),
                "vap_interfaces": set(),
                "wlanconf_ids": set(),
                "states": set(),
                "is_guest": vap.get("is_guest"),
                "client_count": 0,
            },
        )
        if (band := _radio_band(vap.get("radio"))) != "unknown":
            detail["bands"].add(band)
        if radio := vap.get("radio_name"):
            detail["radios"].add(radio)
        if bssid := vap.get("bssid"):
            detail["bssids"].add(bssid)
        if interface := vap.get("name"):
            detail["vap_interfaces"].add(interface)
        if wlanconf_id := vap.get("wlanconf_id"):
            detail["wlanconf_ids"].add(wlanconf_id)
        if state := vap.get("state"):
            detail["states"].add(str(state))
        if vap.get("is_guest") is True:
            detail["is_guest"] = True
        if isinstance(vap.get("num_sta"), int | float):
            detail["client_count"] += int(vap["num_sta"])
    results: list[dict[str, Any]] = []
    for ssid in sorted(grouped):
        detail = grouped[ssid]
        normalized = {
            "ssid": detail["ssid"],
            "bands": sorted(detail["bands"]),
            "radios": sorted(detail["radios"]),
            "bssids": sorted(detail["bssids"]),
            "vap_interfaces": sorted(detail["vap_interfaces"]),
            "wlanconf_ids": sorted(detail["wlanconf_ids"]),
            "states": sorted(detail["states"]),
            "is_guest": detail["is_guest"],
            "client_count": detail["client_count"],
            "broadcasting": True,
        }
        results.append({key: value for key, value in normalized.items() if value not in (None, "", [], set())})
    return results


def _vap_is_broadcasting(vap: dict[str, Any]) -> bool:
    """Return whether a UniFi VAP row looks actively broadcast."""
    if vap.get("up") is False or vap.get("enabled") is False:
        return False
    state = vap.get("state")
    if state not in (None, "") and str(state).upper() not in {"RUN", "UP"}:
        return False
    return True


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


def _port_speed_value(port: UniFiPort) -> str:
    """Return the port speed as a readable state."""
    if port.up is False:
        return "Down"
    if port.speed_mbps is None:
        return "Unknown"
    if port.speed_mbps >= 1000:
        gbps = port.speed_mbps / 1000
        return f"{gbps:g} Gbps"
    return f"{port.speed_mbps} Mbps"


def _port_sensor_name(port: UniFiPort | None) -> str:
    """Return a grouped port sensor name."""
    if port is None:
        return "Port"
    media_group = _port_media_group(port.raw, port.name)
    label = _short_port_label(port.name)
    if media_group == "Port":
        return f"Port {label}"
    return f"Port {media_group} {label}"


def _port_media_group(raw: dict[str, Any], name: str = "") -> str:
    """Return the HA display group for a port row."""
    media_text = " ".join(
        str(value)
        for value in (
            name,
            raw.get("media"),
            raw.get("media_type"),
            raw.get("port_type"),
            raw.get("type"),
            raw.get("connector"),
            raw.get("connector_type"),
            raw.get("interface_type"),
            raw.get("ifname"),
            raw.get("name"),
            raw.get("label"),
        )
        if value not in (None, "")
    ).lower()
    for marker, label in (
        ("qsfp28", "QSFP28"),
        ("qsfp+", "QSFP+"),
        ("qsfp", "QSFP"),
        ("sfp28", "SFP28"),
        ("sfp+", "SFP+"),
        ("sfp", "SFP"),
    ):
        if marker in media_text:
            return label
    if any(marker in media_text for marker in ("fiber", "fibre")):
        return "SFP"
    return "Port"


def _short_port_label(name: str) -> str:
    """Return a port label without duplicate grouping text."""
    label = str(name).strip()
    lowered = label.lower()
    for prefix in ("port ", "qsfp28 ", "qsfp+ ", "qsfp ", "sfp28 ", "sfp+ ", "sfp "):
        if lowered.startswith(prefix):
            return label[len(prefix) :].strip() or label
    return label


def _port_attrs(port: UniFiPort, device: UniFiDevice | None, coordinator: UniFiInfrastructureCoordinator) -> dict[str, Any]:
    """Return detailed port attributes."""
    raw = port.raw
    attrs = {
        "device": device.name if device is not None else port.device_key,
        "port": port.name,
        "port_idx": port.port_idx,
        "interface": _port_value(raw, "ifname"),
        "enabled": port.enabled,
        "link_up": port.up,
        "speed_mbps": port.speed_mbps,
        "max_speed_mbps": _port_number(raw, "max_speed"),
        "speed_capability": _port_value(raw, "speed_caps"),
        "poe_enabled": port.poe_enabled,
        "poe_capable": _port_poe_capable(raw),
        "poe_power_w": _port_poe_power_w(raw),
        "poe_mode": _port_value(raw, "poe_mode", "poe_caps", "port_poe"),
        "poe_class": _port_value(raw, "poe_class"),
        "media": _port_value(raw, "media", "media_type", "port_type", "type"),
        "autoneg": _port_bool(raw, "autoneg"),
        "full_duplex": _port_bool(raw, "full_duplex"),
        "flow_control_rx": _port_bool(raw, "flowctrl_rx"),
        "flow_control_tx": _port_bool(raw, "flowctrl_tx"),
        "is_uplink": port.is_uplink,
        "protection_reasons": list(port.protection_reasons),
        "auto_protected": coordinator.is_port_auto_protected(port.key),
        "protected": coordinator.is_port_locked(port.key),
        "admin_control_allowed": coordinator.can_change_port(port.key),
        "rx_bytes": _port_number(raw, "rx_bytes"),
        "tx_bytes": _port_number(raw, "tx_bytes"),
        "rx_rate_bps": _port_number(raw, "rx_rate"),
        "tx_rate_bps": _port_number(raw, "tx_rate"),
        "rx_rate_bytes_per_second": _port_number(raw, "rx_bytes-r"),
        "tx_rate_bytes_per_second": _port_number(raw, "tx_bytes-r"),
        "rx_errors": _port_number(raw, "rx_errors"),
        "tx_errors": _port_number(raw, "tx_errors"),
        "rx_dropped": _port_number(raw, "rx_dropped"),
        "tx_dropped": _port_number(raw, "tx_dropped"),
        "lldp_neighbors": _port_lldp_neighbors(port, device),
    }
    return {key: value for key, value in attrs.items() if value not in (None, "", [])}


def _port_value(port: dict[str, Any], *keys: str) -> Any:
    """Return the first populated raw port value."""
    for key in keys:
        value = port.get(key)
        if value not in (None, ""):
            return value
    return None


def _port_number(port: dict[str, Any], *keys: str) -> int | float | None:
    """Return the first numeric raw port value."""
    value = _port_value(port, *keys)
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _port_poe_power_w(port: dict[str, Any]) -> int | float | None:
    """Return PoE power in watts when exposed."""
    value = _port_number(port, "poe_power", "poe_power_w")
    if value is not None:
        return value
    value = _port_number(port, "poe_power_mw")
    return value / 1000 if value is not None else None


def _port_poe_capable(port: dict[str, Any]) -> bool | None:
    """Return whether the port is PoE capable."""
    if (value := _port_bool(port, "port_poe", "poe_capable", "is_poe")) is not None:
        return value
    poe_caps = _port_number(port, "poe_caps")
    return poe_caps > 0 if poe_caps is not None else None


def _port_bool(port: dict[str, Any], *keys: str) -> bool | None:
    """Return the first boolean-like raw port value."""
    for key in keys:
        value = port.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "on", "enabled", "1"}:
                return True
            if lowered in {"false", "no", "off", "disabled", "0"}:
                return False
    return None


def _port_lldp_neighbors(port: UniFiPort, device: UniFiDevice | None) -> list[dict[str, Any]]:
    """Return LLDP neighbors for a port when exposed by the controller."""
    if device is None:
        return []
    lldp_table = device.raw.get("lldp_table")
    if not isinstance(lldp_table, list):
        return []
    neighbors: list[dict[str, Any]] = []
    for row in lldp_table:
        if not isinstance(row, dict) or _port_number(row, "local_port_idx") != port.port_idx:
            continue
        detail = {
            "name": _port_value(row, "system_name", "hostname", "device_name", "chassis_name"),
            "port": _port_value(row, "port_id", "port_name", "remote_port"),
            "chassis_id": _port_value(row, "chassis_id"),
            "mac": _port_value(row, "mac"),
        }
        neighbors.append({key: value for key, value in detail.items() if value not in (None, "")})
    return neighbors


SENSOR_DESCRIPTIONS: tuple[UniFiSensorDescription, ...] = (
    UniFiSensorDescription(
        key="state",
        name="System State",
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
        name="IP LAN",
        translation_key="ip_address",
        icon="mdi:ip-network",
        value_fn=lambda device: device.ip,
    ),
    UniFiSensorDescription(
        key="mac_address",
        name="System MAC Address",
        translation_key="mac_address",
        icon="mdi:identifier",
        value_fn=lambda device: device.mac,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="serial_number",
        name="System Serial Number",
        translation_key="serial_number",
        icon="mdi:barcode",
        value_fn=lambda device: device.serial,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="model",
        name="System Model",
        translation_key="model",
        icon="mdi:router-network",
        value_fn=lambda device: device.model,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="cpu_usage",
        name="System CPU Usage",
        translation_key="cpu_usage",
        icon="mdi:cpu-64-bit",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: _number(device, "system-stats.cpu", "cpu"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="memory_usage",
        name="System Memory Usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: _number(device, "system-stats.mem", "mem"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="temperature",
        name="System Temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_temperature,
        attr_fn=_temperature_attrs,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="fan_level",
        name="System Fan Level",
        translation_key="fan_level",
        icon="mdi:fan",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_fan_level,
    ),
    UniFiSensorDescription(
        key="fan_summary",
        name="System Fan Summary",
        translation_key="fan_summary",
        icon="mdi:fan",
        value_fn=_fan_summary,
    ),
    UniFiSensorDescription(
        key="uptime",
        name="System Uptime",
        translation_key="uptime",
        icon="mdi:timer-outline",
        value_fn=_uptime_display,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="last_seen",
        name="System Last Seen",
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
        name="System Firmware",
        translation_key="firmware",
        icon="mdi:chip",
        value_fn=lambda device: device.firmware,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="update_status",
        name="System Update Status",
        translation_key="update_status",
        icon="mdi:update",
        value_fn=_update_state,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="port_count",
        name="Port Count",
        translation_key="port_count",
        icon="mdi:ethernet",
        value_fn=_port_count,
        device_kinds=SWITCH_KINDS | GATEWAY_KINDS,
        entity_registry_enabled_default=False,
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
        key="broadcast_ssids",
        name="Broadcast SSIDs",
        translation_key="broadcast_ssids",
        icon="mdi:wifi-check",
        value_fn=_ap_broadcast_ssid_count,
        attr_fn=lambda device: _ap_broadcast_ssid_attrs(device) or {},
        device_kinds=AP_KINDS,
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
        name="Traffic Received",
        translation_key="rx_bytes",
        icon="mdi:download-network",
        value_fn=lambda device: _traffic_value(device, "rx_bytes"),
        attr_fn=lambda device: _traffic_attrs(device, "received", "rx_bytes"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="tx_bytes",
        name="Traffic Transmitted",
        translation_key="tx_bytes",
        icon="mdi:upload-network",
        value_fn=lambda device: _traffic_value(device, "tx_bytes"),
        attr_fn=lambda device: _traffic_attrs(device, "transmitted", "tx_bytes"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="total_bytes",
        name="Traffic Total",
        translation_key="total_bytes",
        icon="mdi:swap-horizontal-bold",
        value_fn=lambda device: _traffic_value(device, "bytes"),
        attr_fn=lambda device: _traffic_attrs(device, "total", "bytes"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    UniFiSensorDescription(
        key="uplink",
        name="System Uplink",
        translation_key="uplink",
        icon="mdi:lan-connect",
        value_fn=_uplink_summary,
        attr_fn=_uplink_attrs,
        entity_category=EntityCategory.DIAGNOSTIC,
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
    """Set up UniFi Network Infrastructure sensors."""
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
    known_ports: set[str] = set()

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

    def add_port_entities() -> None:
        new_entities = [
            UniFiPortSpeedSensor(coordinator, port_key)
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

    async_add_entities(entities)
    add_wan_entities()
    add_port_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_wan_entities))
    entry.async_on_unload(coordinator.async_add_listener(add_port_entities))


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
        self._attr_name = f"IP {self.wan.name}" if self.wan is not None else "IP WAN"

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


class UniFiPortSpeedSensor(CoordinatorEntity[UniFiInfrastructureCoordinator], SensorEntity):
    """UniFi switch/router port speed sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:ethernet"

    def __init__(self, coordinator: UniFiInfrastructureCoordinator, port_key: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.port_key = port_key
        self._attr_unique_id = f"{port_key}_speed"
        self._attr_name = _port_sensor_name(self.port)

    @property
    def port(self) -> UniFiPort | None:
        """Return the backing port."""
        return self.coordinator.data.ports.get(self.port_key)

    @property
    def device(self) -> UniFiDevice | None:
        """Return the backing device."""
        if self.port is None:
            return None
        return self.coordinator.data.devices.get(self.port.device_key)

    @property
    def native_value(self) -> str | None:
        """Return current negotiated port speed."""
        return _port_speed_value(self.port) if self.port is not None else None

    @property
    def available(self) -> bool:
        """Return whether the port row is currently available."""
        return super().available and self.port is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return port details."""
        if self.port is None:
            return {}
        return _port_attrs(self.port, self.device, self.coordinator)

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
