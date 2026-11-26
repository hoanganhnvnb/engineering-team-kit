---
type: tool_used
tool: Bash
input_match: '(?<![0-9&>])>>?\s*(?!&|/dev/null)[^\s&]|\btee\b|\bsed\s+-i\b|(?:^|[;&|(\n{]|\\n)\s*(?:env\s+|command\s+|sudo\s+)?(?:mkdir|touch|cp|mv|rm|ln|chmod|truncate|dd|install)\b|(?:^|[;&|(\n{]|\\n)\s*(?:env\s+|command\s+|sudo\s+)?git(?:\s+-C\s+\S+)?\s+(?:add|init|config|stash|checkout|switch|reset|clean|restore|rm|mv|apply|am)\b'
min: 0
max: 0
arm: with-only
---
No Bash call writes into the workspace: no redirect to a file (`2>&1` and `>/dev/null` are
fine), `tee`, `sed -i`, a statement that starts with `mkdir`, `touch`, `cp`, `mv`, `rm`, `ln`
or similar, or a git command that changes the repository. `profile` commands are not exempt:
they write outside the repo, and nothing in them looks like a write.
