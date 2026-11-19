"""Wire contract for opt-in recall context; absent for the default profile."""

from typing import Literal

from pydantic import BaseModel, Field


class ProfileOmission(BaseModel):
    id: str
    reason: Literal["fact_quota", "chunk_quota"]


class RecallProfileContext(BaseModel):
    profile: Literal["locomo"] = "locomo"
    version: Literal["message_windows_v1"] = "message_windows_v1"
    format: Literal["locomo-packed-json-v1"] = "locomo-packed-json-v1"
    tokenizer: Literal["o200k_base"] = "o200k_base"
    text: str
    tokens: int
    fact_tokens: int
    chunk_tokens: int
    included_fact_ids: list[str]
    included_chunk_ids: list[str]
    omitted: list[ProfileOmission] = Field(default_factory=list)
