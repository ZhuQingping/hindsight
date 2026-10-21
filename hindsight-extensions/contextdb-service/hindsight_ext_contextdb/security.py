"""Opaque credentials: identity is a server-side mapping, not encrypted in the Key."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

from .models import ServiceError

_USER_KEY = re.compile(r"^ctx_live_([0-9a-f]{32})_([A-Za-z0-9_-]{43})$")
_ADMIN_KEY = re.compile(r"^ctx_admin_([0-9a-f]{32})_([A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class IssuedKey:
    key_id: str
    secret: str = field(repr=False)
    digest: bytes


def key_digest(value: str, pepper: str) -> bytes:
    """Digest the entire credential so changing its public ID also invalidates it."""
    return hmac.digest(pepper.encode(), value.encode(), "sha256")


def issue_key(pepper: str) -> IssuedKey:
    key_id = secrets.token_hex(16)
    secret = f"ctx_live_{key_id}_{secrets.token_urlsafe(32)}"
    return IssuedKey(key_id, secret, key_digest(secret, pepper))


def issue_admin_key() -> IssuedKey:
    """Generate the single deployment credential without contacting an API or PG."""
    key_id = secrets.token_hex(16)
    secret = f"ctx_admin_{key_id}_{secrets.token_urlsafe(32)}"
    return IssuedKey(key_id, secret, hashlib.sha256(secret.encode()).digest())


def credential_key_id(value: str | None) -> str | None:
    """Prefixes locate records only; the authenticated PG owner defines the role."""
    if value is None or len(value) > 256:
        return None
    match = _USER_KEY.fullmatch(value) or _ADMIN_KEY.fullmatch(value)
    return match[1] if match else None


def bearer_credential(headers: list[tuple[bytes, bytes]]) -> str | None:
    """Use the same direct/Bearer syntax for REST, MCP and admin ingress."""
    values = [value for name, value in headers if name.lower() == b"authorization"]
    if len(values) > 1:
        raise ServiceError(401, "invalid_key", "Ambiguous authorization")
    if not values:
        return None
    header = values[0].decode("latin-1").strip()
    return (header[7:] if header.lower().startswith("bearer ") else header).strip()
