---
type: tool_used
tool: Bash
input_match: 'etk\.sh\\?"? profile\\?"? set '
min: 1
arm: with-only
---
The answers and the detected facts are saved with `profile set`, so an interrupted run leaves an
unconfirmed profile rather than nothing.
