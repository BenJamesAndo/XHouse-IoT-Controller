from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XHouseConfigEntry
from .api import XHouseApiError
from .const import LOGGER
from .entity import XHouseEntity
from .protocol import (
    build_trigger_key_property_value,
    trigger_key_channel_number,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XHouseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []

    for device_id, dev in coordinator.data.items():
        if dev.is_trigger_module:
            if dev.ble_code is None:
                LOGGER.warning(
                    "Trigger module %s missing bleCode, skipping its channels",
                    device_id,
                )
                continue
            for prop in dev.get_trigger_channels():
                entities.append(
                    XHouseTriggerKeyButton(
                        coordinator, device_id, prop["key"], prop.get("name")
                    )
                )
            continue
        if not dev.is_ble_gate:
            continue
        if dev.ble_code is None:
            LOGGER.warning(
                "Gate device %s missing bleCode, skipping pedestrian button",
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
            LOGGER.error("No bleCode for gate device %s", self._device_id)
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
        self.coordinator.start_fast_poll()


class XHouseTriggerKeyButton(XHouseEntity, ButtonEntity):
    """One channel on an SM18/SM05 receiver module.

    Momentary channels pulse; latching ones toggle, matching the single button
    the app shows per channel.
    """

    _attr_icon = "mdi:gesture-tap-button"

    def __init__(
        self,
        coordinator,
        device_id: int,
        property_key: str,
        property_name: str | None,
    ) -> None:
        super().__init__(coordinator, device_id, property_key.lower())
        self._property_key = property_key
        self._channel = trigger_key_channel_number(property_key)
        self._attr_name = property_name or property_key

    async def async_press(self) -> None:
        data = self.device_data
        if data is None:
            return
        ble_code = data.ble_code
        if not ble_code or self._channel is None:
            LOGGER.error("Cannot build trigger command for %s", self.entity_id)
            return
        api = self.coordinator.api
        body = {
            "deviceId": self._device_id,
            "userId": int(api.user_id),
            "propertyValue": build_trigger_key_property_value(
                ble_code,
                self._property_key,
                data.prop_values.get(self._property_key),
                data.get_property_mode(self._property_key),
            ),
            # The app sends the channel number here, not the channel's label.
            "action": self._channel,
        }
        try:
            await api.send_command(body)
        except XHouseApiError as err:
            LOGGER.error("Failed to trigger %s: %s", self.entity_id, err)
            return
        await self.coordinator.async_request_refresh()
