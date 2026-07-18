from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import XHouseApi, XHouseApiError, XHouseAuthError
from .const import DOMAIN, KNOWN_MODELS, LOGGER, NON_CONTROL_PROPERTIES

FAST_POLL_INTERVAL = 2.0  # seconds between refreshes during a burst
FAST_POLL_DURATION = 30.0  # total burst length in seconds


class XHouseDeviceData:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.device_id: int = raw.get("id")
        self.alias: str = raw.get("alias", f"XHouse Device {self.device_id}")
        self.model: str = raw.get("model", "Unknown")
        self.device_type: str = raw.get("deviceType", "Unknown")
        self.online: bool = raw.get("status", 0) == 1
        self.properties: list[dict] = raw.get("properties", [])
        self.prop_values: dict[str, str] = {}

    @property
    def is_known_model(self) -> bool:
        identifiers = f"{self.model} {self.device_type}".upper()
        return any(model.upper() in identifiers for model in KNOWN_MODELS)

    @property
    def is_ega(self) -> bool:
        identifiers = f"{self.model} {self.device_type}".upper()
        return "EGA" in identifiers

    @property
    def is_egb(self) -> bool:
        identifiers = f"{self.model} {self.device_type}".upper()
        return "EGB" in identifiers or "PGB" in identifiers

    @property
    def is_ble_gate(self) -> bool:
        # Both families use the SET_MENU BLE command protocol, but their
        # status bytes have different meanings.
        return self.is_ega or self.is_egb

    @property
    def ble_code(self) -> str | None:
        for p in self.properties:
            if p.get("key") == "bleCode":
                return p.get("value")
        return None

    def get_controllable_properties(self) -> list[dict]:
        return [
            p for p in self.properties
            if (p.get("type") == "INT" or (p.get("key") or "").startswith("Switch_"))
            and p.get("key") not in NON_CONTROL_PROPERTIES
        ]


class XHouseCoordinator(DataUpdateCoordinator[dict[int, XHouseDeviceData]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: XHouseApi,
        email: str,
        password: str,
        refresh_interval: int,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=refresh_interval),
        )
        self.api = api
        self._email = email
        self._password = password
        self._fast_poll_task: asyncio.Task | None = None
        self._fast_poll_deadline: float = 0.0

    def start_fast_poll(
        self,
        duration: float = FAST_POLL_DURATION,
        interval: float = FAST_POLL_INTERVAL,
    ) -> None:
        """Poll every ``interval`` seconds for ``duration`` seconds.

        Used right after issuing a command (e.g. opening a gate) so HA
        sees the state transition quickly without permanently increasing
        the global poll rate. Calling again extends the deadline.
        """
        loop = self.hass.loop
        self._fast_poll_deadline = max(
            self._fast_poll_deadline, loop.time() + duration
        )
        if self._fast_poll_task is None or self._fast_poll_task.done():
            self._fast_poll_task = self.hass.async_create_background_task(
                self._fast_poll_loop(interval),
                name=f"{DOMAIN}_fast_poll",
            )

    async def _fast_poll_loop(self, interval: float) -> None:
        loop = self.hass.loop
        try:
            while loop.time() < self._fast_poll_deadline:
                await asyncio.sleep(interval)
                await self.async_refresh()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.exception("Fast-poll loop crashed")

    async def _async_update_data(self) -> dict[int, XHouseDeviceData]:
        try:
            return await self._fetch_all()
        except XHouseAuthError:
            LOGGER.warning("Token expired, re-authenticating")
            try:
                await self.api.login(self._email, self._password)
                return await self._fetch_all()
            except XHouseApiError as err:
                raise UpdateFailed(f"Auth retry failed: {err}") from err
        except XHouseApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch_all(self) -> dict[int, XHouseDeviceData]:
        raw_devices = await self.api.get_devices()
        devices: dict[int, XHouseDeviceData] = {}

        for raw in raw_devices:
            dev = XHouseDeviceData(raw)
            devices[dev.device_id] = dev
            LOGGER.debug("Raw device info: %s", raw)

            if dev.online:
                try:
                    dev.prop_values = await self.api.get_device_properties(dev.device_id)
                    LOGGER.debug(
                        "Properties for device %s (model=%s): %s",
                        dev.device_id, dev.model, dev.prop_values,
                    )
                except XHouseApiError as err:
                    if "device offline" in str(err).lower():
                        dev.online = False
                    else:
                        LOGGER.warning(
                            "Failed to get properties for device %s: %s",
                            dev.device_id, err,
                        )

        return devices
