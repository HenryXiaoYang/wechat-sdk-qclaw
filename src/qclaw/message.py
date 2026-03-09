"""Message model and content-type constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class content:  # noqa: N801  (lowercase for ItChat compatibility)
    """Message content-type constants.

    Usage::

        from qclaw import content

        @bot.msg_register(content.TEXT)
        def handler(msg): ...
    """

    TEXT = "text"
    IMAGE = "image"  # reserved for future use
    VOICE = "voice"  # reserved for future use


@dataclass
class Message:
    """Incoming user message, passed to registered handlers.

    Attributes
    ----------
    msg_id : str
        Unique message ID (UUID from the AGP envelope).
    session_id : str
        Conversation session ID.
    prompt_id : str
        Turn ID for this prompt–response pair.
    guid : str
        Sender device GUID.
    user_id : str
        Sender user ID.
    type : str
        Content type (e.g. ``content.TEXT``).
    text : str
        Extracted text content of the message.
    agent_app : str
        Target agent application identifier.
    raw : dict
        Original AGP envelope for advanced introspection.
    """

    msg_id: str
    session_id: str
    prompt_id: str
    guid: str
    user_id: str
    type: str
    text: str
    agent_app: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def __str__(self) -> str:  # noqa: D105
        preview = self.text[:80] + "..." if len(self.text) > 80 else self.text
        return f"Message(user={self.user_id}, text={preview!r})"
