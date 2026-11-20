"""One PG result set: candidate JSON plus raw scalar chunk rows, with no reread."""

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Json

from ...db_utils import acquire_with_retry
from ...response_models import RecallResult
from ...retain.attachment_content import iter_placeholder_ids
from ...search.types import MergedCandidate
from ..base import FullRecallRequest, RecallCandidateBatch, RecallCandidateChunk
from .recall_beam import BeamPostgresRecallMemories


class StreamRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    part: Literal[0, 1]
    ordinal: int
    payload: Json[list[MergedCandidate]] | list[MergedCandidate] | None
    chunk_id: str | None
    chunk_text: str | None
    chunk_index: int | None
    document_id: str | None


class StreamedPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-streamed-experimental"
    candidate_statement = "SELECT * FROM recall_beam_streamed.candidates($1::jsonb, $2::name)"

    async def full_recall(self, request: FullRecallRequest) -> RecallResult | None:
        if not self.supports(request):
            return None
        assert request.runtime is not None
        from ...memory_engine import get_current_schema

        query = self.candidate_query(request)
        started = time.perf_counter()
        async with acquire_with_retry(request.runtime.backend) as conn:
            records = await conn.fetch(
                self.candidate_statement, query.model_dump_json(), get_current_schema().strip('"')
            )
        # Built-in scalar columns avoid first-request custom-type introspection.
        # The first row owns all candidates; subsequent rows carry unique chunks
        # in JSONB's original key order. No text is omitted, clipped or refetched.
        rows = [StreamRow.model_validate(dict(record)) for record in records]
        if not rows or rows[0].part != 0 or rows[0].ordinal != 0 or rows[0].payload is None:
            raise RuntimeError("PG stream is missing its candidate header")
        candidates = rows[0].payload
        chunks: dict[str, RecallCandidateChunk] = {}
        for ordinal, row in enumerate(rows[1:], start=1):
            if (
                row.part != 1
                or row.ordinal != ordinal
                or row.payload is not None
                or row.chunk_id is None
                or row.chunk_text is None
                or row.chunk_index is None
                or row.document_id is None
                or row.chunk_id in chunks
            ):
                raise RuntimeError("PG stream contains a malformed or duplicate chunk")
            chunks[row.chunk_id] = RecallCandidateChunk(
                chunk_text=row.chunk_text, chunk_index=row.chunk_index, document_id=row.document_id
            )
        if any(candidate.retrieval.attachment_ids for candidate in candidates) or any(
            any(iter_placeholder_ids(chunk.chunk_text)) for chunk in chunks.values()
        ):
            raise RuntimeError("Attachment-bearing data is outside experimental stream scope")
        return await request.runtime.finalize(
            RecallCandidateBatch(
                candidates=candidates,
                chunks=chunks,
                fully_loaded=True,
                stages={"pg_candidates_and_transfer": int((time.perf_counter() - started) * 1_000_000)},
            )
        )
