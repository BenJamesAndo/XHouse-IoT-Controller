from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import XHouseApi, XHouseApiError, XHouseAuthError
from .const import DOMAIN, KNOWN_MODELS, LOGGER, NON_CONTROL_PROPERTIES


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
        return any(m in self.model for m in KNOWN_MODELS)

    @property
    def is_ega(self) -> bool:
        return "EGA" in self.model

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


def parse_ega_status(status_hex: str | None) -> dict[str, Any] | None:
    if not status_hex or len(status_hex) < 12:
        return None

    door_state = int(status_hex[10:12], 16)

    STATE_MAP = {
        0: "open",
        1: "closed",
        2: "opening",
        3: "closing",
    }
    state = STATE_MAP.get(door_state, "open")

    pos_left = 0
    if len(status_hex) >= 20:
        pos_left = int(status_hex[18:20], 16)
        if door_state == 2 and pos_left >= 100:
            state = "open"
        elif door_state == 3 and pos_left == 0:
            state = "closed"

    pos_right = 0
    position = pos_left

    return {
        "state": state,
        "position": position,
        "pos_left": pos_left,
        "pos_right": pos_right,
    }


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

            if dev.online:
                try:
                    dev.prop_values = await self.api.get_device_properties(dev.device_id)
                except XHouseApiError as err:
                    if "device offline" in str(err).lower():
                        dev.online = False
                    else:
                        LOGGER.warning(
                            "Failed to get properties for device %s: %s",
                            dev.device_id, err,
                        )

        return devices
