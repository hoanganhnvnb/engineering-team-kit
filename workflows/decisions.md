# Decisions: when to ask the user, and how

The user is not watching every step. Their attention is the scarcest resource in the
run, so spend it only where their answer changes what happens. Research, reasoning and
the project's own rules come first. A question is never a substitute for them.

## Levels

Classify every open decision once:

| Level | What it is | What you do |
|---|---|---|
| L0 routine | naming, file layout, which test to add | decide |
| L1 delegated | a reasonable assumption the user would accept | decide, log it in `notes`, list it in the report |
| L2 deferred | matters, but nothing waits on it now | queue it for the next gate |
| L3 blocking | one workstream can't go on without it | pause that stream only; keep doing independent work |
| L4 critical | see list below | stop that action until the user authorizes it |

**L4 always:** merge, deploy, rollback, force-push or any history rewrite, pushing to a
protected or default branch when the profile isn't trunk-based, changing the agreed
scope, deleting data or files the run didn't create. Confidence never lowers a level.

## Gates: the only places you ask

1. **Planning gate (intake).** After discovery, in one AskUserQuestion call: missing
   workflow-profile facts (`workflows/profile.md`) plus the open L2/L3 plan decisions.
   Drop questions the code, docs, profile or history already answer.
2. **Exception gate (during the run).** Only when independent work is exhausted, or an
   L4 action is next and the user hasn't authorized it.
3. **Final report.** List L1 assumptions and autonomous choices. Report non-blocking
   ideas as suggestions. Don't turn them into questions.

## Writing a question

- It must stand alone, because the dialog may hide earlier text. Give the evidence, why
  it is the user's call, the options, and what each costs or risks.
- Put the recommended option first, labelled `(Recommended)`. Say whether it can be
  undone.
- Ask in the language the user wrote the request in. Tool limits: 1–4 questions per call, 2–4 options each,
  `header` ≤ 12 characters. "Other" is added for you. Use `preview` only to compare
  concrete artifacts side by side.
- Ask dependent questions in order. Don't ask one whose relevance hangs on an
  unanswered earlier one.

## Never

- Ask before investigating.
- Ask the user to pick between technically equivalent options.
- Add checkpoints between phases the user already approved.
- Re-ask an answered question, unless new evidence invalidates the answer.
- Stop everything because one stream is blocked.
- Settle an L2+ decision silently.
- Pass a subagent's question straight to the user. Subagents report uncertainty to you
  with evidence and a recommendation. You resolve it, or batch it into the next gate.

## Recording

Use `etk.sh run decide --id D1 --level L3 --question "…" --recommended "…"` when you
queue a decision, and the same `--id` with `--status approved --answer-quote "<their
words>"` once it is settled. Authorizations to commit, push, merge or deploy go through
`run authorize` (`workflows/ship.md`). Approving a plan authorizes an L4 action only if
the plan names that action. A preference that will hold beyond this run goes into the
profile's `memory`, and only after the user confirms it.
