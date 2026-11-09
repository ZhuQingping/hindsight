#!/usr/bin/env bash
# Run in a disposable checkout: dependency sync/build commands write local outputs.
set -euo pipefail
if [[ "${CI:-}" != true && "${CONTEXTDB_CI_ISOLATED:-}" != 1 ]]; then
  echo 'Use a disposable checkout and set CONTEXTDB_CI_ISOLATED=1; never run in a deployment checkout.' >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
suite=${1:?Usage: run-ci.sh python|ui|build|system|browser [evidence-directory]}
reports=${2:-"$root/.contextdb-ci-results"}
mkdir -p "$reports"
reports=$(cd "$reports" && pwd)
extension="$root/hindsight-extensions/contextdb-service"
# Inherited operator settings must never redirect tests to a user service/database.
while IFS= read -r variable; do
  case "$variable" in HINDSIGHT_*|CONTEXTBASE_*|CONTEXTDB_*) unset "$variable" ;; esac
done < <(compgen -e)
export PYTHON_DOTENV_DISABLED=1 NEXT_TELEMETRY_DISABLED=1 TZ=UTC
export UV_PYTHON
UV_PYTHON=$(cat "$root/.python-version")
export PYTHONPATH="$extension:$root/hindsight-api-slim:$root/hindsight-clients/python:$root/hindsight-system-tests"

case "$suite" in
  python)
    uv sync --project "$extension"
    uv run --project "$extension" --frozen --with ruff==0.14.9 ruff check --config "$extension/pyproject.toml" "$extension"
    uv run --project "$extension" --frozen --with ruff==0.14.9 ruff format --check --config "$extension/pyproject.toml" "$extension"
    uv run --project "$extension" --frozen --with ty==0.0.84 ty check --project "$extension" "$extension/hindsight_ext_contextdb"
    uv run --project "$extension" --frozen python "$extension/scripts/verify_integration.py" extension -- -q --junitxml="$reports/python.xml"
    python3 "$extension/scripts/ci_gate.py" "$reports/python.xml"
    ;;
  ui)
    npm ci --workspace=contextbase-control-plane --workspace=hindsight-clients/typescript
    # Run tests before building the SDK to catch accidental dist/ dependencies.
    if [[ -d hindsight-clients/typescript/dist ]]; then
      echo "Use a fresh isolated checkout: SDK dist must be absent before UI tests." >&2
      exit 2
    fi
    npm test --workspace=contextbase-control-plane -- ../hindsight-extensions/contextdb-service/tests/ui --maxWorkers=2 --reporter=default --reporter=junit --outputFile="$reports/ui.xml"
    npx --no-install prettier --check "$extension/tests/ui"
    npx --no-install eslint --config contextbase-control-plane/eslint.config.mjs \
      contextbase-control-plane/src/components/contextdb "$extension/tests/ui"
    python3 "$extension/scripts/ci_gate.py" "$reports/ui.xml"
    ;;
  build)
    uv sync --project hindsight-system-tests --frozen --group contextdb
    # Both Worker stories must use the production bundle built from this checkout.
    CONTEXTBASE_CP_DATAPLANE_API_URL=https://synthetic-private-api.invalid \
    CONTEXTBASE_CP_DATAPLANE_API_KEY=synthetic-private-api-key \
    CONTEXTBASE_CP_ACCESS_KEY=synthetic-private-password \
      uv run --project hindsight-system-tests --frozen --group contextdb python -m hindsight_ext_contextdb build-ui --source-root "$root"
    ;;
  system)
    uv run --project hindsight-system-tests --frozen --group contextdb python "$extension/scripts/verify_integration.py" contracts -- -q --junitxml="$reports/contracts.xml"
    export CONTEXTDB_UI_SERVER="$root/contextbase-control-plane/standalone/server.js"
    export CONTEXTDB_TEST_NODE_BIN
    CONTEXTDB_TEST_NODE_BIN=$(command -v node)
    uv run --project hindsight-system-tests --frozen --group contextdb python "$extension/scripts/verify_integration.py" contextdb-system -- \
      --ignore="$extension/tests/system/test_112_contextdb_ui_management.py" -q --junitxml="$reports/system.xml"
    # The dedicated six-case report is mandatory, even if pytest failed or skipped.
    status=0
    uv run --project hindsight-system-tests --frozen --group contextdb python "$extension/scripts/verify_integration.py" contextdb-system -- \
      -k "test_ui_workspace_user_key_and_native_permission_flow or test_connect_page_derives_the_external_api_endpoint or test_fixed_origin_ignores_a_client_supplied_external_origin" -q --junitxml="$reports/production-ui.xml" || status=$?
    uv run --project hindsight-system-tests --frozen --group contextdb python "$extension/scripts/check_production_ui.py" "$reports/production-ui.xml"
    python3 "$extension/scripts/ci_gate.py" "$reports/contracts.xml" "$reports/system.xml" "$reports/production-ui.xml"
    exit "$status"
    ;;
  browser)
    npm install --prefix "$reports/browser-driver" --no-package-lock playwright@1.57.0
    # Pass an absolute driver path independently of the working directory.
    driver=$(node -e 'console.log(require("node:path").resolve(process.argv[1], "browser-driver/node_modules/playwright"))' "$reports")
    CLIPBOARD_PLAYWRIGHT_PATH="$driver" \
      node "$extension/tests/browser/key-copy.cjs"
    ;;
  *) echo "Unknown suite: $suite" >&2; exit 2 ;;
esac
