# Writing briefs for subagents

A subagent knows nothing except its brief and the project's CLAUDE.md files
(which it loads on its own). It can't see this conversation. A longer brief costs
one read; a missing fact costs several turns of rediscovery, or a wrong guess.

Every brief starts with the goal and ends with the expected output. Paste the facts
in; don't make the agent go find them again.

## Context pack (include in every brief)

```markdown
## Goal
<one sentence: what the user wants and why>

## Acceptance criteria
AC-1 …  AC-2 …

## Project context (from discovery: authoritative for this repo)
- Stack: <framework, language, versions that matter>
- Rules that apply here: <the specific CLAUDE.md / rules lines that matter for this change, quoted>
- Skills to use: <project or installed skills relevant to this change, e.g. `shopify-plugin:shopify` for Admin GraphQL; the project's `/db-migrations` skill>
- Commands: test `<cmd>` · lint `<cmd>` · typecheck `<cmd>`
- Invariants / protected areas: <from config or docs: must not change>
- Existing user changes: <uncommitted paths that are not ours; don't touch>

## Scope
- You own: <files/dirs this agent may change>
- Don't touch: <everything else that's nearby and tempting>
```

## Developer brief: add

```markdown
## Task
<what to build or fix; for fixes: the reproduction>
## Constraints
- Follow existing patterns in <similar file> rather than inventing new ones.
- Add/adjust tests that fail without your change.
- No new dependencies unless <condition>; if you need one, stop and say why.
## Return
Use your standard report format (files changed, tests run with exit codes, AC status, open questions).
```

For a fix cycle add the findings JSON and: "For each finding return `fixed` with the
change + test, or `disputed` with evidence."

For a worktree developer (large mode) add: "Commit your work on the worktree
branch with a plain descriptive message when done. Don't push."

## Reviewer brief: add

```markdown
## What to review
Base: `<base ref or sha>`. Review `git diff <base>` (+ untracked files: <list>).
Do not rely on any summary; read the code.
## Focus
<anything specific: concurrency in X, the migration, authz on the new route>
## Already-reported findings to verify (re-review only)
<JSON with status fixed/disputed>
## Return
Your standard format: verdict + findings JSON.
```

Don't send the developer's self-assessment to the reviewer. Send the ACs and the diff
location. The point is an independent read.

## QA brief: add

The ACs, the diff base, the test commands, how to run the app (if relevant), and any
risky areas. Ask for: test cases derived from the ACs, what was executed with real
output, defects as findings, coverage gaps.

## UX brief: add

How to start the app and the URL/route, the user journey(s) to walk, what changed
(files + a screenshot of the old state if you have one), the design system or
component library in use, and which states to check (loading/empty/error/success).
State whether a browser tool is available in this session.

## Choosing agents

- If the project ships its own agent for a role (`.claude/agents/`, e.g. a
  `code-reviewer` that knows the domain), use it for that role. It's authoritative.
  Use the ETK agent as the fallback, or alongside it when the project agent is narrow.
- Model: leave the default unless the project config says otherwise. For a reviewer on
  security-sensitive or large changes, it's reasonable to pass the strongest available
  model.
- Never let two developers own the same file at the same time.
