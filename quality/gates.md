# Quality gates

Six gates. Each one ends in exactly one status, and every status carries evidence
or a reason. The ledger (`.etk/runs/<id>/gates.json`) holds them, and
`scripts/etk_run.py check` refuses an inconsistent ledger.

| Status | Meaning | Needs |
|---|---|---|
| `PASS` | Checked and it holds | What was checked, how, and the result |
| `FAIL` | Checked and it does not hold | What failed (finding IDs, failing test names) |
| `BLOCKED` | Could not check because of something outside our control | What is missing (credentials, service down, no browser) |
| `NOT_RUN` | Applicable but not done yet | Nothing. It is the initial state and never final for a `COMPLETE` run |
| `NOT_APPLICABLE` | Doesn't apply to this change | One sentence on why (e.g. "backend-only change, no UI touched") |

**Rules that are not negotiable**

- Tests that did not run do not pass. A G3/G4 `PASS` lists every command with its
  real exit code. The checker rejects a `PASS` without commands or with a non-zero exit.
- "It compiles" is not G3. "The developer said it works" is not evidence: re-run it
  or have QA run it.
- Pre-existing failures are recorded as such (test name + proof it fails on the base
  commit, e.g. run it in a temporary worktree: `git worktree add ../etk-base HEAD`, never `git stash` in the user's checkout). They
  do not get hidden and they do not get "fixed" by deleting or skipping tests.
- Never write "bug-free", "fully tested" or "production ready". Say what was checked.

## G1: Requirements & acceptance criteria

Before code is written: restate the goal and turn the request into 2–7 testable
acceptance criteria (ACs). Record assumptions explicitly. At the end, every AC is
marked met / not met with a pointer to evidence (test name, screenshot, command output).

In the ledger each AC is an object:
`{"id": "AC-1", "text": "…", "status": "met | not_met | pending", "evidence": "test `…`"}`.
The checker refuses `COMPLETE` unless every AC is `met`.

- PASS: every AC met with evidence.
- FAIL: an AC is not met.
- Never NOT_APPLICABLE.

## G2: Architecture & code review

An independent reviewer (fresh `engineering-team:code-reviewer` or a project
reviewer agent) read the actual diff, not the developer's summary.

- PASS: review done, no open critical/high findings, and medium findings fixed
  or explicitly accepted with a reason.
- Small mode: the Lead may self-review with `git diff`. Say so in the evidence:
  "self-review (small mode), diff of 1 file / 6 lines".
- Never NOT_APPLICABLE on a build/fix/improve-ui run: there is always a diff to look at.

## G3: Automated tests

The project's own test commands, run for real. Prefer the commands from the
project config, CI files, or CLAUDE.md over guesses.

- PASS: relevant suites ran, exit 0, new or changed behavior has a test that would
  fail without the change (for bug fixes: the reproduction test).
- Give each command a `type`: `test`, `lint`, `typecheck`, `build`, `static`, `e2e`,
  `runtime` (the feature actually driven: CLI run, HTTP request, browser journey, driver
  script), or `other`. Tests prove the code, but running it proves the feature. For
  medium/large user-visible changes, record at least one `runtime` or `e2e` command (in
  G3 or G4), or a browser-verified G5. The checker warns when there's none.
- NOT_APPLICABLE: only with a `reason_code` on the gate: `docs_only` (no executable
  behavior changed) or `no_test_setup` (the project has no automated tests at all, e.g.
  many Liquid themes). The report must say plainly that no automated test covers the
  change. If tests exist but can't run here, that's `BLOCKED`, not N/A.
- BLOCKED: the suite cannot run here (missing DB, secrets). Say what was tried.

## G4: Regression

The behavior that existed before still works: the broader suite (not just the new
tests), lint/typecheck when the project has them, and a check of the invariants
and protected areas listed in the project config or docs.

- PASS: full or wide suite + lint/typecheck ran green, or failures are proven
  pre-existing and unrelated. In that case the command entry carries them explicitly:
  ```json
  {"cmd": "npm test", "exit_code": 1,
   "pre_existing_failures": ["formats refunds (negative cents)"],
   "baseline_evidence": "same test fails on base commit abc123 in a temp worktree: exit 1, 1 failure"}
  ```
  Any failure not in that list is a regression, so G4 is `FAIL`.

## G5: UI/UX & accessibility

Applies when user-facing UI changed. Real evidence only: screenshots or
DOM/accessibility-tree reads from a browser tool, at desktop and mobile width,
including loading/empty/error/success states that the change touches.

- BLOCKED (not PASS) when no browser tool or no runnable app is available. Code-only
  UI review can still find issues, but it is reported as "static review only".
- NOT_APPLICABLE: no user-facing change.

## G6: Security & compatibility

Look at the change for: secrets in code or logs, injection (SQL/shell/HTML), authz
checks on new endpoints, unsafe deserialization, new dependencies (license,
maintenance, known CVEs if a tool exists), breaking API/schema/DB changes,
migrations that are not reversible, platform rules (e.g. Shopify API versions and
scopes).

- PASS: reviewed with a short note of what was looked at. For security-sensitive
  changes (auth, payments, permissions, crypto, user data) the reviewer must say so
  explicitly and the run is at least medium mode.

## When is a run COMPLETE

`outcome: COMPLETE` only when:

1. No gate is `FAIL` or `BLOCKED`, and no gate the run owns is `NOT_RUN`. build/fix/improve-ui
   own all six. A `review` run owns G2 + G6, a `test` run owns G3 + G4. Gates outside
   that may stay `NOT_RUN`, and the report says they weren't checked.
2. Every acceptance criterion is `met`.
3. No critical/high finding is `open`, `disputed`, or `fixed` but unverified, and no
   medium finding is `open` or `disputed`.
4. `accepted_risk` or `wont_fix` on a critical/high finding has `accepted_by_user: true`,
   meaning the user actually said so in this conversation. The Lead cannot accept risk
   for the user.

Otherwise the outcome is `INCOMPLETE` (work remains) or `BLOCKED` (needs the user),
and the report says exactly what is missing.
