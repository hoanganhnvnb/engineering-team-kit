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
- Conventions: <absolute paths of the conventions/ topics that apply, from the snapshot's Conventions line; e.g. …/conventions/naming.md, …/style.md>

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

Don't send the developer's self-assessment to the reviewer, or your own conclusions
("looks fine", "just confirm"). Send the request, the ACs, the diff location and the doc
paths. The point is an independent read. Subagents never see this conversation or the
skill text: anything they must obey goes in the brief or is already in their agent file.

## QA brief: add

The ACs, the diff base, the test commands, how to run the app (if relevant), and any
risky areas. Ask for: test cases derived from the ACs, what was executed with real
output, defects as findings, coverage gaps.

## UX brief: add

How to start the app and the URL/route, the user journey(s) to walk, what changed
(files + a screenshot of the old state if you have one), the design system or
component library in use, and which states to check (loading/empty/error/success).
State whether a browser tool is available in this session.

## Scout brief

A numbered list of factual questions, each answerable with paths or command output:
"Where is the discount logic and what calls it?", "Which test files cover `src/cart`?",
"What does CI run?", "Which existing features look like X (give 2 paths)?". Ask for
nothing it would have to judge. Use a scout when answering would take you more than a
few file reads. It's cheap and keeps your own context small.

## Tech writer brief

The audience, the files to create or update (`docs/agent/FEATURES.md`, `DECISIONS.md`,
`CURRENT_STATE.md`, `LESSONS.md`, or a user-facing doc), the facts to record (what
changed, how to reach and prove it, the decisions the user made), the template from
`templates/agent-docs/`, and "verify each claim against the code; leave out what you can't".

## Choosing agents

- If the project ships its own agent for a role (`.claude/agents/`, e.g. a
  `code-reviewer` that knows the domain), use it for that role. It's authoritative.
  Use the ETK agent as the fallback, or alongside it when the project agent is narrow.
- Model: each agent has a sensible default (see the table in `routing.md`). Pass `model`
  only when the project config's `models` overrides it, or for a deliberate second opinion
  on a different model (tie-breaks).
- Lens: for reviewers, say which lens (`correctness`, `security`, `architecture`).
- ID prefix: for reviewers, say which finding-ID prefix to use: `R` for `correctness` and
  `architecture`, `S` for `security`. Reviewers running in parallel must not share a prefix,
  or the ledger rejects the duplicate IDs.
- Never let two developers own the same file at the same time.
