---
type: tool_used
tool: Bash
input_match: '(\bprofile\\?"?|\bP)\s+set\s+(vcs|host|branches|commit|release|deploy)\.'
min: 1
arm: with-only
---
The answers and the detected facts are saved with `profile set`, so an interrupted run leaves an
unconfirmed profile rather than nothing.
