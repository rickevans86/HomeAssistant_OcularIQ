"""Binary sensors for Ocular chargers."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DOMAIN
from .entity import OcularEntity

NOT_PLUGGED = {"", "none", "unplugged", "available", "notplugged", "not_plugged", "false", "0"}
ONLINE_BAD = {"offline", "unavailable", "faulted"}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for pid, ch in coordinator.data.chargers.items():
        for conn in ch.connectors or {1: {}}:
            entities += [
                Plugged(coordinator, pid, "plugged_in", conn),
                Charging(coordinator, pid, "charging", conn),
                Online(coordinator, pid, "online", conn),
            ]
    async_add_entities(entities)


class Plugged(OcularEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PLUG

    @property
    def is_on(self):
        plug = str(self.conn.get("pluggedStatus") or "").strip().lower()
        status = str(self.conn.get("pointStatus") or "").lower()
        if status in ("charging", "suspended", "suspendedev", "suspendedevse", "preparing", "finishing"):
            return True
        if not plug:
            return None
        return plug not in NOT_PLUGGED


class Charging(OcularEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self):
        return str(self.conn.get("pointStatus") or "").lower() == "charging"


class Online(OcularEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        status = str(self.conn.get("pointStatus") or "").lower()
        return bool(status) and status not in ONLINE_BAD
