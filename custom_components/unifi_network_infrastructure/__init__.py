"""UniFi Network Infrastructure integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_call_later
from homeassistant.util import slugify

from .api import UniFiInfrastructureClient
from .const import (
    CONF_ENABLE_FIREWALL_POLICY_CONTROLS,
    CONF_ENABLE_GUEST_WIFI_CONTROLS,
    CONF_ENABLE_INTERFACE_CONTROLS,
    CONF_ENABLE_LOCATE_CONTROL,
    CONF_ENABLE_POE_CONTROLS,
    CONF_ENABLE_POE_RESET,
    CONF_ENABLE_PORT_ADMIN_CONTROLS,
    CONF_ENABLE_PORT_BOUNCE,
    CONF_ENABLE_PORT_FORWARD_CONTROLS,
    CONF_ENABLE_PORT_PROTECTION,
    CONF_ENABLE_REBOOT_CONTROL,
    CONF_ENABLE_ROUTE_POLICY_CONTROLS,
    CONF_ENABLE_WIFI_CONTROLS,
    CONF_SCAN_INTERVAL,
    CONF_SITE,
    CONF_VERIFY_SSL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_SITE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .coordinator import UniFiInfrastructureCoordinator
from .options import option_enabled, port_protection_enabled

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.LOCK, Platform.BUTTON, Platform.SELECT]
DEFAULT_DISABLED_MIGRATION_OPTION = "_default_disabled_entities_migrated"
PORT_COUNT_DISABLED_MIGRATION_OPTION = "_port_count_default_disabled_migrated"
POLICY_SWITCH_DISABLED_MIGRATION_OPTION = "_policy_switch_default_disabled_migrated"

DIAGNOSTIC_SENSOR_SUFFIXES = frozenset(
    {
        "cpu_usage",
        "memory_usage",
        "uptime",
        "last_seen",
        "load_average_1_min",
        "load_average_5_min",
        "load_average_15_min",
        "mac_address",
        "model",
        "serial_number",
        "rx_bytes",
        "temperature",
        "tx_bytes",
        "total_bytes",
        "firmware",
        "update_status",
        "uplink",
    }
)
DEFAULT_DISABLED_SENSOR_SUFFIXES = frozenset(
    {
        "state",
        "last_seen",
        "load_average_1_min",
        "load_average_5_min",
        "load_average_15_min",
        "port_count",
        "radio_count",
        "vap_count",
        "radio_summary",
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UniFi Network Infrastructure from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    client = UniFiInfrastructureClient(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        site=entry.data.get(CONF_SITE, DEFAULT_SITE),
        verify_ssl=verify_ssl,
        session=session,
    )
    coordinator = UniFiInfrastructureCoordinator(
        hass=hass,
        client=client,
        scan_interval=entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
        ),
        storage_key=entry.entry_id,
        port_protection_enabled=port_protection_enabled(entry),
    )
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    should_disable_existing_defaults = not entry.options.get(DEFAULT_DISABLED_MIGRATION_OPTION, False)
    should_disable_port_count = not entry.options.get(PORT_COUNT_DISABLED_MIGRATION_OPTION, False)
    should_disable_policy_switches = not entry.options.get(POLICY_SWITCH_DISABLED_MIGRATION_OPTION, False)
    _async_migrate_entity_ids(
        hass,
        entry,
        coordinator,
        disable_existing_default_entities=should_disable_existing_defaults,
        force_default_disabled_suffixes={"port_count"} if should_disable_port_count else None,
        force_default_disabled_policy_switches=should_disable_policy_switches,
    )
    _async_migrate_device_names(hass, coordinator)
    if should_disable_existing_defaults or should_disable_port_count or should_disable_policy_switches:
        hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                DEFAULT_DISABLED_MIGRATION_OPTION: True,
                PORT_COUNT_DISABLED_MIGRATION_OPTION: True,
                POLICY_SWITCH_DISABLED_MIGRATION_OPTION: True,
            },
        )
    entry.async_on_unload(
        async_call_later(hass, 10, lambda _: _async_migrate_registries(hass, entry, coordinator))
    )
    entry.async_on_unload(
        coordinator.async_add_listener(lambda: _async_migrate_registries(hass, entry, coordinator))
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a UniFi Network Infrastructure config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.cancel_auto_protect_timers()
            await coordinator.client.async_logout()
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_migrate_registries(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> None:
    """Refresh entity and device registry metadata after startup."""
    _async_migrate_entity_ids(hass, entry, coordinator)
    _async_migrate_device_names(hass, coordinator)


def _async_migrate_entity_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: UniFiInfrastructureCoordinator,
    *,
    disable_existing_default_entities: bool = False,
    force_default_disabled_suffixes: set[str] | None = None,
    force_default_disabled_policy_switches: bool = False,
) -> None:
    """Give early development entities stable descriptive names."""
    registry = er.async_get(hass)
    names_by_suffix = {
        "state": "System State",
        "ip_address": "IP LAN",
        "mac_address": "System MAC Address",
        "serial_number": "System Serial Number",
        "model": "System Model",
        "cpu_usage": "System CPU Usage",
        "memory_usage": "System Memory Usage",
        "temperature": "System Temperature",
        "fan_level": "System Fan Level",
        "fan_summary": "System Fan Summary",
        "uptime": "System Uptime",
        "last_seen": "System Last Seen",
        "load_average_1_min": "System Load 1 min",
        "load_average_5_min": "System Load 5 min",
        "load_average_15_min": "System Load 15 min",
        "firmware": "System Firmware",
        "update_status": "System Update Status",
        "port_count": "Port Count",
        "radio_count": "Radio Count",
        "vap_count": "VAP Count",
        "connected_clients": "Connected Clients",
        "rx_bytes": "Traffic Received",
        "tx_bytes": "Traffic Transmitted",
        "total_bytes": "Traffic Total",
        "uplink": "System Uplink",
        "radio_summary": "Radio Details",
    }
    entity_id_suffixes = {
        "state": "system_state",
        "ip_address": "ip_lan",
        "mac_address": "system_mac_address",
        "model": "system_model",
        "serial_number": "system_serial_number",
        "cpu_usage": "system_cpu_usage",
        "memory_usage": "system_memory_usage",
        "temperature": "system_temperature",
        "fan_level": "system_fan_level",
        "fan_summary": "system_fan_summary",
        "uptime": "system_uptime",
        "last_seen": "system_last_seen",
        "load_average_1_min": "system_load_1_min",
        "load_average_5_min": "system_load_5_min",
        "load_average_15_min": "system_load_15_min",
        "firmware": "system_firmware",
        "update_status": "system_update_status",
        "rx_bytes": "traffic_received",
        "tx_bytes": "traffic_transmitted",
        "total_bytes": "traffic_total",
        "uplink": "system_uplink",
    }
    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id or entity.platform != DOMAIN:
            continue
        if _async_remove_disabled_option_entity(registry, entity, entry, coordinator):
            continue
        if entity.entity_id.startswith("lock."):
            _async_migrate_lock_entity_id(registry, entity, coordinator)
            continue
        if entity.entity_id.startswith("switch."):
            if _async_remove_guest_network_switch_entity(registry, entity):
                continue
            if _async_migrate_port_forward_switch_entity_id(
                registry,
                entity,
                coordinator,
                force_default_disabled=force_default_disabled_policy_switches,
            ):
                continue
            if _async_migrate_traffic_route_switch_entity_id(
                registry,
                entity,
                coordinator,
                force_default_disabled=force_default_disabled_policy_switches,
            ):
                continue
            if _async_migrate_firewall_policy_switch_entity(
                registry,
                entity,
                force_default_disabled=force_default_disabled_policy_switches,
            ):
                continue
            _async_migrate_wlan_switch_entity_id(registry, entity, coordinator)
            continue
        if entity.entity_id.startswith("button."):
            _async_migrate_device_button_entity_id(registry, entity, coordinator)
            continue
        if _async_migrate_wan_sensor_entity_id(registry, entity, coordinator):
            continue
        if _async_migrate_port_speed_sensor_entity_id(registry, entity, coordinator):
            continue
        unique_id = str(entity.unique_id or "")
        device_key = ""
        suffix = ""
        for candidate in names_by_suffix:
            marker = f"_{candidate}"
            if unique_id.endswith(marker):
                device_key = unique_id[: -len(marker)]
                suffix = candidate
                break
        if not device_key or not suffix:
            continue
        device = coordinator.data.devices.get(device_key)
        if device is None:
            continue
        desired_suffix = entity_id_suffixes.get(suffix, suffix)
        desired_entity_id = f"sensor.{slugify(device.name)}_{desired_suffix}"
        updates: dict[str, object | None] = {
            "original_name": names_by_suffix[suffix],
            "entity_category": (
                EntityCategory.DIAGNOSTIC
                if suffix in DIAGNOSTIC_SENSOR_SUFFIXES
                else None
            ),
        }
        if (
            (
                disable_existing_default_entities
                and suffix in DEFAULT_DISABLED_SENSOR_SUFFIXES
            )
            or suffix in (force_default_disabled_suffixes or set())
        ) and entity.disabled_by is None:
            updates["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
        if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
            updates["new_entity_id"] = desired_entity_id
        registry.async_update_entity(entity.entity_id, **updates)


def _async_remove_disabled_option_entity(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    entry: ConfigEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> bool:
    """Remove entities for control families disabled in options."""
    unique_id = str(entity.unique_id or "")
    remove = False
    if unique_id.startswith("wlan_") and unique_id.endswith("_enabled"):
        wlan_id = unique_id[len("wlan_") : -len("_enabled")]
        wlan = coordinator.data.wlans.get(wlan_id)
        remove = (
            wlan is not None
            and (
                not option_enabled(entry, CONF_ENABLE_GUEST_WIFI_CONTROLS)
                if wlan.is_guest is True
                else not option_enabled(entry, CONF_ENABLE_WIFI_CONTROLS)
            )
        )
    elif unique_id.startswith("port_forward_") and unique_id.endswith("_enabled"):
        remove = not option_enabled(entry, CONF_ENABLE_PORT_FORWARD_CONTROLS)
    elif unique_id.startswith("traffic_route_") and unique_id.endswith("_enabled"):
        remove = not option_enabled(entry, CONF_ENABLE_ROUTE_POLICY_CONTROLS)
    elif unique_id.startswith("firewall_policy_") and unique_id.endswith("_enabled"):
        remove = not option_enabled(entry, CONF_ENABLE_FIREWALL_POLICY_CONTROLS)
    elif unique_id.endswith("_config_protection"):
        remove = not option_enabled(entry, CONF_ENABLE_PORT_PROTECTION)
    elif unique_id.endswith("_admin_enabled"):
        remove = not (
            option_enabled(entry, CONF_ENABLE_INTERFACE_CONTROLS)
            and option_enabled(entry, CONF_ENABLE_PORT_ADMIN_CONTROLS)
        )
    elif unique_id.endswith("_poe_enabled"):
        remove = not (
            option_enabled(entry, CONF_ENABLE_INTERFACE_CONTROLS)
            and option_enabled(entry, CONF_ENABLE_POE_CONTROLS)
        )
    elif unique_id.endswith("_bounce"):
        remove = not (
            option_enabled(entry, CONF_ENABLE_INTERFACE_CONTROLS)
            and option_enabled(entry, CONF_ENABLE_PORT_BOUNCE)
        )
    elif unique_id.endswith("_poe_reset"):
        remove = not (
            option_enabled(entry, CONF_ENABLE_INTERFACE_CONTROLS)
            and option_enabled(entry, CONF_ENABLE_POE_RESET)
        )
    elif unique_id.endswith("_locate"):
        remove = not option_enabled(entry, CONF_ENABLE_LOCATE_CONTROL)
    elif unique_id.endswith("_reboot") or unique_id == "unifi_reboot_confirmation":
        remove = not option_enabled(entry, CONF_ENABLE_REBOOT_CONTROL)

    if remove:
        registry.async_remove(entity.entity_id)
    return remove


def _async_migrate_device_button_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> bool:
    """Group device-level buttons under the System prefix."""
    unique_id = str(entity.unique_id or "")
    if not unique_id.endswith("_locate"):
        return False
    device_key = unique_id[: -len("_locate")]
    device = coordinator.data.devices.get(device_key)
    if device is None:
        return False
    desired_entity_id = f"button.{slugify(device.name)}_system_locate"
    updates: dict[str, object | None] = {
        "original_name": "System Locate",
        "entity_category": EntityCategory.DIAGNOSTIC,
    }
    if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
        updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
    return True


def _async_migrate_wan_sensor_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> bool:
    """Shorten WAN IP sensor entity IDs."""
    unique_id = str(entity.unique_id or "")
    suffix = "_ip_address"
    if not unique_id.endswith(suffix):
        return False
    wan_key = unique_id[: -len(suffix)]
    wan = coordinator.data.wans.get(wan_key)
    if wan is None:
        return False
    device = coordinator.data.devices.get(wan.device_key)
    if device is None:
        return False
    desired_name = f"IP {wan.name}"
    desired_entity_id = f"sensor.{slugify(device.name)}_ip_{slugify(wan.name)}"
    updates: dict[str, object | None] = {
        "original_name": desired_name,
        "entity_category": EntityCategory.CONFIG,
    }
    if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
        updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
    return True


def _async_migrate_port_speed_sensor_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> bool:
    """Shorten port speed sensor names now that speed is the state."""
    unique_id = str(entity.unique_id or "")
    suffix = "_speed"
    if not unique_id.endswith(suffix):
        return False
    port_key = unique_id[: -len(suffix)]
    port = coordinator.data.ports.get(port_key)
    if port is None:
        return False
    device = coordinator.data.devices.get(port.device_key)
    if device is None:
        return False
    desired_name = _port_sensor_name(port.name, port.raw)
    desired_entity_id = f"sensor.{slugify(device.name)}_{slugify(desired_name)}"
    updates: dict[str, object | None] = {
        "original_name": desired_name,
        "entity_category": EntityCategory.CONFIG,
    }
    if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
        updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
    return True


def _port_sensor_name(name: str, raw: dict[str, object]) -> str:
    """Return a grouped display name for a port sensor."""
    media = " ".join(
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
    group = "Port"
    for marker, label in (
        ("qsfp28", "QSFP28"),
        ("qsfp+", "QSFP+"),
        ("qsfp", "QSFP"),
        ("sfp28", "SFP28"),
        ("sfp+", "SFP+"),
        ("sfp", "SFP"),
    ):
        if marker in media:
            group = label
            break
    else:
        if any(marker in media for marker in ("fiber", "fibre")):
            group = "SFP"
    label = str(name).strip()
    lowered = label.lower()
    for prefix in ("port ", "qsfp28 ", "qsfp+ ", "qsfp ", "sfp28 ", "sfp+ ", "sfp "):
        if lowered.startswith(prefix):
            label = label[len(prefix) :].strip() or label
            break
    if group == "Port":
        return f"Port {label}"
    return f"Port {group} {label}"


def _async_migrate_wlan_switch_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> None:
    """Shorten WLAN/SSID switch entity IDs."""
    unique_id = str(entity.unique_id or "")
    prefix = "wlan_"
    suffix = "_enabled"
    if not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
        return
    wlan_id = unique_id[len(prefix) : -len(suffix)]
    wlan = coordinator.data.wlans.get(wlan_id)
    router_key = coordinator.data.router_device_key
    router = coordinator.data.devices.get(router_key) if router_key is not None else None
    if wlan is None or router is None:
        return
    desired_name = f"WiFi {wlan.name}"
    desired_entity_id = f"switch.{slugify(router.name)}_wifi_{slugify(wlan.name)}"
    updates: dict[str, object | None] = {"original_name": desired_name}
    if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
        updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)


def _async_remove_guest_network_switch_entity(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
) -> bool:
    """Remove old wired guest-network switch entities."""
    unique_id = str(entity.unique_id or "")
    prefix = "guest_network_"
    suffix = "_enabled"
    if not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
        return False
    registry.async_remove(entity.entity_id)
    return True


def _async_migrate_port_forward_switch_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
    *,
    force_default_disabled: bool = False,
) -> bool:
    """Shorten port-forward switch entity IDs."""
    unique_id = str(entity.unique_id or "")
    prefix = "port_forward_"
    suffix = "_enabled"
    if not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
        return False
    rule_id = unique_id[len(prefix) : -len(suffix)]
    rule = coordinator.data.port_forwards.get(rule_id)
    router_key = coordinator.data.router_device_key
    router = coordinator.data.devices.get(router_key) if router_key is not None else None
    if rule is None or router is None:
        return True
    desired_name = f"Port Forward {rule.name}"
    desired_entity_id = f"switch.{slugify(router.name)}_port_forward_{slugify(rule.name)}"
    updates: dict[str, object | None] = {"original_name": desired_name}
    if force_default_disabled and entity.disabled_by is None:
        updates["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
    if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
        updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
    return True


def _async_migrate_traffic_route_switch_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
    *,
    force_default_disabled: bool = False,
) -> bool:
    """Shorten traffic route policy switch entity IDs."""
    unique_id = str(entity.unique_id or "")
    prefix = "traffic_route_"
    suffix = "_enabled"
    if not unique_id.startswith(prefix) or not unique_id.endswith(suffix):
        return False
    route_id = unique_id[len(prefix) : -len(suffix)]
    route = coordinator.data.traffic_routes.get(route_id)
    router_key = coordinator.data.router_device_key
    router = coordinator.data.devices.get(router_key) if router_key is not None else None
    if route is None or router is None:
        return True
    desired_name = f"Route Policy {route.name}"
    desired_entity_id = f"switch.{slugify(router.name)}_route_policy_{slugify(route.name)}"
    updates: dict[str, object | None] = {"original_name": desired_name}
    if force_default_disabled and entity.disabled_by is None:
        updates["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
    if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
        updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
    return True


def _async_migrate_firewall_policy_switch_entity(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    *,
    force_default_disabled: bool = False,
) -> bool:
    """Disable existing firewall policy switches once to match the default."""
    unique_id = str(entity.unique_id or "")
    if not (
        unique_id.startswith("firewall_policy_")
        and unique_id.endswith("_enabled")
    ):
        return False
    updates: dict[str, object | None] = {"entity_category": EntityCategory.CONFIG}
    if force_default_disabled and entity.disabled_by is None:
        updates["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
    registry.async_update_entity(entity.entity_id, **updates)
    return True


def _async_migrate_device_names(
    hass: HomeAssistant,
    coordinator: UniFiInfrastructureCoordinator,
) -> None:
    """Shorten existing UniFi device registry names."""
    registry = dr.async_get(hass)
    for entry in list(registry.devices.values()):
        if not entry.identifiers:
            continue
        device_key = next(
            (
                identifier
                for domain, identifier in entry.identifiers
                if domain == DOMAIN
            ),
            None,
        )
        if device_key is None:
            continue
        device = coordinator.data.devices.get(device_key)
        if device is None or entry.name == device.name:
            continue
        registry.async_update_device(entry.id, name=device.name)


def _async_migrate_lock_entity_id(
    registry: er.EntityRegistry,
    entity: er.RegistryEntry,
    coordinator: UniFiInfrastructureCoordinator,
) -> None:
    """Shorten early port protection lock names."""
    unique_id = str(entity.unique_id or "")
    suffix = "_config_protection"
    if not unique_id.endswith(suffix):
        return
    port_key = unique_id[: -len(suffix)]
    port = coordinator.data.ports.get(port_key)
    if port is None:
        return
    device = coordinator.data.devices.get(port.device_key)
    desired_name = f"Protection {port.name}"
    updates: dict[str, object | None] = {
        "name": desired_name,
        "original_name": desired_name,
        "icon": None,
        "entity_category": EntityCategory.CONFIG,
    }
    if device is not None:
        desired_entity_id = f"lock.{slugify(device.name)}_protection_{slugify(port.name)}"
        if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
            updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
