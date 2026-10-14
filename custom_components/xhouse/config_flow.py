from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback

from .api import XHouseApi, XHouseAuthError
from .const import (
    CONF_DEBUG_MODE,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL): vol.All(
            int, vol.Range(min=5)
        ),
        vol.Optional(CONF_DEBUG_MODE, default=False): bool,
    }
)


async def _validate_login(email: str, password: str) -> dict[str, str]:
    """Try the credentials and return form errors (empty on success)."""
    session = aiohttp.ClientSession()
    api = XHouseApi(session)
    try:
        await api.login(email, password)
    except XHouseAuthError:
        return {"base": "invalid_auth"}
    except Exception:
        return {"base": "cannot_connect"}
    finally:
        await session.close()
    return {}


class XHouseConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await _validate_login(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(user_input[CONF_EMAIL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data=user_input,
                    options={
                        CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
                        CONF_DEBUG_MODE: False,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            errors = await _validate_login(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return XHouseOptionsFlow(config_entry)


class XHouseOptionsFlow(OptionsFlowWithReload):
    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_REFRESH_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                        ),
                    ): vol.All(int, vol.Range(min=5)),
                    vol.Optional(
                        CONF_DEBUG_MODE,
                        default=self._config_entry.options.get(CONF_DEBUG_MODE, False),
                    ): bool,
                }
            ),
        )
