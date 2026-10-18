#!/bin/bash
# Foreground commands for an existing node Agent/systemd/container supervisor.
set -euo pipefail
umask 077

CODE=$(cd "$(dirname "$0")/../../.." && pwd)
PY=${CONTEXTDB_PYTHON:-"$CODE/.venv/bin/python"}
DEPLOY=${CONTEXTDB_DEPLOY_DIR:?Set CONTEXTDB_DEPLOY_DIR to the private persistent directory}
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service:$CODE/hindsight-api-slim"
export HINDSIGHT_API_ENV_FILE=''
command=${1:-preflight}
if [ "$#" -gt 0 ]; then shift; fi

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
export HINDSIGHT_API_ENV_FILE=''

case "$command" in
  preflight)
    exec "$PY" -m hindsight_ext_contextdb preflight --source-root "$CODE" "$@"
    ;;
  init)
    "$PY" -m hindsight_ext_contextdb preflight --source-root "$CODE" --language "${CONTEXTDB_VALIDATION_LANGUAGE:-english}"
    if [ -f "$DEPLOY/ui.env" ]; then
      private_config "$DEPLOY/ui.env"
      set -a
      . "$DEPLOY/ui.env"
      set +a
    fi
    "$PY" -m hindsight_ext_contextdb prepare --directory "$DEPLOY"
    "$PY" -m hindsight_ext_contextdb migrate --directory "$DEPLOY" --admin-key-file "$DEPLOY/admin-key.json"
    # Bootstrap the native shared task tables offline. API startup migration is
    # disabled so a stale process cannot recreate a recycled workspace schema.
    # This explicit public migration has no tenant/bank context; do not ask the
    # generic CLI to enumerate ContextDB tenants (it has no bound engine).
    HINDSIGHT_API_TENANT_EXTENSION='' exec "$PY" -m hindsight_api.admin.cli run-db-migration \
      --schema public --embedding-dimension 1024
    ;;
  api|worker)
    "$PY" -m hindsight_ext_contextdb preflight --source-root "$CODE" --language "${CONTEXTDB_VALIDATION_LANGUAGE:-english}"
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
    echo 'Usage: service.sh {preflight|init|api|worker|ui}' >&2
    exit 2
    ;;
esac
