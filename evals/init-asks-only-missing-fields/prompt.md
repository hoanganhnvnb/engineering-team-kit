---
description: init must not ask what detect already found (git, GitHub, Conventional Commits, test command), must ask the missing release and deploy fields, and must not write into the repository.
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Bash, AskUserQuestion]
---

/engineering-team:init
