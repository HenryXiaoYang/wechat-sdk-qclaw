"""Core bot class — handler registration, dispatch, and run loop.

This is the main entry point for building a QChat WeChat bot.  It ties
together authentication, the AGP WebSocket transport, and user-defined
message handlers behind an ItChat-style API.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import signal
import threading
import uuid
from typing import Any, Callable, Optional

from qclaw.api import QChatAPI, TokenExpiredError
from qclaw.auth import WeChatLogin
from qclaw.config import Config, clear_state, load_state, save_state
from qclaw.message import Message, content
from qclaw.reply import ReplyContext
from qclaw.transport.protocol import (
    StopReason,
    extract_text,
    make_prompt_response,
)
from qclaw.transport.websocket import AGPClientConfig, AGPWebSocketClient
from qclaw.utils import get_machine_guid, nested_get

logger = logging.getLogger("qclaw")

# ---------------------------------------------------------------------------
# Handler metadata (attached at registration time)
# ---------------------------------------------------------------------------

_ATTR_IS_ASYNC = "_qchat_is_async"
_ATTR_PARAM_COUNT = "_qchat_param_count"


def _annotate_handler(fn: Callable) -> Callable:
    """Inspect *fn* once and cache its metadata on the function object."""
    sig = inspect.signature(fn)
    required = sum(
        1
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    )
    setattr(fn, _ATTR_IS_ASYNC, asyncio.iscoroutinefunction(fn))
    setattr(fn, _ATTR_PARAM_COUNT, required)
    return fn


# ---------------------------------------------------------------------------
# QChat bot
# ---------------------------------------------------------------------------


class QChat:
    """WeChat chatbot powered by the QChat / OpenClaw backend.

    Parameters
    ----------
    env : str
        ``"production"`` or ``"test"``.
    config : Config | None
        Full configuration object.  When supplied, *env* is ignored.

    Quick start::

        from qclaw import QChat, content

        bot = QChat()

        @bot.msg_register(content.TEXT)
        def echo(msg):
            return f"Echo: {msg.text}"

        bot.auto_login()
        bot.run()
    """

    def __init__(
        self,
        env: str = "production",
        config: Config | None = None,
    ) -> None:
        self._config = config or Config(env=env)
        self._handlers: dict[str, Callable] = {}
        self._ws_client: Optional[AGPWebSocketClient] = None
        self._api: Optional[QChatAPI] = None
        self._credentials: dict[str, Any] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    # ---- public: handler registration ------------------------------------

    def msg_register(self, msg_type: str = content.TEXT):
        """Decorator that registers a handler for the given message type.

        The handler may be sync or async, and may accept one or two
        positional arguments:

        - ``fn(msg)`` — receive a :class:`Message`; return a string to reply.
        - ``fn(msg, reply)`` — additionally receive a :class:`ReplyContext`
          for streaming chunks and tool calls.
        """

        def decorator(fn: Callable) -> Callable:
            _annotate_handler(fn)
            self._handlers[msg_type] = fn
            logger.debug("Registered handler for %r", msg_type)
            return fn

        return decorator

    # ---- public: login ---------------------------------------------------

    def auto_login(
        self,
        hot_reload: bool = True,
        skip_invite: bool = True,
    ) -> dict[str, Any]:
        """Log in via WeChat QR code scan (synchronous wrapper).

        When *hot_reload* is ``True`` (default), cached credentials are
        reused if available, skipping the QR-code step.

        When *skip_invite* is ``True`` (default), the invite-code
        verification step is skipped entirely.

        Returns the credentials dict.
        """
        return asyncio.run(
            self.auto_login_async(hot_reload=hot_reload, skip_invite=skip_invite)
        )

    async def auto_login_async(
        self,
        hot_reload: bool = True,
        skip_invite: bool = True,
    ) -> dict[str, Any]:
        """Async version of :meth:`auto_login`."""
        guid = get_machine_guid()

        # Try cached credentials
        if hot_reload:
            state = load_state(self._config.state_file)
            if state.get("channel_token"):
                logger.info(
                    "Reusing cached token: %s…", state["channel_token"][:6]
                )
                print(
                    f"[QChat] 使用已保存的 token: {state['channel_token'][:6]}…"
                )
                print("       (使用 hot_reload=False 强制重新登录)")
                self._credentials = state
                self._credentials.setdefault("guid", guid)
                return self._credentials

        # Full login flow
        api = QChatAPI(self._config, guid=guid)
        self._api = api
        login_flow = WeChatLogin(api, self._config)
        credentials = await login_flow.login()

        # Invite-code check (skipped by default — server doesn't enforce it)
        user_id = str(credentials.get("user_info", {}).get("user_id", ""))
        if user_id and not skip_invite:
            await login_flow.check_and_submit_invite_code(user_id)

        # Persist
        save_state(
            self._config.state_file,
            {
                "jwt_token": credentials["jwt_token"],
                "channel_token": credentials["channel_token"],
                "api_key": credentials.get("api_key", ""),
                "guid": credentials["guid"],
                "user_info": credentials.get("user_info", {}),
            },
        )
        self._credentials = credentials
        return credentials

    # ---- public: run / stop ----------------------------------------------

    def run(self, block: bool = True) -> None:
        """Start the bot's event loop (synchronous wrapper).

        Parameters
        ----------
        block : bool
            If ``True`` (default), blocks the calling thread until the
            bot is stopped.  If ``False``, the event loop runs in a
            background daemon thread.
        """
        if block:
            asyncio.run(self.run_async())
        else:
            self._thread = threading.Thread(
                target=self._run_in_thread, daemon=True
            )
            self._thread.start()

    async def run_async(self) -> None:
        """Async version of :meth:`run`."""
        token = self._credentials.get("channel_token", "")
        if not token:
            raise RuntimeError(
                "No channel token.  Call auto_login() first."
            )

        guid = self._credentials.get("guid", "")
        ws_url = self._config.env_config["wechat_ws_url"]

        config = AGPClientConfig(
            url=ws_url,
            token=token,
            guid=guid,
            heartbeat_interval=self._config.heartbeat_interval,
            reconnect_interval=self._config.reconnect_interval,
            max_reconnect_attempts=self._config.max_reconnect_attempts,
        )
        client = AGPWebSocketClient(config)
        self._ws_client = client

        # Wire callbacks
        client.on_prompt(self._handle_prompt)
        client.on_cancel(self._handle_cancel)

        self._loop = asyncio.get_running_loop()

        # Graceful shutdown on SIGINT / SIGTERM
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._loop.add_signal_handler(sig, client.stop)

        print(f"[QChat] 启动机器人，连接 {ws_url}")
        print("[QChat] 等待微信用户消息…")
        await client.start()

    def stop(self) -> None:
        """Stop the bot gracefully."""
        if self._ws_client:
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._ws_client.stop)
            else:
                self._ws_client.stop()

    def logout(self) -> None:
        """Clear saved login credentials."""
        clear_state(self._config.state_file)
        self._credentials = {}
        print("[QChat] 已清除登录态。")

    # ---- internal: dispatch ----------------------------------------------

    async def _handle_prompt(self, envelope: dict) -> None:
        """Dispatch an incoming ``session.prompt`` to the registered handler."""
        payload = envelope.get("payload", {})
        session_id = payload.get("session_id", "")
        prompt_id = payload.get("prompt_id", "")
        content_blocks = payload.get("content", [])
        guid = envelope.get("guid", "")
        user_id = envelope.get("user_id", "")
        agent_app = payload.get("agent_app", "")

        user_text = extract_text(content_blocks)
        logger.info("Received message from user=%s: %s", user_id, user_text[:100])

        msg = Message(
            msg_id=envelope.get("msg_id", str(uuid.uuid4())),
            session_id=session_id,
            prompt_id=prompt_id,
            guid=guid,
            user_id=user_id,
            type=content.TEXT,
            text=user_text,
            agent_app=agent_app,
            raw=envelope,
        )

        assert self._ws_client is not None

        try:
            reply_text = await self._dispatch_to_handler(msg)

            await self._ws_client.send(
                make_prompt_response(
                    session_id,
                    prompt_id,
                    stop_reason=StopReason.END_TURN,
                    text=reply_text,
                    guid=guid,
                    user_id=user_id,
                )
            )
        except Exception as exc:
            logger.error("Handler error: %s", exc, exc_info=True)
            await self._ws_client.send(
                make_prompt_response(
                    session_id,
                    prompt_id,
                    stop_reason=StopReason.ERROR,
                    error=str(exc),
                    guid=guid,
                    user_id=user_id,
                )
            )

    async def _handle_cancel(self, envelope: dict) -> None:
        """Handle an incoming ``session.cancel``."""
        payload = envelope.get("payload", {})
        session_id = payload.get("session_id", "")
        prompt_id = payload.get("prompt_id", "")
        guid = envelope.get("guid", "")
        user_id = envelope.get("user_id", "")

        logger.info("Cancel received for prompt_id=%s", prompt_id)

        if self._ws_client:
            await self._ws_client.send(
                make_prompt_response(
                    session_id,
                    prompt_id,
                    stop_reason=StopReason.CANCELLED,
                    guid=guid,
                    user_id=user_id,
                )
            )

    async def _dispatch_to_handler(self, msg: Message) -> Optional[str]:
        """Find and invoke the matching handler for *msg*."""
        handler = self._handlers.get(msg.type)
        if handler is None:
            return f"Echo: {msg.text}"

        is_async = getattr(handler, _ATTR_IS_ASYNC, False)
        param_count = getattr(handler, _ATTR_PARAM_COUNT, 1)

        # Build args
        if param_count >= 2:
            assert self._ws_client is not None
            reply_ctx = ReplyContext(
                self._ws_client,
                msg.session_id,
                msg.prompt_id,
                msg.guid,
                msg.user_id,
            )
            args: tuple = (msg, reply_ctx)
        else:
            args = (msg,)

        if is_async:
            result = await handler(*args)
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, handler, *args)

        if isinstance(result, str):
            return result
        return None

    # ---- internal: background thread -------------------------------------

    def _run_in_thread(self) -> None:
        """Entry point for ``run(block=False)``."""
        asyncio.run(self.run_async())
