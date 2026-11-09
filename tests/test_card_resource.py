"""The card is added to dashboard resources once and its version kept current."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.ocular import _register_lovelace_resource


async def test_resource_registration(hass: HomeAssistant):
    assert await async_setup_component(hass, "lovelace", {})
    resources = hass.data["lovelace"].resources

    assert await _register_lovelace_resource(hass, "/ocular_static/ocular-charger-card.js?v=0.2.0")
    assert await _register_lovelace_resource(hass, "/ocular_static/ocular-charger-card.js?v=0.2.0")
    items = resources.async_items()
    assert len(items) == 1 and items[0]["type"] == "module"

    assert await _register_lovelace_resource(hass, "/ocular_static/ocular-charger-card.js?v=0.2.1")
    items = resources.async_items()
    assert len(items) == 1 and items[0]["url"].endswith("v=0.2.1")
