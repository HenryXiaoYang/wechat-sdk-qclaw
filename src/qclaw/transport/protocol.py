"""AGP (Agent Gateway Protocol) message builders and type constants.

Every WebSocket frame is a JSON-serialised *envelope* with the shape::

    {
        "msg_id":   "<uuid>",
        "guid":     "<device-guid>",
        "user_id":  "<user-id>",
        "method":   "<method>",
        "payload":  { ... }
    }

This module provides thin helpers that construct those envelopes so the
rest of the SDK never has to assemble raw dicts.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional


# ---------------------------------------------------------------------------
# Constant enums (strings — kept lightweight, no ``enum.Enum`` overhead)
# ---------------------------------------------------------------------------

class AGPMethod:
    PROMPT = "session.prompt"
    CANCEL = "session.cancel"
    UPDATE = "session.update"
    PROMPT_RESPONSE = "session.promptResponse"


class UpdateType:
    MESSAGE_CHUNK = "message_chunk"
    TOOL_CALL = "tool_call"
    TOOL_CALL_UPDATE = "tool_call_update"


class StopReason:
    END_TURN = "end_turn"
    CANCELLED = "cancelled"
    REFUSAL = "refusal"
    ERROR = "error"


class ToolCallKind:
    READ = "read"
    EDIT = "edit"
    DELETE = "delete"
    EXECUTE = "execute"
    SEARCH = "search"
    FETCH = "fetch"
    THINK = "think"
    OTHER = "other"


class ToolCallStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------


def make_envelope(
    method: str,
    payload: dict,
    guid: str = "",
    user_id: str = "",
) -> str:
    """Return a JSON string for an AGP envelope."""
    envelope = {
        "msg_id": str(uuid.uuid4()),
        "guid": guid,
        "user_id": user_id,
        "method": method,
        "payload": payload,
    }
    return json.dumps(envelope, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Upstream message helpers (client → server)
# ---------------------------------------------------------------------------


def make_message_chunk(
    session_id: str,
    prompt_id: str,
    text: str,
    guid: str = "",
    user_id: str = "",
) -> str:
    """Build a ``session.update`` message with ``update_type=message_chunk``."""
    return make_envelope(
        AGPMethod.UPDATE,
        {
            "session_id": session_id,
            "prompt_id": prompt_id,
            "update_type": UpdateType.MESSAGE_CHUNK,
            "content": {"type": "text", "text": text},
        },
        guid,
        user_id,
    )


def make_tool_call(
    session_id: str,
    prompt_id: str,
    tool_call_id: str,
    title: str,
    kind: str = ToolCallKind.EXECUTE,
    status: str = ToolCallStatus.IN_PROGRESS,
    guid: str = "",
    user_id: str = "",
) -> str:
    """Build a ``session.update`` message with ``update_type=tool_call``."""
    return make_envelope(
        AGPMethod.UPDATE,
        {
            "session_id": session_id,
            "prompt_id": prompt_id,
            "update_type": UpdateType.TOOL_CALL,
            "tool_call": {
                "tool_call_id": tool_call_id,
                "title": title,
                "kind": kind,
                "status": status,
            },
        },
        guid,
        user_id,
    )


def make_tool_call_update(
    session_id: str,
    prompt_id: str,
    tool_call_id: str,
    status: str,
    content_text: Optional[str] = None,
    guid: str = "",
    user_id: str = "",
) -> str:
    """Build a ``session.update`` with ``update_type=tool_call_update``."""
    tool_call: dict = {"tool_call_id": tool_call_id, "status": status}
    if content_text is not None:
        tool_call["content"] = [{"type": "text", "text": content_text}]
    return make_envelope(
        AGPMethod.UPDATE,
        {
            "session_id": session_id,
            "prompt_id": prompt_id,
            "update_type": UpdateType.TOOL_CALL_UPDATE,
            "tool_call": tool_call,
        },
        guid,
        user_id,
    )


def make_prompt_response(
    session_id: str,
    prompt_id: str,
    stop_reason: str = StopReason.END_TURN,
    text: Optional[str] = None,
    error: Optional[str] = None,
    guid: str = "",
    user_id: str = "",
) -> str:
    """Build a ``session.promptResponse`` envelope."""
    payload: dict = {
        "session_id": session_id,
        "prompt_id": prompt_id,
        "stop_reason": stop_reason,
    }
    if text is not None:
        payload["content"] = [{"type": "text", "text": text}]
    if error is not None:
        payload["error"] = error
    return make_envelope(AGPMethod.PROMPT_RESPONSE, payload, guid, user_id)


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------


def extract_text(content_blocks: list[dict]) -> str:
    """Join all ``text``-type content blocks into a single string."""
    return "\n".join(
        block["text"]
        for block in content_blocks
        if block.get("type") == "text" and block.get("text")
    )
