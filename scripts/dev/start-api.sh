#!/bin/bash
# Local ContextBase always uses persisted deployment authentication.
set -euo pipefail
umask 077
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT_DIR/hindsight-extensions/contextdb-service:$ROOT_DIR/hindsight-api-slim${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT_DIR"
exec uv run --package hindsight-api-slim --extra embedded-db --inexact python -m hindsight_ext_contextdb.local --component api "$@"
