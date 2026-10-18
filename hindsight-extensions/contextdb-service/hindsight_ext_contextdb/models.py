"""Tenant-level users and explicitly scoped credentials, separate from memory data."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, computed_field, field_validator, model_validator


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Scope(StrEnum):
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    KNOWLEDGE_READ = "knowledge.read"
    REFLECT = "reflect"


def normalized_name(value: str) -> str:
    """One canonical spelling for persisted names and exact directory lookups."""
    return unicodedata.normalize("NFKC", value).strip()


def workspace_name(value: str) -> str:
    value = normalized_name(value).lower()
    if re.fullmatch(r"[a-z][a-z0-9_]{0,53}", value) is None:
        raise ValueError("Workspace name must start with an ASCII letter and contain 1 to 54 letters, digits or _")
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def nonblank_name(cls, value: object, info: ValidationInfo) -> object:
        if info.field_name == "name" and isinstance(value, str):
            value = normalized_name(value)
            if not value:
                raise ValueError("Name cannot be blank")
        return value


class Permission(StrEnum):
    READ = "read"
    READ_WRITE = "read_write"


class WorkspaceCreate(Input):
    name: str = Field(
        min_length=1,
        max_length=54,
        description="Stable Bank ID: normalized to lowercase ASCII, starts with a letter; remaining characters are letters, digits or _. Maximum 54 characters.",
    )
    description: str = Field(default="", max_length=512)

    @field_validator("name", mode="after")
    @classmethod
    def path_name(cls, value: str) -> str:
        return workspace_name(value)


class UserCreate(Input):
    name: str = Field(min_length=1, max_length=64)


class UserPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def validate_change(self) -> UserPatch:
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Provide at least one non-null change")
        return self


class WorkspaceGrant(Input):
    bank_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{0,53}$")
    workspace_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
        description="Optional expected generation from the workspace picker; a stale generation is rejected rather than granting its same-name successor.",
    )
    permission: Permission = Permission.READ_WRITE


class ExplicitWorkspaceGrant(WorkspaceGrant):
    permission: Permission


class StoredWorkspaceGrant(WorkspaceGrant):
    workspace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    workspace_name: str | None = Field(default=None, json_schema_extra={"readOnly": True})


class StoredSelectedAuthorization(Input):
    mode: Literal["selected"] = "selected"
    workspaces: list[StoredWorkspaceGrant] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique_workspaces(self) -> StoredSelectedAuthorization:
        ids = [grant.bank_id for grant in self.workspaces]
        if len(ids) != len(set(ids)):
            raise ValueError("Bank IDs must be unique")
        return self


class SelectedAuthorization(StoredSelectedAuthorization):
    workspaces: list[WorkspaceGrant] = Field(min_length=1, max_length=1000)


class ExplicitSelectedAuthorization(SelectedAuthorization):
    workspaces: list[ExplicitWorkspaceGrant] = Field(min_length=1, max_length=1000)


class AllAuthorization(Input):
    mode: Literal["all"]
    permission: Permission = Permission.READ_WRITE


class ExplicitAllAuthorization(AllAuthorization):
    permission: Permission


Authorization = Annotated[SelectedAuthorization | AllAuthorization, Field(discriminator="mode")]
ExplicitAuthorization = Annotated[ExplicitSelectedAuthorization | ExplicitAllAuthorization, Field(discriminator="mode")]


class ApiKeyCreate(Input):
    name: str = Field(min_length=1, max_length=64)
    authorization: Authorization


class ApiKeyPatch(Input):
    """Name is independent; submitted authorization is a complete, explicit replacement."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    authorization: ExplicitAuthorization | None = None

    @model_validator(mode="after")
    def validate_change(self) -> ApiKeyPatch:
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Provide at least one non-null change")
        return self


class Workspace(BaseModel):
    bank_id: str
    workspace_id: str
    instance_id: str
    cloud_tenant_id: str
    schema_name: str
    name: str
    description: str
    state: str
    version: int
    created_at: datetime
    latest_operation_id: str | None = None

    @computed_field
    @property
    def etag(self) -> str:
        return f'"{self.workspace_id}:{self.version}"'


class User(BaseModel):
    user_id: str
    name: str
    status: str
    version: int
    created_at: datetime


StoredAuthorization = Annotated[StoredSelectedAuthorization | AllAuthorization, Field(discriminator="mode")]


class KeyEditable(BaseModel):
    key_id: str
    user_id: str
    name: str
    authorization: StoredAuthorization
    display_key: str | None = None
    version: int
    created_at: datetime


class KeyMetadata(KeyEditable):
    """List projection includes approximate usage; it has no edit ETag."""

    last_used_at: datetime | None


class KeyIssued(KeyEditable):
    secret: str = Field(repr=False)


class ManagementOperation(BaseModel):
    operation_id: str
    workspace_id: str
    instance_id: str
    actor_subject: str
    action: str
    state: str
    attempts: int
    lease_token: str | None = Field(repr=False)
    error_code: str | None


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class IssuedApiKey:
    metadata: KeyMetadata
    secret: str = field(repr=False)

    def response(self) -> KeyIssued:
        return KeyIssued(**self.metadata.model_dump(), secret=self.secret)


@dataclass(frozen=True)
class ControlPrincipal:
    control_key_id: str
    cloud_tenant_id: str
    actor_subject: str


@dataclass(frozen=True)
class BusinessPrincipal:
    key_id: str
    user_id: str
    role: Role
    access_mode: str
    workspace_ids: frozenset[str]
    permission: Permission
    workspace_id: str | None = None
    schema_name: str | None = None
    scopes: frozenset[Scope] = frozenset()
    workspace_permissions: tuple[StoredWorkspaceGrant, ...] = ()


class ServiceError(Exception):
    """Sanitized domain failures, never database or credential diagnostics."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
