#!/bin/sh
# Run the plugin evals against a temporary copy of the plugin.
#
# Why a copy: `claude plugin eval` runs each case in a sandbox whose temp dir is
# read-only for the harness's own shell wrapper. A skill's `!` snapshot line then
# counts as failed and the run ends at turn 0. In the copy, that line becomes
# "run this with the Bash tool", which the sandbox allows. Everything else (agents,
# hooks, scripts, workflows, graders) is the real thing, and the real skills in the
# repo are not changed.
#
#   evals/run.sh                       all cases
#   evals/run.sh --case 'small-*'      extra flags go straight to `claude plugin eval`
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/etk-eval.XXXXXX")
trap 'rm -r -- "$tmp"' EXIT INT TERM

# Copy tracked files plus the new ones that aren't ignored; leave out git history and old results.
(cd "$root" && git ls-files -co --exclude-standard) | (cd "$root" && xargs -d '\n' tar -cf -) | tar -xf - -C "$tmp"

for py in python3 /usr/bin/python3 /usr/local/bin/python3 python; do
  if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    "$py" - "$tmp" <<'EOF'
import re, sys
from pathlib import Path
for p in Path(sys.argv[1], "skills").glob("*/SKILL.md"):
    s = p.read_text()
    s = re.sub(r'^!`(sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/etk\.sh" discover)`$',
               r'Run this first with the Bash tool and read its output: `\1`', s, flags=re.M)
    p.write_text(s)
EOF
    break
  fi
done

out="$root/evals/results/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out"
cd "$tmp"
claude plugin eval . --trust-plugin --scaffold --allow-tools Bash Write Edit \
  --ablation none --judge-model sonnet --no-publish --max-cost-usd 12 --threshold 0 \
  --output-dir "$out" --report "$out/report.html" --json "$out/result.json" "$@"
echo "results: $out"
