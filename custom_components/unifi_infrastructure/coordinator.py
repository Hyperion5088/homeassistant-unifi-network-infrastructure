"""Coordinator for UniFi Infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniFiInfrastructureClient, UniFiInfrastructureError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)
AUTO_PROTECT_SECONDS = 15 * 60


@dataclass(slots=True)
class UniFiDevice:
    """Normalized UniFi infrastructure device."""

    key: str
    name: str
    kind: str
    model: str | None
    mac: str | None
    ip: str | None
    serial: str | None
    firmware: str | None
    state: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class UniFiPort:
    """Normalized UniFi switch port."""

    key: str
    device_key: str
    port_idx: int
    name: str
    enabled: bool | None
    up: bool | None
    is_uplink: bool
    speed_mbps: int | None
    poe_enabled: bool | None
    raw: dict[str, Any]


@dataclass(slots=True)
class UniFiInfrastructureData:
    """Coordinator data."""

    devices: dict[str, UniFiDevice]
    ports: dict[str, UniFiPort]
    wlans: dict[str, "UniFiWlan"]
    router_device_key: str | None


@dataclass(slots=True)
class UniFiWlan:
    """Normalized UniFi WLAN/SSID configuration."""

    key: str
    name: str
    enabled: bool | None
    security: str | None
    band: str | None
    is_guest: bool | None
    raw: dict[str, Any]


class UniFiInfrastructureCoordinator(DataUpdateCoordinator[UniFiInfrastructureData]):
    """Fetch UniFi infrastructure device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: UniFiInfrastructureClient,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval) if scan_interval > 0 else DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self._temporarily_unlocked_ports: set[str] = set()
        self._auto_protect_timers: dict[str, Callable[[], None]] = {}

    async def _async_update_data(self) -> UniFiInfrastructureData:
        """Fetch data from UniFi Network."""
        try:
            devices = await self.client.async_get_devices()
            wlans = await self.client.async_get_wlans()
        except UniFiInfrastructureError as err:
            raise UpdateFailed(str(err)) from err
        normalized = [_normalize_device(device) for device in devices]
        normalized_wlans: list[UniFiWlan] = []
        for wlan in wlans:
            if (normalized_wlan := _normalize_wlan(wlan)) is not None:
                normalized_wlans.append(normalized_wlan)
        device_map = {device.key: device for device in normalized}
        return UniFiInfrastructureData(
            devices=device_map,
            ports=_normalize_ports(normalized),
            wlans={wlan.key: wlan for wlan in normalized_wlans},
            router_device_key=_router_device_key(device_map),
        )

    async def async_set_wlan_enabled(self, wlan_id: str, enabled: bool) -> None:
        """Enable or disable a WLAN/SSID and refresh data."""
        await self.client.async_set_wlan_enabled(wlan_id, enabled)
        await self.async_request_refresh()

    def is_port_locked(self, port_key: str) -> bool:
        """Return whether port configuration controls are protected."""
        return self.is_port_auto_protected(port_key) and port_key not in self._temporarily_unlocked_ports

    def is_port_auto_protected(self, port_key: str) -> bool:
        """Return whether UniFi marks the port as an uplink."""
        port = self.data.ports.get(port_key) if self.data is not None else None
        return port.is_uplink if port is not None else False

    def port_protection_reason(self, port_key: str) -> str | None:
        """Return why a port is auto-protected."""
        if self.is_port_auto_protected(port_key):
            return "UniFi marks this port as the switch uplink"
        return None

    def is_port_temporarily_unlocked(self, port_key: str) -> bool:
        """Return whether an auto-protected port is temporarily unlocked."""
        return port_key in self._temporarily_unlocked_ports

    def lock_port(self, port_key: str) -> None:
        """Protect a port immediately."""
        self._temporarily_unlocked_ports.discard(port_key)
        self._cancel_auto_protect(port_key)
        self.async_update_listeners()

    def unlock_port(self, port_key: str) -> None:
        """Temporarily allow configuration changes on an auto-protected port."""
        if self.is_port_auto_protected(port_key):
            self._temporarily_unlocked_ports.add(port_key)
            self._schedule_auto_protect(port_key)
        self.async_update_listeners()

    def can_change_port(self, port_key: str) -> bool:
        """Return whether configuration controls are allowed for a port."""
        return not self.is_port_locked(port_key)

    def cancel_auto_protect_timers(self) -> None:
        """Cancel pending auto-protection callbacks."""
        for cancel in self._auto_protect_timers.values():
            cancel()
        self._auto_protect_timers.clear()

    def _schedule_auto_protect(self, port_key: str) -> None:
        """Schedule protection to return after a temporary unlock."""
        self._cancel_auto_protect(port_key)

        def _auto_lock(_: Any) -> None:
            self._auto_protect_timers.pop(port_key, None)
            self._temporarily_unlocked_ports.discard(port_key)
            self.async_update_listeners()

        self._auto_protect_timers[port_key] = async_call_later(
            self.hass,
            AUTO_PROTECT_SECONDS,
            _auto_lock,
        )

    def _cancel_auto_protect(self, port_key: str) -> None:
        """Cancel a pending auto-protect callback for one port."""
        if cancel := self._auto_protect_timers.pop(port_key, None):
            cancel()


def _normalize_device(device: dict[str, Any]) -> UniFiDevice:
    """Normalize a UniFi device row."""
    mac = _first_string(device, "mac")
    key = _first_string(device, "_id", "device_id", "serial", "mac") or "unknown"
    name = _first_string(device, "name", "display_name", "hostname", "model", "mac") or key
    return UniFiDevice(
        key=_clean_key(key),
        name=name,
        kind=str(device.get("type") or "device").lower(),
        model=_first_string(device, "model", "model_in_eol", "model_in_lts"),
        mac=mac,
        ip=_first_string(device, "ip", "display_ip", "last_ip"),
        serial=_first_string(device, "serial"),
        firmware=_first_string(device, "version", "firmwareVersion"),
        state=_device_state(device),
        raw=device,
    )


def _normalize_ports(devices: list[UniFiDevice]) -> dict[str, UniFiPort]:
    """Normalize UniFi switch port rows."""
    ports: dict[str, UniFiPort] = {}
    for device in devices:
        if device.kind != "usw":
            continue
        port_table = device.raw.get("port_table")
        if not isinstance(port_table, list):
            continue
        for row in port_table:
            if not isinstance(row, dict):
                continue
            port_idx = _int_value(row.get("port_idx"))
            if port_idx is None:
                port_idx = _int_value(row.get("port"))
            if port_idx is None:
                continue
            key = f"{device.key}_port_{port_idx}"
            ports[key] = UniFiPort(
                key=key,
                device_key=device.key,
                port_idx=port_idx,
                name=_port_name(row, port_idx),
                enabled=_bool_value(row.get("enabled")),
                up=_bool_value(row.get("up")),
                is_uplink=row.get("is_uplink") is True,
                speed_mbps=_int_value(row.get("speed")),
                poe_enabled=_poe_enabled(row),
                raw=row,
            )
    return ports


def _normalize_wlan(wlan: dict[str, Any]) -> UniFiWlan | None:
    """Normalize a WLAN row."""
    key = _first_string(wlan, "_id", "id")
    name = _first_string(wlan, "name", "ssid")
    if key is None or name is None:
        return None
    enabled = wlan.get("enabled")
    return UniFiWlan(
        key=key,
        name=name,
        enabled=enabled if isinstance(enabled, bool) else None,
        security=_first_string(wlan, "security"),
        band=_first_string(wlan, "wlan_band"),
        is_guest=wlan.get("is_guest") if isinstance(wlan.get("is_guest"), bool) else None,
        raw=wlan,
    )


def _router_device_key(devices: dict[str, UniFiDevice]) -> str | None:
    """Return the preferred router/gateway device key for WLAN controls."""
    for device in devices.values():
        if device.kind in {"udm", "ugw"}:
            return device.key
    return next(iter(devices), None)


def _port_name(port: dict[str, Any], port_idx: int) -> str:
    """Return a readable UniFi port label."""
    for key in ("name", "ifname", "label"):
        value = port.get(key)
        if value not in (None, ""):
            return str(value)
    return f"Port {port_idx}"


def _poe_enabled(port: dict[str, Any]) -> bool | None:
    """Return whether PoE is enabled when the controller exposes it."""
    for key in ("port_poe", "poe_enable", "poe_enabled"):
        value = _bool_value(port.get(key))
        if value is not None:
            return value
    return None


def _bool_value(value: Any) -> bool | None:
    """Return a boolean if the value is explicitly boolean-like."""
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


def _int_value(value: Any) -> int | None:
    """Return an integer from simple numeric values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _device_state(device: dict[str, Any]) -> str | None:
    """Return a readable device state."""
    state = _first_string(device, "state")
    if state is not None:
        return state
    if device.get("disabled"):
        return "disabled"
    if device.get("upgradable"):
        return "update_available"
    if device.get("adopted") is False:
        return "not_adopted"
    if device.get("connected") is False:
        return "offline"
    if device.get("online") is True or device.get("connected") is True:
        return "online"
    return None


def _first_string(device: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-empty string value."""
    for key in keys:
        value = device.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _clean_key(value: str) -> str:
    """Return a stable key safe for unique IDs."""
    return value.lower().replace(":", "").replace(" ", "_")
