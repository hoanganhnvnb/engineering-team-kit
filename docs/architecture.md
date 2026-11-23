# Architecture

## Components

```
.claude-plugin/
  plugin.json          name "engineering-team" → commands are /engineering-team:<skill>
  marketplace.json     this repo is its own marketplace (source "./")
skills/                user-invoked commands; the main session runs them as Lead
  build/ fix/ review/ test/ improve-ui/
agents/                subagents the Lead spawns as engineering-team:<name>
  developer.md         full tools except Agent
  code-reviewer.md     read-only (no Edit/Write), no Agent
  qa-engineer.md       no Edit (may Write new test files), no Agent
  ux-reviewer.md       read-only, inherits MCP tools so it can use a browser
workflows/             reference docs the Lead reads at the step that needs them
  discovery.md routing.md briefs.md review-loop.md parallel.md project-memory.md
quality/
  gates.md findings.md report-template.md
scripts/
  discover.py          project snapshot, injected into every command
  etk_run.py           ledger: init / check / render / latest
hooks/
  hooks.json, guard.py PreToolUse seatbelt for engineering-team:* subagents only
templates/             project config + docs/agent templates
tests/                 unit + structure tests, fixtures, e2e runner
```

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
   `git diff … | git apply --3way` (no commits on your branch).
5. **Review loop.** Fresh reviewer (+QA, +UX in parallel) → Lead triages findings →
   fresh developer fixes → re-test → fresh reviewer verifies. Max 3 cycles.
6. **Gates.** G1–G6 with evidence → `etk_run.py check` → outcome.
7. **Report** in the user's language, plus `docs/agent/` updates for long tasks.

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
