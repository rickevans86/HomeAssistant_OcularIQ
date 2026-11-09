"""Switches: start/stop charging, plug & charge."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .controls import run
from .entity import OcularEntity

ACTIVE = {"charging", "suspended", "suspendedev", "suspendedevse", "starting"}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for pid, ch in coordinator.data.chargers.items():
        for conn in ch.connectors or {1: {}}:
            entities.append(ChargeSwitch(coordinator, pid, "charge", conn))
        entities.append(PlugAndCharge(coordinator, pid, "plug_and_charge"))
    async_add_entities(entities)


class ChargeSwitch(OcularEntity, SwitchEntity):
    """On = remote start on this connector, off = remote stop of the active transaction."""

    _attr_icon = "mdi:ev-station"

    @property
    def is_on(self):
        status = str(self.conn.get("pointStatus") or "").lower()
        return status in ACTIVE or self.transaction_id is not None

    async def async_turn_on(self, **kwargs):
        await run(self, self.coordinator.api.remote_start(self.point_id, self.connector or 1))

    async def async_turn_off(self, **kwargs):
        tid = self.transaction_id
        if tid is None:
            raise HomeAssistantError("No active charging session to stop")
        await run(self, self.coordinator.api.remote_stop(tid))


class PlugAndCharge(OcularEntity, SwitchEntity):
    """Start charging automatically when plugged in (app: 'Just charge')."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:power-plug-outline"

    @property
    def is_on(self):
        v = self.charger.plug_and_charge if self.charger else None
        if isinstance(v, dict):
            v = v.get("valid", v.get("enabled", v.get("value")))
        if v is None:
            return None
        return str(v).lower() in ("true", "1")

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)

    async def _set(self, value: bool):
        self.coordinator.force_history_refresh()
        await run(self, self.coordinator.api.set_plug_and_charge(self.point_id, value), delay=1)
