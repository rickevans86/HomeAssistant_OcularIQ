"""Current limit controls."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfElectricCurrent

from .const import DOMAIN, MIN_CURRENT
from .controls import run
from .entity import OcularEntity, num


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for pid, ch in coordinator.data.chargers.items():
        for conn in ch.connectors or {1: {}}:
            entities += [
                SessionLimit(coordinator, pid, "session_current_limit", conn),
                DefaultLimit(coordinator, pid, "default_current_limit", conn),
            ]
    async_add_entities(entities)


class _Limit(OcularEntity, NumberEntity):
    _attr_device_class = NumberDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_native_step = 1
    _attr_native_min_value = MIN_CURRENT
    _attr_mode = NumberMode.SLIDER

    @property
    def native_max_value(self):
        return self.max_current


class SessionLimit(_Limit):
    """Change the current of the session in progress."""

    @property
    def available(self):
        return super().available and self.transaction_id is not None

    @property
    def native_value(self):
        return num(self.conn.get("limitCurrent"))

    async def async_set_native_value(self, value: float):
        await run(self, self.coordinator.api.set_session_current(self.transaction_id, value))


class DefaultLimit(_Limit):
    """Default maximum current the charger uses for new sessions."""

    _attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self):
        ch = self.charger
        v = ch.default_limits.get(self.connector or 1) if ch else None
        if isinstance(v, dict):
            v = v.get("currentValue", v.get("limitCurrent", v.get("current")))
        return num(v)

    async def async_set_native_value(self, value: float):
        self.coordinator.force_history_refresh()  # re-read slow-poll settings
        await run(
            self,
            self.coordinator.api.set_default_limit(self.point_id, self.connector or 1, value),
            delay=1,
        )
