"""QChat backend HTTP API client.

All requests go through the JPRX gateway at ``{jprx_gateway}{path}``
(e.g. ``https://jprx.m.qq.com/data/4026/forward``).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from qclaw.config import Config
from qclaw.utils import nested_get

logger = logging.getLogger("qclaw.api")


class TokenExpiredError(Exception):
    """Raised when the server reports the login token has expired (code 21004)."""


class QChatAPI:
    """Async HTTP client for the QChat / OpenClaw backend.

    Parameters
    ----------
    config : Config
        SDK configuration (selects environment URLs).
    guid : str
        Device GUID.
    jwt_token : str
        JWT login token (set after successful login).
    """

    def __init__(
        self,
        config: Config,
        guid: str = "",
        jwt_token: str = "",
    ) -> None:
        self.config = config
        self.guid = guid
        self.jwt_token = jwt_token
        self.user_id = ""
        self.login_key = "m83qdao0AmE5"  # default from QChat source

    # ----- internal helpers ------------------------------------------------

    @property
    def _env(self) -> dict[str, str]:
        return self.config.env_config

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Version": "1",
            "X-Token": self.login_key,
            "X-Guid": self.guid,
            "X-Account": self.user_id or "1",
            "X-Session": "",
        }
        if self.jwt_token:
            headers["X-OpenClaw-Token"] = self.jwt_token
        return headers

    def _url(self, path: str) -> str:
        return f"{self._env['jprx_gateway']}{path}"

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {**(body or {}), "web_version": "1.4.0", "web_env": "release"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._url(path),
                headers=self._headers(),
                json=payload,
            )
            # Handle token renewal
            new_token = resp.headers.get("X-New-Token")
            if new_token:
                self.jwt_token = new_token
            data = resp.json()

        ret = data.get("ret")
        common_code = (
            nested_get(data, "data", "resp", "common", "code")
            or nested_get(data, "data", "common", "code")
            or nested_get(data, "resp", "common", "code")
            or nested_get(data, "common", "code")
        )

        # Token expired
        if common_code == 21004:
            raise TokenExpiredError("登录已过期，请重新登录")

        if ret == 0 or common_code == 0:
            return {
                "success": True,
                "data": (
                    nested_get(data, "data", "resp", "data")
                    or nested_get(data, "data", "data")
                    or data.get("data")
                    or data
                ),
            }

        msg = (
            nested_get(data, "data", "common", "message")
            or nested_get(data, "resp", "common", "message")
            or nested_get(data, "common", "message")
            or "请求失败"
        )
        return {"success": False, "message": msg, "data": data}

    # ----- public business APIs -------------------------------------------

    async def get_wx_login_state(self) -> dict[str, Any]:
        """Obtain an OAuth *state* value for the WeChat login flow."""
        return await self._post("data/4050/forward", {"guid": self.guid})

    async def wx_login(self, code: str, state: str) -> dict[str, Any]:
        """Exchange a WeChat authorization *code* for tokens."""
        return await self._post(
            "data/4026/forward",
            {"guid": self.guid, "code": code, "state": state},
        )

    async def create_api_key(self) -> dict[str, Any]:
        """Create a model API key."""
        return await self._post("data/4055/forward", {})

    async def get_user_info(self) -> dict[str, Any]:
        """Retrieve current user information."""
        return await self._post("data/4027/forward", {})

    async def check_invite_code(self, user_id: str) -> dict[str, Any]:
        """Check whether the user has completed invite-code verification."""
        return await self._post("data/4056/forward", {"user_id": user_id})

    async def submit_invite_code(self, user_id: str, code: str) -> dict[str, Any]:
        """Submit an invite code for verification."""
        return await self._post("data/4057/forward", {"user_id": user_id, "code": code})

    async def refresh_channel_token(self) -> Optional[str]:
        """Refresh the WebSocket channel token.  Returns ``None`` on failure."""
        result = await self._post("data/4058/forward", {})
        if result.get("success"):
            return result["data"].get("openclaw_channel_token")
        return None
