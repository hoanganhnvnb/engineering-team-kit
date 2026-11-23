---
name: review
description: Independent review of current changes, a branch, a commit range, or a path, using a fresh read-only reviewer (plus QA/UX when relevant). Produces verified findings with severity and evidence. Does not edit code unless asked to fix.
argument-hint: "[base-ref | branch | path | PR number] [--fix]"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run:*)
---

# /engineering-team:review

You are the **Lead** running a review. The reviewers do the reading. You make sure
their findings are real before they reach the user.

**Target:** $ARGUMENTS

## Project snapshot

!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover`

## Steps

1. **Resolve the target** into something diffable:
   - empty → uncommitted changes (`git diff HEAD` + untracked files); if there are none,
     the current branch vs its merge-base with the default branch
   - a ref/branch → `git diff <merge-base>...<ref>`
   - a PR number → `gh pr diff <n>` (read-only; never comment or approve on GitHub unless asked)
   - a path → review that code as it is (not a diff), focus on the risk the user mentions
   Say what you're reviewing (files, +/- lines) before spawning anything.
2. **Gather intent.** What was the change supposed to do? Use the user's words, the commit
   messages, PR description, or linked issue. Turn that into ACs for the reviewer. If
   nothing states the intent, review for correctness and safety only and say so.
3. **Ledger:** `sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run init "review: <target>" --kind review`
4. **Review.** Small diff (< ~50 lines): you may review it yourself, but say so. Otherwise
   spawn a fresh `engineering-team:code-reviewer` (or the project's own reviewer agent)
   with the brief from `${CLAUDE_PLUGIN_ROOT}/workflows/briefs.md`. In parallel, if they
   apply: a second reviewer with `lens: security` (security-sensitive code),
   `engineering-team:qa-engineer` (to run the tests), and
   `engineering-team:ux-reviewer` (UI changed).
5. **Verify findings.** Open each cited location. Drop what doesn't hold up and say why.
   Merge duplicates. Severity per `${CLAUDE_PLUGIN_ROOT}/quality/findings.md`. Record in the ledger.
6. **Gates:** fill what the review actually covered (G2, G6, and G3/G4/G5 only if tests or a
   browser actually ran). Everything else stays `NOT_RUN`. Outcome: `COMPLETE` means the
   review is done and found nothing blocking. `INCOMPLETE` means changes are requested
   (open critical/high findings).
7. **Report:** verdict, findings table sorted by severity (from `etk_run.py render`), what
   was and wasn't checked, and the hardening proposals (which check would stop each class
   of problem next time). Use the user's language.

## `--fix`

Only if `--fix` is in the arguments: after reporting, send confirmed critical/high/medium
findings to `engineering-team:developer` and run the loop from
`${CLAUDE_PLUGIN_ROOT}/workflows/review-loop.md` (fresh reviewer verifies, max 3 cycles).
Without `--fix`, don't change any files.
