from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XHouseConfigEntry
from .api import XHouseApiError
from .const import LOGGER
from .coordinator import XHouseDeviceData, parse_ega_status, parse_gate_mode
from .entity import XHouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XHouseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[CoverEntity] = []

    for device_id, dev in coordinator.data.items():
        if not dev.is_known_model:
            continue
        device_class = _determine_device_class(dev)
        if dev.is_ega:
            entities.append(XHouseEgaCover(coordinator, device_id, device_class))
        else:
            entities.append(XHouseKnownCover(coordinator, device_id, device_class))

    async_add_entities(entities)


def _determine_device_class(dev: XHouseDeviceData) -> CoverDeviceClass:
    alias_lower = dev.alias.lower()
    model = dev.model
    if "XH-SGC01" in model or "EGA" in model or "EGB" in model:
        return CoverDeviceClass.GATE
    if "gate" in alias_lower:
        return CoverDeviceClass.GATE
    if "garage" in alias_lower or "door" in alias_lower:
        return CoverDeviceClass.GARAGE
    return CoverDeviceClass.GATE


class XHouseKnownCover(XHouseEntity, CoverEntity):
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(
        self,
        coordinator,
        device_id: int,
        device_class: CoverDeviceClass,
    ) -> None:
        super().__init__(coordinator, device_id, "cover")
        self._attr_device_class = device_class
        if "XH-SGC01" in (coordinator.data[device_id].model or ""):
            self._attr_name = "Gate Opener"
        else:
            self._attr_name = None

    @property
    def is_closed(self) -> bool | None:
        data = self.device_data
        if data is None or not data.online:
            return None
        val = data.prop_values.get("Switch_1")
        return val != "1"

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._send_switch_command(1)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._send_switch_command(0)

    async def _send_switch_command(self, value: int) -> None:
        api = self.coordinator.api
        body = {
            "deviceId": self._device_id,
            "userId": int(api.user_id),
            "propertyValue": {"Switch_1": value},
            "action": "On" if value else "Off",
        }
        try:
            await api.send_command(body)
        except XHouseApiError as err:
            LOGGER.error("Failed to control cover %s: %s", self.entity_id, err)
            return
        await self.coordinator.async_request_refresh()


class XHouseEgaCover(XHouseEntity, CoverEntity):
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    # Keep all action buttons available in case of partial open/close from pedestrian events.
    _attr_assumed_state = True   

    def __init__(
        self,
        coordinator,
        device_id: int,
        device_class: CoverDeviceClass,
    ) -> None:
        super().__init__(coordinator, device_id, "cover")
        self._attr_device_class = device_class

    @property
    def _ble_code(self) -> str | None:
        data = self.device_data
        return data.ble_code if data else None

    @property
    def _ega_status(self) -> dict | None:
        data = self.device_data
        if data is None or not data.online:
            return None
        return parse_ega_status(data.prop_values.get("status"), self._gate_mode)

    @property
    def is_closed(self) -> bool | None:
        status = self._ega_status
        if status is None:
            return None
        return status["state"] == "closed"

    @property
    def is_opening(self) -> bool:
        status = self._ega_status
        return status is not None and status["state"] == "opening"

    @property
    def is_closing(self) -> bool:
        status = self._ega_status
        return status is not None and status["state"] == "closing"

    @property
    def current_cover_position(self) -> int | None:
        status = self._ega_status
        if status is None:
            return None
        return status["position"]

    @property
    def _gate_mode(self) -> str:
        data = self.device_data
        menu_code = data.prop_values.get("menuCode") if data else None
        return parse_gate_mode(menu_code)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"gate_mode": self._gate_mode}
        status = self._ega_status
        if status is not None:
            attrs["wing_left"] = status["pos_left"]
            attrs["wing_right"] = status["pos_right"]
        return attrs

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._send_ega_command("01")

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._send_ega_command("02")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self._send_ega_command("03")

    async def _send_ega_command(self, action_code: str) -> None:
        ble_code = self._ble_code
        if not ble_code:
            LOGGER.error("No bleCode for EGA device %s", self._device_id)
            return
        hex_value = f"3A{ble_code}04{action_code}"
        api = self.coordinator.api
        body = {
            "deviceId": self._device_id,
            "userId": int(api.user_id),
            "propertyValue": {"type": "SET_MENU", "object": {"value": hex_value}},
            "action": "",
        }
        try:
            await api.send_command(body)
        except XHouseApiError as err:
            LOGGER.error("Failed to control EGA cover %s: %s", self.entity_id, err)
            return
        self.coordinator.start_fast_poll()
