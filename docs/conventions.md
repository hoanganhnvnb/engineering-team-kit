# Conventions pack

`conventions/` holds the rules agents follow when they write code, commit, or review:
naming, style, git, API and database design, versioning, testing and errors, security,
docs and review, and UI. They are instructions for the agents, not a linter for people.
Nothing in the plugin checks or blocks commits you write yourself.

## How it stays small

Agents never load the whole pack. The snapshot prints one line with the path of
`conventions/README.md`. That index says which topic to read for which job. The Lead
then copies only the relevant topic paths onto the brief's `Conventions:` line, and
each agent reads those files when it needs them.

| File | Approx. tokens |
|---|---|
| README.md (index) | ~460 |
| each topic | 460–850 |
| all 11 files | ~6,900 |

A typical change reads the index plus one or two topics, about 1,500 tokens. The
budgets are enforced by tests: ≤ 40 lines and 2.5 KB for the index, ≤ 60 lines and
4 KB for each topic.

## Your project wins

The order is: safety rules → what you say in the conversation → project rules
(CLAUDE.md, `.claude/rules/`, linters and formatters, commitlint/commitizen config, and
the code itself) → your workflow profile → this pack. If your project already does
something one way, agents keep doing it that way. They don't rewrite git history or
reformat code they didn't touch.

Commit messages follow one rule:

1. Commit tooling (commitlint, commitizen, gitmoji, a `commit-msg` hook) or a format
   written in the project's docs decides.
2. Else your workflow profile's `commit.style`.
3. Else the style that at least 70% of the last 20 non-merge subjects share.
4. Else Conventional Commits: `type(scope): description`.

## Turning it off or adding your own

In `.claude/engineering-team.json`:

```json
{ "conventions": { "disable": ["ui", "api"], "extra": ["docs/our-api-guide.md"] } }
```

- `disable` drops the named topics from the snapshot.
- `disable: ["all"]` drops the pack entirely.
- `extra` adds repo-relative files inside the project for agents to read alongside the
  pack. Paths outside the project are ignored.

## Upgrading

The pack ships with 0.4.0. Earlier installs don't have it, and nothing changes for them
until they update the plugin. After an update, it applies to new runs only. Existing
commits, branches and code are left alone.
