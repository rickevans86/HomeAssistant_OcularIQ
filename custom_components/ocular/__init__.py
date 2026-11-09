"""Ocular EV Charger (cloud) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv
from pathlib import Path
import logging

from .api import OcularApi
from .const import CARD_VERSION, CONF_PASSWORD_HASH, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import OcularCoordinator

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


_LOGGER = logging.getLogger(__name__)

CARD_URL = "/ocular_static/ocular-charger-card.js"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card and load it on every dashboard."""
    if getattr(hass, "http", None) is None:
        return True  # headless install or tests: nothing to serve
    from homeassistant.components.http import StaticPathConfig

    card = Path(__file__).parent / "frontend" / "ocular-charger-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card), False)]
    )
    url = f"{CARD_URL}?v={CARD_VERSION}"
    try:
        registered = await _register_lovelace_resource(hass, url)
    except Exception as err:  # never block setup over the card
        _LOGGER.warning("Could not add the Ocular card to dashboard resources: %s", err)
        registered = False
    if not registered:
        # YAML-mode dashboards: inject the module into the frontend instead.
        try:
            from homeassistant.components.frontend import add_extra_js_url

            add_extra_js_url(hass, url)
        except Exception as err:
            _LOGGER.warning(
                "Could not load the Ocular card automatically (%s). Add %s as a "
                "JavaScript module resource on your dashboard", err, url
            )
    return True


async def _register_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Add (or update the version of) the card in the dashboard resources.

    Only possible when dashboards are managed from the UI (storage mode).
    """
    data = hass.data.get("lovelace")
    if data is None:
        return False
    if isinstance(data, dict):  # older Home Assistant
        mode, resources = data.get("mode"), data.get("resources")
    else:
        mode = getattr(data, "resource_mode", None) or getattr(data, "mode", None)
        resources = getattr(data, "resources", None)
    if mode != "storage" or resources is None or not hasattr(resources, "async_create_item"):
        return False

    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True

    base = url.split("?")[0]
    for item in resources.async_items():
        if str(item.get("url", "")).split("?")[0] == base:
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                _LOGGER.info("Updated Ocular card resource to %s", url)
            return True
    await resources.async_create_item({"res_type": "module", "url": url})
    _LOGGER.info("Added Ocular card to dashboard resources: %s", url)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = OcularApi(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD_HASH],
    )
    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = OcularCoordinator(hass, entry, api, interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
