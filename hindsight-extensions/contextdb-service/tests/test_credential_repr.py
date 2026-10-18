"""Diagnostic repr must not accidentally log an issued plaintext credential."""

from datetime import datetime, timezone

from hindsight_ext_contextdb.__main__ import AdministratorCredential
from hindsight_ext_contextdb.models import (
    IssuedApiKey,
    KeyIssued,
    KeyMetadata,
    ManagementOperation,
)
from hindsight_ext_contextdb.security import issue_key


def test_plaintext_credentials_are_hidden_from_repr_but_returned_once() -> None:
    issued = issue_key("synthetic-repr-pepper")
    assert issued.secret not in repr(issued)
    now = datetime.now(timezone.utc)
    metadata = KeyMetadata(
        key_id=issued.key_id,
        user_id="user",
        authorization={
            "mode": "selected",
            "workspaces": [{"bank_id": "demo", "workspace_id": "a" * 32, "permission": "read"}],
        },
        version=1,
        name="Synthetic key",
        created_at=now,
        last_used_at=None,
    )
    domain = IssuedApiKey(metadata, issued.secret)
    response = KeyIssued.model_validate({**metadata.model_dump(), "secret": issued.secret})
    assert issued.secret not in repr(domain)
    assert issued.secret not in repr(response)
    assert response.model_dump()["secret"] == issued.secret
    control = AdministratorCredential(key_id="a" * 32, secret="synthetic-control-secret", sha256="b" * 64)
    assert control.secret not in repr(control)
    assert control.model_dump()["secret"] == control.secret
    operation = ManagementOperation(
        operation_id="operation",
        workspace_id="workspace",
        instance_id="instance",
        actor_subject="actor",
        action="create_workspace",
        state="running",
        attempts=1,
        lease_token="synthetic-private-lease",
        error_code=None,
    )
    assert operation.lease_token is not None
    assert operation.lease_token not in repr(operation)
