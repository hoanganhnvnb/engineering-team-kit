# Engineering Team Kit

[![CI](https://github.com/hoanganhnvnb/engineering-team-kit/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/hoanganhnvnb/engineering-team-kit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/hoanganhnvnb/engineering-team-kit)](https://github.com/hoanganhnvnb/engineering-team-kit/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-orange)

**A small AI engineering team for Claude Code: it implements, gets an independent review,
tests until it really passes, and ships only as far as you allow.**

One request in any project:

```text
fix the cart total rounding bug; when review and tests pass, commit, push and deploy staging
```

The main Claude session becomes the **Lead**. It reads your project's rules, sizes the
task, and hands the work to a **developer**. An independent **reviewer** checks it,
with **QA** and **UX** when they're worth the cost. The Lead loops on real findings
until gates G1–G6 pass, and every "passed" is backed by a command and its exit code.
Then it commits, pushes, opens the PR and deploys, following your own
[workflow profile](docs/workflow.md) and the permission you gave in that request.

Built for solo developers and small teams. Most tasks stay small and cheap, and the
process scales up only when the change does. Installed, it adds about 600 tokens to a
session; the workflows load only when used.

## Quick start (60 seconds)

Requires Claude Code with plugin support (built and tested on 2.1.329) and Python 3.12+.

```bash
claude plugin marketplace add hoanganhnvnb/engineering-team-kit
claude plugin install engineering-team@engineering-team-kit
```

Restart Claude Code, open a project, and ask for something:

```text
add CSV export to the orders report; open a PR once review passes
```

On the first run in a project, Claude detects your git host, branches and commit style,
asks once about what it can't detect (PR or direct merge, how you deploy), and saves the
answers to your own profile, outside the repo. More in [docs/install.md](docs/install.md).

![A team run: plan, review, tests, commit, push, deploy](docs/assets/demo.gif)

## Why not just prompt Claude?

| | Plain prompt | Engineering Team Kit |
|---|---|---|
| Review | The context that wrote the code | A fresh reviewer that sees only the diff and the acceptance criteria |
| "Tests pass" | Taken on trust | Each command and exit code is recorded; a PASS without evidence fails the check |
| Shipping | Whenever asked | Only this run's files, after the gates pass; merge and deploy need your words |
| Subagents | Can do anything you can | A guard hook keeps them from pushing, deploying or touching secrets |

## Commands

| Command | What it does |
|---|---|
| `/engineering-team:team <task>` (or just ask) | Implement → review → test/fix until pass → commit, push, PR, deploy as you allow |
| `/engineering-team:build <feature>` | Feature loop up to the gates and a report |
| `/engineering-team:fix <bug>` | Failing test first, root-cause fix, no regressions |
| `/engineering-team:review [ref\|PR\|path] [--fix]` | Independent read-only review; `--fix` runs the fix loop |
| `/engineering-team:test [scope\|regression]` | QA pass: real suites, edge cases, new vs pre-existing failures |
| `/engineering-team:improve-ui <screen>` | Before/after UX review in a browser, then fix and re-verify |
| `/engineering-team:retro [last N]` | Recurring findings and the checks worth adding |

## How it works

```
 request → Lead: discover → acceptance criteria → size S / M / L
             small: Lead alone │ medium: developer ⇄ reviewer (+QA, +UX) │ large: parallel worktrees
                           gates G1–G6 in a ledger → `etk run check` → release (G7) → report
```

- **Independent review.** The reviewer never sees the developer's summary and can't edit
  files. Each fix is verified by a fresh reviewer. ([review loop](workflows/review-loop.md))
- **Gates with evidence.** Requirements, review, tests, regression, UI and security, each
  backed by commands and exit codes. ([gates](quality/gates.md))
- **Your project wins.** Its CLAUDE.md, rules, skills, CI and commands come first; agents
  follow a small [conventions pack](docs/conventions.md) only where the project is silent.
- **Seatbelt, not sandbox.** A hook keeps the plugin's subagents from pushing, deploying,
  rewriting history or writing secrets. ([limitations](docs/limitations.md))

Optional per-project settings (test commands, UI URL, invariants, protected paths) go in
`.claude/engineering-team.json`: see [docs/configuration.md](docs/configuration.md).

## FAQ

**Will it push to my main branch?** Only if your profile is trunk-based with push `auto`,
or you asked. It never force-pushes or skips hooks.

**Where is my profile?** On your machine only, in
`~/.claude/plugins/data/engineering-team-engineering-team-kit/projects/`. Delete it to reset.

**Without GitHub?** GitLab uses `glab`; Bitbucket gets a PR link; SVN gets commits only.

**Cost?** A small fix is about a minute and under a dollar. See [validation](docs/validation.md).

## Docs

[Workflow](docs/workflow.md) · [Conventions](docs/conventions.md) · [Usage](docs/usage.md) ·
[Configuration](docs/configuration.md) · [Architecture](docs/architecture.md) ·
[Validation](docs/validation.md) · [Limitations](docs/limitations.md) · [Evals](evals/README.md)

## Contributing

```bash
git clone https://github.com/hoanganhnvnb/engineering-team-kit && cd engineering-team-kit
bash scripts/selftest.sh        # manifests + unit/structure tests
claude --plugin-dir .           # try it
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately ([SECURITY.md](SECURITY.md)).

## License

MIT
