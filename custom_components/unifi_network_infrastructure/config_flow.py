"""Config flow for UniFi Network Infrastructure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import selector

from .api import UniFiInfrastructureAuthError, UniFiInfrastructureClient, UniFiInfrastructureError
from .const import (
    CONF_ENABLE_FIREWALL_POLICY_CONTROLS,
    CONF_ENABLE_LOCATE_CONTROL,
    CONF_ENABLE_GUEST_WIFI_CONTROLS,
    CONF_ENABLE_INTERFACE_CONTROLS,
    CONF_ENABLE_POE_CONTROLS,
    CONF_ENABLE_POE_RESET,
    CONF_ENABLE_PORT_FORWARD_CONTROLS,
    CONF_ENABLE_PORT_ADMIN_CONTROLS,
    CONF_ENABLE_PORT_BOUNCE,
    CONF_ENABLE_PORT_PROTECTION,
    CONF_ENABLE_REBOOT_CONTROL,
    CONF_ENABLE_ROUTE_POLICY_CONTROLS,
    CONF_ENABLE_WIFI_CONTROLS,
    CONF_SCAN_INTERVAL,
    CONF_SITE,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_FIREWALL_POLICY_CONTROLS,
    DEFAULT_ENABLE_LOCATE_CONTROL,
    DEFAULT_ENABLE_GUEST_WIFI_CONTROLS,
    DEFAULT_ENABLE_INTERFACE_CONTROLS,
    DEFAULT_ENABLE_POE_CONTROLS,
    DEFAULT_ENABLE_POE_RESET,
    DEFAULT_ENABLE_PORT_FORWARD_CONTROLS,
    DEFAULT_ENABLE_PORT_ADMIN_CONTROLS,
    DEFAULT_ENABLE_PORT_BOUNCE,
    DEFAULT_ENABLE_PORT_PROTECTION,
    DEFAULT_ENABLE_REBOOT_CONTROL,
    DEFAULT_ENABLE_ROUTE_POLICY_CONTROLS,
    DEFAULT_ENABLE_WIFI_CONTROLS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DEFAULT_SITE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)
from .options import CONTROL_OPTION_KEYS, OPTION_DEFAULTS, monitoring_options

SECTION_ROUTER_POLICY_CONTROLS = "router_policy_controls"
SECTION_CONTROLLER_SETTINGS = "controller_settings"
SECTION_MONITORING_SETTINGS = "monitoring_settings"
SECTION_PROTECTION_SETTINGS = "protection_settings"
SECTION_WIFI_CONTROLS = "wifi_controls"
SECTION_INTERFACE_CONTROLS = "port_controls"
SECTION_MAINTENANCE_CONTROLS = "device_maintenance_controls"

FIELD_HOST = CONF_HOST
FIELD_USERNAME = CONF_USERNAME
FIELD_PASSWORD = CONF_PASSWORD
FIELD_NEW_PASSWORD = "new_password"
FIELD_PORT = CONF_PORT
FIELD_VERIFY_SSL = CONF_VERIFY_SSL
FIELD_SCAN_INTERVAL = CONF_SCAN_INTERVAL
FIELD_PORT_PROTECTION = CONF_ENABLE_PORT_PROTECTION
FIELD_WIFI_CONTROLS = CONF_ENABLE_WIFI_CONTROLS
FIELD_GUEST_WIFI_CONTROLS = CONF_ENABLE_GUEST_WIFI_CONTROLS
FIELD_INTERFACE_CONTROLS = CONF_ENABLE_INTERFACE_CONTROLS
FIELD_PORT_ADMIN_CONTROLS = CONF_ENABLE_PORT_ADMIN_CONTROLS
FIELD_PORT_BOUNCE = CONF_ENABLE_PORT_BOUNCE
FIELD_POE_CONTROLS = CONF_ENABLE_POE_CONTROLS
FIELD_POE_RESET = CONF_ENABLE_POE_RESET
FIELD_PORT_FORWARD_CONTROLS = CONF_ENABLE_PORT_FORWARD_CONTROLS
FIELD_ROUTE_POLICY_CONTROLS = CONF_ENABLE_ROUTE_POLICY_CONTROLS
FIELD_FIREWALL_POLICY_CONTROLS = CONF_ENABLE_FIREWALL_POLICY_CONTROLS
FIELD_LOCATE_CONTROL = CONF_ENABLE_LOCATE_CONTROL
FIELD_REBOOT_CONTROL = CONF_ENABLE_REBOOT_CONTROL

ROUTER_POLICY_CONTROL_OPTIONS = (
    CONF_ENABLE_PORT_FORWARD_CONTROLS,
    CONF_ENABLE_ROUTE_POLICY_CONTROLS,
    CONF_ENABLE_FIREWALL_POLICY_CONTROLS,
)
CONNECTION_OPTIONS = (
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_VERIFY_SSL,
)
SECTION_OPTION_KEYS = {
    SECTION_CONTROLLER_SETTINGS: {
        FIELD_HOST: CONF_HOST,
        FIELD_USERNAME: CONF_USERNAME,
        FIELD_PASSWORD: CONF_PASSWORD,
        FIELD_NEW_PASSWORD: CONF_PASSWORD,
        FIELD_PORT: CONF_PORT,
        FIELD_VERIFY_SSL: CONF_VERIFY_SSL,
        FIELD_SCAN_INTERVAL: CONF_SCAN_INTERVAL,
    },
    SECTION_MONITORING_SETTINGS: {FIELD_SCAN_INTERVAL: CONF_SCAN_INTERVAL},
    SECTION_PROTECTION_SETTINGS: {FIELD_PORT_PROTECTION: CONF_ENABLE_PORT_PROTECTION},
    SECTION_WIFI_CONTROLS: {
        FIELD_WIFI_CONTROLS: CONF_ENABLE_WIFI_CONTROLS,
        FIELD_GUEST_WIFI_CONTROLS: CONF_ENABLE_GUEST_WIFI_CONTROLS,
    },
    SECTION_ROUTER_POLICY_CONTROLS: {
        FIELD_PORT_FORWARD_CONTROLS: CONF_ENABLE_PORT_FORWARD_CONTROLS,
        FIELD_ROUTE_POLICY_CONTROLS: CONF_ENABLE_ROUTE_POLICY_CONTROLS,
        FIELD_FIREWALL_POLICY_CONTROLS: CONF_ENABLE_FIREWALL_POLICY_CONTROLS,
    },
    SECTION_INTERFACE_CONTROLS: {
        FIELD_INTERFACE_CONTROLS: CONF_ENABLE_INTERFACE_CONTROLS,
        FIELD_PORT_ADMIN_CONTROLS: CONF_ENABLE_PORT_ADMIN_CONTROLS,
        FIELD_PORT_BOUNCE: CONF_ENABLE_PORT_BOUNCE,
        FIELD_POE_CONTROLS: CONF_ENABLE_POE_CONTROLS,
        FIELD_POE_RESET: CONF_ENABLE_POE_RESET,
    },
    SECTION_MAINTENANCE_CONTROLS: {
        FIELD_LOCATE_CONTROL: CONF_ENABLE_LOCATE_CONTROL,
        FIELD_REBOOT_CONTROL: CONF_ENABLE_REBOOT_CONTROL,
    },
}


def _setup_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return setup schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(SECTION_CONTROLLER_SETTINGS): section(
                vol.Schema(
                    {
                        vol.Required(FIELD_HOST, default=defaults.get(CONF_HOST, "")): str,
                        vol.Required(FIELD_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                        vol.Required(FIELD_PASSWORD): str,
                        vol.Optional(FIELD_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
                        vol.Optional(
                            FIELD_VERIFY_SSL,
                            default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                        ): bool,
                    }
                ),
                {"collapsed": False},
            ),
        }
    )


def _boolean_field(*, read_only: bool = False):
    """Return a Home Assistant boolean field, optionally read-only."""
    if read_only:
        return selector({"boolean": {"read_only": True}})
    return bool


def _control_default(defaults: dict[str, Any], key: str, fallback: bool, *, can_control: bool) -> bool:
    """Return a visible option default, forcing write controls off for read-only accounts."""
    if not can_control:
        return False
    return bool(defaults.get(key, fallback))


def _options_schema(
    defaults: dict[str, Any],
    *,
    can_control: bool,
    include_connection: bool = False,
) -> vol.Schema:
    """Return options schema, hiding write controls for read-only accounts."""
    schema: dict[Any, Any] = {}
    control_field = _boolean_field(read_only=not can_control)
    if include_connection:
        schema[vol.Optional(SECTION_CONTROLLER_SETTINGS)] = section(
            vol.Schema(
                {
                    vol.Required(FIELD_HOST, default=defaults.get(CONF_HOST, "")): str,
                    vol.Required(FIELD_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                    vol.Optional(FIELD_NEW_PASSWORD, default=""): str,
                    vol.Optional(FIELD_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
                    vol.Optional(FIELD_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
                    vol.Optional(
                        FIELD_SCAN_INTERVAL,
                        default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
                    ): int,
                }
            ),
            {"collapsed": False},
        )
    else:
        schema[vol.Optional(SECTION_MONITORING_SETTINGS)] = section(
            vol.Schema(
                {
                    vol.Optional(
                        FIELD_SCAN_INTERVAL,
                        default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
                    ): int,
                }
            ),
            {"collapsed": False},
        )
    schema[vol.Optional(SECTION_PROTECTION_SETTINGS)] = section(
        vol.Schema(
            {
                vol.Optional(
                    FIELD_PORT_PROTECTION,
                    default=defaults.get(CONF_ENABLE_PORT_PROTECTION, DEFAULT_ENABLE_PORT_PROTECTION),
                ): bool,
            }
        ),
        {"collapsed": False},
    )
    schema[vol.Optional(SECTION_WIFI_CONTROLS)] = section(
        vol.Schema(
            {
                vol.Optional(
                    FIELD_WIFI_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_WIFI_CONTROLS,
                        DEFAULT_ENABLE_WIFI_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_GUEST_WIFI_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_GUEST_WIFI_CONTROLS,
                        DEFAULT_ENABLE_GUEST_WIFI_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
            }
        ),
        {"collapsed": not can_control},
    )
    schema[vol.Optional(SECTION_INTERFACE_CONTROLS)] = section(
        vol.Schema(
            {
                vol.Optional(
                    FIELD_INTERFACE_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_INTERFACE_CONTROLS,
                        DEFAULT_ENABLE_INTERFACE_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_PORT_ADMIN_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_PORT_ADMIN_CONTROLS,
                        DEFAULT_ENABLE_PORT_ADMIN_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_PORT_BOUNCE,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_PORT_BOUNCE,
                        DEFAULT_ENABLE_PORT_BOUNCE,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_POE_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_POE_CONTROLS,
                        DEFAULT_ENABLE_POE_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_POE_RESET,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_POE_RESET,
                        DEFAULT_ENABLE_POE_RESET,
                        can_control=can_control,
                    ),
                ): control_field,
            }
        ),
        {"collapsed": not can_control},
    )
    schema[vol.Optional(SECTION_ROUTER_POLICY_CONTROLS)] = section(
        vol.Schema(
            {
                vol.Optional(
                    FIELD_PORT_FORWARD_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_PORT_FORWARD_CONTROLS,
                        DEFAULT_ENABLE_PORT_FORWARD_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_ROUTE_POLICY_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_ROUTE_POLICY_CONTROLS,
                        DEFAULT_ENABLE_ROUTE_POLICY_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_FIREWALL_POLICY_CONTROLS,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_FIREWALL_POLICY_CONTROLS,
                        DEFAULT_ENABLE_FIREWALL_POLICY_CONTROLS,
                        can_control=can_control,
                    ),
                ): control_field,
            }
        ),
        {"collapsed": not can_control},
    )
    schema[vol.Optional(SECTION_MAINTENANCE_CONTROLS)] = section(
        vol.Schema(
            {
                vol.Optional(
                    FIELD_LOCATE_CONTROL,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_LOCATE_CONTROL,
                        DEFAULT_ENABLE_LOCATE_CONTROL,
                        can_control=can_control,
                    ),
                ): control_field,
                vol.Optional(
                    FIELD_REBOOT_CONTROL,
                    default=_control_default(
                        defaults,
                        CONF_ENABLE_REBOOT_CONTROL,
                        DEFAULT_ENABLE_REBOOT_CONTROL,
                        can_control=can_control,
                    ),
                ): control_field,
            }
        ),
        {"collapsed": True},
    )
    return vol.Schema(schema)


def _control_options(user_input: dict[str, Any], *, can_control: bool) -> dict[str, Any]:
    """Return stored options, forcing controls off for read-only accounts."""
    flat_input = _flatten_section_options(user_input)
    if can_control:
        options: dict[str, Any] = {
            CONF_SCAN_INTERVAL: flat_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
        }
        for key in CONTROL_OPTION_KEYS:
            if key in flat_input:
                options[key] = flat_input[key]
        for key in CONTROL_OPTION_KEYS:
            options.setdefault(key, OPTION_DEFAULTS[key])
        return options
    return monitoring_options(int(flat_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)))


def _flatten_section_options(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten native Home Assistant section input into stored option keys."""
    flat_input = dict(user_input)
    for section_key, field_map in SECTION_OPTION_KEYS.items():
        section_options = flat_input.pop(section_key, {})
        if isinstance(section_options, dict):
            for field_key, option_key in field_map.items():
                if field_key in section_options:
                    flat_input[option_key] = section_options[field_key]
                if option_key in section_options:
                    flat_input[option_key] = section_options[option_key]
    for field_map in SECTION_OPTION_KEYS.values():
        for field_key, option_key in field_map.items():
            if field_key in flat_input:
                flat_input[option_key] = flat_input.pop(field_key)
    return flat_input


def _connection_data(current_data: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """Return updated config-entry data from an options-flow submission."""
    data = dict(current_data)
    if CONF_HOST in user_input:
        data[CONF_HOST] = str(user_input[CONF_HOST]).strip()
    if CONF_USERNAME in user_input:
        data[CONF_USERNAME] = user_input[CONF_USERNAME]
    if CONF_PASSWORD in user_input and user_input[CONF_PASSWORD] not in (None, ""):
        data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
    if CONF_PORT in user_input:
        data[CONF_PORT] = user_input[CONF_PORT]
    if CONF_VERIFY_SSL in user_input:
        data[CONF_VERIFY_SSL] = user_input[CONF_VERIFY_SSL]
    data.setdefault(CONF_SITE, DEFAULT_SITE)
    return data


class UniFiInfrastructureConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Network Infrastructure."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._pending_data: dict[str, Any] | None = None
        self._pending_summary: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle manual setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            flat_input = _flatten_section_options(user_input)
            host = flat_input[CONF_HOST].strip()
            site = DEFAULT_SITE
            await self.async_set_unique_id(f"{host}_{site}".lower())
            self._abort_if_unique_id_configured()
            session = async_create_clientsession(self.hass, verify_ssl=flat_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
            client = UniFiInfrastructureClient(
                host=host,
                username=flat_input[CONF_USERNAME],
                password=flat_input[CONF_PASSWORD],
                port=flat_input.get(CONF_PORT, DEFAULT_PORT),
                site=site,
                verify_ssl=flat_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                session=session,
            )
            try:
                summary = await client.async_validate()
            except UniFiInfrastructureAuthError:
                errors["base"] = "invalid_auth"
            except UniFiInfrastructureError:
                errors["base"] = "cannot_connect"
            else:
                await client.async_logout()
                self._pending_data = {**flat_input, CONF_HOST: host, CONF_SITE: site}
                self._pending_summary = summary
                return await self.async_step_control_options()

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_schema(_flatten_section_options(user_input) if user_input else None),
            errors=errors,
        )

    async def async_step_control_options(self, user_input: dict[str, Any] | None = None):
        """Let write-capable accounts choose optional control families."""
        if self._pending_data is None or self._pending_summary is None:
            return await self.async_step_user()
        can_control = self._pending_summary.get("can_control") is True
        if user_input is not None:
            return self.async_create_entry(
                title=f"UniFi Network Infrastructure ({self._pending_data[CONF_SITE]})",
                data=self._pending_data,
                options=_control_options(user_input, can_control=can_control),
                description_placeholders={
                    "device_count": str(self._pending_summary["device_count"]),
                    "permission_mode": "controls_allowed" if can_control else "read_only",
                },
            )
        defaults = {
            CONF_SCAN_INTERVAL: self._pending_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
            **OPTION_DEFAULTS,
        }
        return self.async_show_form(
            step_id="control_options",
            data_schema=_options_schema(defaults, can_control=can_control),
            description_placeholders={
                "device_count": str(self._pending_summary["device_count"]),
                "permission_mode": "controls_allowed" if can_control else "read_only",
            },
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow."""
        return UniFiInfrastructureOptionsFlow(config_entry)


class UniFiInfrastructureOptionsFlow(config_entries.OptionsFlow):
    """Options flow for UniFi Network Infrastructure."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._can_control: bool | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        errors: dict[str, str] = {}
        if self._can_control is None:
            try:
                self._can_control = await self._async_account_can_control()
            except UniFiInfrastructureError:
                errors["base"] = "cannot_connect"
                self._can_control = False
        if user_input is not None:
            flat_input = _flatten_section_options(user_input)
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=_connection_data(self._config_entry.data, flat_input),
            )
            return self.async_create_entry(
                title="",
                data=_control_options(flat_input, can_control=self._can_control),
            )
        defaults = {
            **OPTION_DEFAULTS,
            CONF_HOST: self._config_entry.data.get(CONF_HOST, ""),
            CONF_USERNAME: self._config_entry.data.get(CONF_USERNAME, ""),
            CONF_PORT: self._config_entry.data.get(CONF_PORT, DEFAULT_PORT),
            CONF_VERIFY_SSL: self._config_entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            **self._config_entry.options,
            CONF_SCAN_INTERVAL: self._config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(defaults, can_control=self._can_control, include_connection=True),
            errors=errors,
            description_placeholders={
                "permission_mode": "controls_allowed" if self._can_control else "read_only",
            },
        )

    async def _async_account_can_control(self) -> bool:
        """Return whether the configured account can use write controls."""
        verify_ssl = self._config_entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        session = async_create_clientsession(self.hass, verify_ssl=verify_ssl)
        client = UniFiInfrastructureClient(
            host=self._config_entry.data[CONF_HOST],
            username=self._config_entry.data[CONF_USERNAME],
            password=self._config_entry.data[CONF_PASSWORD],
            port=self._config_entry.data.get(CONF_PORT, DEFAULT_PORT),
            site=self._config_entry.data.get(CONF_SITE, DEFAULT_SITE),
            verify_ssl=verify_ssl,
            session=session,
        )
        try:
            permissions = await client.async_get_account_permissions()
        finally:
            await client.async_logout()
        return permissions.get("can_control") is True
