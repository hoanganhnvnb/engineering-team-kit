# Review loop

```
implement ─► review ─► findings ─► fix ─► re-test ─► re-review ─► gates
                ▲                                         │
                └──────────── max N cycles (default 3) ◄──┘
```

One **cycle** = the developer addresses a batch of findings + the reviewer re-checks.
Increment `cycles` in the ledger each time a fix batch goes back to a developer.

## Steps

1. **Review.** Spawn a fresh `engineering-team:code-reviewer` (or the project's own
   reviewer agent) with the review brief from `workflows/briefs.md`. Give it the base
   ref and the ACs, not the developer's report. In parallel, if they apply:
   `qa-engineer` and `ux-reviewer`.
2. **Triage (Lead).** Copy findings into the ledger. For each one:
   - Check it's real. Open the file and line. Drop anything that doesn't hold up and
     note why. Reviewers can be wrong too.
   - Merge duplicates across reviewers (keep the lowest ID, note the others).
   - Resolve conflicts: project rules > ACs > reviewer preference. Write the reason.
   - **Tie-breaker.** If the developer disputes a critical/high finding and the evidence
     doesn't settle it, spawn one more reviewer on a *different* model (pass `model`,
     e.g. `sonnet` if the reviewer ran on `opus`) with both arguments and the code.
     Different models have different blind spots. If it's still unclear, ask the user.
3. **Fix.** Send open critical/high/medium findings to a developer as one batch.
   Use a **fresh** developer with the original brief + the findings, because a long-lived
   agent carries its own blind spots forward. Small fixes: the Lead may fix directly.
   The developer returns, per finding: `fixed` (what changed + test) or `disputed`
   (evidence).
4. **Re-test.** Run the relevant tests again yourself or via QA. Don't take "tests
   pass" from a report: the command and exit code go in the ledger.
5. **Re-review.** A fresh reviewer gets the new diff plus the list of findings
   marked fixed. It marks each `verified` or re-opens it, and may add new findings
   (new IDs). Scope it to the changes + the findings, not a full re-review of everything.
6. **Exit** when no critical/high is open/unverified and mediums are fixed or
   accepted with a reason. Then fill the gates.
7. **Make it stick.** Collect the `hardening` proposals from medium+ findings and put
   them in the report ([hardening](../quality/hardening.md)). Don't implement them
   unasked: a new lint rule or CI step is a project change the user decides on.

## Bounds

- After `max_cycles` (default 3, overridable in project config) with blocking findings
  still open: stop. Set the outcome to `INCOMPLETE`, list what's still open and why it
  isn't converging, and recommend a next step. Don't keep looping.
- If the same finding re-opens twice, the brief or the design is probably wrong.
  The Lead looks at it directly before another cycle.
- Low findings never trigger a cycle on their own.

## Never

- Silently drop a critical/high finding.
- Mark something `verified` because the developer said it's fixed.
- Let the reviewer edit code. Reviewers report and developers fix. That's what
  keeps the review independent.
