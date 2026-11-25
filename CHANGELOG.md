# Changelog

All notable changes to this plugin. Versions follow semver; the version in
`.claude-plugin/plugin.json` is what installed copies pin to.

## 0.3.0

- **Breaking: Python 3.12 or newer is required.** `etk.sh`, the guard wrapper and
  `evals/run.sh` pick the first working Python that is 3.12+ (also trying `python3.12` and
  `python3.13`). If there is none, the guard blocks the plugin's subagents with a message
  instead of letting them run unguarded; the main session is not affected. CI now runs on
  Python 3.12, on Linux and macOS.
- The guard now reads shell commands with a real tokenizer and parser (quotes, heredocs,
  nested shells, `cd` tracking) instead of pattern matching. New protections: `protected_paths`
  from the project config, write-style MCP tools, read-only git for read-only roles, `.git` and
  bulk deletes, env/sudo options that change directory. It fails closed when it hits an error.
- The guard is a best-effort tripwire, not a sandbox. Known open items are in
  `docs/limitations.md`: obfuscated commands, MCP tools with neutral names, files created by
  earlier tool calls, agents mapped through the `agents` config, and the main session.
- Ledger: new `invalid` finding status (needs a `resolution`); a report-only review can finish
  `COMPLETE` with open mediums; `etk.sh exec <gate> --type test -- <cmd>` runs a command and records
  its real exit code, and `check` warns about G3/G4 passes recorded any other way. `exec` is not
  pre-approved by any skill and is only as guarded as the guard's wrapper handling.
- Fixes: two `init` runs in the same second no longer crash; `render` copes with malformed
  criteria and gates; the project snapshot no longer hides skills named `build` or `test`;
  parallel reviewers get distinct finding ID prefixes; review and improve-ui wording matches the
  routing rules; `evals/run.sh` no longer needs GNU `xargs` and fails if its patch step misses.

## 0.2.1

- `evals/run.sh`: run the evals on a temporary copy so a harness sandbox problem with
  `!` injection doesn't end every run at turn 0. Eval results recorded in `docs/validation.md`.

## 0.2.0

- New agents: `scout` (haiku; fact gathering and data export) and `tech-writer` (opus;
  project docs, verifies every claim). Default models per role: `code-reviewer` opus,
  `qa-engineer` sonnet; `developer` and `ux-reviewer` keep the session's model. Project
  config `models` overrides.
- New command `/engineering-team:retro`: run statistics, recurring finding categories,
  and a short ratchet plan of hard checks; writes `docs/agent/LESSONS.md`.
- Runtime verification: developer and QA drive the change for real; ledger commands take
  a `type` (`runtime`, `e2e`, `test`, …); the checker warns when a medium/large build has
  no runtime evidence. New `docs/agent/FEATURES.md` template (how to reach and prove each
  feature, and what usually lies).
- Hardening: findings carry a `category` and, from medium up, a `hardening` proposal
  (`architecture` / `static` / `runtime` / `prose`), rendered in the report.
- Reviewer lenses (`correctness`, `security`, `architecture`); a second security-lens
  reviewer for sensitive changes; a tie-breaker on a different model for disputed
  critical/high findings; pattern-spread and justifying-comment checks; grounded root causes.
- Snapshot: "Hard checks" section (lint, types, format, tests, CI, pre-commit, import
  boundaries) with a warning when they're thin; path-scoped `rules` from config.
- Config: `rules`, `verify`, `models`.
- `etk_run.py stats [--json] [--last N]`.
- Evals: three `claude plugin eval` cases for skill behaviour.
- `scripts/etk.sh` launcher: skills and the hook use the first Python that actually runs,
  so a broken `python3` shim no longer kills the snapshot.
- Guard: the tech-writer can't edit agent instructions (CLAUDE.md, AGENTS.md, SKILL.md,
  `.claude/`); read-only roles can't write through in-place flags (`perl -i`, `--write`,
  `--fix`) or inline code.
- `check`, `stats` and the snapshot report malformed ledgers/config instead of crashing.

## 0.1.1

- Guard: refuse `cp`/`mv`/`install`/`ln` target-directory forms it can't parse
  (`-t.`, `-rt`, `--target`) for read-only and create-only roles.

## 0.1.0

First release.

- `/engineering-team:build`, `fix`, `review`, `test`, `improve-ui`
- Agents: `developer`, `code-reviewer`, `qa-engineer`, `ux-reviewer`
- Small / medium / large routing; worktree isolation for parallel work
- Review loop with finding IDs, severities, and a 3-cycle limit
- Quality gates G1–G6 with a ledger and a strict checker (`scripts/etk_run.py`)
- Project discovery snapshot (`scripts/discover.py`)
- Guard hook for the plugin's own subagents (push/deploy/destructive git/secret files,
  read-only reviewers, create-only QA), via a shell wrapper that skips the main session
- End-to-end scenario runner and fixtures; results in `docs/validation.md`
