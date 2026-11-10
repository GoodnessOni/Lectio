"""Opaque id helpers. Invite tokens are long and unguessable."""

from __future__ import annotations

import re
import secrets

_SAFE = re.compile(r"[^A-Za-z0-9]+")


def _token(nbytes: int) -> str:
    # token_urlsafe can include - and _; strip those for compact ids.
    return _SAFE.sub("", secrets.token_urlsafe(nbytes))


def new_id(prefix: str, nbytes: int = 9) -> str:
    return f"{prefix}_{_token(nbytes)}"


def new_invite_token() -> str:
    return f"tok_{_token(32)}"


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
