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
# The tests drive scripts that need Python 3.12+; pick the interpreter the way scripts/etk.sh does.
candidates="python3 python3.13 python3.12 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 python"
py=""
for cand in $candidates; do
  if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    py=$cand
    break
  fi
done
if [ -z "$py" ]; then
  echo "selftest: Python 3.12+ not found (tried ${candidates// /, }); install one or put it on PATH" >&2
  exit 127
fi
"$py" -m unittest discover -s tests
