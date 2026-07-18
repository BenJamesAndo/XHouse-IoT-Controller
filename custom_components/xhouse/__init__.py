from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import XHouseApi
from .const import (
    CONF_DEBUG_MODE,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    LOGGER,
    PLATFORMS,
)
from .coordinator import XHouseCoordinator

type XHouseConfigEntry = ConfigEntry[XHouseCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: XHouseConfigEntry) -> bool:
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    refresh_interval = entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
    debug_mode = entry.options.get(CONF_DEBUG_MODE, False)

    if debug_mode:
        LOGGER.setLevel("DEBUG")

    session = async_get_clientsession(hass)
    api = XHouseApi(session)
    await api.login(email, password)

    coordinator = XHouseCoordinator(hass, api, email, password, refresh_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: XHouseConfigEntry) -> None:
    coordinator: XHouseCoordinator = entry.runtime_data
    new_interval = entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
    coordinator.update_interval = timedelta(seconds=new_interval)
    # Apply debug_mode immediately; "NOTSET" reverts to inheriting HA's level.
    LOGGER.setLevel("DEBUG" if entry.options.get(CONF_DEBUG_MODE, False) else "NOTSET")
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: XHouseConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
