"""Opaque credentials: identity is a server-side mapping, not encrypted in the Key."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

from .models import ControlPrincipal, ServiceError

_USER_KEY = re.compile(r"^ctx_live_([0-9a-f]{32})_([A-Za-z0-9_-]{43})$")
_CONTROL_KEY = re.compile(r"^ctx_ctrl_([0-9a-f]{32})_([A-Za-z0-9_-]{43})$")
_SAFE_ACTOR = re.compile(r"^[!-~]{1,256}$")


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


def user_key_id(value: str | None) -> str | None:
    if value is None or len(value) > 256:
        return None
    match = _USER_KEY.fullmatch(value)
    return match[1] if match else None


@dataclass(frozen=True)
class ControlKey:
    key_id: str
    digest: bytes


class ControlPlaneKeyAuth:
    """Verify a deployment credential before trusting the control plane's actor header.

    The actor assertion is deliberately not a second login system. Its truth is
    guaranteed by the trusted backend and private ingress, not by Key encryption.
    """

    def __init__(self, cloud_tenant_id: str, keys: list[ControlKey]) -> None:
        if not cloud_tenant_id or not keys or any(len(key.digest) != 32 for key in keys):
            raise ValueError("A tenant and SHA-256 control Key digests are required")
        if len({key.key_id for key in keys}) != len(keys):
            raise ValueError("Control Key IDs must be unique")
        self.cloud_tenant_id = cloud_tenant_id
        self.keys = keys

    def authenticate(self, credential: str | None, actor: str | None) -> ControlPrincipal:
        match = _CONTROL_KEY.fullmatch(credential) if credential and len(credential) <= 256 else None
        if match is None:
            raise ServiceError(401, "invalid_control_key", "A valid control-plane Key is required")
        assert credential is not None  # A successful format match implies a concrete credential.
        digest = hashlib.sha256(credential.encode()).digest()
        selected: ControlKey | None = None
        # Compare every configured digest, including during a dual-Key rotation.
        # The small fixed set is configuration, never a customer-provided key list.
        for key in self.keys:
            if hmac.compare_digest(digest, key.digest):
                selected = key
        if selected is None or not hmac.compare_digest(selected.key_id, match[1]):
            raise ServiceError(401, "invalid_control_key", "A valid control-plane Key is required")
        if actor is None or not _SAFE_ACTOR.fullmatch(actor):
            raise ServiceError(400, "invalid_actor", "A verified control-plane actor is required")
        return ControlPrincipal(selected.key_id, self.cloud_tenant_id, actor)
