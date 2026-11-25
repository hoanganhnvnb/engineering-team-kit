#!/usr/bin/env bash
# Quick local check before committing: manifests + unit/structure tests.
# End-to-end scenarios (real model calls) live in tests/e2e/run.py and are run by hand.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/.."
if command -v claude >/dev/null 2>&1; then
  claude plugin validate . --strict
else
  echo "claude CLI not found; skipping manifest validation"
fi
# The tests drive scripts that need Python 3.12+; pick the interpreter the way scripts/etk.sh does.
. "$here/find-python.sh"
if ! etk_find_python; then
  echo "selftest: $(etk_python_hint)" >&2
  exit 127
fi
"$ETK_PY" -m unittest discover -s tests
