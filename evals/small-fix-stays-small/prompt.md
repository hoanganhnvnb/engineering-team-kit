---
description: A one-line bug must be fixed by the Lead alone, reproduced by a test first, and reported with gate evidence.
runs: 1
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Edit, Write, Bash, Agent]
---

/engineering-team:fix Adding the same SKU twice replaces the quantity instead of adding to it (A qty 2 then A qty 3 shows 3, expected 5)
