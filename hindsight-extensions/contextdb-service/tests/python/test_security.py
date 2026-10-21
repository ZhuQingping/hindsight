"""Opaque business credentials and the single offline administrator credential."""

import hashlib

import pytest
from hindsight_ext_contextdb.models import ServiceError
from hindsight_ext_contextdb.security import (
    bearer_credential,
    credential_key_id,
    issue_admin_key,
    issue_key,
    key_digest,
)


def test_random_business_keys_are_independent_and_bound_to_pepper() -> None:
    first = issue_key("test-pepper")
    second = issue_key("test-pepper")
    assert first != second
    assert credential_key_id(first.secret) == first.key_id
    assert len(first.digest) == 32
    assert first.digest == key_digest(first.secret, "test-pepper")
    assert first.digest != key_digest(first.secret, "other-pepper")


@pytest.mark.parametrize("credential", [None, "", "legacy-key", "ctx_live_broken", "x" * 257])
def test_unified_parser_rejects_unknown_business_formats(credential: str | None) -> None:
    assert credential_key_id(credential) is None


def test_offline_admin_checksum_is_not_a_runtime_authenticator() -> None:
    admin = issue_admin_key()
    assert admin.digest.hex() == hashlib.sha256(admin.secret.encode()).hexdigest()
    assert credential_key_id(admin.secret) == admin.key_id
    assert admin.secret not in repr(admin)
    business = issue_key("pepper")
    assert credential_key_id(business.secret) == business.key_id
    # The parser intentionally makes no authority claim. Changing an ID or
    # prefix changes the full HMAC checked against PG in repository regressions.
    assert key_digest(admin.secret, "pepper") != key_digest(admin.secret.replace(admin.key_id, "0" * 32), "pepper")


@pytest.mark.parametrize("credential", [None, "", "ctx_admin_broken", "x" * 257])
def test_unified_parser_fails_closed(credential: str | None) -> None:
    assert credential_key_id(credential) is None


def test_rest_and_mcp_bearer_parser_rejects_ambiguous_authorization() -> None:
    with pytest.raises(ServiceError) as error:
        bearer_credential([(b"authorization", b"Bearer one"), (b"Authorization", b"Bearer two")])
    assert error.value.status == 401
    assert bearer_credential([(b"authorization", b"Bearer secret")]) == "secret"
    assert bearer_credential([]) is None
