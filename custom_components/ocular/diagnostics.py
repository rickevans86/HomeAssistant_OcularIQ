"""Diagnostics download: raw cloud data with personal fields redacted."""

from __future__ import annotations

from dataclasses import asdict

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_PASSWORD_HASH, DOMAIN

REDACT = {
    CONF_PASSWORD_HASH, "username", "email", "account", "phoneNumber", "address",
    "zipCode", "firstName", "lastName", "headUrl", "serialNumber", "code",
    "androidToken", "iosToken", "idTag", "rfCardName", "evccId", "familyName",
}


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "family_id": data.family_id if data else None,
            "user": data.user if data else None,
            "price": data.price if data else None,
            "chargers": {k: asdict(v) for k, v in data.chargers.items()} if data else None,
        },
        REDACT,
    )
