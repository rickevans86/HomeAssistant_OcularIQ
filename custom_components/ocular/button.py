"""Buttons: refresh status, reboot."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory

from .const import DOMAIN
from .controls import run
from .entity import OcularEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for pid in coordinator.data.chargers:
        entities += [
            RefreshButton(coordinator, pid, "refresh"),
            HistoryButton(coordinator, pid, "refresh_history"),
            RebootButton(coordinator, pid, "reboot"),
        ]
    async_add_entities(entities)


class RefreshButton(OcularEntity, ButtonEntity):
    """Ask the charger to re-send its connector status, then poll."""

    _attr_icon = "mdi:refresh"

    async def async_press(self):
        conns = list(self.charger.connectors) if self.charger else [1]
        await run(self, self.coordinator.api.refresh_status(self.point_id, conns or [1]))


class HistoryButton(OcularEntity, ButtonEntity):
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self):
        self.coordinator.force_history_refresh()
        await self.coordinator.async_request_refresh()


class RebootButton(OcularEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self):
        await run(self, self.coordinator.api.reboot(self.point_id), delay=1)
