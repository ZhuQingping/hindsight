#!/usr/bin/env bash
# The single reproducible product rename workflow. --check never writes outputs.
set -euo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--check" ) ]]; then
  echo "Usage: bash scripts/sync-product-brand.sh [--check]" >&2
  exit 2
fi
cd "$(dirname "$0")/.."
node scripts/generate-brand.mjs "$@"
node hindsight-integrations/coding-agents/scripts/build-skill.mjs "$@"
node hindsight-docs/scripts/sync-coding-agents-doc.mjs "$@"
