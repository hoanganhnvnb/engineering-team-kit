# Docs and review

How to write docs, ADRs, PR descriptions and review comments.

## Docs

- README covers: what it is, install, quick start, configuration, license.
- Comments and docstrings explain why (intent, constraints, trade-offs), not what
  the code already says. Delete comments that restate the code.
- Keep docs next to the code they describe. Update them in the same change.
- Match the project's doc tool and format; do not add a new one.

## ADRs

- Write one only for decisions costly to reverse (datastore, framework, public API
  shape, auth model). Not for routine choices.
- Path `docs/adr/NNNN-title.md` (e.g. `0007-use-postgres-for-jobs.md`), or the
  project's existing location.
- Michael Nygard format: Title, Context, Decision, Status (proposed, accepted, deprecated,
  superseded by NNNN), Consequences (good and bad).
- Never edit an accepted ADR's decision; supersede it with a new one.

## PR description

- What and why, in a few lines.
- How tested: exact commands and their results.
- Risk and rollback plan.
- Screenshots or a recording for UI changes.
- Linked ticket.
- Keep PRs small and focused; split unrelated work. Use the project's PR template
  if it has one.

## Review comments

- Each finding: severity, location (`path:line`), evidence, suggested fix.
- Separate blocking issues from nits; prefix nits with `nit:`.
- Review the change, not the author. Be specific and neutral.
- Do not raise style nits a formatter or linter would fix.
- Prioritize correctness, security, design, tests, then readability.
- Approve when the change improves the code base overall, even if not perfect.
- Say what you did not check.

Sources: Documenting Architecture Decisions (Nygard)
https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions ;
Google eng-practices https://google.github.io/eng-practices/review/
