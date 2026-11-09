"""Sensors for Ocular chargers."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HISTORY_DAYS, NOMINAL_VOLTAGE
from .entity import OcularEntity, num


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for pid, ch in coordinator.data.chargers.items():
        for conn in ch.connectors or {1: {}}:
            entities += [
                StatusSensor(coordinator, pid, "status", conn),
                PlugSensor(coordinator, pid, "plug_status", conn),
                CurrentSensor(coordinator, pid, "charging_current", conn),
                LimitSensor(coordinator, pid, "active_current_limit", conn),
                PowerSensor(coordinator, pid, "charging_power", conn),
                SessionEnergySensor(coordinator, pid, "session_energy", conn),
                SessionStartSensor(coordinator, pid, "session_start", conn),
                SessionModeSensor(coordinator, pid, "session_mode", conn),
                SolarModeSensor(coordinator, pid, "solar_mode", conn),
            ]
        entities += [
            LastSessionEnergy(coordinator, pid, "last_session_energy"),
            LastSessionDuration(coordinator, pid, "last_session_duration"),
            LastSessionEnd(coordinator, pid, "last_session_end"),
            PeriodEnergy(coordinator, pid, "energy_last_30_days"),
            RawStatus(coordinator, pid, "raw_status"),
        ]
    async_add_entities(entities)


class StatusSensor(OcularEntity, SensorEntity):
    _attr_icon = "mdi:ev-station"

    @property
    def native_value(self):
        return self.conn.get("pointStatus")

    @property
    def extra_state_attributes(self):
        c = self.conn
        return {"transaction_id": self.transaction_id, "delay_time": c.get("delayTime")}


class PlugSensor(OcularEntity, SensorEntity):
    _attr_icon = "mdi:ev-plug-type2"

    @property
    def native_value(self):
        return self.conn.get("pluggedStatus")


class CurrentSensor(OcularEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    @property
    def native_value(self):
        return num(self.conn.get("currentCurrent"))


class LimitSensor(OcularEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_icon = "mdi:speedometer"

    @property
    def native_value(self):
        return num(self.conn.get("limitCurrent"))


class PowerSensor(OcularEntity, SensorEntity):
    """Estimated: the API reports live amps only, so P = I x V x phases."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    def native_value(self):
        amps = num(self.conn.get("currentCurrent"))
        if amps is None:
            return None
        ch = self.charger
        rated_kw = num((ch.detail.get("power") if ch else None) or self.conn.get("power")) or 7
        phases = 3 if rated_kw > 12 else 1
        return round(amps * NOMINAL_VOLTAGE * phases)

    @property
    def extra_state_attributes(self):
        return {"estimated": True, "rated_power_kw": num(self.conn.get("power"))}


class SessionEnergySensor(OcularEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    @property
    def native_value(self):
        return num(self.conn.get("energy"))


class SessionStartSensor(OcularEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        return parse_time(self.conn.get("startTime")) if self.transaction_id else None


class SessionModeSensor(OcularEntity, SensorEntity):
    _attr_icon = "mdi:leaf"

    @property
    def native_value(self):
        return self.conn.get("eco")


class SolarModeSensor(OcularEntity, SensorEntity):
    _attr_icon = "mdi:solar-power"

    @property
    def native_value(self):
        return self.conn.get("gatewayMode")


# ---------------------------------------------------------------- history
def _sorted_records(ch):
    return sorted(
        ch.records or [],
        key=lambda r: parse_time(r.get("endTime") or r.get("startTime")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


class _History(OcularEntity, SensorEntity):
    @property
    def last(self):
        recs = _sorted_records(self.charger) if self.charger else []
        return recs[0] if recs else None


class LastSessionEnergy(_History):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    @property
    def native_value(self):
        return num(self.last.get("electricValue")) if self.last else None

    @property
    def extra_state_attributes(self):
        if not self.last:
            return None
        r = self.last
        return {
            "start": r.get("startTime"),
            "end": r.get("endTime"),
            "connector": r.get("connectorId"),
            "user": " ".join(x for x in (r.get("firstName"), r.get("lastName")) if x),
            "cost": r.get("priceStr"),
            "card": r.get("code"),
        }


class LastSessionDuration(_History):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    @property
    def native_value(self):
        if not self.last:
            return None
        s = parse_time(self.last.get("startTime"))
        e = parse_time(self.last.get("endTime"))
        if s and e:
            return round((e - s).total_seconds() / 60)
        return num(self.last.get("electricTime"))


class LastSessionEnd(_History):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        return parse_time(self.last.get("endTime")) if self.last else None


class PeriodEnergy(_History):
    """Total kWh over the last 30 days, with the session list as an attribute."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:history"

    @property
    def native_value(self):
        ch = self.charger
        if not ch:
            return None
        return round(sum(num(r.get("electricValue")) or 0 for r in ch.records), 3)

    @property
    def extra_state_attributes(self):
        ch = self.charger
        recs = _sorted_records(ch) if ch else []
        return {
            "days": HISTORY_DAYS,
            "session_count": len(recs),
            "sessions": [
                {
                    "start": r.get("startTime"),
                    "end": r.get("endTime"),
                    "kwh": num(r.get("electricValue")),
                    "cost": r.get("priceStr"),
                    "user": " ".join(x for x in (r.get("firstName"), r.get("lastName")) if x),
                }
                for r in recs[:50]
            ],
        }


class RawStatus(OcularEntity, SensorEntity):
    """Everything the cloud returns, for debugging and templates."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:code-json"

    @property
    def native_value(self):
        return dt_util.utcnow().replace(microsecond=0).isoformat() if self.charger else None

    @property
    def extra_state_attributes(self):
        ch = self.charger
        if not ch:
            return None
        return {
            "point": ch.info,
            "detail": ch.detail,
            "connectors": ch.connectors,
            "default_limits": ch.default_limits,
            "eco_setting": ch.eco_setting,
            "plug_and_charge": ch.plug_and_charge,
        }


def parse_time(value):
    """Cloud times are UTC; formats seen: ISO with Z, or 'yyyy-MM-dd HH:mm:ss'."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), timezone.utc)
    dt = dt_util.parse_datetime(str(value).replace(" ", "T", 1))
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
