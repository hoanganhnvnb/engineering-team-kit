# Conventions (agent rules)

Rules every agent follows when it writes code, commits, or reviews. Read only the topic
you need, when you need it. These are defaults, not a linter for humans.

## Precedence

1. Safety rules (no secrets, no unauthorized push/merge/deploy, no discarding work).
2. The user's words in this conversation.
3. Project rules: CLAUDE.md, `.claude/rules/`, AGENTS.md, contributing docs, linter and
   formatter configs, commitlint/commitizen config, and the code around the change.
4. The developer's workflow profile.
5. These files.

When the project already does something consistently, do it the project's way, even if
this pack says otherwise. Never rewrite history or reformat untouched code to match.

## When you … read …

| When you | Read |
|---|---|
| commit, name a branch, tag, write a changelog | `git.md`, `versioning.md` |
| name files, symbols, routes, tables | `naming.md` |
| write or format code in a language | `style.md` |
| design an HTTP/JSON API or error responses | `api.md` |
| change a schema, migration or query | `database.md` |
| add tests, handle errors, log | `testing-errors.md` |
| touch input, auth, secrets, dependencies | `security.md` |
| write docs, an ADR, a PR description, review text | `docs-review.md` |
| build or change UI | `ui.md` |

## Commit style in one rule

Commit tooling or a format stated in project docs decides; else the workflow profile's
`commit.style`; else the style ≥70% of the last 20 non-merge subjects share; else
Conventional Commits: `type(scope): description`. Details are in `git.md`.

Reviewers report a style, naming or format miss as category `convention`, severity low unless the
project states the rule. A miss of a security, data-safety or correctness rule (`security.md`,
`database.md`, `testing-errors.md`) keeps its real severity and category.
