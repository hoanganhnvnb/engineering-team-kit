# Principles

ETK is a small team, not a corporate process. These are the ideas it's built on,
and where each one shows up in the code.

## 1. Size the process to the task

Most changes are small. A two-line fix doesn't need a plan, three agents, and a
review board. The Lead decides small / medium / large after looking at the code, and
delegation only happens when the independent check is worth what it costs.
→ [`workflows/routing.md`](../workflows/routing.md)

## 2. Trust artifacts, not self-reports

Agents report what they meant to do, not always what happened. The reviewer reads the
diff, not the developer's summary. The Lead re-runs the tests a developer says pass.
Gate evidence is a command and its exit code.
→ [`agents/code-reviewer.md`](../agents/code-reviewer.md), [`quality/gates.md`](../quality/gates.md)

## 3. Put rules in structure, not only in prose

A sentence in a prompt gets ignored now and then. A script that refuses an inconsistent
ledger doesn't. "Tests that didn't run can't pass", "high findings block completion",
"subagents can't push" are all enforced in code (`etk_run.py check`, `hooks/guard.py`,
`tests/test_plugin.py`), not just written down.

## 4. Independence comes from separation

Reviewers can't edit. Fix rounds go to a fresh developer, and a fresh reviewer
verifies them, so nobody grades their own work and blind spots don't carry over.

## 5. Guard the context window

Subagents do the reading and return summaries and findings, not file dumps. The
discovery snapshot lists where things are instead of pasting them. Skills keep what's
needed on every run inline and load the rest only at the step that needs it.

## 6. A complete brief beats rediscovery

A subagent can't see the conversation. One longer brief costs a single read; a missing
fact costs several turns or a wrong guess. Briefs open with the goal and the
acceptance criteria and carry the project context pack.
→ [`workflows/briefs.md`](../workflows/briefs.md)

## 7. Proceed, then present

The Lead doesn't stop to ask about things it can decide sensibly. It states the
assumption and moves on. It asks only for credentials, destructive or outward-facing
actions, product decisions, or breaking a documented project rule.

## 8. The project is the authority

ETK brings a process, not opinions about your stack. Your CLAUDE.md, your skills,
your agents, and your architecture decisions win within their scope.

## 9. Trust before parallelism

Parallel developers only help once a single developer + review produces clean results
on that codebase. Large mode needs a contract and file-disjoint workstreams. If the work
can't be split that way, it runs sequentially.

## 10. Verification is the step that matters

Tests prove code; running the feature proves the feature. The team drives changes for
real (a request, a CLI call, a browser step) and records it as `runtime` evidence.
When verification is expensive, spend there: more checking beats more builders.
→ [`agents/qa-engineer.md`](../agents/qa-engineer.md), `docs/agent/FEATURES.md`

## 11. Fix the class, not the instance

Order of strength: architecture that makes the bug impossible > a static check (types,
lint, a structural test) > a runtime check > a sentence in a prompt > hoping a reviewer
notices. Every medium+ finding gets a proposal one level up from prose. Ratchet it:
block new occurrences first, clean up the old ones, watch the count fall. One correction
is not a rule.
→ [`quality/hardening.md`](../quality/hardening.md), [`skills/retro`](../skills/retro/SKILL.md)

## 12. Agents copy what they see

Every workaround in the codebase is a pattern the next agent will repeat, and each copy
makes the next one more likely. Developers list "pattern risks" instead of copying them;
reviewers count when a bad pattern spreads. Justifying comments ("we do X because the
framework…") are treated as a smell, not documentation. A greenfield project with thin
hard checks is flagged in the snapshot.

## 13. Match the model to the work

A fast model for finding files and exporting data, a thorough one for running suites,
the strongest for review and docs. A second opinion on a different model breaks ties,
because different models miss different things.
→ [`workflows/routing.md`](../workflows/routing.md)

## 14. Honest reports

INCOMPLETE and BLOCKED are normal outcomes and get reported plainly. No "bug-free",
no "fully tested", no visual claims without a browser.

## Credits

Principles 10–13 draw on two public conference talks on building with coding agents
([1](https://www.youtube.com/watch?v=O_zcc6Xl12g), [2](https://www.youtube.com/watch?v=Cmoh-yR-usA)):
the trust curve, the strength ordering of checks, the correction ratchet, feature maps
for verification, and evals as unit tests for skills.

Several of these ideas (triage before planning, trust artifacts over self-reports,
encoding lessons in structure, guarding the context window, cost-aware delegation,
"proceed, then present", trust before parallelism) are taken from Lauren Tan's
published agent workflows, especially
[poteto/brainmaxxing](https://github.com/poteto/brainmaxxing) and
[poteto/verification-skill-example](https://github.com/poteto/verification-skill-example).
Mistakes in how they're applied here are ours.
