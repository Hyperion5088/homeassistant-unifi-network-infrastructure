"""Coordinator for UniFi Network Infrastructure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UniFiInfrastructureClient, UniFiInfrastructureError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)
AUTO_PROTECT_SECONDS = 15 * 60
PORT_DEVICE_KINDS = {"usw", "udm", "ugw"}
DOMAIN_LABEL_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
DOMAIN_NAME_RE = re.compile(
    rf"\b(?P<host>{DOMAIN_LABEL_PATTERN})(?:\.{DOMAIN_LABEL_PATTERN})*\.[A-Za-z]{{2,}}\b\.?"
)


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
    protection_reasons: tuple[str, ...]
    speed_mbps: int | None
    poe_enabled: bool | None
    raw: dict[str, Any]


@dataclass(slots=True)
class UniFiInfrastructureData:
    """Coordinator data."""

    devices: dict[str, UniFiDevice]
    ports: dict[str, UniFiPort]
    wans: dict[str, "UniFiWan"]
    wlans: dict[str, "UniFiWlan"]
    port_forwards: dict[str, "UniFiPortForward"]
    traffic_routes: dict[str, "UniFiTrafficRoute"]
    router_device_key: str | None


@dataclass(slots=True)
class UniFiWan:
    """Normalized UniFi router WAN/internet uplink."""

    key: str
    device_key: str
    name: str
    ip: str
    ifname: str | None
    port_idx: int | None
    status: str | None
    alive: bool | None
    raw: dict[str, Any]


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


@dataclass(slots=True)
class UniFiPortForward:
    """Normalized UniFi port-forward rule."""

    key: str
    name: str
    enabled: bool | None
    protocol: str | None
    source: str | None
    destination: str | None
    destination_port: str | None
    forward_ip: str | None
    forward_port: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class UniFiTrafficRoute:
    """Normalized UniFi policy-based traffic route."""

    key: str
    name: str
    enabled: bool | None
    matching_target: str | None
    network_id: str | None
    next_hop: str | None
    kill_switch_enabled: bool | None
    domain_count: int
    ip_address_count: int
    ip_range_count: int
    region_count: int
    target_device_count: int
    raw: dict[str, Any]


class UniFiInfrastructureCoordinator(DataUpdateCoordinator[UniFiInfrastructureData]):
    """Fetch UniFi infrastructure device data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: UniFiInfrastructureClient,
        scan_interval: int,
        storage_key: str | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval) if scan_interval > 0 else DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self._manually_locked_ports: set[str] = set()
        self._temporarily_unlocked_ports: set[str] = set()
        self._auto_protect_timers: dict[str, Callable[[], None]] = {}
        self._store: Store[dict[str, Any]] | None = (
            Store(hass, 1, f"{DOMAIN}.{storage_key}") if storage_key else None
        )

    async def async_load_state(self) -> None:
        """Load persisted local control state."""
        if self._store is None:
            return
        stored = await self._store.async_load()
        if not stored:
            return
        self._manually_locked_ports = {
            str(port_key)
            for port_key in stored.get("manually_locked_ports", [])
            if port_key not in (None, "")
        }

    def _schedule_save_state(self) -> None:
        """Persist local control state without blocking entity updates."""
        if self._store is not None:
            self.hass.create_task(self._async_save_state())

    async def _async_save_state(self) -> None:
        """Persist local control state."""
        if self._store is None:
            return
        await self._store.async_save(
            {
                "manually_locked_ports": sorted(self._manually_locked_ports),
            }
        )

    async def _async_update_data(self) -> UniFiInfrastructureData:
        """Fetch data from UniFi Network."""
        try:
            devices = await self.client.async_get_devices()
            wlans = await self.client.async_get_wlans()
            port_forwards = await self.client.async_get_port_forwards()
            traffic_routes = await self.client.async_get_traffic_routes()
        except UniFiInfrastructureError as err:
            raise UpdateFailed(str(err)) from err
        normalized = [_normalize_device(device) for device in devices]
        normalized_wlans: list[UniFiWlan] = []
        for wlan in wlans:
            if (normalized_wlan := _normalize_wlan(wlan)) is not None:
                normalized_wlans.append(normalized_wlan)
        normalized_port_forwards: list[UniFiPortForward] = []
        for rule in port_forwards:
            if (normalized_rule := _normalize_port_forward(rule)) is not None:
                normalized_port_forwards.append(normalized_rule)
        normalized_traffic_routes: list[UniFiTrafficRoute] = []
        for route in traffic_routes:
            if (normalized_route := _normalize_traffic_route(route)) is not None:
                normalized_traffic_routes.append(normalized_route)
        device_map = {device.key: device for device in normalized}
        return UniFiInfrastructureData(
            devices=device_map,
            ports=_normalize_ports(normalized),
            wans=_normalize_wans(normalized),
            wlans={wlan.key: wlan for wlan in normalized_wlans},
            port_forwards={rule.key: rule for rule in normalized_port_forwards},
            traffic_routes={route.key: route for route in normalized_traffic_routes},
            router_device_key=_router_device_key(device_map),
        )

    async def async_set_wlan_enabled(self, wlan_id: str, enabled: bool) -> None:
        """Enable or disable a WLAN/SSID and refresh data."""
        await self.client.async_set_wlan_enabled(wlan_id, enabled)
        await self.async_request_refresh()

    async def async_set_port_forward_enabled(self, rule_id: str, enabled: bool) -> None:
        """Enable or disable a port-forward rule and refresh data."""
        rule = self.data.port_forwards.get(rule_id) if self.data is not None else None
        if rule is None:
            raise UniFiInfrastructureError("Port-forward rule is no longer available")
        await self.client.async_set_port_forward_enabled(rule.raw, enabled)
        await self.async_request_refresh()

    async def async_set_traffic_route_enabled(self, route_id: str, enabled: bool) -> None:
        """Enable or disable a policy-based traffic route and refresh data."""
        route = self.data.traffic_routes.get(route_id) if self.data is not None else None
        if route is None:
            raise UniFiInfrastructureError("Traffic route is no longer available")
        await self.client.async_set_traffic_route_enabled(route.raw, enabled)
        await self.async_request_refresh()

    def is_port_locked(self, port_key: str) -> bool:
        """Return whether port configuration controls are protected."""
        return port_key in self._manually_locked_ports or (
            self.is_port_auto_protected(port_key) and port_key not in self._temporarily_unlocked_ports
        )

    def is_port_auto_protected(self, port_key: str) -> bool:
        """Return whether UniFi marks the port as infrastructure-facing."""
        port = self.data.ports.get(port_key) if self.data is not None else None
        return bool(port.protection_reasons) if port is not None else False

    def port_protection_reason(self, port_key: str) -> str | None:
        """Return why a port is auto-protected."""
        port = self.data.ports.get(port_key) if self.data is not None else None
        if port is None or not port.protection_reasons:
            return None
        return " | ".join(port.protection_reasons)

    def is_port_temporarily_unlocked(self, port_key: str) -> bool:
        """Return whether an auto-protected port is temporarily unlocked."""
        return port_key in self._temporarily_unlocked_ports

    def is_port_manually_locked(self, port_key: str) -> bool:
        """Return whether the user manually locked a non-infrastructure port."""
        return port_key in self._manually_locked_ports

    def lock_port(self, port_key: str) -> None:
        """Protect a port immediately."""
        self._temporarily_unlocked_ports.discard(port_key)
        if not self.is_port_auto_protected(port_key):
            self._manually_locked_ports.add(port_key)
        self._cancel_auto_protect(port_key)
        self._schedule_save_state()
        self.async_update_listeners()

    def unlock_port(self, port_key: str) -> None:
        """Temporarily allow configuration changes on an auto-protected port."""
        self._manually_locked_ports.discard(port_key)
        if self.is_port_auto_protected(port_key):
            self._temporarily_unlocked_ports.add(port_key)
            self._schedule_auto_protect(port_key)
        self._schedule_save_state()
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
    name = _shorten_domain_names(
        _first_string(device, "name", "display_name", "hostname", "model", "mac") or key
    )
    kind = str(device.get("type") or "device").lower()
    return UniFiDevice(
        key=_clean_key(key),
        name=name,
        kind=kind,
        model=_first_string(device, "model", "model_in_eol", "model_in_lts"),
        mac=mac,
        ip=_management_ip(device, kind),
        serial=_first_string(device, "serial"),
        firmware=_first_string(device, "version", "firmwareVersion"),
        state=_device_state(device),
        raw=device,
    )


def _management_ip(device: dict[str, Any], kind: str) -> str | None:
    """Return the internal/controller-facing management IP."""
    if kind in {"udm", "ugw"}:
        return _first_string(device, "lan_ip", "display_ip", "last_ip", "ip")
    return _first_string(device, "ip", "display_ip", "last_ip")


def _normalize_ports(devices: list[UniFiDevice]) -> dict[str, UniFiPort]:
    """Normalize UniFi switch port rows."""
    ports: dict[str, UniFiPort] = {}
    protection_reasons = _port_protection_reasons(devices)
    for device in devices:
        if device.kind not in PORT_DEVICE_KINDS:
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
                protection_reasons=tuple(protection_reasons.get(key, ())),
                speed_mbps=_int_value(row.get("speed")),
                poe_enabled=_poe_enabled(row),
                raw=row,
            )
    return ports


def _normalize_wans(devices: list[UniFiDevice]) -> dict[str, UniFiWan]:
    """Normalize WAN/internet uplinks for UniFi gateways."""
    wans: dict[str, UniFiWan] = {}
    for device in devices:
        if device.kind not in {"udm", "ugw"}:
            continue
        status_by_name = _wan_status_by_name(device.raw)
        alive_by_name = _wan_alive_by_name(device.raw)
        for source_key, row in sorted(device.raw.items()):
            if not source_key.startswith("wan") or not source_key[3:].isdigit() or not isinstance(row, dict):
                continue
            ip = _first_string(row, "ip")
            if ip is None:
                continue
            wan_number = int(source_key[3:])
            name = f"WAN {wan_number}"
            status_key = "WAN" if wan_number == 1 else f"WAN{wan_number}"
            key = f"{device.key}_wan_{wan_number}"
            wans[key] = UniFiWan(
                key=key,
                device_key=device.key,
                name=name,
                ip=ip,
                ifname=_first_string(row, "ifname", "name", "uplink_ifname"),
                port_idx=_int_value(row.get("port_idx")),
                status=status_by_name.get(status_key),
                alive=alive_by_name.get(status_key),
                raw=row,
            )
    return wans


def _port_protection_reasons(devices: list[UniFiDevice]) -> dict[str, list[str]]:
    """Return auto-protection reasons keyed by local switch port."""
    devices_by_mac = {
        device.mac.lower(): device
        for device in devices
        if device.mac is not None
    }
    reasons: dict[str, list[str]] = {}
    for device in devices:
        if device.kind in PORT_DEVICE_KINDS:
            for port_idx, wan_name in _router_wan_ports(device).items():
                _add_protection_reason(
                    reasons,
                    f"{device.key}_port_{port_idx}",
                    f"Internet uplink {wan_name}",
                )
            for port_idx, neighbor in _lldp_port_neighbors(device).items():
                _add_protection_reason(
                    reasons,
                    f"{device.key}_port_{port_idx}",
                    f"LLDP neighbor {neighbor}",
                )
            port_table = device.raw.get("port_table")
            if isinstance(port_table, list):
                for row in port_table:
                    if not isinstance(row, dict) or row.get("is_uplink") is not True:
                        continue
                    port_idx = _int_value(row.get("port_idx"))
                    if port_idx is None:
                        port_idx = _int_value(row.get("port"))
                    if port_idx is not None:
                        _add_protection_reason(
                            reasons,
                            f"{device.key}_port_{port_idx}",
                            "UniFi marks this port as the switch uplink",
                        )

        uplink = device.raw.get("uplink")
        if not isinstance(uplink, dict):
            continue
        parent_mac = _mac_value(uplink.get("uplink_mac"))
        parent_port = _int_value(uplink.get("uplink_remote_port"))
        if parent_mac is None or parent_port is None:
            continue
        parent = devices_by_mac.get(parent_mac)
        if parent is None or parent.kind not in PORT_DEVICE_KINDS:
            continue
        _add_protection_reason(
            reasons,
            f"{parent.key}_port_{parent_port}",
            f"Feeds {device.name}",
        )
    return reasons


def _router_wan_ports(device: UniFiDevice) -> dict[int, str]:
    """Return router WAN port indexes keyed by physical port index."""
    if device.kind not in {"udm", "ugw"}:
        return {}
    wan_ports: dict[int, str] = {}
    wan_ifnames: dict[str, str] = {}
    for source_key, row in sorted(device.raw.items()):
        if not source_key.startswith("wan") or not source_key[3:].isdigit() or not isinstance(row, dict):
            continue
        wan_number = int(source_key[3:])
        name = f"WAN {wan_number}"
        port_idx = _int_value(row.get("port_idx"))
        if port_idx is not None:
            wan_ports[port_idx] = name
        for key in ("ifname", "name", "uplink_ifname"):
            if (ifname := row.get(key)) not in (None, ""):
                wan_ifnames[str(ifname)] = name

    port_table = device.raw.get("port_table")
    if isinstance(port_table, list) and wan_ifnames:
        for row in port_table:
            if not isinstance(row, dict):
                continue
            port_idx = _int_value(row.get("port_idx"))
            if port_idx is None:
                continue
            ifname = row.get("ifname")
            if ifname in wan_ifnames:
                wan_ports[port_idx] = wan_ifnames[str(ifname)]
    return wan_ports


def _lldp_port_neighbors(device: UniFiDevice) -> dict[int, str]:
    """Return LLDP neighbors keyed by local port index."""
    lldp_table = device.raw.get("lldp_table")
    if not isinstance(lldp_table, list):
        return {}

    neighbors: dict[int, str] = {}
    for row in lldp_table:
        if not isinstance(row, dict):
            continue
        port_idx = _int_value(row.get("local_port_idx"))
        if port_idx is None:
            continue
        if row.get("is_wired") is False:
            continue
        label = _first_string(
            row,
            "system_name",
            "hostname",
            "device_name",
            "chassis_name",
            "port_id",
            "chassis_id",
            "local_port_name",
        )
        if label is None:
            label = f"on port {port_idx}"
        neighbors[port_idx] = label
    return neighbors


def _add_protection_reason(reasons: dict[str, list[str]], port_key: str, reason: str) -> None:
    """Add a protection reason once."""
    port_reasons = reasons.setdefault(port_key, [])
    if reason not in port_reasons:
        port_reasons.append(reason)


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


def _normalize_port_forward(rule: dict[str, Any]) -> UniFiPortForward | None:
    """Normalize a UniFi port-forward rule."""
    key = _first_string(rule, "_id", "id")
    if key is None:
        return None
    name = _first_string(rule, "name", "description", "dst_port", "fwd_port") or key
    enabled = rule.get("enabled")
    return UniFiPortForward(
        key=key,
        name=name,
        enabled=enabled if isinstance(enabled, bool) else None,
        protocol=_first_string(rule, "proto", "protocol"),
        source=_first_string(rule, "src", "src_ip", "src_address"),
        destination=_first_string(rule, "dst", "dst_ip", "dst_address"),
        destination_port=_first_string(rule, "dst_port", "dst_ports", "dst_port_start"),
        forward_ip=_first_string(rule, "fwd", "fwd_ip", "forward_ip"),
        forward_port=_first_string(rule, "fwd_port", "forward_port"),
        raw=rule,
    )


def _normalize_traffic_route(route: dict[str, Any]) -> UniFiTrafficRoute | None:
    """Normalize a UniFi policy-based traffic route."""
    key = _first_string(route, "_id", "id")
    if key is None:
        return None
    name = _first_string(route, "description", "name") or key
    enabled = route.get("enabled")
    kill_switch_enabled = route.get("kill_switch_enabled")
    return UniFiTrafficRoute(
        key=key,
        name=name,
        enabled=enabled if isinstance(enabled, bool) else None,
        matching_target=_first_string(route, "matching_target"),
        network_id=_first_string(route, "network_id"),
        next_hop=_first_string(route, "next_hop"),
        kill_switch_enabled=kill_switch_enabled if isinstance(kill_switch_enabled, bool) else None,
        domain_count=_list_count(route.get("domains")),
        ip_address_count=_list_count(route.get("ip_addresses")),
        ip_range_count=_list_count(route.get("ip_ranges")),
        region_count=_list_count(route.get("regions")),
        target_device_count=_list_count(route.get("target_devices")),
        raw=route,
    )


def _router_device_key(devices: dict[str, UniFiDevice]) -> str | None:
    """Return the preferred router/gateway device key for WLAN controls."""
    for device in devices.values():
        if device.kind in {"udm", "ugw"}:
            return device.key
    return next(iter(devices), None)


def _wan_status_by_name(device: dict[str, Any]) -> dict[str, str]:
    """Return WAN status values from the controller payload."""
    status = device.get("last_wan_status")
    if not isinstance(status, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in status.items()
        if value not in (None, "")
    }


def _wan_alive_by_name(device: dict[str, Any]) -> dict[str, bool]:
    """Return WAN alive values from the controller payload."""
    interfaces = device.get("last_wan_interfaces")
    if not isinstance(interfaces, dict):
        return {}
    alive: dict[str, bool] = {}
    for key, value in interfaces.items():
        if not isinstance(value, dict):
            continue
        is_alive = _bool_value(value.get("alive"))
        if is_alive is not None:
            alive[str(key)] = is_alive
    return alive


def _port_name(port: dict[str, Any], port_idx: int) -> str:
    """Return a readable UniFi port label."""
    for key in ("name", "ifname", "label"):
        value = port.get(key)
        if value not in (None, ""):
            return str(value)
    return f"Port {port_idx}"


def _poe_enabled(port: dict[str, Any]) -> bool | None:
    """Return whether PoE is enabled when the controller exposes it."""
    for key in ("poe_enable", "poe_enabled"):
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


def _list_count(value: Any) -> int:
    """Return the length of a list-like API field."""
    return len(value) if isinstance(value, list) else 0


def _mac_value(value: Any) -> str | None:
    """Return a normalized MAC address string."""
    if value in (None, ""):
        return None
    return str(value).strip().lower()


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


def _shorten_domain_names(value: str) -> str:
    """Remove DNS suffixes from display names."""
    shortened = DOMAIN_NAME_RE.sub(lambda match: match.group("host"), value)
    return " ".join(shortened.split()) or value


def _clean_key(value: str) -> str:
    """Return a stable key safe for unique IDs."""
    return value.lower().replace(":", "").replace(" ", "_")
