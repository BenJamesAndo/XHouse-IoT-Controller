from __future__ import annotations

import time

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfElectricPotential
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import XHouseConfigEntry
from .entity import XHouseEntity
from .protocol import estimate_battery_soc, is_gate_in_motion, parse_battery_reply

# Hold the last SoC this long after motion stops, so the pack can recover from
# motor-load sag before it is sampled again.
SETTLE_SECONDS = 15.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XHouseConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for device_id, dev in coordinator.data.items():
        # EGA only: the battery byte offsets do not apply to EGB/PGB frames.
        if not dev.is_ega:
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
        if not battery or not battery["battery_present"]:
            return None
        return battery["voltage"]


class XHouseBatterySoCSensor(XHouseEntity, RestoreSensor):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "battery_soc")
        self._attr_name = "Backup Battery Estimated Charge"
        self._last_soc: int | None = None
        self._hold_until: float = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            try:
                self._last_soc = int(last.native_value)
            except (TypeError, ValueError):
                self._last_soc = None
        self._refresh_soc()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._refresh_soc()
        super()._handle_coordinator_update()

    @callback
    def _refresh_soc(self) -> None:
        """Update the cached SoC, skipping samples taken under motor load."""
        data = self.device_data
        if data is None or not data.online:
            return

        status_hex = data.prop_values.get("status")
        if is_gate_in_motion(status_hex, data.is_egb, data.gate_mode):
            self._hold_until = time.monotonic() + SETTLE_SECONDS
            return
        if time.monotonic() < self._hold_until:
            return

        battery = parse_battery_reply(status_hex)
        if not battery:
            return
        soc = estimate_battery_soc(battery["voltage"], battery["battery_present"])
        if soc is not None:
            self._last_soc = soc

    @property
    def native_value(self) -> int | None:
        return self._last_soc
