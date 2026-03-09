"""AGP WebSocket client — pure transport layer.

Handles connection lifecycle, heartbeat, reconnection with exponential
back-off, and message de-duplication.  Business-level dispatch is *not*
done here; the client simply fires callbacks when messages arrive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse, urlunparse

import websockets
from websockets.asyncio.client import connect as ws_connect

from qclaw.transport.protocol import extract_text

logger = logging.getLogger("qclaw.transport")

# Type aliases for callbacks
PromptCallback = Callable[[dict], Awaitable[None]]
CancelCallback = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# Message de-duplicator
# ---------------------------------------------------------------------------


class _Deduplicator:
    """Bounded, TTL-based message-ID de-duplication."""

    def __init__(self, ttl: float = 300.0, max_size: int = 5000) -> None:
        self._seen: dict[str, float] = {}
        self._ttl = ttl
        self._max_size = max_size

    def is_duplicate(self, msg_id: str) -> bool:
        now = time.monotonic()
        if len(self._seen) > self._max_size:
            cutoff = now - self._ttl
            self._seen = {k: v for k, v in self._seen.items() if v > cutoff}
        if msg_id in self._seen:
            return True
        self._seen[msg_id] = now
        return False

    def clear(self) -> None:
        self._seen.clear()


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------


@dataclass
class AGPClientConfig:
    """Connection parameters for the AGP WebSocket gateway."""

    url: str = ""
    token: str = ""
    guid: str = ""
    user_id: str = ""
    heartbeat_interval: float = 20.0
    reconnect_interval: float = 3.0
    max_reconnect_attempts: int = 0


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------


class AGPWebSocketClient:
    """Async WebSocket client for the AGP gateway.

    The client is a pure transport layer.  Register callbacks via the
    ``on_prompt``, ``on_cancel``, ``on_connected``, ``on_disconnected``,
    and ``on_error`` setter methods.
    """

    def __init__(self, config: AGPClientConfig) -> None:
        self.config = config
        self._ws: Optional[object] = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._reconnect_attempts = 0
        self._dedup = _Deduplicator()

        # Callbacks — set by the owner (core.py)
        self._prompt_handler: Optional[PromptCallback] = None
        self._cancel_handler: Optional[CancelCallback] = None
        self._on_connected: Optional[Callable[[], None]] = None
        self._on_disconnected: Optional[Callable[[str], None]] = None
        self._on_error: Optional[Callable[[Exception], None]] = None

    # ---- callback setters ------------------------------------------------

    def on_prompt(self, handler: PromptCallback) -> None:
        self._prompt_handler = handler

    def on_cancel(self, handler: CancelCallback) -> None:
        self._cancel_handler = handler

    def on_connected(self, handler: Callable[[], None]) -> None:
        self._on_connected = handler

    def on_disconnected(self, handler: Callable[[str], None]) -> None:
        self._on_disconnected = handler

    def on_error(self, handler: Callable[[Exception], None]) -> None:
        self._on_error = handler

    # ---- public lifecycle ------------------------------------------------

    async def start(self) -> None:
        """Connect to the gateway and run the message loop.

        Blocks until :meth:`stop` is called or max reconnect attempts are
        exhausted.
        """
        if not self.config.token:
            logger.warning("token is empty — cannot connect")
            return
        if not self.config.url:
            logger.warning("url is empty — cannot connect")
            return

        logger.info("Starting AGP client — target: %s", self.config.url)
        self._stop_event.clear()

        while not self._stop_event.is_set():
            try:
                await self._connect_and_run()
            except Exception as exc:
                logger.error("Connection error: %s", exc)

            if self._stop_event.is_set():
                break

            self._reconnect_attempts += 1
            max_att = self.config.max_reconnect_attempts
            if max_att > 0 and self._reconnect_attempts > max_att:
                logger.error(
                    "Max reconnect attempts reached (%d)", max_att
                )
                break

            delay = min(
                self.config.reconnect_interval
                * (1.5 ** (self._reconnect_attempts - 1)),
                25.0,
            )
            logger.info(
                "Reconnecting in %.1fs (attempt %d)…",
                delay,
                self._reconnect_attempts,
            )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                break
            except asyncio.TimeoutError:
                pass

        logger.info("AGP client stopped")

    def stop(self) -> None:
        """Request the client to stop (may be called from any thread)."""
        logger.info("Stopping AGP client…")
        self._stop_event.set()

    @property
    def connected(self) -> bool:
        return self._connected

    async def send(self, data: str) -> None:
        """Send a raw JSON string through the WebSocket."""
        if self._ws and self._connected:
            await self._ws.send(data)
            logger.debug(">>> %s", data[:200])

    # ---- internal --------------------------------------------------------

    def _build_url(self) -> str:
        parsed = urlparse(self.config.url)
        query = f"token={self.config.token}" if self.config.token else ""
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment)
        )

    async def _connect_and_run(self) -> None:
        url = self._build_url()
        token_preview = self.config.token[:6] + "…" if self.config.token else "(empty)"
        logger.info("Connecting… token=%s", token_preview)

        async with ws_connect(url, ping_interval=None) as ws:
            self._ws = ws
            self._connected = True
            self._reconnect_attempts = 0
            logger.info("Connected! Waiting for messages…")
            if self._on_connected:
                self._on_connected()

            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            try:
                await self._message_loop()
            finally:
                heartbeat_task.cancel()
                self._connected = False
                self._ws = None
                logger.info("Disconnected")

    async def _heartbeat_loop(self) -> None:
        try:
            while self._connected and not self._stop_event.is_set():
                await asyncio.sleep(self.config.heartbeat_interval)
                if self._ws and self._connected:
                    try:
                        pong = await self._ws.ping()
                        await asyncio.wait_for(pong, timeout=10.0)
                    except Exception as exc:
                        logger.warning("Heartbeat failed: %s", exc)
                        if self._ws:
                            await self._ws.close()
                        return
        except asyncio.CancelledError:
            pass

    async def _message_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                await self._handle_message(raw)
        except websockets.ConnectionClosed as exc:
            reason = f"code={exc.code} reason={exc.reason}"
            logger.info("Connection closed: %s", reason)
            if self._on_disconnected:
                self._on_disconnected(reason)

    async def _handle_message(self, raw: str) -> None:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error: %s", exc)
            return

        msg_id = envelope.get("msg_id", "")
        method = envelope.get("method", "")

        if self._dedup.is_duplicate(msg_id):
            return

        logger.debug("<<< method=%s msg_id=%s", method, msg_id[:8])

        if method == "session.prompt":
            if self._prompt_handler:
                await self._prompt_handler(envelope)
        elif method == "session.cancel":
            if self._cancel_handler:
                await self._cancel_handler(envelope)
