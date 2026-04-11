from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import XHouseCoordinator, XHouseDeviceData


class XHouseEntity(CoordinatorEntity[XHouseCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: XHouseCoordinator,
        device_id: int,
        entity_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"xhouse_{device_id}_{entity_key}"

    @property
    def device_data(self) -> XHouseDeviceData | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        data = self.device_data
        return data is not None and data.online

    @property
    def device_info(self) -> DeviceInfo:
        data = self.device_data
        name = data.alias if data else f"XHouse {self._device_id}"
        model = data.model if data else None
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            name=name,
            manufacturer="XHouse",
            model=model,
        )
