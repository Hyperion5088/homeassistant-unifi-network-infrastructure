"""UniFi Infrastructure integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.event import async_call_later
from homeassistant.util import slugify

from .api import UniFiInfrastructureClient
from .const import (
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

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.LOCK]
DEFAULT_DISABLED_MIGRATION_OPTION = "_default_disabled_entities_migrated"

DIAGNOSTIC_SENSOR_SUFFIXES = frozenset(
    {
        "cpu_usage",
        "memory_usage",
        "uptime",
        "last_seen",
        "load_average_1_min",
        "load_average_5_min",
        "load_average_15_min",
        "rx_bytes",
        "tx_bytes",
        "total_bytes",
    }
)
DEFAULT_DISABLED_SENSOR_SUFFIXES = frozenset(
    {
        "state",
        "last_seen",
        "load_average_1_min",
        "load_average_5_min",
        "load_average_15_min",
        "radio_count",
        "vap_count",
        "radio_summary",
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up UniFi Infrastructure from a config entry."""
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
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    should_disable_existing_defaults = not entry.options.get(DEFAULT_DISABLED_MIGRATION_OPTION, False)
    _async_migrate_entity_ids(
        hass,
        entry,
        coordinator,
        disable_existing_default_entities=should_disable_existing_defaults,
    )
    if should_disable_existing_defaults:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, DEFAULT_DISABLED_MIGRATION_OPTION: True},
        )
    entry.async_on_unload(
        async_call_later(hass, 10, lambda _: _async_migrate_entity_ids(hass, entry, coordinator))
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a UniFi Infrastructure config entry."""
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


def _async_migrate_entity_ids(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: UniFiInfrastructureCoordinator,
    *,
    disable_existing_default_entities: bool = False,
) -> None:
    """Give early development entities stable descriptive names."""
    registry = er.async_get(hass)
    names_by_suffix = {
        "state": "State",
        "ip_address": "IP Address",
        "mac_address": "MAC Address",
        "serial_number": "Serial Number",
        "model": "Model",
        "cpu_usage": "CPU Usage",
        "memory_usage": "Memory Usage",
        "temperature": "Temperature",
        "fan_level": "Fan Level",
        "fan_summary": "Fan Summary",
        "uptime": "Uptime",
        "last_seen": "Last Seen",
        "load_average_1_min": "System Load 1 min",
        "load_average_5_min": "System Load 5 min",
        "load_average_15_min": "System Load 15 min",
        "firmware": "Firmware",
        "update_status": "Update Status",
        "port_count": "Port Count",
        "radio_count": "Radio Count",
        "vap_count": "VAP Count",
        "connected_clients": "Connected Clients",
        "rx_bytes": "Received Traffic",
        "tx_bytes": "Transmitted Traffic",
        "total_bytes": "Total Traffic",
        "uplink": "Uplink",
        "radio_summary": "Radio Details",
    }
    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id or entity.platform != DOMAIN:
            continue
        if entity.entity_id.startswith("lock."):
            _async_migrate_lock_entity_id(registry, entity, coordinator)
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
        desired_entity_id = f"sensor.{slugify(device.name)}_{suffix}"
        updates: dict[str, object | None] = {
            "original_name": names_by_suffix[suffix],
            "entity_category": EntityCategory.DIAGNOSTIC if suffix in DIAGNOSTIC_SENSOR_SUFFIXES else None,
        }
        if (
            disable_existing_default_entities
            and suffix in DEFAULT_DISABLED_SENSOR_SUFFIXES
            and entity.disabled_by is None
        ):
            updates["disabled_by"] = er.RegistryEntryDisabler.INTEGRATION
        if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
            updates["new_entity_id"] = desired_entity_id
        registry.async_update_entity(entity.entity_id, **updates)


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
        "entity_category": EntityCategory.CONFIG,
    }
    if device is not None:
        desired_entity_id = f"lock.{slugify(device.name)}_protection_{slugify(port.name)}"
        if entity.entity_id != desired_entity_id and registry.async_get(desired_entity_id) is None:
            updates["new_entity_id"] = desired_entity_id
    registry.async_update_entity(entity.entity_id, **updates)
