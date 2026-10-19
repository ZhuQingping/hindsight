#!/bin/bash
# Operations API examples for Hindsight CLI
# Run: bash examples/api/operations.sh

set -e

BANK_ID="my-bank"

# =============================================================================
# Setup (not shown in docs)
# =============================================================================
# Submit an async retain so we have a real pending operation_id to exercise
# get / cancel below.
OPERATION_ID=$(
  contextbase memory retain "$BANK_ID" "setup-1 for ops examples" --async -o json \
    | jq -r '.operation_id'
)


# =============================================================================
# Doc Examples
# =============================================================================

# [docs:operations-list]
contextbase operation list my-bank
# [/docs:operations-list]


# [docs:operations-get]
contextbase operation get my-bank "$OPERATION_ID"
# [/docs:operations-get]


# [docs:operations-cancel]
contextbase operation cancel my-bank "$OPERATION_ID"
# [/docs:operations-cancel]


# Setup for retry: create another op and cancel it so it's in a retryable state.
OPERATION_ID=$(
  contextbase memory retain "$BANK_ID" "setup-2 for retry example" --async -o json \
    | jq -r '.operation_id'
)
contextbase operation cancel "$BANK_ID" "$OPERATION_ID" >/dev/null


# [docs:operations-retry]
contextbase operation retry my-bank "$OPERATION_ID"
# [/docs:operations-retry]


# [docs:operations-async-retain]
# Submit an async retain and capture the operation_id from the JSON response.
OPERATION_ID=$(
  contextbase memory retain my-bank "Alice joined Google in 2023" --async -o json \
    | jq -r '.operation_id'
)

# Poll until the worker finishes — completed/failed/cancelled are all terminal.
while true; do
  STATUS=$(contextbase operation get my-bank "$OPERATION_ID" -o json | jq -r '.status')
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] || [ "$STATUS" = "cancelled" ]; then
    echo "finished: $STATUS"
    break
  fi
  sleep 2
done
# [/docs:operations-async-retain]
