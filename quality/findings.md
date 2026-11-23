# Findings

A finding is a claim about the code that someone else can check. If it can't be
checked, it isn't a finding yet. Investigate more or drop it.

## Format

Reviewers return findings as a JSON array in a fenced block (the Lead copies them
into the ledger):

```json
[
  {
    "id": "R1-003",
    "severity": "high",
    "category": "correctness",
    "location": "src/cart/total.ts:42",
    "evidence": "applyDiscount() runs before tax; test `cart.total with 10% code` returns 90.00, see repro",
    "expected": "Discount applies to subtotal after tax rules per AC-2 (total 99.00)",
    "actual": "Total is 90.00 because tax is computed on the discounted amount",
    "remediation": "Compute tax on the pre-discount subtotal, add a test for AC-2",
    "status": "open"
  }
]
```

- `id`: `<source><cycle>-<n>`. Source letter: `R` reviewer, `Q` QA, `U` UX, `S`
  security pass, `L` Lead. `R1-003` = reviewer, cycle 1, third finding. IDs never get
  reused, so a re-review that finds a new problem gives it a new number.
- `location`: `path:line`, or `path` + symbol, or a URL + selector for UI.
- `evidence`: the thing that makes it checkable: a failing command, a code quote, a
  screenshot reference, or exact reproduction steps.

## Severity

| Severity | Use when | Blocks completion |
|---|---|---|
| `critical` | Data loss/corruption, security hole, crash on a main path, money/order wrong | yes |
| `high` | An AC not met, a real bug users will hit, a regression, a broken project rule/invariant | yes |
| `medium` | Bug on an edge path, missing test for new logic, poor error handling, a11y issue that blocks some users | fix or explicitly accept |
| `low` | Naming, small duplication, minor polish | no |

Style preferences that the project rules don't require are not findings. Mention
them in one line or skip them. Every extra finding costs a fix cycle.

## Lifecycle

```
open ──► fixed ──► verified          (reviewer re-checked the code/test)
  │        └────► open               (re-check failed; same ID, note added)
  ├────► disputed ──► Lead decides ──► open | wont_fix
  └────► accepted_risk               (critical/high: only with the user's explicit OK)
```

- **The developer** marks `fixed` with what changed and how it was tested, or `disputed`
  with evidence (a test, a doc, a project rule). "I think it's fine" is not a dispute.
- **The reviewer** marks `verified` only after looking at the new code. They do not take
  the developer's word for it.
- **The Lead** settles disputes by checking the evidence and writes the reason in
  `resolution`. When reviewer and project rules disagree, the project rules win.
  When reviewer and developer disagree on facts, run the test.
- `wont_fix`, `disputed` and `accepted_risk` always carry a `resolution`.
