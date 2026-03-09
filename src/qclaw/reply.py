"""Reply context for streaming and tool-call responses.

When a handler accepts two arguments, the second argument is a
:class:`ReplyContext` that provides helpers for sending incremental
text chunks and tool-call status updates back to the user *during*
processing, before the final response is sent.

Example::

    @bot.msg_register(content.TEXT)
    async def handle(msg, reply):
        handle = reply.tool_call("Searching…")
        await handle.complete("Found 3 results")
        await reply.send_chunk("Here are the results…")
        return "Done!"
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from qclaw.transport.protocol import (
    ToolCallKind,
    ToolCallStatus,
    make_message_chunk,
    make_tool_call,
    make_tool_call_update,
)

if TYPE_CHECKING:
    from qclaw.transport.websocket import AGPWebSocketClient


class ToolCallHandle:
    """Manage the lifecycle of a single tool call.

    Obtained by calling :meth:`ReplyContext.tool_call`.
    """

    def __init__(
        self,
        client: AGPWebSocketClient,
        session_id: str,
        prompt_id: str,
        tool_call_id: str,
        guid: str,
        user_id: str,
    ) -> None:
        self._client = client
        self._session_id = session_id
        self._prompt_id = prompt_id
        self._tool_call_id = tool_call_id
        self._guid = guid
        self._user_id = user_id

    async def update(self, text: str) -> None:
        """Push an in-progress status update with *text*."""
        await self._client.send(
            make_tool_call_update(
                self._session_id,
                self._prompt_id,
                self._tool_call_id,
                ToolCallStatus.IN_PROGRESS,
                content_text=text,
                guid=self._guid,
                user_id=self._user_id,
            )
        )

    async def complete(self, text: str = "") -> None:
        """Mark the tool call as completed."""
        await self._client.send(
            make_tool_call_update(
                self._session_id,
                self._prompt_id,
                self._tool_call_id,
                ToolCallStatus.COMPLETED,
                content_text=text or None,
                guid=self._guid,
                user_id=self._user_id,
            )
        )

    async def fail(self, text: str = "") -> None:
        """Mark the tool call as failed."""
        await self._client.send(
            make_tool_call_update(
                self._session_id,
                self._prompt_id,
                self._tool_call_id,
                ToolCallStatus.FAILED,
                content_text=text or None,
                guid=self._guid,
                user_id=self._user_id,
            )
        )


class ReplyContext:
    """Streaming reply context passed to two-argument handlers.

    Parameters
    ----------
    client : AGPWebSocketClient
        The underlying WebSocket transport.
    session_id, prompt_id, guid, user_id : str
        Identifiers for the current turn (echoed back to the server).
    """

    def __init__(
        self,
        client: AGPWebSocketClient,
        session_id: str,
        prompt_id: str,
        guid: str,
        user_id: str,
    ) -> None:
        self._client = client
        self._session_id = session_id
        self._prompt_id = prompt_id
        self._guid = guid
        self._user_id = user_id

    async def send_chunk(self, text: str) -> None:
        """Send an incremental text chunk to the user."""
        await self._client.send(
            make_message_chunk(
                self._session_id,
                self._prompt_id,
                text,
                guid=self._guid,
                user_id=self._user_id,
            )
        )

    # Convenience alias
    send_text = send_chunk

    async def tool_call(
        self,
        title: str,
        kind: str = ToolCallKind.EXECUTE,
    ) -> ToolCallHandle:
        """Start a new tool call and return a handle.

        Sends the initial ``tool_call`` update (status = in_progress) and
        returns a :class:`ToolCallHandle` for pushing progress updates
        and marking completion.
        """
        tc_id = f"tc-{uuid.uuid4().hex[:8]}"

        await self._client.send(
            make_tool_call(
                self._session_id,
                self._prompt_id,
                tc_id,
                title,
                kind=kind,
                status=ToolCallStatus.IN_PROGRESS,
                guid=self._guid,
                user_id=self._user_id,
            )
        )

        return ToolCallHandle(
            self._client,
            self._session_id,
            self._prompt_id,
            tc_id,
            self._guid,
            self._user_id,
        )
