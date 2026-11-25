# Quality gates

Seven gates (G7 only for `ship` runs). Each one ends in exactly one status, and every
status carries evidence or a reason. The ledger (`.etk/runs/<id>/gates.json`) holds them,
and `scripts/etk_run.py check` refuses an inconsistent ledger.

Without a path, `check`/`render`/`exec`/`latest` use the newest run this session could have
made: never a symlink, a future-dated run name, or a ledger git tracks. If `.etk` or
`.etk/runs` is a symlink, or git tracks anything under `.etk/`, `init` and the no-path
commands refuse (exit 2). An explicit path must lie inside the repo's real `.etk/runs/`.

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
- Record commands with `sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" exec G3 --type test -- <cmd>`.
  It runs the command, prints its output, and writes the real exit code and last output line
  into the gate, so the number in the ledger is not typed by hand. `check` warns about G3/G4
  `PASS` commands that were not recorded this way (a warning, so older ledgers still
  validate). `exec` is deliberately not in any skill's `allowed-tools`: it runs arbitrary
  commands, so pre-approving it would skip the permission prompt. Expect to be asked.
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

## G7: Release

Only a `ship` run (implement + review + test + release) owns G7; other kinds may leave it
`NOT_RUN`, and ledgers from before G7 may lack it. The Lead commits, pushes, opens the PR,
merges, tags or deploys only as the user's permission and the workflow profile allow, and
records each step:

```sh
etk.sh run phase release                         # intake|implement|review|test|release|deploy|report|done
etk.sh run ready                                 # exit 0 only when a release step may run now
etk.sh run authorize --action merge --source prompt --quote "merge it when green" [--target main] [--condition pass]
etk.sh run authorize --action push --source profile --data "${CLAUDE_PLUGIN_DATA}"
etk.sh run act --action merge --target main --ref abc123 --url <pr> --command "gh pr merge 12" --exit 0
etk.sh run act --action deploy --target web-eu --production --data "${CLAUDE_PLUGIN_DATA}" --exit 0
etk.sh run decide --id D1 --level L4 --question "Drop the legacy table?" --options "yes|no" --recommended no \
                  [--status pending|approved|autonomous|superseded] [--answer-quote "no, keep it"]
```

Each takes an optional trailing run path. New ledger fields: `phase`, `phase_history`,
`authorizations` (`action`, `target`, `source`, `quote`, `condition`, `granted_at`),
`actions` (`action`, `target`, `ref`, `url`, `command`, `exit`, `production`, `at`,
`gates_ok`), `decisions` (upserted by `id`) and `profile_hash` (sha256 of the profile file a
`--source profile` authorization was checked against). Actions:
`commit|push|pr|merge|tag|deploy|rollback`. Sources: `prompt` / `answer` (the user's verbatim
words in `quote`) or `profile` (the workflow profile; only for commit, push, pr).
`authorize --source profile` needs `--data DIR` and checks the profile: `release.<action>`
must be `auto` (a PR needs `release.integrate: pr` and `release.push: auto`), and `auto`
values from a profile set up in another checkout or for another push URL don't count until
the developer runs `profile confirm` here.

`run ready [RUN]` exits 0 only when the release preconditions hold: every gate except G7 is
PASS or a justified NOT_APPLICABLE, every AC is met, no open or disputed finding of medium
severity or above, and no high/critical one left unverified. Otherwise it exits 1 and lists
what is missing. `run check` is different: it only says the ledger is consistent, and an
in-progress run with G3 FAIL is consistent. `act` computes `gates_ok` the same way and refuses
(exit 2, nothing recorded) a commit/push/pr/merge/tag/deploy while `ready` would fail, unless
`--force-record` is given to record a step that already happened (stored with `gates_ok:
false`). With `--data`, `act --action deploy --target T` looks `T` up in the profile's
`deploy.targets` and records `production: true` when the profile says so; the profile can
add the flag, not remove it.

`check` rejects:
- an action with no authorization for the same action and target (an authorization without
  a target covers any target; one granted after the action covers nothing);
- a commit/push/pr/merge/tag/deploy with `gates_ok: false`: released before the gates passed
  (rollback is exempt);
- a merge/tag/deploy/rollback authorized only by the profile;
- a source-profile authorization without `profile_hash` (written by hand, not by `authorize`);
- a `--production` deploy without an authorization for exactly that target, or whose quote
  names neither the target nor production/prod/live as whole words (`-`/`_` count as part of
  a word, so "web" isn't "web-staging"; a negated clause like "don't touch prod" doesn't count).

- PASS: at least one recorded action, every one exit 0.
- FAIL: an action failed.
- NOT_APPLICABLE: with the reason (no VCS, the user said to leave it uncommitted), and no
  recorded actions.

## When is a run COMPLETE

`outcome: COMPLETE` only when:

1. No gate is `FAIL` or `BLOCKED`, and no gate the run owns is `NOT_RUN`. build/fix/improve-ui
   own G1–G6, `ship` owns all seven. A `review` run owns G2 + G6, a `test` run owns G3 + G4. Gates outside
   that may stay `NOT_RUN`, and the report says they weren't checked.
2. Every acceptance criterion is `met`.
3. No critical/high finding is `open`, `disputed`, or `fixed` but unverified, and no
   medium finding is `open` or `disputed`. The one exception is a report-only `review` run,
   which may finish with open mediums as long as the report lists them. `invalid` findings
   (with a `resolution`) never block.
4. `accepted_risk` or `wont_fix` on a critical/high finding has `accepted_by_user: true`,
   meaning the user actually said so in this conversation. The Lead cannot accept risk
   for the user.
5. No release action exited non-zero, and no L4 decision is still `pending`.

Otherwise the outcome is `INCOMPLETE` (work remains) or `BLOCKED` (needs the user),
and the report says exactly what is missing.
