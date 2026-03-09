"""QChat — WeChat chatbot SDK with an ItChat-style API.

Quick start::

    from qclaw import QChat, content

    bot = QChat()

    @bot.msg_register(content.TEXT)
    def echo(msg):
        return f"Echo: {msg.text}"

    bot.auto_login()
    bot.run()

Or use the module-level singleton (mirrors ItChat's style)::

    import qclaw

    @qclaw.msg_register(qclaw.content.TEXT)
    def echo(msg):
        return f"Echo: {msg.text}"

    qclaw.auto_login()
    qclaw.run()
"""

from __future__ import annotations

from qclaw.api import TokenExpiredError
from qclaw.config import Config
from qclaw.core import QChat
from qclaw.message import Message, content
from qclaw.reply import ReplyContext, ToolCallHandle

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Module-level singleton — for ItChat-style convenience
# ---------------------------------------------------------------------------

_bot = QChat()

msg_register = _bot.msg_register
auto_login = _bot.auto_login
run = _bot.run
stop = _bot.stop
logout = _bot.logout

__all__ = [
    # Classes
    "QChat",
    "Message",
    "content",
    "Config",
    "ReplyContext",
    "ToolCallHandle",
    "TokenExpiredError",
    # Singleton shortcuts
    "msg_register",
    "auto_login",
    "run",
    "stop",
    "logout",
    # Meta
    "__version__",
]
