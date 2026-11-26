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

. "$root/scripts/find-python.sh"
if ! etk_find_python; then
  echo "evals/run.sh: $(etk_python_hint) The skill snapshot lines cannot be patched without it." >&2
  exit 1
fi
"$ETK_PY" - "$tmp" <<'EOF'
import re, sys
from pathlib import Path
skills = list(Path(sys.argv[1], "skills").glob("*/SKILL.md"))
left = []
for p in skills:
    s = p.read_text()
    s = re.sub(r'^!`(sh "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/etk\.sh" discover(?: --data "\$\{CLAUDE_PLUGIN_DATA\}")?)`$',
               r'Run this first with the Bash tool and read its output: `\1`', s, flags=re.M)
    p.write_text(s)
    fenced = False
    for line in s.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and re.search(r'!`[^`]+`', line):
            left.append(p.parent.name)
            break
if not skills or left:
    sys.exit(f"evals/run.sh: a snapshot line was left in {', '.join(left) or 'no skills'}; "
             "the eval would fail at turn 0 for them")
EOF

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
