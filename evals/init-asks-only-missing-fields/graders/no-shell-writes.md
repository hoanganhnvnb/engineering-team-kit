---
type: tool_used
tool: Bash
input_match: '^(?!\s*sh\s+\S*etk\.sh\S*\s+profile\s)[\s\S]*?((?<![0-9&])>>?\s*[^&\s/]|>>?\s*/(?!dev/null)|\btee\b|\bmkdir\b|\btouch\b|\bsed\s+-i|\b(cp|mv|rm)\s|git\s+(add|init|config|stash))'
min: 0
max: 0
arm: with-only
---
No Bash call writes into the workspace: no redirect to a file, `tee`, `mkdir`, `touch`,
`sed -i`, `cp`, `mv`, `rm`, or a git command that changes the repository. A call that
starts with `sh .../etk.sh profile ...` is exempt, because those commands write outside the
repo and their quoted note text may contain any word.
