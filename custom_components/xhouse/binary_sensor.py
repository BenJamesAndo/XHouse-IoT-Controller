from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XHouseConfigEntry
from .entity import XHouseEntity
from .protocol import parse_battery_reply


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XHouseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []

    for device_id, dev in coordinator.data.items():
        # EGA only: the battery byte offsets do not apply to EGB/PGB frames.
        if not dev.is_ega:
            continue
        entities.append(XHouseBatteryPresentBinarySensor(coordinator, device_id))

    async_add_entities(entities)


class XHouseBatteryPresentBinarySensor(XHouseEntity, BinarySensorEntity):
    _attr_icon = "mdi:car-battery"

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "battery_present")
        self._attr_name = "Backup Battery Present"

    @property
    def is_on(self) -> bool | None:
        data = self.device_data
        if data is None or not data.online:
            return None
        battery = parse_battery_reply(data.prop_values.get("status"))
        return battery["battery_present"] if battery else None
