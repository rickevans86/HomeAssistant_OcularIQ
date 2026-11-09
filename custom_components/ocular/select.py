"""Charging mode selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity

from .const import DOMAIN, SESSION_MODES, SOLAR_MODES
from .controls import run
from .entity import OcularEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for pid, ch in coordinator.data.chargers.items():
        for conn, data in (ch.connectors or {1: {}}).items():
            entities.append(SessionMode(coordinator, pid, "session_mode_select", conn))
            if data.get("internalGatewayId") or ch.info.get("internalGatewayId"):
                entities.append(SolarMode(coordinator, pid, "solar_mode_select", conn))
    async_add_entities(entities)


class SessionMode(OcularEntity, SelectEntity):
    """Fast / Eco / EcoPlus for the session in progress."""

    _attr_options = SESSION_MODES
    _attr_icon = "mdi:leaf"

    @property
    def available(self):
        return super().available and self.transaction_id is not None

    @property
    def current_option(self):
        v = self.conn.get("eco")
        return v if v in SESSION_MODES else None

    async def async_select_option(self, option: str):
        await run(self, self.coordinator.api.set_session_mode(self.transaction_id, option))


class SolarMode(OcularEntity, SelectEntity):
    """Fast / Solar Assist / Solar on chargers with a built-in solar gateway (IQ Solar/Home)."""

    _attr_options = list(SOLAR_MODES.values())
    _attr_icon = "mdi:solar-power"

    @property
    def gateway_id(self):
        ch = self.charger
        return self.conn.get("internalGatewayId") or (ch.info.get("internalGatewayId") if ch else None)

    @property
    def current_option(self):
        mode = self.conn.get("gatewayMode")
        if isinstance(mode, dict):
            mode = mode.get("mode") or mode.get("name")
        return SOLAR_MODES.get(mode, mode if mode in SOLAR_MODES.values() else None)

    async def async_select_option(self, option: str):
        code = next(k for k, v in SOLAR_MODES.items() if v == option)
        await run(self, self.coordinator.api.set_solar_mode(self.gateway_id, code))
