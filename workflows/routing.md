# Routing: how much team does this task need?

Delegation has a real cost: every subagent re-reads files, and every handoff
loses detail. Default to the smallest setup that still gets an independent check
where it matters. Pick the mode once after discovery and write it in the ledger.
Move up a mode if the work turns out bigger, and never move down to skip a gate.

## Small: the Lead does it

All of these are true:
- 1–2 files, roughly < 50 changed lines, the approach is obvious
- no new dependency, no schema/API/auth/payment change
- a test (existing or new) can show it works

Flow: implement → run tests → self-review the diff → gates → report.
No subagents. Use QA or a reviewer only if the result surprises you.

## Medium: Developer + independent Reviewer

Any of these:
- 3–8 files, or one module with real logic
- a new endpoint, component, or job
- security-sensitive even if small (auth, permissions, payments, user data, secrets handling)
- the user asked for review

Flow: Lead writes ACs + brief → `developer` implements with tests → fresh
`code-reviewer` reads the diff → review loop → `qa-engineer` only when test design is
non-trivial (many edge cases, state machines, money, concurrency, data migrations)
→ `ux-reviewer` if UI changed → gates → report.

## Large: Lead designs, several Developers, integration

Any of these:
- crosses several modules/layers with parts that can be built independently
- needs a contract first (API shape, DB schema, event format)
- more than ~8 files or more than a day of human work

Flow: Lead writes ACs, the contract, and a work breakdown where **no two
workstreams touch the same file** → developers in isolated worktrees, in parallel
only where the parts are truly independent (otherwise one after another) → Lead
integrates → reviewer on the combined diff → QA on the integrated result → UX if UI →
gates → report. See `workflows/parallel.md`.

If you can't split it into file-disjoint pieces, it's a medium task done in
several sequential rounds, not a large one.

## Signals to escalate

- Requirements are ambiguous in a way that changes what gets built → ask the user
  one focused question (with a recommended answer), then continue.
- The change would break a documented project rule or invariant → stop and ask.
- Three remediation cycles didn't converge → stop and report (see review-loop).
