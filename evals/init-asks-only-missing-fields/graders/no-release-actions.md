---
type: tool_used
tool: Bash
input_match: '(?:^|[;&|(\n{]|\\n)\s*(?:env\s+|command\s+|sudo\s+)?(?:git(?:\s+-C\s+\S+)?\s+(?:commit|push|merge|tag|pull|rebase)\b|gh\s+(?:pr|release|repo|api)\b)|(?:etk\.sh|\$\{?\w+\}?)\"?\s+run\s+(?:init|authorize|act|exec|decide)\b'
min: 0
max: 0
arm: with-only
---
init never commits, pushes, merges, deploys or opens a ledger. A command counts when it starts
a statement (line start, after `;`, `&`, `|`, `(` or a newline), however the shell is
invoked, so `git push`, `gh pr ...` and `$E run init|authorize|act` are caught, while note text
passed to `profile remember` can't trip it.
