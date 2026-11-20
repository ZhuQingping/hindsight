"""BEAM compatibility boundary, separate from measured performance variants."""

from ....config import get_config
from ...search.retrieval import tokenize_query
from ..base import FullRecallRequest
from .recall_pushdown import CandidateQuery, EquivalentPostgresRecallMemories


class BeamCandidateQuery(CandidateQuery):
    tokens: list[str]
    term_limit: int
    selective_terms: bool
    language: str


class BeamPostgresRecallMemories(EquivalentPostgresRecallMemories):
    name = "postgres-beam-compatible-experimental"
    candidate_statement = "SELECT recall_beam_compatible.candidates($1::jsonb, $2::name) AS bundle"

    def supports_query_terms(self, request: FullRecallRequest) -> bool:
        # The separate PG baseline reproduces the original term-df lookup inside
        # the candidate call, including fallback and token-position tie handling.
        return True

    def candidate_query(self, request: FullRecallRequest) -> BeamCandidateQuery:
        config = get_config()
        base = super().candidate_query(request)
        return BeamCandidateQuery(
            **base.model_dump(),
            tokens=tokenize_query(request.query_text),
            term_limit=config.bm25_max_query_terms,
            selective_terms=config.bm25_selective_terms,
            language=config.text_search_extension_native_language,
        )
