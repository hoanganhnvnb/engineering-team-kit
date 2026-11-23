# Validation

End-to-end runs of the plugin against the throwaway fixtures in `tests/fixtures/`,
using `tests/e2e/run.py`. Each run:

- copied a fixture to a temp dir and committed it as the baseline
- ran `claude -p "<command>" --plugin-dir <repo>`
- afterwards ran `etk_run.py check` on the ledger the Lead wrote, and re-ran the project's
  tests independently, without trusting the transcript

No real project was touched.

Date: 2026-11-23 · Claude Code 2.1.329 · Linux · default model of the session.

## Results

| # | Scenario | Command | Mode picked | Agents used | Outcome | Ledger check | Independent re-run | Time / cost |
|---|---|---|---|---|---|---|---|---|
| A | Small bug fix | `fix` (qty overwritten) | small | none, Lead alone | COMPLETE | OK | `npm test` exit 0 | 75 s / $0.44 |
| B | Medium feature | `build` (discount codes) | medium | developer → code-reviewer + qa-engineer | COMPLETE | OK | `npm test` exit 0 (12 tests) | 7 min / $1.67 |
| C | Large, parallel | `build` (inventory + shipping + receipt + checkout) | large | 3 × developer in **worktrees** in parallel → reviewer + QA → developer (fixes) → 2 × fresh reviewer | COMPLETE, 2 cycles | OK | `npm test` exit 0 (70 tests) | 12 min / $4.09 |
| D | Existing domain skill (Shopify theme) | `build` (Sale badge) | small | Lead, used project skill `liquid-conventions` | **BLOCKED** (G5: no browser/store) | OK | n/a (no test suite) | 6 min / $0.64 |
| E | Strict architecture rules | `build` (email-prefix search) | medium | developer → code-reviewer | COMPLETE | OK | unittest exit 0 | 6 min / $1.18 |
| F | Pre-existing failing test | `build` (removeItem) | small | Lead alone | COMPLETE, failure recorded as pre-existing | OK | `npm test` exit **1** (the pre-existing failure, as expected) | 99 s / $0.39 |
| G | UI with visual review | `improve-ui` (signup form) | medium | ux-reviewer (baseline) → developer → ux-reviewer + code-reviewer ×3 rounds | COMPLETE, 2 cycles, G5 browser-verified | OK | n/a (static site) | 16 min / $4.10 |
| H | Security-sensitive change | `review --fix` on uncommitted string-formatted SQL | medium | Lead review → developer → fresh code-reviewer | COMPLETE (review kind) | OK | unittest exit 0 (8 tests) | 5 min / $1.35 |

## What each scenario showed

**A. Small fix.** The Lead didn't spawn anyone. It wrote the reproduction test first
("failed with expected 5, actual 3"), changed one line, and ran the suite. The report also
flagged two related issues (unvalidated qty, price drift on re-add) without fixing them.

**B. Medium feature.** Developer, then an independent reviewer (which got the base ref, not
the developer's summary) and QA in parallel. QA did mutation-style checks (removing guards
and confirming tests fail). Three low findings were recorded as `wont_fix` with reasons.

**C. Large feature.** The Lead wrote a contract, then started three developers with
`isolation: "worktree"` at the same time, each owning different files. It integrated their
work into the main checkout. The first review found a medium issue (silently wrong totals);
a fresh developer fixed it; a fresh reviewer verified the fix and found another medium
(R2-1), which went through a second cycle. All 15 findings ended `verified`.

**D. Shopify project with its own skill.** The snapshot detected the Liquid theme, and the
Lead invoked the project's `liquid-conventions` skill: the badge went through
`snippets/badge.liquid` with a locale key and CSS tokens. With no test suite, it wrote an
ad-hoc render test with `liquidjs` (failing on the base commit, passing after) and ran
`shopify theme check`, separating three pre-existing `ValidJSON` errors from its change.
No browser or store was available, so G5 is `BLOCKED` and the outcome is **BLOCKED**, not
COMPLETE. That's the intended behavior.

**E. Strict architecture.** The CLAUDE.md layering rules and `protected_paths` were
checked explicitly in G4: `grep` proving the domain doesn't import infra, and
`git diff --quiet -- app/infra/schema.sql` proving the protected file is unchanged. The
search avoided `LIKE` (so `%`/`_` in user input aren't wildcards) and bound every value
with `?`.

**F. Failing tests.** The suite had one unrelated failing test before the task. The ledger
records `npm test` with `exit_code: 1`, `pre_existing_failures: ["formats refunds (negative
cents)"]`, and baseline evidence. The checker accepts that for G4 only. The independent
re-run also exits 1, which matches the report rather than contradicting it.

**G. UI.** The baseline UX review found 14 issues, including a critical one: no viewport
meta, so the page rendered at 0.38 scale on 375 px. It also found a `div` button you can't
reach by keyboard, placeholder-only labels, and 1.74:1 text contrast. The UX reviewer used
headless Chromium (Playwright) at 1280/375/320 px. The Lead opened the final screenshots
itself before filling G5. Two fix cycles; all high/medium findings verified.

**H. Security.** An uncommitted change added `search_by_name` with f-string SQL. The
review flagged it as critical (it breaks the project's own rule 4) plus missing tests and
a port/layering gap. The fix uses `?` binding, escapes `LIKE` wildcards, validates `limit`,
and adds a test with an injection payload. A fresh reviewer verified all four findings.
One new low finding (huge ints raise `OverflowError`) stayed open, which is allowed for a
low.

## 0.2.0 re-runs

Default permission mode (`acceptEdits` + the runner's narrow allowlist), final 0.2.0 skills
and the `etk.sh` launcher.

| # | Scenario | Mode picked | Agents used | Outcome | Ledger check | Independent re-run | Time / cost |
|---|---|---|---|---|---|---|---|
| A′ | Small bug fix (`fix`, qty overwritten) | small | none | COMPLETE | OK | `npm test` exit 0 (5 tests) | 44 s / $0.32 |
| B′ | Feature (`build`, discount codes) | small, plus an independent reviewer | code-reviewer (2 low findings, both fixed) | COMPLETE | OK | `npm test` exit 0 (11 tests) | 154 s / $1.02 |

What B′ showed about the 0.2.0 changes:
- The snapshot's **Hard checks** section reached the report: "the project has no lint,
  type checks or CI; adding at least lint and CI would help before larger features".
- **Runtime verification was reported honestly.** The Lead tried to call the new function
  directly, the runner's allowlist didn't permit it, and the report says "I did not run the
  code outside the tests" instead of claiming it. (The runner's allowlist is deliberately
  narrow; in a normal session you'd approve the command.)
- It noticed the fixture's pre-existing quantity bug, said it feeds into the discount, and
  asked before touching it instead of widening scope.
- The Lead chose small mode for a +24-line additive change but still got an independent
  review. That's within the routing rules (the Lead may add a reviewer when unsure).

### Evals

Run through `evals/run.sh` (see [evals/README.md](../evals/README.md) for why it uses a
patched copy), one run per case, judge on sonnet:

| Case | Score | Turns / cost | Notes |
|---|---|---|---|
| `small-fix-stays-small` | 5/5, then 4/5 on a repeat | 10–11 / $0.23–0.27 | Root cause named with `file:line`, reproduction test first, no subagents. The repeat failed only "ledger checked": its sandbox wouldn't let it create `.etk/`, and the agent said so and filled the gates by hand |
| `ui-without-browser-is-honest` | 2/2 | 9 / $1.11 | Viewport meta added; reported G5 BLOCKED and "nothing was checked in a browser" |
| `security-change-gets-independent-review` | 3/3 | 13 / $0.45 | Independent reviewer spawned; bound parameters; LIKE wildcards escaped |

Running the suite directly against the real skills gives turn-0 failures with meaningless
scores (see limitations). Getting there found three real problems: a broken `python3` shim
on PATH made the snapshot fail (fixed with the `etk.sh` launcher), one grader used a key the
schema doesn't allow, and two graders could pass without the agent doing anything.

## Problems the runs found in the plugin (and fixes)

- **Snapshot injection denied outside bypass mode.** The original `!python3 … || echo …`
  counted as multiple operations, and the permission check refused it, so the command
  did nothing. Fixed by dropping the fallback and declaring the two plugin scripts in each
  skill's `allowed-tools`. A and H were re-run in default permission mode after the fix
  (the numbers above for A and H are from those re-runs).
- **The Lead had to read `etk_run.py` source to learn the stricter AC format** in G, because
  the checker changed mid-run. The format is now spelled out in `skills/build/SKILL.md` and
  `quality/gates.md`, and the checker's messages say what's expected.

## Caveats

- B–G ran with `--permission-mode bypassPermissions` (the runner's default at the time)
  while the guard hook and ledger checker were being hardened, so some of those runs used
  an earlier version of those two files. A and H ran in the runner's current default mode
  (`acceptEdits` + a narrow shell allowlist) against the final skills.
- One run per scenario. Model behavior varies between runs. These show the workflow works
  as designed, not that it always will.
- Costs are from the `total_cost_usd` field of each run and will be higher on real
  codebases.

## Reproducing

```bash
python3 tests/e2e/run.py node-small-bug "/engineering-team:fix …" --check "npm test"
python3 tests/e2e/run.py python-strict-arch "/engineering-team:review --fix" --overlay sqli-search \
  --check "python3 -m unittest discover -s tests"
```

Results land in `tests/e2e/results/<timestamp>-<fixture>/` (git-ignored): `summary.json`,
`report.md`, `gates.json`, `diff.patch`, and the full `transcript.jsonl`.
