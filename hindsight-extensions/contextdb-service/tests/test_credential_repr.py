"""Diagnostic repr must not accidentally log an issued plaintext credential."""

from datetime import datetime, timedelta, timezone

from hindsight_ext_contextdb.http import KeyIssuedResponse
from hindsight_ext_contextdb.__main__ import ControlCredential
from hindsight_ext_contextdb.models import IssuedApiKey, KeyMetadata, ManagementOperation, Scope
from hindsight_ext_contextdb.security import issue_key


def test_plaintext_credentials_are_hidden_from_repr_but_returned_once() -> None:
    issued = issue_key("synthetic-repr-pepper")
    assert issued.secret not in repr(issued)
    now = datetime.now(timezone.utc)
    metadata = KeyMetadata(
        key_id=issued.key_id,
        workspace_id="workspace",
        member_id="member",
        name="Synthetic key",
        scopes=[Scope.MEMORY_READ],
        expires_at=now + timedelta(days=1),
        revoked_at=None,
        created_by="admin",
        created_at=now,
        last_used_at=None,
    )
    domain = IssuedApiKey(metadata, issued.secret)
    response = KeyIssuedResponse.model_validate({**metadata.model_dump(), "secret": issued.secret})
    assert issued.secret not in repr(domain)
    assert issued.secret not in repr(response)
    assert response.model_dump()["secret"] == issued.secret
    control = ControlCredential(key_id="synthetic", secret="synthetic-control-secret", sha256="synthetic-digest")
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
    assert operation.lease_token not in repr(operation)
