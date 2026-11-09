"""End-to-end test against a mock Ocular cloud that mimics the app's response shapes."""

import json
from unittest.mock import patch

import pytest
from aiohttp import web
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ocular.api import hash_password
from custom_components.ocular.const import DOMAIN

PID = "1234"
STATE = {"status": "Charging", "tid": 77, "calls": []}


def ok(data):
    return web.json_response({"code": 200, "message": "success", "data": data})


async def handler(request: web.Request):
    path = request.path
    STATE["calls"].append((request.method, path, dict(request.query), await request.text()))
    if path.endswith("/auth/login/customer"):
        body = await request.json()
        if body["password"] != hash_password("secret"):
            return web.json_response({"code": 500, "message": "bad password", "data": None})
        return ok({"accessToken": "tok", "refreshToken": "ref", "expiresIn": 3600})
    if request.headers.get("Authorization") != "bearer tok":
        return web.Response(status=401)
    if path.endswith("/app/customer/login"):
        return ok({"email": "a@b.c", "setting": {"familyId": 9, "language": "en"}})
    if path.endswith("/point/family/9/v2"):
        return ok([{"id": PID, "name": "Garage", "model": "IQ Solar", "current": 32,
                    "internalGatewayId": "gw1", "connectorStatusList": [{"connectorId": 1, "pointStatus": "Charging"}]}])
    if path.endswith(f"/app/point/{PID}"):
        return ok({"id": PID, "name": "Garage", "model": "IQ Solar", "serialNumber": "SN1",
                   "firmwareVersion": "1.2", "current": 32, "power": 7})
    if path.endswith(f"/point/status/{PID}/v2"):
        charging = STATE["status"] == "Charging"
        return ok({"pointStatusInfoList": [{
            "id": PID, "name": "Garage", "pointStatus": STATE["status"], "pluggedStatus": "Plugged",
            "currentCurrent": 15.5 if charging else 0, "limitCurrent": 16, "energy": 4.25, "power": 7,
            "current": 32, "eco": "Fast", "gatewayMode": "PV", "internalGatewayId": "gw1",
            "startTime": "2026-11-09T01:00:00.000Z", "transactionId": STATE["tid"] if charging else 0}]})
    if path.endswith("/limit/current"):
        return ok(16)
    if path.endswith(f"/app/eco/{PID}"):
        return ok({"defaultModel": "Fast"})
    if path.endswith("/plug/charging"):
        return ok(True)
    if path.endswith("/transaction/record"):
        return ok([
            {"pointId": PID, "startTime": "2026-11-07 08:00:00", "endTime": "2026-11-07 10:30:00",
             "electricValue": 12.5, "priceStr": "$3.75", "firstName": "Rick"},
            {"pointId": PID, "startTime": "2026-11-08 08:00:00", "endTime": "2026-11-08 09:00:00",
             "electricValue": 5.0, "priceStr": "$1.50"},
        ])
    if path.endswith("/price"):
        return ok({"price": 0.3, "currencySign": "$"})
    if path.endswith("/remoteStop"):
        STATE["status"] = "Available"
        return ok(True)
    if path.endswith("/remoteStart"):
        STATE["status"] = "Charging"
        return ok(True)
    return ok(True)


@pytest.fixture
async def mock_cloud(socket_enabled, unused_tcp_port):
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = unused_tcp_port
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    with patch("custom_components.ocular.api.BASE_URL", f"http://127.0.0.1:{port}/"), \
         patch("custom_components.ocular.controls.asyncio.sleep", return_value=None):
        yield
    await runner.cleanup()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_config_flow_and_entities(hass: HomeAssistant, mock_cloud):
    # bad password
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"username": "a@b.c", "password": "nope"})
    assert r["errors"] == {"base": "invalid_auth"}
    # good password
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"username": "a@b.c", "password": "secret"})
    assert r["type"] == "create_entry"
    assert "password" not in r["data"] and r["data"]["password_hash"] == hash_password("secret")
    await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all()}
    for eid, s in sorted(states.items()):
        print(eid, s.state)

    assert states["sensor.garage_status"].state == "Charging"
    assert float(states["sensor.garage_charging_current"].state) == 15.5
    assert float(states["sensor.garage_session_energy"].state) == 4.25
    assert float(states["sensor.garage_charging_power_estimated"].state) == round(15.5 * 230)
    assert float(states["sensor.garage_energy_last_30_days"].state) == 17.5
    assert float(states["sensor.garage_last_session_energy"].state) == 5.0
    assert states["sensor.garage_last_session_duration"].state == "60"
    assert states["binary_sensor.garage_charging"].state == "on"
    assert states["binary_sensor.garage_plugged_in"].state == "on"
    assert states["switch.garage_charge"].state == "on"
    assert states["switch.garage_plug_and_charge"].state == "on"
    assert float(states["number.garage_session_current_limit"].state) == 16
    assert float(states["number.garage_default_current_limit"].state) == 16
    assert states["select.garage_solar_charging_mode"].state == "Solar Assist"
    assert states["select.garage_session_charge_mode"].state == "Fast"

    # stop charging -> remoteStop with the transaction id
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.garage_charge"}, blocking=True)
    assert any(c[1].endswith("/transaction/77/remoteStop") and c[0] == "PUT" for c in STATE["calls"])
    assert hass.states.get("switch.garage_charge").state == "off"
    assert hass.states.get("number.garage_session_current_limit").state == "unavailable"

    # start charging
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.garage_charge"}, blocking=True)
    assert any(c[1].endswith(f"/point/{PID}/1/remoteStart") for c in STATE["calls"])

    # session current
    await hass.services.async_call("number", "set_value", {"entity_id": "number.garage_session_current_limit", "value": 10}, blocking=True)
    assert any(c[1].endswith("/transaction/77/setLimitCurrent") and c[2].get("limitCurrent") == "10.0" for c in STATE["calls"])

    # solar mode
    await hass.services.async_call("select", "select_option", {"entity_id": "select.garage_solar_charging_mode", "option": "Solar"}, blocking=True)
    assert any(c[1].endswith("/energy/gw1/ecoMode") and c[2].get("mode") == "PV_plus" for c in STATE["calls"])

    # session mode body
    await hass.services.async_call("select", "select_option", {"entity_id": "select.garage_session_charge_mode", "option": "Eco"}, blocking=True)
    assert any(c[1].endswith("/transaction/77/setting") and json.loads(c[3]) == {"eco": "Eco"} for c in STATE["calls"])

    # refresh button: repeated connectorList params
    await hass.services.async_call("button", "press", {"entity_id": "button.garage_refresh_status"}, blocking=True)
    assert any(c[1].endswith("/connector/refreshStatus") and c[2].get("connectorList") == "1" for c in STATE["calls"])
    # every request carried lang=en
    assert all(c[2].get("lang") == "en" for c in STATE["calls"])
