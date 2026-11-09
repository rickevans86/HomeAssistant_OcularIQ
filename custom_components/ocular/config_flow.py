"""Config flow for Ocular."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OcularApi, OcularAuthError, OcularError, hash_password
from .const import CONF_PASSWORD_HASH, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

SCHEMA = vol.Schema({vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str})


class OcularConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _try(self, username: str, password: str) -> tuple[dict, str | None]:
        pw_hash = hash_password(password)
        api = OcularApi(async_get_clientsession(self.hass), username, pw_hash)
        try:
            await api.login()
            await api.get_user()
        except OcularAuthError:
            return {"base": "invalid_auth"}, None
        except OcularError:
            return {"base": "cannot_connect"}, None
        return {}, pw_hash

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            errors, pw_hash = await self._try(username, user_input[CONF_PASSWORD])
            if not errors:
                # Only the double-MD5 hash the app sends is stored, never the plain password.
                return self.async_create_entry(
                    title=f"Ocular ({username})",
                    data={CONF_USERNAME: username, CONF_PASSWORD_HASH: pw_hash},
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reauth_entry()
        errors: dict = {}
        if user_input is not None:
            errors, pw_hash = await self._try(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_PASSWORD_HASH: pw_hash}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry):
        return OcularOptionsFlow()


class OcularOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        int, vol.Range(min=10, max=600)
                    )
                }
            ),
        )
