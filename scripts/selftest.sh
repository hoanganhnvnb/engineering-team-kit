#!/usr/bin/env bash
# Quick local check before committing: manifests + unit/structure tests.
# End-to-end scenarios (real model calls) live in tests/e2e/run.py and are run by hand.
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v claude >/dev/null 2>&1; then
  claude plugin validate . --strict
else
  echo "claude CLI not found; skipping manifest validation"
fi
python3 -m unittest discover -s tests
