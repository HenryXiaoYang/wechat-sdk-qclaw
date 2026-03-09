"""Environment configuration and login-state persistence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Environment presets
# ---------------------------------------------------------------------------

ENVIRONMENTS: dict[str, dict[str, str]] = {
    "production": {
        "jprx_gateway": "https://jprx.m.qq.com/",
        "qclaw_base_url": "https://mmgrcalltoken.3g.qq.com/aizone/v1",
        "wx_login_redirect_uri": "https://security.guanjia.qq.com/login",
        "wechat_ws_url": "wss://mmgrcalltoken.3g.qq.com/agentwss",
        "wx_appid": "wx9d11056dd75b7240",
    },
    "test": {
        "jprx_gateway": "https://jprx.sparta.html5.qq.com/",
        "qclaw_base_url": "https://jprx.sparta.html5.qq.com/aizone/v1",
        "wx_login_redirect_uri": "https://security-test.guanjia.qq.com/login",
        "wechat_ws_url": "wss://jprx.sparta.html5.qq.com/agentwss",
        "wx_appid": "wx3dd49afb7e2cf957",
    },
}


@dataclass
class Config:
    """SDK-wide configuration.

    Parameters
    ----------
    env : str
        ``"production"`` or ``"test"``.
    state_file : str
        Path where login credentials are persisted between runs.
    heartbeat_interval : float
        WebSocket heartbeat period in seconds.
    reconnect_interval : float
        Base delay between reconnect attempts (uses exponential back-off).
    max_reconnect_attempts : int
        ``0`` means unlimited.
    """

    env: str = "production"
    state_file: str = field(
        default_factory=lambda: os.path.join(
            os.path.expanduser("~"), ".qclaw_state.json"
        )
    )
    heartbeat_interval: float = 20.0
    reconnect_interval: float = 3.0
    max_reconnect_attempts: int = 0

    @property
    def env_config(self) -> dict[str, str]:
        """Return the URL / appid dict for the selected environment."""
        return ENVIRONMENTS[self.env]


# ---------------------------------------------------------------------------
# Login-state persistence
# ---------------------------------------------------------------------------


def save_state(path: str, state: dict[str, Any]) -> None:
    """Write login credentials to *path*."""
    with open(path, "w") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def load_state(path: str) -> dict[str, Any]:
    """Read previously-saved login credentials.  Returns ``{}`` on failure."""
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def clear_state(path: str) -> None:
    """Remove the persisted state file."""
    if os.path.exists(path):
        os.remove(path)
