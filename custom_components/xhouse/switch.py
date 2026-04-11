from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    entities: list[SwitchEntity] = []

    for device_id, dev in coordinator.data.items():
        if dev.is_known_model:
            continue
        props = dev.get_controllable_properties()
        if not props:
            LOGGER.warning(
                "Device %s (%s) has no controllable properties",
                device_id, dev.model,
            )
            continue
        for prop in props:
            entities.append(
                XHouseSwitch(coordinator, device_id, prop["key"], prop.get("name"))
            )

    async_add_entities(entities)


class XHouseSwitch(XHouseEntity, SwitchEntity):
    _attr_icon = "mdi:toggle-switch"

    def __init__(
        self,
        coordinator,
        device_id: int,
        property_key: str,
        property_name: str | None,
    ) -> None:
        super().__init__(coordinator, device_id, property_key.lower())
        self._property_key = property_key
        self._attr_name = property_name or property_key

    @property
    def is_on(self) -> bool | None:
        data = self.device_data
        if data is None or not data.online:
            return None
        return data.prop_values.get(self._property_key) == "1"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send_command(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send_command(0)

    async def _send_command(self, value: int) -> None:
        api = self.coordinator.api
        body = {
            "deviceId": self._device_id,
            "userId": int(api.user_id),
            "propertyValue": {self._property_key: value},
            "action": "On" if value else "Off",
        }
        try:
            await api.send_command(body)
        except XHouseApiError as err:
            LOGGER.error("Failed to control switch %s: %s", self.entity_id, err)
            return
        await self.coordinator.async_request_refresh()
