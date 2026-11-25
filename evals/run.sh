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
(cd "$root" && git ls-files -co --exclude-standard) | while IFS= read -r f; do
  [ -f "$root/$f" ] || continue
  mkdir -p "$tmp/$(dirname "$f")"
  cp -p "$root/$f" "$tmp/$f"
done

patched=0
for py in python3 python3.13 python3.12 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 python; do
  if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    "$py" - "$tmp" <<'EOF'
import re, sys
from pathlib import Path
skills = list(Path(sys.argv[1], "skills").glob("*/SKILL.md"))
done = 0
for p in skills:
    s = p.read_text()
    s, n = re.subn(r'^!`(sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/etk\.sh" discover)`$',
                   r'Run this first with the Bash tool and read its output: `\1`', s, flags=re.M)
    p.write_text(s)
    done += n > 0
if not skills or done != len(skills):
    sys.exit(f"evals/run.sh: rewrote the snapshot line in {done} of {len(skills)} skills; "
             "the eval would fail at turn 0 for the rest")
EOF
    patched=1
    break
  fi
done
if [ "$patched" != 1 ]; then
  echo "evals/run.sh: Python 3.12+ not found; the skill snapshot lines cannot be patched" >&2
  exit 1
fi

case " $* " in
  *" --threshold"*) ;;
  *) echo "warning: evals/run.sh passes --threshold 0, so it exits 0 whatever the scores are; read the report, or pass --threshold N to make low scores fail" >&2 ;;
esac

out="$root/evals/results/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out"
cd "$tmp"
claude plugin eval . --trust-plugin --scaffold --allow-tools Bash Write Edit \
  --ablation none --judge-model sonnet --no-publish --max-cost-usd 12 --threshold 0 \
  --output-dir "$out" --report "$out/report.html" --json "$out/result.json" "$@"
echo "results: $out"
