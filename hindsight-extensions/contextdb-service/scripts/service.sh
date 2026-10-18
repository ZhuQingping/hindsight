#!/bin/bash
# Foreground commands for an existing node Agent/systemd/container supervisor.
set -euo pipefail
umask 077

CODE=$(cd "$(dirname "$0")/../../.." && pwd)
PY=${CONTEXTDB_PYTHON:-"$CODE/.venv/bin/python"}
DEPLOY=${CONTEXTDB_DEPLOY_DIR:?Set CONTEXTDB_DEPLOY_DIR to the private persistent directory}
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service:$CODE/hindsight-api-slim"
export PYTHON_DOTENV_DISABLED=1
command=${1:-preflight}
if [ "$#" -gt 0 ]; then shift; fi

if [ "$command" = all ]; then
  # Child entrypoints retain their own environment and readiness checks.
  export CONTEXTDB_COMBINED=1
  exec "$PY" "$(dirname "$0")/run_combined.py" "$0" "$@"
fi

private_config() {
  "$PY" - "$1" <<'PY'
import stat, sys
from pathlib import Path
path = Path(sys.argv[1])
mode = path.lstat().st_mode
if not stat.S_ISREG(mode) or mode & 0o077:
    raise SystemExit('Deployment configuration must be a private regular file (0600)')
PY
}

if [ "$command" = ui ]; then
  private_config "$DEPLOY/ui.env"
  set -a
  . "$DEPLOY/ui.env"
  set +a
else
  private_config "$DEPLOY/api.env"
  set -a
  . "$DEPLOY/api.env"
  set +a
fi
# Always override discovery after loading the explicit deployment file.
export PYTHON_DOTENV_DISABLED=1

case "$command" in
  preflight)
    exec "$PY" -m hindsight_ext_contextdb preflight --source-root "$CODE" "$@"
    ;;
  init)
    "$PY" -m hindsight_ext_contextdb preflight --source-root "$CODE" --language english
    if [ -f "$DEPLOY/ui.env" ]; then
      private_config "$DEPLOY/ui.env"
      set -a
      . "$DEPLOY/ui.env"
      set +a
    fi
    "$PY" -m hindsight_ext_contextdb prepare --directory "$DEPLOY"
    "$PY" -m hindsight_ext_contextdb migrate --directory "$DEPLOY" --admin-key-file "$DEPLOY/admin-key.json"
    # Native tables are created only inside each workspace schema. An empty
    # instance needs metadata and credentials, not a default public Bank.
    ;;
  api|worker)
    if [ "${CONTEXTDB_COMBINED:-0}" = 1 ] && [ "${HINDSIGHT_API_WORKER_ENABLED:-false}" != true ]; then
      echo 'Combined deployment requires the in-process Worker' >&2
      exit 2
    fi
    "$PY" -m hindsight_ext_contextdb preflight --source-root "$CODE" --language english
    exec "$PY" -m hindsight_ext_contextdb run --component "$command" --directory "$DEPLOY" --source-root "$CODE"
    ;;
  ui)
    ready="${HINDSIGHT_CP_DATAPLANE_API_URL:-http://127.0.0.1:8888}/health/ready"
    deadline=$((SECONDS + 60))
    while ! "$PY" -m hindsight_api.http_probe "$ready" 1; do
      if [ "$SECONDS" -ge "$deadline" ]; then
        echo 'API readiness timed out; UI was not started' >&2
        exit 1
      fi
      sleep 1
    done
    exec "$PY" -m hindsight_ext_contextdb run --component ui --directory "$DEPLOY" --source-root "$CODE"
    ;;
  *)
    echo 'Usage: service.sh {preflight|init|all|api|worker|ui}' >&2
    exit 2
    ;;
esac
