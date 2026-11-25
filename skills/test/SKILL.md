---
name: test
description: QA pass on current changes, a feature, or the whole project. Derives test cases from requirements, runs the real test suites, probes edge cases, separates pre-existing failures from regressions, and reports coverage gaps with evidence.
argument-hint: "[feature, area, or 'regression']"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run:*)
---

# /engineering-team:test

You are the **Lead** running a QA pass. Nothing counts unless it actually ran.

**Scope:** $ARGUMENTS

## Project snapshot

!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover`

## Steps

1. **Scope.** Empty → the uncommitted changes, or the current branch vs its base.
   "regression" → the full suite. A feature name → that area. Figure out what the code
   is supposed to do (user's words, docs, tests, commit messages) and write it as ACs.
2. **Commands.** Find the real test/lint/typecheck/e2e commands (project config → CI →
   package scripts → CLAUDE.md). Run the main one once yourself first. If it can't run
   at all (missing deps/services), report that as `BLOCKED` with what's missing, and
   offer the fix (e.g. "run `npm ci`").
3. **Ledger:** `sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run init "test: <scope>" --kind test`
4. **QA.** For anything bigger than a quick run, spawn `engineering-team:qa-engineer` with
   the ACs, commands, base ref, and risky areas (`${CLAUDE_PLUGIN_ROOT}/workflows/briefs.md`).
   Add `engineering-team:ux-reviewer` in parallel if the scope includes UI and a browser
   tool is available.
5. **Check the QA report.** Re-run at least one of the commands it reports to confirm the
   numbers. Record defects as findings and commands with exit codes in G3/G4, preferably
   with `etk.sh exec G3 --type test --run <run dir> -- <cmd>` (see `${CLAUDE_PLUGIN_ROOT}/quality/gates.md`).
6. **New tests.** QA may create new test files for gaps or defects. List them. Keep the
   ones that are correct and useful. Delete the ones that aren't, and say so. Don't fix
   source code in this command. If defects are found, suggest
   `/engineering-team:fix <defect>`, or offer to run it.
7. **Gates + report:** G3 and G4 always, G5 if UI was checked, others `NOT_RUN` unless
   covered. `etk.sh run check <run dir>` (the directory `run init` printed), then report: what ran (commands, exit codes, counts), what
   failed (new vs pre-existing), coverage gaps, what couldn't run. User's language.

Never report a suite as passing unless it ran in this session with exit code 0.
