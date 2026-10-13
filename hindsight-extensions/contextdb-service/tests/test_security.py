"""Pure credential/model tests; all Keys here are synthetic, not deployment secrets."""

import hashlib
import secrets
from datetime import datetime, timezone

import pytest
from hindsight_ext_contextdb.models import ApiKeyCreate, MemberCreate, MemberPatch, ServiceError, WorkspacePatch
from hindsight_ext_contextdb.security import ControlKey, ControlPlaneKeyAuth, issue_key, key_digest, user_key_id
from pydantic import ValidationError


def test_random_user_keys_have_server_side_ids_and_distinct_secrets() -> None:
    first = issue_key("test-pepper")
    second = issue_key("test-pepper")
    assert first != second
    assert user_key_id(first.secret) == first.key_id
    assert len(first.digest) == 32
    assert first.digest == key_digest(first.secret, "test-pepper")
    assert first.digest != key_digest(first.secret, "other-pepper")


@pytest.mark.parametrize("credential", [None, "", "legacy-key", "ctx_live_broken", "x" * 257])
def test_business_key_parser_rejects_unknown_formats(credential: str | None) -> None:
    assert user_key_id(credential) is None


def test_control_auth_validates_service_before_actor() -> None:
    key_id = secrets.token_hex(16)
    value = f"ctx_ctrl_{key_id}_{secrets.token_urlsafe(32)}"
    verifier = ControlPlaneKeyAuth("tenant-one", [ControlKey(key_id, hashlib.sha256(value.encode()).digest())])
    principal = verifier.authenticate(value, "user-one")
    assert principal.cloud_tenant_id == "tenant-one"
    assert principal.actor_subject == "user-one"
    assert principal.control_key_id == key_id
    with pytest.raises(ServiceError) as invalid:
        verifier.authenticate("not-a-key", None)
    assert invalid.value.status == 401
    with pytest.raises(ServiceError) as missing_actor:
        verifier.authenticate(value, None)
    assert missing_actor.value.status == 400
    with pytest.raises(ServiceError):
        verifier.authenticate(value, "user\r\nrole:admin")


def test_business_key_cannot_be_registered_as_control_credential() -> None:
    key = issue_key("test-pepper")
    verifier = ControlPlaneKeyAuth("tenant", [ControlKey(key.key_id, hashlib.sha256(key.secret.encode()).digest())])
    with pytest.raises(ServiceError) as error:
        verifier.authenticate(key.secret, "admin")
    assert error.value.status == 401


def test_control_rotation_accepts_only_registered_keys() -> None:
    old_id, new_id = secrets.token_hex(16), secrets.token_hex(16)
    old = f"ctx_ctrl_{old_id}_{secrets.token_urlsafe(32)}"
    new = f"ctx_ctrl_{new_id}_{secrets.token_urlsafe(32)}"
    old_key = ControlKey(old_id, hashlib.sha256(old.encode()).digest())
    new_key = ControlKey(new_id, hashlib.sha256(new.encode()).digest())
    rotating = ControlPlaneKeyAuth("tenant", [old_key, new_key])
    assert rotating.authenticate(old, "actor").control_key_id == old_id
    assert rotating.authenticate(new, "actor").control_key_id == new_id
    with pytest.raises(ServiceError):
        ControlPlaneKeyAuth("tenant", [new_key]).authenticate(old, "actor")


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"state": "deleted"}, {"schema_name": "public"}])
def test_workspace_patch_rejects_empty_null_or_injected_fields(payload: dict[str, str | None]) -> None:
    with pytest.raises(ValidationError):
        WorkspacePatch.model_validate(payload)


def test_member_roles_and_login_binding_are_explicit() -> None:
    assert MemberCreate(member_name="robot").iam_subject is None
    assert MemberCreate(member_name="admin", role="admin", iam_subject="verified-user").role == "admin"
    with pytest.raises(ValidationError):
        MemberCreate(member_name="admin", role="admin")
    with pytest.raises(ValidationError):
        MemberCreate(member_name="user", role="owner")
    with pytest.raises(ValidationError):
        MemberPatch()


@pytest.mark.parametrize("subject", ["bad actor", "bad\nactor", "用户", "bad\x7factor"])
def test_uncallable_administrator_binding_is_rejected(subject: str) -> None:
    with pytest.raises(ValidationError):
        MemberCreate(member_name="Admin", role="admin", iam_subject=subject)


def test_key_scope_and_expiry_inputs_are_validated() -> None:
    aware = datetime(2030, 1, 1, tzinfo=timezone.utc)
    valid = ApiKeyCreate(name="test", scopes=["memory.read", "memory.write"], expires_at=aware)
    assert len(valid.scopes) == 2
    for scopes in [["memory.write"], ["reflect"], ["memory.read", "memory.read"], ["users.manage"]]:
        with pytest.raises(ValidationError):
            ApiKeyCreate(name="test", scopes=scopes, expires_at=aware)
    with pytest.raises(ValidationError):
        ApiKeyCreate(name="test", scopes=["memory.read"], expires_at=datetime(2030, 1, 1))
