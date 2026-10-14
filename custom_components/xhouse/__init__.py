from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import XHouseApi, XHouseApiError, XHouseLoginRejected
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

    if entry.options.get(CONF_DEBUG_MODE, False):
        LOGGER.setLevel("DEBUG")
        # Undo it on unload so turning the option off takes effect.
        entry.async_on_unload(lambda: LOGGER.setLevel("NOTSET"))

    session = async_get_clientsession(hass)
    api = XHouseApi(session)
    try:
        await api.login(email, password)
    except XHouseLoginRejected as err:
        if err.wrong_credentials:
            raise ConfigEntryAuthFailed(str(err)) from err
        raise ConfigEntryNotReady(str(err)) from err
    except XHouseApiError as err:
        # Typically the network or cloud isn't reachable yet right after an
        # HA restart; ConfigEntryNotReady makes HA retry with backoff.
        raise ConfigEntryNotReady(f"Cannot reach XHouse cloud: {err}") from err

    coordinator = XHouseCoordinator(hass, api, email, password, refresh_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: XHouseConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
