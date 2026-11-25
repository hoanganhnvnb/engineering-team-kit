# Architecture

## Components

```
.claude-plugin/
  plugin.json          name "engineering-team" → commands are /engineering-team:<skill>
  marketplace.json     this repo is its own marketplace (source "./")
skills/                commands; the main session runs them as Lead
  team/                the one model-invocable skill: implement → review/test → release → deploy
  build/ fix/ review/ test/ improve-ui/ retro/ readme/   user-only step commands
agents/                subagents the Lead spawns as engineering-team:<name>
  scout.md             haiku; read-only fact gathering and run-data export
  developer.md         session model; full tools except Agent
  code-reviewer.md     opus; read-only (no Edit/Write), no Agent; lenses
  qa-engineer.md       sonnet; no Edit (may Write new test files), no Agent
  ux-reviewer.md       session model; read-only, inherits MCP tools so it can use a browser
  tech-writer.md       opus; Markdown only, verifies every claim against the code
workflows/             reference docs the Lead reads at the step that needs them
  discovery.md routing.md briefs.md review-loop.md parallel.md project-memory.md
  decisions.md (when to ask) profile.md (onboarding) ship.md (commit/push/PR/deploy)
conventions/           agent rules: index + 10 topics, read on demand (see docs/conventions.md)
quality/
  gates.md findings.md hardening.md report-template.md
scripts/
  discover.py          project snapshot (incl. hard checks, path rules), injected into every command
  etk_run.py           ledger: init / check / render / stats / latest / phase / authorize / act / decide
  etk_profile.py       per-developer workflow profile in ${CLAUDE_PLUGIN_DATA} (never in the repo)
hooks/
  hooks.json           PreToolUse → run-guard.sh (exits at once unless the caller is an ETK agent)
  guard.py             parses each command segment; blocks push/deploy/discarding work/secrets,
                       shell writes by reviewers, overwrites by QA
templates/             project config + docs/agent templates (incl. FEATURES, LESSONS)
evals/                 `claude plugin eval` cases: behaviour tests for the skills
tests/                 unit + structure tests, fixtures, e2e runner
```

Subagents never see the skill text or this conversation. Whatever they must obey is in
their agent file or in the brief the Lead writes, never only in a skill.

## Why these mechanisms

**The main session is the Lead.** It's the only agent the user talks to, it can spawn
subagents (subagents shouldn't spawn more; the agents disallow the `Agent` tool), and it
keeps the whole picture. A separate "orchestrator agent" would only add a handoff.

**Skills, not commands.** Plugin skills are namespaced (`/engineering-team:build`), take
`$ARGUMENTS`, can inject live context with `` !`…` ``, and can point at supporting files
via `${CLAUDE_PLUGIN_ROOT}`. They're marked `disable-model-invocation: true`, so the team
workflow starts only when you ask for it, not because a prompt mentioned "fix".

**Subagents, not agent teams.** Agent teams are experimental and off by default. Regular
subagents work everywhere, including headless `claude -p`, and the Agent tool's
`isolation: "worktree"` gives large tasks separate checkouts.

**No MCP server.** Nothing here needs one. Orchestration is prose the Lead follows plus
two small scripts. An MCP server would add a process to install and keep running.

**A ledger file plus a checker.** Status lives in `.etk/runs/<id>/gates.json`, not in
the conversation, so it survives context compaction, can be checked by a script, and
can be picked up in a later session. `.etk/` is added to `.git/info/exclude` (local only;
your tracked `.gitignore` isn't touched).

**The hook only applies to ETK agents.** Hook input carries `agent_type` for subagent
tool calls (verified on 2.1.329). The guard does nothing unless it starts with
`engineering-team:`, so installing the plugin doesn't change how your own sessions or
other plugins behave.

## The build flow in detail

1. **Snapshot.** `discover.py` runs before the Lead sees the skill. It reports the git
   state and uncommitted files, instruction files, project skills/agents, architecture
   docs, stack, declared test commands, CI files, Shopify signals, the ETK config, and
   the last run.
2. **Understand.** The Lead reads the applicable instructions and code, writes
   acceptance criteria, and asks only if the ambiguity changes what gets built.
3. **Size + ledger.** `etk_run.py init`, then a baseline test run for medium/large.
4. **Build.** Small: the Lead. Medium: `developer` with a brief. Large: plan.md
   (contract + file-disjoint workstreams) → worktree developers → integrate with
   plain `git apply` after checking the files are untouched (no commits, nothing staged).
5. **Review loop.** Fresh reviewer (+ a security-lens reviewer when it matters, +QA,
   +UX in parallel) → Lead triages findings → fresh developer fixes → re-test → fresh
   reviewer verifies. Max 3 cycles. Disputed critical/high findings get a tie-breaker
   on a different model.
5b. **Run it.** The developer and QA drive the change for real and record `runtime`
   commands; the checker warns on a medium/large build without any.
6. **Gates.** G1–G6 with evidence → `etk_run.py check` → outcome.
7. **Report** in the user's language, with hardening proposals ("make it stick"). The
   `tech-writer` updates `docs/agent/` when it's worth it.

## Model tiering

Agent frontmatter sets a default `model` per role (haiku for the scout, sonnet for QA,
opus for review and writing, the session's model for building and UX). Project config
`models` overrides it, and the Lead passes `model` when spawning. Rationale: mechanical
work (finding files, exporting data, running suites) is fine on a fast model; finding
real bugs and writing durable docs is where accuracy pays.

## Learning over time

Findings carry a `category` and, from medium up, a `hardening` proposal (`architecture`,
`static`, `runtime`, `prose`). `etk_run.py stats` aggregates every ledger in `.etk/runs/`:
outcomes, findings per run (older vs newer half), runtime-evidence share, and categories
that recurred across runs. `/engineering-team:retro` has the scout export that, the
tech-writer record it in `docs/agent/LESSONS.md`, and the Lead propose 1–3 hard checks as
a ratchet (block new occurrences → clean up old ones → watch the trend). Nothing is
added to the project unless the user agrees.

## Evals

`evals/` holds `claude plugin eval` cases that check behaviour, not just structure: a
small fix stays small (no subagents), a UI change without a browser is reported honestly
(G5 BLOCKED, not COMPLETE), and a security change gets an independent reviewer. Each case
builds its own fixture with a scaffold script and is graded by tool-use checks, file
regexes, and an LLM judge on a different model.

## Project compatibility

- **Instructions.** Non-fork subagents load the project's CLAUDE.md hierarchy
  themselves. The Lead also quotes the specific rules that matter in each brief,
  because "somewhere in CLAUDE.md" is easy to miss.
- **Skills.** The snapshot lists project skills with descriptions, and the Lead names
  the relevant ones in briefs. Subagents keep the Skill tool, so they can use them.
- **Agents.** If the project defines an agent for a role (e.g. a domain-aware reviewer),
  the Lead uses it for that role. The config can map roles explicitly.
- **Platform rules.** Shopify-specific guidance is only triggered by real Shopify signals
  (app toml, theme layout, extension toml, `@shopify/*` packages). Then the Lead points
  agents at the installed Shopify skill. Nothing Shopify-related appears otherwise.
