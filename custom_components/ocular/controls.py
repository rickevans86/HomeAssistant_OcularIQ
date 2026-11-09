"""Helper for control entities: call the API then refresh soon after."""

from __future__ import annotations

import asyncio

from homeassistant.exceptions import HomeAssistantError

from .api import OcularError


async def run(entity, coro, delay: float = 3.0) -> None:
    try:
        await coro
    except OcularError as err:
        raise HomeAssistantError(f"Ocular: {err}") from err
    # The charger confirms via OCPP a moment later; give it time before re-polling.
    await asyncio.sleep(delay)
    await entity.coordinator.async_refresh()
