---
type: tool_used
tool: Bash
input_match: '^(?!\s*sh\s+\S*etk\.sh\S*\s+profile\s)\s*(git\s+(commit|push|merge|tag)|gh\s+(pr|release)|sh\s+\S*etk\.sh\S*\s+run\s+init)'
min: 0
max: 0
arm: with-only
---
init never commits, pushes, merges, deploys or opens a ledger. Only a command that starts
with one of these counts, so note text passed to `profile remember` can't trip it.
