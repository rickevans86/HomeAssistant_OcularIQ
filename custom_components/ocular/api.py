"""Async client for the Ocular / IoCharger family cloud API.

Endpoints, auth and payloads were taken from the Ocular Android app v1.7.9.
Every response is wrapped as {"code": int, "message": str, "data": ...};
code 200 means success.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import BASE_URL, LANG

_LOGGER = logging.getLogger(__name__)


class OcularError(Exception):
    """General API error."""


class OcularAuthError(OcularError):
    """Credentials rejected."""


def hash_password(password: str) -> str:
    """The app sends md5(md5(password)) as lowercase hex."""
    once = hashlib.md5(password.encode()).hexdigest()
    return hashlib.md5(once.encode()).hexdigest()


def _iso(dt: datetime, zero_millis: bool = False) -> str:
    dt = dt.astimezone(timezone.utc)
    ms = "000" if zero_millis else f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


class OcularApi:
    """Thin wrapper around the Ocular cloud REST API."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password_hash: str
    ) -> None:
        self._session = session
        self._username = username
        self._password_hash = password_hash
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ auth
    async def login(self) -> None:
        data = await self._raw(
            "POST",
            "family-user-service/auth/login/customer",
            json={"username": self._username, "password": self._password_hash},
            auth=False,
        )
        self._store_tokens(data)

    async def _refresh(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            data = await self._raw(
                "GET",
                "family-user-service/auth/token/refresh",
                params={"refreshToken": self._refresh_token},
                auth=False,
            )
        except OcularError:
            return False
        self._store_tokens(data)
        return True

    def _store_tokens(self, data: Any) -> None:
        if not isinstance(data, dict) or not data.get("accessToken"):
            raise OcularAuthError(f"Unexpected login response: {data}")
        self._access_token = data["accessToken"]
        self._refresh_token = data.get("refreshToken")

    # --------------------------------------------------------------- transport
    async def _raw(
        self,
        method: str,
        path: str,
        params: dict | list | None = None,
        json: Any = None,
        auth: bool = True,
    ) -> Any:
        """Send one request; return `data`, or raise. Status 401 -> _Unauthorized."""
        if isinstance(params, list):  # repeated keys, e.g. connectorList=1&connectorList=2
            params = [*params, ("lang", LANG)]
        else:
            params = {**(params or {}), "lang": LANG}
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"bearer {self._access_token}"
        url = BASE_URL + path
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                text = await resp.text()
                _LOGGER.debug("%s %s %s -> %s %s", method, path, params, resp.status, text)
                if resp.status == 401:
                    raise _Unauthorized
                if resp.status >= 400:
                    raise OcularError(f"HTTP {resp.status} for {path}: {text[:200]}")
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise OcularError(f"Cannot reach Ocular cloud: {err}") from err

        code = body.get("code") if isinstance(body, dict) else None
        if code == 401:
            raise _Unauthorized
        if code != 200:
            msg = body.get("message") if isinstance(body, dict) else body
            if not auth:
                raise OcularAuthError(msg or f"code {code}")
            raise OcularError(f"{path}: {msg} (code {code})")
        return body.get("data")

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        async with self._lock:
            if not self._access_token:
                await self.login()
        try:
            return await self._raw(method, path, **kw)
        except _Unauthorized:
            async with self._lock:
                if not await self._refresh():
                    await self.login()
            try:
                return await self._raw(method, path, **kw)
            except _Unauthorized as err:
                raise OcularAuthError("Token rejected after re-login") from err

    # ------------------------------------------------------------- read data
    async def get_user(self) -> dict:
        return await self._call("GET", "family-user-service/app/customer/login") or {}

    async def get_families(self) -> list:
        return await self._call("GET", "family-user-service/app/family") or []

    async def get_family_points(self, family_id: int | str) -> list:
        data = await self._call(
            "GET", f"family-device-service/app/point/family/{family_id}/v2"
        )
        return _as_list(data)

    async def get_point_detail(self, point_id: str) -> dict:
        return await self._call("GET", f"family-device-service/app/point/{point_id}") or {}

    async def get_point_status(self, point_id: str) -> list:
        data = await self._call(
            "GET", f"family-device-service/app/point/status/{point_id}/v2"
        )
        if isinstance(data, dict):
            return data.get("pointStatusInfoList") or []
        return _as_list(data)

    async def get_default_limit(self, point_id: str, connector: int) -> Any:
        return await self._call(
            "GET", f"family-device-service/app/point/{point_id}/{connector}/limit/current"
        )

    async def get_eco_setting(self, point_id: str) -> dict:
        return await self._call("GET", f"family-device-service/app/eco/{point_id}") or {}

    async def get_plans(self, point_id: str) -> list:
        return _as_list(
            await self._call("GET", f"family-device-service/app/plan/point/{point_id}")
        )

    async def get_records(
        self, family_id: int | str, point_ids: list[str], days: int
    ) -> list:
        end = datetime.now(timezone.utc)
        start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0)
        data = await self._call(
            "GET",
            "family-device-service/app/transaction/record",
            params={
                "pointIds": ",".join(point_ids),
                "startTime": _iso(start, zero_millis=True),
                "endTime": _iso(end),
                "familyId": str(family_id),
            },
        )
        return _as_list(data)

    async def get_price(self, family_id: int | str) -> dict:
        return await self._call("GET", f"family-user-service/app/family/{family_id}/price") or {}

    async def firmware_is_latest(self, point_id: str) -> Any:
        return await self._call(
            "GET", f"family-device-service/app/point/{point_id}/firmwareIsLatestVersion"
        )

    # --------------------------------------------------------------- control
    async def remote_start(self, point_id: str, connector: int) -> Any:
        return await self._call(
            "PUT", f"family-device-service/app/point/{point_id}/{connector}/remoteStart"
        )

    async def remote_stop(self, transaction_id: int) -> Any:
        return await self._call(
            "PUT", f"family-device-service/app/transaction/{transaction_id}/remoteStop"
        )

    async def set_session_current(self, transaction_id: int, amps: float) -> Any:
        # Note: the app really uses GET for this one.
        return await self._call(
            "GET",
            f"family-device-service/app/transaction/{transaction_id}/setLimitCurrent",
            params={"limitCurrent": str(amps)},
        )

    async def set_default_limit(self, point_id: str, connector: int, amps: float) -> Any:
        return await self._call(
            "PUT",
            f"family-device-service/app/point/{point_id}/{connector}/limit/current",
            params={"currentValue": str(int(amps))},
        )

    async def set_session_mode(self, transaction_id: int, mode: str) -> Any:
        return await self._call(
            "PUT",
            f"family-device-service/app/transaction/{transaction_id}/setting",
            json={"eco": mode},
        )

    async def set_solar_mode(self, gateway_id: str, mode: str) -> Any:
        return await self._call(
            "PUT",
            f"family-device-service/app/energy/{gateway_id}/ecoMode",
            params={"mode": mode},
        )

    async def set_plug_and_charge(self, point_id: str, enabled: bool) -> Any:
        return await self._call(
            "PUT",
            f"family-device-service/app/point/{point_id}/plug/charging",
            params={"valid": "true" if enabled else "false"},
        )

    async def get_plug_and_charge(self, point_id: str) -> Any:
        return await self._call(
            "GET", f"family-device-service/app/point/{point_id}/plug/charging"
        )

    async def refresh_status(self, point_id: str, connectors: list[int]) -> Any:
        return await self._call(
            "PUT",
            f"family-device-service/app/point/{point_id}/connector/refreshStatus",
            params=[("connectorList", str(c)) for c in connectors],
        )

    async def reboot(self, point_id: str) -> Any:
        return await self._call(
            "PUT", f"family-device-service/app/point/{point_id}/reset", params={"type": "Soft"}
        )


class _Unauthorized(Exception):
    pass


def _as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "records", "rows", "content", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []
