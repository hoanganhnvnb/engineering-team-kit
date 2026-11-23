---
name: fix
description: Fix a bug with the small AI team. Reproduce it with a failing test first, find the root cause, fix minimally, review independently when the fix is non-trivial, and prove there's no regression.
argument-hint: <bug description, error, or issue link>
disable-model-invocation: true
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discover.py"), Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/etk_run.py":*)
---

# /engineering-team:fix

You are the **Lead**. Same team, same rules as `/engineering-team:build`, but for
fixing a defect.

**Bug:** $ARGUMENTS

If the bug report is empty, ask for the symptom (what happens, what was expected,
how to trigger it) and stop.

## Project snapshot

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discover.py"`

## Steps

1. **Understand.** Read the applicable project instructions from the snapshot
   (see `${CLAUDE_PLUGIN_ROOT}/workflows/discovery.md`). Turn the report into: symptom,
   expected behavior, trigger. These become the ACs ("AC-1: <trigger> results in
   <expected>", plus "AC-n: existing behavior X unchanged").
2. **Reproduce before fixing.** Write a test (or a minimal script if the project has no
   test setup) that fails because of the bug. Run it and see it fail for the right reason.
   If you can't reproduce it, say so, list what you tried, and ask for more information
   rather than guessing a fix.
3. **Root cause.** Trace from the symptom to the cause. Fix the cause, not the symptom.
   Check whether the same mistake exists in sibling code paths, and mention them, but only
   fix them if they're clearly the same bug.
4. **Size and ledger.** Small (obvious, 1–2 files) → you fix it. Otherwise medium: a
   developer fixes, a fresh reviewer checks. Security-sensitive or data-corrupting bugs
   are always at least medium.
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/etk_run.py" init "<bug>" --mode <mode> --kind fix
   ```
5. **Fix** minimally. Run the reproduction test (now green) and the module suite.
6. **Review loop** (medium+): `${CLAUDE_PLUGIN_ROOT}/workflows/review-loop.md`. Ask the
   reviewer specifically: does the fix address the root cause, and could it break other
   callers?
7. **Regression (G4):** run the wider suite + lint/typecheck. If tests were already failing
   before you started, prove they're pre-existing (run them on a temporary worktree of the
   base commit). Don't hide or delete them.
8. **Gates + report:** fill G1–G6 (`${CLAUDE_PLUGIN_ROOT}/quality/gates.md`), run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/etk_run.py" check`, report with
   `${CLAUDE_PLUGIN_ROOT}/quality/report-template.md`. Include the root cause in one or
   two sentences and the reproduction test name.

## Safety

Same as build: no commits unless asked, never push/deploy, never discard the user's
uncommitted changes, no secrets, no `PASS` without evidence from this session.
