"""The request contract must not silently expand write permission during editing."""

import pytest
from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    ApiKeyPatch,
    UserCreate,
    WorkspaceCreate,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "authorization",
    [
        {"mode": "selected", "workspaces": [{"bank_id": "a" * 32}]},
        {"mode": "all"},
    ],
)
def test_post_defaults_permission_but_patch_requires_explicit_permission(authorization):
    created = ApiKeyCreate(name="test", authorization=authorization)
    if created.authorization.mode == "all":
        assert created.authorization.permission == "read_write"
    else:
        assert created.authorization.workspaces[0].permission == "read_write"
    with pytest.raises(ValidationError):
        ApiKeyPatch(authorization=authorization)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"authorization": None},
        {"name": " "},
        {"authorization": {"mode": "all", "permission": "admin"}},
        {"authorization": {"mode": "selected", "workspaces": []}},
        {"authorization": {"mode": "selected", "workspaces": [{"bank_id": "a" * 32, "permission": "read"}] * 2}},
        {"name": "ok", "permission": "read_write"},
        {"authorization": {"mode": "all", "permission": "read", "workspaces": []}},
    ],
)
def test_patch_rejects_null_empty_legacy_and_ambiguous_fields(body):
    with pytest.raises(ValidationError):
        ApiKeyPatch.model_validate(body)


@pytest.mark.parametrize("model", [UserCreate, WorkspaceCreate])
def test_customer_names_trim_and_reject_blank(model):
    assert model(name="  Display  ").name == ("display" if model is WorkspaceCreate else "Display")
    with pytest.raises(ValidationError):
        model(name="\t\n  ")


def test_key_name_edit_has_no_implicit_authorization():
    patch = ApiKeyPatch(name="new name")
    assert patch.authorization is None and patch.model_fields_set == {"name"}
