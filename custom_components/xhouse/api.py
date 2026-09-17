from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    APP_TYPE,
    HMAC_SECRET_KEY,
    LOGGER,
    PLATFORM_CODE,
    SAAS_CODE,
)


SESSION_INVALID_CODES = frozenset(
    {"000000000011", "000000000008", "100009", "000000000010", "100012"}
)


class XHouseApiError(Exception):
    pass


class XHouseAuthError(XHouseApiError):
    pass


class XHouseApi:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.user_id: str | None = None
        self.token: str | None = None
        self._credentials: tuple[str, str] | None = None

    def _generate_signature(self) -> tuple[str, str]:
        timestamp = str(int(time.time()))
        signature = hmac.new(
            HMAC_SECRET_KEY.encode(),
            (PLATFORM_CODE + timestamp).encode(),
            hashlib.md5,
        ).hexdigest()
        return signature, timestamp

    def _build_headers(self, authenticated: bool = True) -> dict[str, str]:
        signature, timestamp = self._generate_signature()
        headers = {
            "apptype": APP_TYPE,
            "l": "EN",
            "platformcode": PLATFORM_CODE,
            "saascode": SAAS_CODE,
            "timestamp": timestamp,
            "signature": signature,
            "content-type": "application/json; charset=utf-8",
            "user-agent": "okhttp/4.2.0",
            "host": "iemp.giigleiot.net",
            "connection": "Keep-Alive",
        }
        if authenticated and self.token and self.user_id:
            headers["token"] = self.token
            headers["userid"] = self.user_id
            headers["phonetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return headers

    async def _api_post(
        self, endpoint: str, body: dict, authenticated: bool = True
    ) -> dict[str, Any]:
        headers = self._build_headers(authenticated=authenticated)
        body_string = json.dumps(body, separators=(",", ":"))
        headers["content-length"] = str(len(body_string.encode()))
        url = f"{API_BASE_URL}/{endpoint}"

        try:
            async with self._session.post(
                url, headers=headers, data=body_string, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                resp.raise_for_status()
                # A displaced session is answered with HTTP 200 but
                # content-type text/json, which aiohttp's strict decoder
                # rejects. Parse regardless so the code/msg can be seen.
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise XHouseApiError(f"API request to {endpoint} failed: {err}") from err

    async def login(self, email: str, password: str) -> bool:
        body = {
            "saasCode": SAAS_CODE,
            "type": "EMAIL",
            "email": email,
            "password": password,
            "appType": APP_TYPE.upper(),
        }
        data = await self._api_post("clientUser/login", body, authenticated=False)

        if data.get("code") == "0":
            self.user_id = data["result"]["userId"]
            self.token = data["result"]["token"]
            self._credentials = (email, password)
            LOGGER.debug("Login successful, user_id=%s", self.user_id)
            return True

        msg = data.get("msg", "Unknown error")
        raise XHouseAuthError(f"Login failed: {msg}")

    async def _post_authed(self, endpoint: str, body: dict) -> dict[str, Any]:
        """POST as the logged-in user, re-authenticating once if displaced.

        The account allows a single session: any other login (the phone app,
        another HA instance) invalidates this token. Recover transparently so
        a poll or command issued after that still succeeds.
        """
        data = await self._api_post(endpoint, body)
        try:
            self._check_token_error(data)
        except XHouseAuthError:
            if not self._credentials:
                raise
            LOGGER.warning(
                "XHouse session was displaced by another login; re-authenticating"
            )
            await self.login(*self._credentials)
            data = await self._api_post(endpoint, body)
            self._check_token_error(data)
        return data

    async def get_devices(self) -> list[dict[str, Any]]:
        data = await self._post_authed(
            "group/queryGroupDevices",
            {"userId": int(self.user_id), "groupId": 0},
        )
        if data.get("code") != "0":
            raise XHouseApiError(f"Failed to get devices: {data.get('msg')}")
        return (data.get("result") or {}).get("deviceInfos") or []

    async def get_device_properties(self, device_id: int) -> list[dict[str, Any]]:
        """Return the live property objects, including the gate status frame.

        The APK calls its polling helper ``getWifiDeviceKeysStatus``, but that
        helper resolves to this ``wifi/getWifiProperties`` HTTP route. The full
        objects are returned because SM18 modules carry per-channel ``mode``
        here, and the app reads it from this poll rather than the device list.
        """
        data = await self._post_authed(
            "wifi/getWifiProperties",
            {"userId": int(self.user_id), "deviceId": device_id},
        )
        if data.get("code") == "0":
            return (data.get("result") or {}).get("properties") or []
        msg = (data.get("msg") or "").lower()
        if "device offline" in msg:
            raise XHouseApiError("device offline")
        raise XHouseApiError(f"Failed to get device state: {data.get('msg')}")

    async def send_command(self, body: dict[str, Any]) -> bool:
        data = await self._post_authed("wifi/sendWifiCode", body)
        if data.get("code") == "0":
            return True
        msg = (data.get("msg") or "").lower()
        if "device offline" in msg:
            raise XHouseApiError("device offline")
        raise XHouseApiError(f"Failed to control device: {data.get('msg')}")

    def _check_token_error(self, data: dict) -> None:
        data = data or {}
        msg = (data.get("msg") or "").lower()
        # 000000000011 is what a displaced token gets ("token invalid!"); the
        # other four are the codes the app maps to its logged-out screen.
        if str(data.get("code")) in SESSION_INVALID_CODES or "token invalid" in msg:
            self.token = None
            self.user_id = None
            raise XHouseAuthError("Token invalid")
