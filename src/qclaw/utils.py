"""Utility functions for the qclaw SDK."""

from __future__ import annotations

import hashlib
import os


def get_machine_guid() -> str:
    """Return a stable device identifier, similar to QChat's getMachineId.

    On macOS, uses the IOPlatformUUID.  Falls back to a hash derived from
    hostname + username so the result is deterministic across restarts.
    """
    # macOS: read IOPlatformUUID
    try:
        import subprocess

        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                uid = line.split('"')[-2]
                return hashlib.md5(uid.encode()).hexdigest()
    except Exception:
        pass

    # Fallback: hostname + username
    identity = f"{os.uname().nodename}:{os.getenv('USER', 'unknown')}"
    return hashlib.md5(identity.encode()).hexdigest()


def nested_get(d: dict, *keys):
    """Safely traverse nested dicts.  Returns ``None`` on any missing key."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d
