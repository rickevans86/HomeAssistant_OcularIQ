"""Shared entity helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Charger, OcularCoordinator


class OcularEntity(CoordinatorEntity[OcularCoordinator]):
    """Entity tied to one charger, optionally one connector."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OcularCoordinator, point_id: str, key: str, connector: int | None = None
    ) -> None:
        super().__init__(coordinator)
        self.point_id = point_id
        self.connector = connector
        suffix = f"_{connector}" if connector and connector > 1 else ""
        self._attr_unique_id = f"{point_id}_{key}{suffix}"
        self._attr_translation_key = key
        ch = self.charger
        detail = ch.detail if ch else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, point_id)},
            name=ch.name if ch else point_id,
            manufacturer="Ocular",
            model=detail.get("model") or (ch.info.get("model") if ch else None),
            serial_number=detail.get("serialNumber"),
            sw_version=detail.get("firmwareVersion"),
        )

    @property
    def charger(self) -> Charger | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.chargers.get(self.point_id)

    @property
    def conn(self) -> dict:
        ch = self.charger
        if not ch:
            return {}
        return ch.connectors.get(self.connector or 1, {})

    @property
    def transaction_id(self) -> int | None:
        tid = self.conn.get("transactionId")
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            return None
        return tid if tid > 0 else None

    @property
    def max_current(self) -> float:
        ch = self.charger
        for v in (
            (ch.detail.get("current") if ch else None),
            (ch.info.get("current") if ch else None),
            self.conn.get("current"),
        ):
            try:
                if v and float(v) > 0:
                    return float(v)
            except (TypeError, ValueError):
                pass
        return 32.0

    @property
    def available(self) -> bool:
        return super().available and self.charger is not None


def num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
