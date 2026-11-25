---
name: fix
description: Fix a bug with the small AI team. Reproduce it with a failing test first, find the root cause, fix minimally, review independently when the fix is non-trivial, and prove there's no regression.
argument-hint: <bug description, error, or issue link>
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run:*)
---

# /engineering-team:fix

You are the **Lead**. Same team, same rules as `/engineering-team:build`, but for
fixing a defect.

**Bug:** $ARGUMENTS

If the bug report is empty, ask for the symptom (what happens, what was expected,
how to trigger it) and stop.

## Project snapshot

!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover`

## Steps

1. **Understand.** Read the applicable project instructions from the snapshot
   (see `${CLAUDE_PLUGIN_ROOT}/workflows/discovery.md`). Turn the report into: symptom,
   expected behavior, trigger. These become the ACs ("AC-1: <trigger> results in
   <expected>", plus "AC-n: existing behavior X unchanged").
2. **Reproduce before fixing.** Write a test (or a minimal script if the project has no
   test setup) that fails because of the bug. Run it and see it fail for the right reason.
   If you can't reproduce it, say so, list what you tried, and ask for more information
   rather than guessing a fix.
3. **Root cause.** Trace from the symptom to the cause through code you actually read,
   and cite it (`file:line`). No "smoking gun" from a stack trace or screenshot alone.
   Fix the cause, not the symptom: no deferred timers, retries, or suppressions that just
   hide it.
   Check whether the same mistake exists in sibling code paths, and mention them, but only
   fix them if they're clearly the same bug.
4. **Size and ledger.** Small (obvious, 1–2 files) → you fix it. Otherwise medium: a
   developer fixes, a fresh reviewer checks. Security-sensitive or data-corrupting bugs
   are always at least medium.
   ```bash
   sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run init "<bug>" --mode <mode> --kind fix
   ```
5. **Fix** minimally. Run the reproduction test (now green) and the module suite.
6. **Review loop** (medium+): `${CLAUDE_PLUGIN_ROOT}/workflows/review-loop.md`. Ask the
   reviewer specifically: does the fix address the root cause, and could it break other
   callers?
7. **Regression (G4):** run the wider suite + lint/typecheck. If tests were already failing
   before you started, prove they're pre-existing (run them on a temporary worktree of the
   base commit). Don't hide or delete them.
8. **Make it stick.** Ask whether a lint rule, type, or test at a higher layer would have
   caught this class of bug, and put the proposal in the report (see
   `${CLAUDE_PLUGIN_ROOT}/quality/hardening.md`). Don't add it unasked.
9. **Gates + report:** fill G1–G6 (`${CLAUDE_PLUGIN_ROOT}/quality/gates.md`; record test
   commands with `etk.sh exec G3 --type test -- <cmd>` where you can), run
   `sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run check`, report with
   `${CLAUDE_PLUGIN_ROOT}/quality/report-template.md`. Include the root cause in one or
   two sentences and the reproduction test name.

## Safety

Same as build: no commits unless asked, never push/deploy, never discard the user's
uncommitted changes, no secrets, no `PASS` without evidence from this session.
