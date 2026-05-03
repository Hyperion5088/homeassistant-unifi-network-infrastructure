"""Config flow for UniFi Infrastructure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import UniFiInfrastructureAuthError, UniFiInfrastructureClient, UniFiInfrastructureError
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


def _setup_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return setup schema."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(CONF_SITE, default=defaults.get(CONF_SITE, DEFAULT_SITE)): str,
            vol.Optional(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)): bool,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
            ): int,
        }
    )


class UniFiInfrastructureConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for UniFi Infrastructure."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle manual setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            site = user_input.get(CONF_SITE, DEFAULT_SITE).strip() or DEFAULT_SITE
            await self.async_set_unique_id(f"{host}_{site}".lower())
            self._abort_if_unique_id_configured()
            session = async_create_clientsession(self.hass, verify_ssl=user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
            client = UniFiInfrastructureClient(
                host=host,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                port=user_input.get(CONF_PORT, DEFAULT_PORT),
                site=site,
                verify_ssl=user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
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
                return self.async_create_entry(
                    title=f"UniFi Infrastructure ({site})",
                    data={**user_input, CONF_HOST: host, CONF_SITE: site},
                    options={CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)},
                    description_placeholders={"device_count": str(summary["device_count"])},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_setup_schema(user_input),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow."""
        return UniFiInfrastructureOptionsFlow(config_entry)


class UniFiInfrastructureOptionsFlow(config_entries.OptionsFlow):
    """Options flow for UniFi Infrastructure."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
                        ),
                    ): int,
                }
            ),
        )
