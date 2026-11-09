"""Data coordinator for Ocular."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OcularApi, OcularAuthError, OcularError
from .const import DOMAIN, HISTORY_DAYS, HISTORY_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class Charger:
    """One charge point and its connectors."""

    id: str
    info: dict
    detail: dict = field(default_factory=dict)
    # connector number (1-based) -> PointStatusInfo dict
    connectors: dict[int, dict] = field(default_factory=dict)
    default_limits: dict[int, Any] = field(default_factory=dict)
    eco_setting: dict = field(default_factory=dict)
    plug_and_charge: Any = None
    records: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.info.get("name") or self.detail.get("name") or f"Charger {self.id}"


@dataclass
class OcularData:
    family_id: Any
    user: dict
    chargers: dict[str, Charger]
    price: dict = field(default_factory=dict)


class OcularCoordinator(DataUpdateCoordinator[OcularData]):
    """Polls the Ocular cloud."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: OcularApi, interval: int
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.api = api
        self._last_slow = 0.0
        self._static: dict[str, dict] = {}

    async def _async_update_data(self) -> OcularData:
        try:
            return await self._fetch()
        except OcularAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except OcularError as err:
            raise UpdateFailed(str(err)) from err

    async def _fetch(self) -> OcularData:
        prev = self.data
        user = await self.api.get_user()
        family_id = (user.get("setting") or {}).get("familyId")
        if family_id is None:
            families = await self.api.get_families()
            if not families:
                raise UpdateFailed("No family/home found on this Ocular account")
            family_id = families[0].get("id")

        points = await self.api.get_family_points(family_id)
        slow = time.monotonic() - self._last_slow > HISTORY_INTERVAL or prev is None

        chargers: dict[str, Charger] = {}
        for info in points:
            pid = str(info.get("id"))
            ch = Charger(id=pid, info=info)
            old = prev.chargers.get(pid) if prev else None

            if pid not in self._static:
                try:
                    self._static[pid] = await self.api.get_point_detail(pid)
                except OcularError as err:
                    _LOGGER.debug("point detail failed: %s", err)
                    self._static[pid] = {}
            ch.detail = self._static[pid]

            status = await self.api.get_point_status(pid)
            for idx, item in enumerate(status, start=1):
                ch.connectors[idx] = item
            if not ch.connectors:
                for cs in info.get("connectorStatusList") or []:
                    ch.connectors[int(cs.get("connectorId", 1))] = cs

            if slow or old is None:
                for conn in ch.connectors:
                    ch.default_limits[conn] = await _safe(
                        self.api.get_default_limit(pid, conn)
                    )
                ch.eco_setting = await _safe(self.api.get_eco_setting(pid)) or {}
                ch.plug_and_charge = await _safe(self.api.get_plug_and_charge(pid))
            else:
                ch.default_limits = old.default_limits
                ch.eco_setting = old.eco_setting
                ch.plug_and_charge = old.plug_and_charge
                ch.records = old.records
            chargers[pid] = ch

        price = prev.price if prev else {}
        if slow and chargers:
            records = await _safe(
                self.api.get_records(family_id, list(chargers), HISTORY_DAYS)
            ) or []
            for ch in chargers.values():
                ch.records = [r for r in records if str(r.get("pointId")) == ch.id]
            price = await _safe(self.api.get_price(family_id)) or {}
            self._last_slow = time.monotonic()

        return OcularData(family_id=family_id, user=user, chargers=chargers, price=price)

    def force_history_refresh(self) -> None:
        self._last_slow = 0.0


async def _safe(coro):
    """Optional endpoints: log and carry on if one fails."""
    try:
        return await coro
    except OcularAuthError:
        raise
    except OcularError as err:
        _LOGGER.debug("optional call failed: %s", err)
        return None
