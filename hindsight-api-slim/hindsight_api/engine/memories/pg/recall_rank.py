"""P3 with an exact native cover-density rank specialization, one PG call."""

from .recall_beam import BeamPostgresRecallMemories


class RankPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-rank-experimental"
    candidate_statement = "SELECT recall_beam_rank.candidates($1::jsonb, $2::name) AS bundle"


class RankJsonPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-rank-json-experimental"
    candidate_statement = "SELECT recall_beam_rank_json.candidates($1::jsonb, $2::name) AS bundle"
