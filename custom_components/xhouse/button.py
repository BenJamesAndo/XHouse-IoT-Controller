from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XHouseConfigEntry
from .api import XHouseApiError
from .const import LOGGER
from .entity import XHouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XHouseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []

    for device_id, dev in coordinator.data.items():
        if not dev.is_ega:
            continue
        if dev.ble_code is None:
            LOGGER.warning(
                "EGA device %s missing bleCode, skipping pedestrian button",
                device_id,
            )
            continue
        entities.append(XHousePedestrianButton(coordinator, device_id))

    async_add_entities(entities)


class XHousePedestrianButton(XHouseEntity, ButtonEntity):
    _attr_icon = "mdi:walk"

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "pedestrian")
        self._attr_name = "Pedestrian"

    async def async_press(self) -> None:
        data = self.device_data
        if data is None:
            return
        ble_code = data.ble_code
        if not ble_code:
            LOGGER.error("No bleCode for EGA device %s", self._device_id)
            return
        hex_value = f"3A{ble_code}0404"
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
            LOGGER.error("Failed to send pedestrian command for %s: %s", self.entity_id, err)
            return
        await self.coordinator.async_request_refresh()
