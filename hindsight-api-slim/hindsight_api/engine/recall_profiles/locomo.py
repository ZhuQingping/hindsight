"""LoCoMo message-window context selection, ported without changing the v1 algorithm.

Ported from benchmarks/memory/support.py query-turn-windows-v1. No benchmark runner, QA labels,
network, model or database access. Historical client output is the replay oracle.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

import tiktoken
from nltk.stem import PorterStemmer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hindsight_api.engine.chunk_ids import parse_chunk_id


class SessionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    timestamp: str


class SelectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_id: str
    sessions: list[SessionMetadata]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackingSettings(StrictModel):
    algorithm: Literal[
        "complete-json-separate-budgets-v2", "query-turn-windows-v1", "query-turn-windows-metadata-v2"
    ] = "complete-json-separate-budgets-v2"
    tokenizer: Literal["o200k_base", "cl100k_base"] = "o200k_base"
    max_tokens: int = Field(default=8192, ge=32)
    fact_tokens: int = Field(default=4000, ge=0)
    chunk_tokens: int = Field(default=4000, ge=0)
    fact_order: Literal["recall_order"] = "recall_order"
    chunk_order: Literal["response_order", "query_relevance"] = "response_order"

    @model_validator(mode="after")
    def budgets(self) -> PackingSettings:
        if self.fact_tokens + self.chunk_tokens > self.max_tokens:
            raise ValueError("Fact and chunk quotas cannot exceed the total context budget")
        if (self.algorithm != "complete-json-separate-budgets-v2") != (self.chunk_order == "query_relevance"):
            raise ValueError("Query window packing requires explicit query_relevance chunk order")
        return self


class Fact(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    text: str
    document_id: str | None = None
    chunk_id: str | None = None
    mentioned_at: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None


class Chunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str


class RecallReply(BaseModel):
    model_config = ConfigDict(extra="allow")
    results: list[Fact]
    chunks: dict[str, Chunk] | None = None


class PackedFact(StrictModel):
    text: str
    document: str | None = None
    mentioned_at: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None


class PackedChunk(StrictModel):
    document: str
    index: int
    timestamp: str
    text: str


class Payload(StrictModel):
    facts: list[PackedFact] = Field(default_factory=list)
    chunks: list[PackedChunk] = Field(default_factory=list)

    def render(self) -> str:
        return self.model_dump_json(exclude_none=True)


class Omitted(StrictModel):
    id: str
    reason: Literal["fact_quota", "chunk_quota"]


class Packed(StrictModel):
    text: str
    tokens: int
    fact_tokens: int
    chunk_tokens: int
    included_fact_ids: list[str]
    included_chunk_ids: list[str]
    omitted: list[Omitted]


_QUERY_STOPWORDS = frozenset(
    "a an the and or of to in on at for with from by about what which who when where why how do does did is are was were has have had can could would should mention describe say according".split()
)


class ChatTurn(BaseModel):
    speaker: str
    text: str
    dia_id: str | None = None
    blip_caption: str | None = None
    source_image_search_query: str | None = Field(default=None, validation_alias="query")

    @field_validator("source_image_search_query", mode="before")
    @classmethod
    def textual_image_query(cls, value: object) -> str | None:
        # Malformed optional metadata must not discard speech that v1 could already read.
        return value if isinstance(value, str) else None

    def render(self, *, include_image_search_query: bool = False) -> str:
        label = f"[{self.dia_id}] " if self.dia_id else ""
        caption = f"\nImage caption: {self.blip_caption}" if self.blip_caption else ""
        metadata = ""
        if include_image_search_query and self.source_image_search_query:
            metadata = (
                "\nSource image-search query (metadata, not an observed caption): " + self.source_image_search_query
            )
        return f"{label}{self.speaker}: {self.text}{caption}{metadata}"


@dataclass
class WindowSource:
    identifier: str
    template: PackedChunk
    units: list[str]


@dataclass
class RankedWindow:
    source_index: int
    center: int
    score: float


class WindowSelection(StrictModel):
    included_chunk_ids: list[str]
    omitted: list[Omitted]


def complete_turns(text: str) -> list[ChatTurn]:
    """Recover only observed complete message objects, including from clipped JSON.

    Chunks may end mid-array or start mid-session. Matching the original speaker
    key avoids inventing missing endings or treating a model-generated repair as
    source evidence. Non-JSON passages retain the legacy complete-text fallback.
    """
    turns: list[ChatTurn] = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"speaker"\s*:', text):
        try:
            value, _end = decoder.raw_decode(text, match.start())
            turns.append(ChatTurn.model_validate(value))
        except (ValueError, TypeError):
            continue
    return turns


def _query_lexemes(text: str, stemmer: PorterStemmer) -> list[str]:
    return [stemmer.stem(word) for word in re.findall(r"[^\W_]+", text.casefold()) if word not in _QUERY_STOPWORDS]


def _window_text(units: list[str], positions: set[int]) -> str:
    lines: list[str] = []
    previous = -2
    for position in sorted(positions):
        if previous != -2 and position != previous + 1:
            lines.append("[intervening messages omitted]")
        lines.append(units[position])
        previous = position
    return "\n".join(lines)


def pack_query_windows(
    recalled: RecallReply,
    conversation: SelectionContext,
    settings: PackingSettings,
    query: str,
    payload: Payload,
    fact_total: int,
) -> WindowSelection:
    """BM25-style lexical window selection over returned raw text only, never QA labels."""
    encoder = tiktoken.get_encoding(settings.tokenizer)
    documents = {s.document_id: s for s in conversation.sessions}
    sources: list[WindowSource] = []
    stemmer = PorterStemmer()
    lexemes: list[list[list[str]]] = []
    for identifier, chunk in (recalled.chunks or {}).items():
        ref = parse_chunk_id(identifier)
        if ref is None or ref.bank_id != conversation.bank_id or ref.document_id not in documents:
            raise ValueError("Chunk identity is invalid or outside the question's Bank")
        turns = complete_turns(chunk.text)
        include_metadata = settings.algorithm == "query-turn-windows-metadata-v2"
        units = [turn.render(include_image_search_query=include_metadata) for turn in turns] if turns else [chunk.text]
        sources.append(
            WindowSource(
                identifier=identifier,
                units=units,
                template=PackedChunk(
                    document=ref.document_id,
                    index=ref.chunk_index,
                    timestamp=documents[ref.document_id].timestamp,
                    text=chunk.text,
                ),
            )
        )
        lexemes.append([_query_lexemes(unit, stemmer) for unit in units])
    all_units = [tokens for group in lexemes for tokens in group]
    if not all_units:
        return WindowSelection(included_chunk_ids=[], omitted=[])
    query_tokens = _query_lexemes(query, stemmer)
    frequency = Counter(term for tokens in all_units for term in set(tokens))
    n = len(all_units)
    average = max(1.0, sum(map(len, all_units)) / n)
    idf = {term: math.log(1 + (n - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in set(query_tokens)}
    windows: list[RankedWindow] = []
    for source_index, group in enumerate(lexemes):
        for center, tokens in enumerate(group):
            tf = Counter(tokens)
            norm = 1.2 * (0.25 + 0.75 * len(tokens) / average)
            score = sum(weight * tf[term] * 2.2 / (tf[term] + norm) for term, weight in idf.items() if tf[term])
            pairs = set(zip(tokens, tokens[1:]))
            score += sum(
                0.25 * (idf[left] + idf[right])
                for left, right in zip(query_tokens, query_tokens[1:])
                if (left, right) in pairs
            )
            windows.append(RankedWindow(source_index=source_index, center=center, score=score))
    windows.sort(key=lambda window: (-window.score, window.source_index, window.center))
    selected: dict[int, set[int]] = {}
    order: list[int] = []
    omitted: list[Omitted] = []
    # A fixed cap bounds tokenizer/serialization work; it is shared by all questions.
    # Neighboring turns preserve pronouns, attributions and image discussion context.
    for window in windows[:128]:
        source_index = window.source_index
        source = sources[source_index]
        positions = set(range(max(0, window.center - 1), min(len(source.units), window.center + 2)))
        if positions <= selected.get(source_index, set()):
            continue
        proposed = {key: set(value) for key, value in selected.items()}
        proposed.setdefault(source_index, set()).update(positions)
        proposed_order = order if source_index in order else [*order, source_index]
        chunks = [
            sources[index].template.model_copy(update={"text": _window_text(sources[index].units, proposed[index])})
            for index in proposed_order
        ]
        trial = Payload(facts=payload.facts, chunks=chunks)
        tokens = len(encoder.encode(trial.render()))
        if tokens <= settings.max_tokens and tokens - fact_total <= settings.chunk_tokens:
            selected, order = proposed, proposed_order
            payload.chunks = chunks
        else:
            omitted.append(Omitted(id=f"{source.identifier}#turn-{window.center}", reason="chunk_quota"))
    return WindowSelection(included_chunk_ids=[sources[index].identifier for index in order], omitted=omitted)


def pack_context(
    recalled: RecallReply, conversation: SelectionContext, settings: PackingSettings, query: str | None = None
) -> Packed:
    """Use only returned evidence and input-history dates; never receives QA gold/evidence annotations."""
    encoder = tiktoken.get_encoding(settings.tokenizer)
    payload = Payload()
    empty_tokens = len(encoder.encode(payload.render()))
    documents = {s.document_id: s for s in conversation.sessions}
    omitted: list[Omitted] = []
    fact_ids: list[str] = []
    chunk_ids: list[str] = []
    # Unlike v1's prefix slice, separate quotas reserve room for original text.
    # Measure full serializations each time: token counts are not additive at boundaries.
    fact_budget = min(settings.fact_tokens, settings.max_tokens - empty_tokens - settings.chunk_tokens)
    for fact in recalled.results:
        if fact.document_id is not None and fact.document_id not in documents:
            raise ValueError("Recall returned a document outside the question's conversation")
        candidate = PackedFact(
            text=fact.text,
            document=fact.document_id,
            mentioned_at=fact.mentioned_at,
            occurred_start=fact.occurred_start,
            occurred_end=fact.occurred_end,
        )
        trial = Payload(facts=[*payload.facts, candidate])
        tokens = len(encoder.encode(trial.render()))
        if tokens - empty_tokens <= fact_budget:
            payload.facts.append(candidate)
            fact_ids.append(fact.id)
        else:
            omitted.append(Omitted(id=fact.id, reason="fact_quota"))
    fact_total = len(encoder.encode(payload.render()))
    if settings.algorithm != "complete-json-separate-budgets-v2":
        if query is None or not query.strip():
            raise ValueError("Query-aware packing requires the question text")
        selection = pack_query_windows(recalled, conversation, settings, query, payload, fact_total)
        chunk_ids = selection.included_chunk_ids
        omitted.extend(selection.omitted)
    else:
        for identifier, chunk in (recalled.chunks or {}).items():
            ref = parse_chunk_id(identifier)
            if ref is None or ref.bank_id != conversation.bank_id or ref.document_id not in documents:
                raise ValueError("Chunk identity is invalid or outside the question's Bank")
            source = documents[ref.document_id]
            candidate = PackedChunk(
                document=ref.document_id, index=ref.chunk_index, timestamp=source.timestamp, text=chunk.text
            )
            trial = Payload(facts=payload.facts, chunks=[*payload.chunks, candidate])
            tokens = len(encoder.encode(trial.render()))
            if tokens <= settings.max_tokens and tokens - fact_total <= settings.chunk_tokens:
                payload.chunks.append(candidate)
                chunk_ids.append(identifier)
            else:
                omitted.append(Omitted(id=identifier, reason="chunk_quota"))
    if recalled.chunks and settings.chunk_tokens > 0 and not chunk_ids:
        raise ValueError("No complete original passage fits the reserved chunk quota; do not silently run facts-only")
    text = payload.render()
    total = len(encoder.encode(text))
    if total > settings.max_tokens:
        raise ValueError("Context envelope itself exceeds the token budget")
    return Packed(
        text=text,
        tokens=total,
        fact_tokens=fact_total - empty_tokens,
        chunk_tokens=total - fact_total,
        included_fact_ids=fact_ids,
        included_chunk_ids=chunk_ids,
        omitted=omitted,
    )


def apply_profile(
    recalled: RecallReply,
    *,
    recall_profile: str = "default",
    query: str | None = None,
    context: SelectionContext | None = None,
    settings: PackingSettings | None = None,
) -> RecallReply | Packed:
    """Prototype dispatch; default is an exact passthrough and beam is reserved."""
    if recall_profile == "default":
        return recalled
    if recall_profile == "beam":
        raise NotImplementedError("recall_profile beam is reserved and not enabled")
    if recall_profile != "locomo":
        raise ValueError("Unknown recall_profile")
    if context is None:
        raise ValueError("Server-verified document dates and Bank are required")
    settings = settings or PackingSettings(algorithm="query-turn-windows-v1", chunk_order="query_relevance")
    if settings.algorithm != "query-turn-windows-v1":
        raise ValueError("locomo supports only query-turn-windows-v1")
    if len({s.document_id for s in context.sessions}) != len(context.sessions):
        raise ValueError("Duplicate document metadata")
    return pack_context(recalled, context, settings, query)
