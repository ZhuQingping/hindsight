"""Experimental performance variants of the frozen equivalent PG path.

Each variant keeps the original native cursor queries and legacy ordinals. Model,
final scoring and budgets remain in the inherited ContextBase finalizer.
"""

from .recall_beam import BeamPostgresRecallMemories


class ProjectionPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-projection-experimental"
    candidate_statement = "SELECT recall_beam_projection.candidates($1::jsonb, $2::name) AS bundle"


class PackedPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-packed-experimental"
    candidate_statement = "SELECT recall_beam_packed.candidates($1::jsonb, $2::name) AS bundle"


class ArrayPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-arrays-experimental"
    candidate_statement = "SELECT recall_beam_arrays.candidates($1::jsonb, $2::name) AS bundle"


class ParallelPostgresRecallMemories(BeamPostgresRecallMemories):
    name = "postgres-recall-parallel-experimental"
    candidate_statement = "SELECT recall_beam_parallel.candidates($1::jsonb, $2::name) AS bundle"
