---
description: A change that puts user input into SQL is security-sensitive, so it gets an independent reviewer even though it is small.
runs: 1
max_turns: 60
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill, Edit, Write, Bash, Agent]
---

/engineering-team:build Add Repo.search_by_name(term) returning users whose name contains term, case-insensitive, max 20
