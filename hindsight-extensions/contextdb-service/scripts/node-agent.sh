#!/bin/bash
# Local file/foreground-command contract consumed by the ECS node Agent.
set -euo pipefail
umask 077
CODE=$(cd "$(dirname "$0")/../../.." && pwd)
PY=${CONTEXTDB_PYTHON:-"$CODE/.venv/bin/python"}
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service:$CODE/hindsight-api-slim"
exec "$PY" -m hindsight_ext_contextdb.deployment "$@"
