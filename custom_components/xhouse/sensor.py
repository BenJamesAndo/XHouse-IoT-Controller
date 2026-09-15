from __future__ import annotations

import time

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XHouseConfigEntry
from .entity import XHouseEntity
from .protocol import estimate_battery_soc, is_gate_in_motion, parse_battery_reply


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XHouseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for device_id, dev in coordinator.data.items():
        if not dev.is_ble_gate or dev.ble_code is None:
            continue
        entities.append(XHouseBatteryVoltageSensor(coordinator, device_id))
        entities.append(XHouseBatterySoCSensor(coordinator, device_id))

    async_add_entities(entities)


class XHouseBatteryVoltageSensor(XHouseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "battery_voltage")
        self._attr_name = "Backup Battery Voltage"

    @property
    def native_value(self) -> float | None:
        data = self.device_data
        if data is None or not data.online:
            return None
        battery = parse_battery_reply(data.prop_values.get("status"))
        return battery.get("voltage") if battery else None


SETTLE_SECONDS = 15.0  # hold last SoC this long after motion stops, to let
# motor-load sag in the battery voltage recover before sampling again.


class XHouseBatterySoCSensor(XHouseEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "battery_soc")
        self._attr_name = "Backup Battery Estimated Charge"
        self._last_soc: int | None = None
        self._hold_until: float = 0.0

    @property
    def native_value(self) -> int | None:
        data = self.device_data
        if data is None or not data.online:
            return self._last_soc

        status_hex = data.prop_values.get("status")
        if is_gate_in_motion(status_hex, data.is_egb, data.gate_mode):
            # Motor current sags pack voltage; sampling now would read as a
            # charge drop that has nothing to do with actual state of charge.
            self._hold_until = time.monotonic() + SETTLE_SECONDS
            return self._last_soc
        if time.monotonic() < self._hold_until:
            # Still within the recovery window right after motion stopped.
            return self._last_soc

        battery = parse_battery_reply(status_hex)
        if battery:
            soc = estimate_battery_soc(battery.get("voltage"), battery.get("battery_present", False))
            if soc is not None:
                self._last_soc = soc
        return self._last_soc
