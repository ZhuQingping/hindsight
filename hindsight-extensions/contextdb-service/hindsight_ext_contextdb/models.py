"""Typed management inputs and persisted identities, separate from memory data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class Scope(StrEnum):
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    KNOWLEDGE_READ = "knowledge.read"
    REFLECT = "reflect"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstanceCreate(Input):
    instance_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)


class WorkspaceCreate(Input):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=512)


class WorkspacePatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    state: str | None = Field(default=None, pattern="^(active|frozen)$")

    @model_validator(mode="after")
    def require_change(self) -> WorkspacePatch:
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Provide at least one non-null change")
        return self


class MemberCreate(Input):
    member_name: str = Field(min_length=1, max_length=64)
    iam_subject: str | None = Field(default=None, min_length=1, max_length=256)
    role: Role = Role.MEMBER

    @field_validator("iam_subject")
    @classmethod
    def require_callable_subject(cls, value: str | None) -> str | None:
        # Match the trusted actor assertion syntax. An unreachable active admin
        # must not satisfy the last-administrator safeguard.
        if value is not None and (not value.isascii() or any(ord(char) < 33 or ord(char) == 127 for char in value)):
            raise ValueError("iam_subject must use visible ASCII, matching the trusted actor HTTP header")
        return value

    @model_validator(mode="after")
    def bind_admin(self) -> MemberCreate:
        if self.role == Role.ADMIN and not self.iam_subject:
            raise ValueError("An administrator must be bound to a verified control-plane login")
        return self


class MemberPatch(Input):
    member_name: str | None = Field(default=None, min_length=1, max_length=64)
    role: Role | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")

    @model_validator(mode="after")
    def require_change(self) -> MemberPatch:
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Provide at least one non-null change")
        return self


class ApiKeyCreate(Input):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[Scope] = Field(min_length=1, max_length=4)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[Scope]) -> list[Scope]:
        if len(value) != len(set(value)):
            raise ValueError("scopes must be unique")
        if Scope.MEMORY_WRITE in value and Scope.MEMORY_READ not in value:
            raise ValueError("memory.write requires memory.read")
        if Scope.REFLECT in value and Scope.MEMORY_READ not in value:
            raise ValueError("reflect requires memory.read")
        return value


class Workspace(BaseModel):
    workspace_id: str
    instance_id: str
    cloud_tenant_id: str
    schema_name: str
    name: str
    description: str
    state: str
    version: int
    created_at: datetime


class Member(BaseModel):
    member_id: str
    workspace_id: str
    member_name: str
    iam_subject: str | None
    role: Role
    status: str
    version: int
    created_at: datetime


class KeyMetadata(BaseModel):
    key_id: str
    workspace_id: str
    member_id: str
    name: str
    scopes: list[Scope]
    expires_at: datetime
    revoked_at: datetime | None
    created_by: str
    created_at: datetime
    last_used_at: datetime | None

    @computed_field
    @property
    def status(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        return "expired" if self.expires_at <= datetime.now(timezone.utc) else "active"


class Instance(BaseModel):
    instance_id: str
    cloud_tenant_id: str
    name: str
    created_by: str
    created_at: datetime


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


@dataclass(frozen=True)
class ControlPrincipal:
    control_key_id: str
    cloud_tenant_id: str
    actor_subject: str


@dataclass(frozen=True)
class BusinessPrincipal:
    key_id: str
    member_id: str
    workspace_id: str
    schema_name: str
    scopes: frozenset[Scope]


class ServiceError(Exception):
    """Domain failure; routers translate it without exposing DB errors or credentials."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
