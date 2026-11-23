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

Flow: (`scout` first if the area is unfamiliar) → Lead writes ACs + brief →
`developer` implements with tests → fresh `code-reviewer` reads the diff → review
loop → `qa-engineer` only when test design is non-trivial (many edge cases, state
machines, money, concurrency, data migrations) → `ux-reviewer` if UI changed → gates
→ report.

Security-sensitive: add a second `code-reviewer` with `lens: security` in parallel with
the regular one. Two different angles catch more than one reviewer reading twice.

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

## Who does what, on which model

The plugin's agents come with a default model, matched to the kind of work. Mechanical
work uses a fast, cheap model, and judgement and writing use the strongest one:

| Agent | Default model | Why |
|---|---|---|
| `scout` | haiku | finding files, collecting commands, exporting run data: speed over depth |
| `qa-engineer` | sonnet | running suites, driving the app, comparing output: thorough and cheaper |
| `developer` | inherit (your session's model) | you chose that model for this work |
| `ux-reviewer` | inherit | visual and usability judgement |
| `code-reviewer` | opus | finding real bugs needs the strongest reasoning |
| `tech-writer` | opus | knowledge synthesis and docs must be accurate |

The project config can override any of these (`"models": {"developer": "sonnet"}`). The
Lead then passes `model` when spawning. Where verification is expensive, spend there:
more QA/runtime checking beats more developers.

## Signals to escalate

- Requirements are ambiguous in a way that changes what gets built → ask the user
  one focused question (with a recommended answer), then continue.
- The change would break a documented project rule or invariant → stop and ask.
- Three remediation cycles didn't converge → stop and report (see review-loop).
