# Hardening: turn corrections into checks

Every finding is a lesson. If the lesson only lives in a review comment, a rules
file, or this conversation, it'll be forgotten and the same mistake will come back.
Agents copy whatever patterns already exist, so one workaround left in the code
gets copied again and again. The fix is to push each lesson down to the cheapest
layer that enforces it automatically.

## The layers, cheapest to enforce first

| Layer | Examples | Strength |
|---|---|---|
| **architecture** | a better API that makes the mistake impossible, one folder per feature, a framework helper that owns the tricky part | removes the problem class |
| **static** | lint rule, type, import-boundary check, compiler flag, test, CI step | fails before merge, every time |
| **runtime** | verification script, smoke test, property-based test, feature-map driver | catches what static checks can't see |
| **prose** | CLAUDE.md line, skill, rules file | soft: agents forget it under pressure |
| **none** | genuinely one-off, not worth a check | say why |

Human review sits beneath all of these. It's the most expensive layer, and the goal is
to need it less over time.

## In every review

For each confirmed finding of medium severity or higher, the reviewer adds a
`hardening` proposal:

```json
"hardening": { "layer": "static", "proposal": "eslint no-restricted-syntax for setTimeout(…, 0) in src/ui/**, message: 'fix the ordering bug instead of deferring'" }
```

Prefer the highest layer (in the table) that is realistic for this project. A lint
message should tell the agent what to do instead, not just "forbidden".

The Lead lists the proposals in the final report. **It doesn't implement them
unasked.** A new lint rule or CI step changes the project, so it's the user's call.

## The ratchet (when the user agrees)

1. **Stop new occurrences:** add the rule/check scoped to new code, or with a baseline of
   existing violations.
2. **Clean up existing occurrences** as a separate, reviewable task.
3. **Track the trend:** `etk_run.py stats` shows which finding categories keep recurring.
   A category that keeps appearing is the next rule to add.

`/engineering-team:retro` runs this loop on demand: it collects data across runs,
writes the lessons down, and proposes the next checks.

## What not to do

- Don't add a CLAUDE.md rule because of a single correction. One correction is an
  anecdote. A rule is a decision the user makes, and if it can be code, it should be.
- Don't write comments in code that justify a shortcut ("would be a larger change", "in
  case it comes back"). That's a finding, not a fix.
- Don't automate a bad loop. If reviews keep finding the same thing, fix that first, then
  add more agents or more autonomy.
