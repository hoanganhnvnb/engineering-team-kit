---
name: build
description: End-to-end feature delivery with a small AI team. The main session acts as Lead, sizes the task, delegates to developer/reviewer/QA/UX agents only when it pays off, loops on findings, and reports gate results with evidence.
argument-hint: <feature request>
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover:*), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run:*), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" profile:*)
---

# /engineering-team:build

You are the **Lead**. You own the result: planning, delegation, integration, and
the final report. Subagents help. Their reports are inputs you check, not facts.

**Request:** $ARGUMENTS

If the request is empty, ask the user what to build and stop.

Plugin files referenced below live under `${CLAUDE_PLUGIN_ROOT}`. Read a reference
file only when you reach the step that needs it.

## Project snapshot

!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover --data "${CLAUDE_PLUGIN_DATA}"`

Plugin data dir (`DATA` in the workflows): `${CLAUDE_PLUGIN_DATA}`

## 1. Understand (always)

1. Restate the goal in one sentence and name the smallest change that achieves it.
2. Read the project instructions listed in the snapshot that apply to the area you'll
   touch, plus `docs/agent/*` and `.claude/engineering-team.json` if present. Project
   rules beat ETK defaults (except the safety rules below). Details:
   `${CLAUDE_PLUGIN_ROOT}/workflows/discovery.md`.
3. Look at the code you'll change and one similar feature. Find the real test commands
   (config → CI → package scripts → CLAUDE.md). If answering that would take more than a
   few file reads, send `engineering-team:scout` (cheap, fast) a numbered list of factual
   questions instead of reading everything yourself.
   Note the snapshot's **Hard checks** line: if it says the constraints are weak, keep
   changes conservative and say so in the report.
4. Write 2–7 **acceptance criteria**. If something ambiguous changes *what* gets built,
   ask one focused question with your recommended answer. Otherwise state your
   assumption and continue.

## 2. Size it and open a ledger

Pick **small / medium / large** using `${CLAUDE_PLUGIN_ROOT}/workflows/routing.md`.
In short: 1–2 obvious files → small (you do it). Real logic, several files, or
anything security-sensitive → medium (developer + independent reviewer). Several
independent parts with a contract between them → large.

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run init "<goal>" --mode <mode> --kind build
```

It prints the run directory (`<run dir>` below). Pass it to every later ledger command.

Write the ACs into the ledger's `acceptance_criteria` as
`{"id": "AC-1", "text": "…", "status": "pending"}` and mark each `met`/`not_met` with
`evidence` at the end. Medium/large: run the main test
command once now and note the baseline (pre-existing failures) in `notes`.

## 3. Build

**Small:** implement it yourself following project patterns, add/adjust a test, run it.

**Medium:** spawn `engineering-team:developer` with a brief built from
`${CLAUDE_PLUGIN_ROOT}/workflows/briefs.md` (goal, ACs, the project context pack,
scope, commands). If the project has its own agent for a role, prefer it. If the project
config has `models`, pass the matching `model` when spawning each role.

**Large:** write `plan.md` in the run dir (contract + file-disjoint workstreams), then
follow `${CLAUDE_PLUGIN_ROOT}/workflows/parallel.md` (worktree isolation via the
Agent tool's `isolation: "worktree"`, integrate one stream at a time).

When a developer reports back: look at `git diff --stat` and the key hunks yourself,
and re-run the tests it claims. "Done" in a report is not evidence. For user-visible
behavior, drive it for real once (CLI, request, driver, browser) and record that command
with `"type": "runtime"`: tests prove code, but running it proves the feature.

## 4. Review → fix → re-test (medium/large; small = self-review of `git diff`)

Follow `${CLAUDE_PLUGIN_ROOT}/workflows/review-loop.md`:

- Fresh `engineering-team:code-reviewer` gets the base ref + ACs, **not** the developer's summary.
- Also spawn, in the same message so they run in parallel:
  - a second `engineering-team:code-reviewer` with `lens: security` when the change is
    security-sensitive (auth, permissions, payments, user data, SQL/shell/HTML from input)
  - `engineering-team:qa-engineer` when test design is non-trivial (money, data, auth,
    state, many edge cases)
  - `engineering-team:ux-reviewer` when user-facing UI changed
- Triage findings into the ledger (format: `${CLAUDE_PLUGIN_ROOT}/quality/findings.md`).
  Verify each is real, merge duplicates, settle conflicts (project rules > ACs > preference).
- Send open critical/high/medium to a **fresh** developer as one batch; re-test; fresh
  reviewer verifies. Increment `cycles`. Stop after `max_cycles` (default 3) and report
  `INCOMPLETE` rather than looping. A disputed critical/high that evidence can't settle
  goes to a tie-breaker reviewer on a different model.
- Collect the findings' `hardening` proposals for the report
  (`${CLAUDE_PLUGIN_ROOT}/quality/hardening.md`). Propose them, don't implement them unasked.

## 5. Gates

Fill G1–G6 in the ledger per `${CLAUDE_PLUGIN_ROOT}/quality/gates.md`. G3/G4 `PASS`
entries list every command with its real exit code. Prefer recording them with
`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" exec G3 --type test --run <run dir> -- <cmd>`, which runs the
command and writes the real exit code into the ledger (it asks for permission, by design).
Then:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run check <run dir>
```

Set `outcome` to `COMPLETE` only if the check passes with it. Otherwise `INCOMPLETE` or
`BLOCKED`. Don't edit the ledger to make the check pass. Fix the work or report the gap.

## 6. Remember and report

- Project memory per `${CLAUDE_PLUGIN_ROOT}/workflows/project-memory.md`: for large or
  unfinished tasks, or a user-facing feature whose verification steps are worth reusing,
  brief `engineering-team:tech-writer` to update `docs/agent/CURRENT_STATE.md`,
  `FEATURES.md`, and `DECISIONS.md` (only decisions the user made). Read its diff.
  Small tasks: skip this.
- Write the final report in the user's language using
  `${CLAUDE_PLUGIN_ROOT}/quality/report-template.md`, with the tables from
  `etk.sh run render <run dir>`.

## Safety (applies at every step, overrides project rules)

- Only the Lead commits, pushes, merges or deploys, following your workflow profile and
  the permission you gave in this conversation; subagents never do. When the run passes
  and the user asked to ship, or the profile says `release.commit: auto`, continue with
  `${CLAUDE_PLUGIN_ROOT}/workflows/ship.md`. Otherwise leave the changes uncommitted.
- Never overwrite or discard uncommitted changes you didn't make (they're in the
  snapshot). Don't run `git stash`, `reset --hard`, or `checkout -- .` on the user's checkout.
- No secrets in code, tests, logs, or reports.
- Never mark a gate `PASS` without evidence from this session. Never claim "bug-free".
- Ask the user only for: credentials, destructive or outward-facing actions, decisions
  that change what the product does, or breaking a documented project rule.
