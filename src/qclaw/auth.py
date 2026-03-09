"""WeChat OAuth2 QR-code login flow.

Implements the complete login sequence:

1. Fetch an OAuth ``state`` value from the QChat backend.
2. Build the WeChat authorization URL and display a QR code.
3. Wait for the user to scan and authorize.
4. Exchange the authorization ``code`` for JWT + channel tokens.
5. Optionally create a model API key.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import webbrowser
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from qclaw.api import QChatAPI, TokenExpiredError
from qclaw.config import Config
from qclaw.utils import nested_get

logger = logging.getLogger("qclaw.auth")

try:
    import qrcode as _qrcode_mod
except ImportError:
    _qrcode_mod = None  # QR display in terminal is optional


class WeChatLogin:
    """Encapsulates the WeChat scan-to-login flow."""

    def __init__(self, api: QChatAPI, config: Config) -> None:
        self.api = api
        self.config = config
        self.state = ""

    async def login(self) -> dict[str, Any]:
        """Execute the full login flow and return credentials.

        Returns
        -------
        dict
            Keys: ``jwt_token``, ``channel_token``, ``user_info``,
            ``api_key``, ``guid``.
        """
        env = self.config.env_config

        # 1. Obtain OAuth state
        logger.info("Step 1/5: obtaining login state…")
        state_result = await self.api.get_wx_login_state()
        if state_result.get("success"):
            self.state = (
                nested_get(state_result, "data", "state")
                or str(uuid.uuid4().int % 10000)
            )
        else:
            self.state = "233"  # QChat fallback
        logger.info("state=%s", self.state)

        # 2. Build authorization URL and show QR
        logger.info("Step 2/5: generating QR code…")
        auth_url = self._build_auth_url(env)
        self._show_qrcode(auth_url)

        # 3. Wait for the user to paste the code
        logger.info("Step 3/5: waiting for authorization…")
        code = await self._wait_for_code()
        if not code:
            raise RuntimeError("未获取到授权 code")

        # 4. Exchange code for tokens
        logger.info("Step 4/5: exchanging code for token…")
        login_result = await self.api.wx_login(code, self.state)
        if not login_result.get("success"):
            raise RuntimeError(
                f"登录失败: {login_result.get('message', '未知错误')}"
            )

        data = login_result["data"]
        jwt_token = data.get("token", "")
        channel_token = data.get("openclaw_channel_token", "")
        user_info = data.get("user_info", {})

        self.api.jwt_token = jwt_token
        self.api.user_id = str(user_info.get("user_id", ""))
        if user_info.get("loginKey"):
            self.api.login_key = user_info["loginKey"]

        nickname = user_info.get("nickname", "unknown")
        logger.info("Login successful! User: %s", nickname)
        print(f"[QChat] 登录成功! 用户: {nickname}")

        # 5. Create API key
        logger.info("Step 5/5: creating API key…")
        api_key = ""
        try:
            key_result = await self.api.create_api_key()
            if key_result.get("success"):
                api_key = (
                    nested_get(key_result, "data", "key")
                    or nested_get(key_result, "data", "resp", "data", "key")
                    or ""
                )
        except Exception as exc:
            logger.warning("Failed to create API key (non-fatal): %s", exc)

        return {
            "jwt_token": jwt_token,
            "channel_token": channel_token,
            "user_info": user_info,
            "api_key": api_key,
            "guid": self.api.guid,
        }

    # ------------------------------------------------------------------
    # Invite-code helpers
    # ------------------------------------------------------------------

    async def check_and_submit_invite_code(self, user_id: str) -> None:
        """Check invite-code status and prompt the user if needed."""
        try:
            check = await self.api.check_invite_code(user_id)
            if check.get("success"):
                verified = nested_get(check, "data", "already_verified")
                if not verified:
                    print("\n[QChat] 需要邀请码验证。")
                    loop = asyncio.get_running_loop()
                    code = await loop.run_in_executor(
                        None, lambda: input("请输入邀请码: ").strip()
                    )
                    if code:
                        result = await self.api.submit_invite_code(user_id, code)
                        if not result.get("success"):
                            raise SystemExit(
                                f"邀请码验证失败: {result.get('message')}"
                            )
                        print("[QChat] 邀请码验证通过!")
        except (TokenExpiredError, SystemExit):
            raise
        except Exception as exc:
            logger.warning("Invite-code check failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_auth_url(self, env: dict[str, str]) -> str:
        params = {
            "appid": env["wx_appid"],
            "redirect_uri": env["wx_login_redirect_uri"],
            "response_type": "code",
            "scope": "snsapi_login",
            "state": self.state,
        }
        return (
            f"https://open.weixin.qq.com/connect/qrconnect?"
            f"{urlencode(params)}#wechat_redirect"
        )

    @staticmethod
    def _show_qrcode(url: str) -> None:
        print(f"\n{'=' * 60}")
        print("请用微信扫描下方二维码登录")
        print(f"{'=' * 60}")

        if _qrcode_mod:
            qr = _qrcode_mod.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        else:
            print("\n(未安装 qrcode 库，无法在终端显示二维码)")
            print("请安装: pip install qrcode[pil]")

        print(f"\n或者在浏览器中打开以下链接：")
        print(f"  {url}")
        print(f"{'=' * 60}")

        try:
            webbrowser.open(url)
            print("(已自动打开浏览器)")
        except Exception:
            pass

    @staticmethod
    async def _wait_for_code() -> str:
        print()
        print("微信扫码授权后，浏览器会跳转到一个新页面。")
        print("请从浏览器地址栏复制完整 URL，或只复制 code 参数值。")
        print()

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None, lambda: input("请粘贴 URL 或 code: ").strip()
        )
        if not raw:
            return ""

        # Try to extract code from a URL
        if "code=" in raw:
            parsed = urlparse(raw)
            params = parse_qs(parsed.query)
            if "code" in params:
                return params["code"][0]
            params = parse_qs(parsed.fragment)
            if "code" in params:
                return params["code"][0]

        return raw
