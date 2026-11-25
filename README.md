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
add CSV export to the orders report; review pass thì tạo PR
```

On the first run in a project, Claude detects your git host, branches and commit style.
It asks once, in one or two short rounds, about what it can't detect: PR or direct
merge, and how you deploy, if you do. It saves the answers to your per-developer
profile, outside the repo.

Pinning, team-wide setup, upgrades and rollback are in [docs/install.md](docs/install.md).

## Demo

![A team run: plan, review, tests, commit, push, deploy](docs/assets/demo.gif)

## Why not just prompt Claude?

| | Plain prompt | Engineering Team Kit |
|---|---|---|
| Review | The same context that wrote the code | A fresh reviewer that sees only the diff and the acceptance criteria |
| "Tests pass" | Taken on trust | A ledger records each command and its exit code; `check` refuses a PASS that has no evidence |
| Loop | Ends when it feels done | Continues until the gates pass, or the cycle cap is hit and it says INCOMPLETE |
| Shipping | Pushes whenever asked, including half-done work | Commits only this run's files, after the gates pass; merge and deploy need your words; production must be named |
| Your rules | Sometimes remembered | The snapshot lists CLAUDE.md, rules, skills, CI and hard checks; project rules win |
| Subagents | Can do anything you can | A guard hook keeps them from pushing, deploying, touching secrets or editing outside the project |

## Commands

| Command | What it does |
|---|---|
| `/engineering-team:team <task>` (or just ask) | Whole task: implement → review → test/fix until pass → commit, push, PR, deploy as your profile and your words allow |
| `/engineering-team:build <feature>` | Feature loop up to gates and a report |
| `/engineering-team:fix <bug>` | Reproduce with a failing test first, fix the root cause, prove there's no regression |
| `/engineering-team:review [ref\|PR\|path] [--fix]` | Independent read-only review with verified findings; `--fix` runs the fix loop |
| `/engineering-team:test [scope\|regression]` | QA pass: run the real suites, probe edge cases, separate new failures from pre-existing ones |
| `/engineering-team:improve-ui <screen> [problem]` | Before/after UX review with browser evidence, then implement and re-verify |
| `/engineering-team:retro [last N]` | Recurring findings, trust trend, and the 1–3 hard checks worth adding |

`team` is the only command Claude may start on its own. The others run when you type
them. Agents follow a compact [conventions pack](docs/conventions.md) (commits, naming,
style, API, database, versioning…) unless your project says otherwise.

## How it works

```
           ┌──────────── Lead (your main session) ─────────────┐
 request → │ discover → acceptance criteria → size: S / M / L  │
           └───────┬───────────────────────────────────────────┘
     small         │ medium                    │ large
  Lead does it     ▼                           ▼
  + self-review  developer ──► reviewer    contract + file-disjoint workstreams
                    ▲            │  (+QA, +UX)   developers in git worktrees
                    └─ findings ◄┘           → integrate → reviewer/QA on the whole
                     (max 3 cycles)
                           │
                gates G1–G6 in a ledger → `etk run check` → release (G7) → report
```

- **Sizing.** 1–2 obvious files: the Lead just does it. Real logic or anything
  security-sensitive: developer + independent reviewer. Several independent parts:
  a contract first, then parallel developers in isolated worktrees.
  ([routing](workflows/routing.md))
- **Independent review.** The reviewer gets the base ref and the acceptance
  criteria, never the developer's summary, and it can't edit files. Each fix round
  goes to a fresh developer, and a fresh reviewer verifies it.
  ([review loop](workflows/review-loop.md), [findings](quality/findings.md))
- **Gates with teeth.** G1 requirements · G2 review · G3 tests · G4 regression · G5
  UI/a11y · G6 security. Each is PASS / FAIL / BLOCKED / NOT_RUN / NOT_APPLICABLE
  with evidence. `scripts/etk_run.py check` rejects a test gate marked PASS without
  a recorded command and exit code 0, a COMPLETE run with an open high-severity
  finding, a fix nobody verified, and so on. ([gates](quality/gates.md))
- **Your project wins.** Before planning, a discovery snapshot lists your
  CLAUDE.md/AGENTS.md/rules files, project skills and agents, architecture docs, test
  commands, CI config, and uncommitted changes. Project rules override ETK
  defaults. If your project has its own reviewer agent or a migrations skill, the
  team uses it. Shopify conventions show up only when the snapshot finds a Shopify
  app or theme. ([discovery](workflows/discovery.md))
- **The right model for each job.** Six agents, each with a default model matched to
  the work: a cheap `scout` (haiku) gathers facts and exports run data, `qa-engineer`
  (sonnet) runs and drives things, `code-reviewer` and `tech-writer` (opus) do the
  judgement and the writing, and `developer`/`ux-reviewer` use your session's model.
  Security-sensitive changes get a second reviewer with a security lens; disputed
  critical findings get a tie-breaker on a different model.
  ([routing](workflows/routing.md))
- **Run it, don't just test it.** Tests prove code; running the feature proves the
  feature. Developers and QA drive the change for real (a request, a CLI call, a browser
  step) and record it as `runtime` evidence. The checker warns when a medium/large build
  finishes without any. A `docs/agent/FEATURES.md` map keeps the "how to reach it, how to
  prove it" steps reusable.
- **Make it stick.** Every medium+ finding carries a `hardening` proposal: the cheapest
  automatic check (lint rule, type, test, CI step) that would have caught it. The snapshot
  shows which hard checks the project already has and warns when they're thin, because
  agents copy whatever patterns they find. `/engineering-team:retro` turns repeated findings
  into a short ratchet plan. ([hardening](quality/hardening.md))
- **Seatbelt.** A hook stops the plugin's own subagents from pushing, deploying,
  publishing, rewriting history, discarding changes, running `git stash`, or writing
  `.env`/key files, or anything in your `protected_paths`. It also keeps reviewers read-only,
  even through the shell, and refuses write-style MCP tools. Your main session, other plugins
  and agents you map in through config aren't affected: the hook's shell wrapper exits right
  away for them.
  ([guard](hooks/guard.py))

## Optional project config

Nothing is required. If you want to pin commands, invariants, or the UI URL, add
`.claude/engineering-team.json` to the project ([template](templates/engineering-team.json),
[reference](docs/configuration.md)):

```json
{
  "commands": { "test": "pnpm test", "lint": "pnpm lint", "typecheck": "pnpm tsc --noEmit" },
  "ui": { "start": "pnpm dev", "url": "http://localhost:3000" },
  "invariants": ["Order totals are computed server-side only"],
  "protected_paths": ["prisma/migrations/"],
  "rules": [{ "paths": "src/domain/**", "rule": "No imports from src/infra", "check": "pnpm depcruise src" }],
  "verify": ["curl -sf http://localhost:3000/api/health"],
  "models": { "developer": "sonnet" }
}
```

For long tasks the Lead keeps short notes in `docs/agent/CURRENT_STATE.md` and
`DECISIONS.md`, only when it's useful and without duplicating your existing docs
([project memory](workflows/project-memory.md)).

## What it won't do

- Push, merge or deploy beyond what your workflow profile and your own words allow.
  Subagents never do any of it.
- Touch uncommitted changes it didn't make.
- Mark tests as passed when they didn't run, or call anything "bug-free".
- Claim it looked at your UI without a browser tool actually showing it. Without one,
  G5 is `BLOCKED` and the report says "static review only".

## FAQ

**Will it push to my main branch?** Only if your profile says trunk-based and push is
`auto`, or you asked. Pushing to a protected or default branch while you use feature
branches always needs a yes from you. It never force-pushes or skips hooks.

**Where is my profile, and can my team see it?** It's in
`~/.claude/plugins/data/<plugin>/projects/<key>/profile.json`, on your machine only.
Run `etk.sh profile path` to find it. Delete the file to reset.

**Does it work without GitHub?** Yes. GitLab uses `glab`. With Bitbucket, or without a
signed-in CLI, you get the PR link to open yourself. SVN gets commits only. With no VCS,
the release steps are skipped.

**How much does a run cost?** A small fix takes about a minute and under a dollar. A
large parallel build has run about 12 minutes and $4. Numbers are in
[docs/validation.md](docs/validation.md).

**Is the guard a sandbox?** No. It's a seatbelt against the mistakes agents actually
make. For untrusted code, use a container. See [docs/limitations.md](docs/limitations.md).

## Docs

- [Running a task end to end](docs/workflow.md): phases, profile, who may do what
- [Conventions pack](docs/conventions.md)
- [Usage examples](docs/usage.md), including Shopify and non-Shopify projects
- [Configuration](docs/configuration.md)
- [Architecture and design decisions](docs/architecture.md)
- [Principles](docs/principles.md): where the ideas come from
- [Validation results](docs/validation.md)
- [Known limitations](docs/limitations.md)
- [Evals](evals/README.md): behaviour tests for the skills

## Contributing

```bash
git clone https://github.com/hoanganhnvnb/engineering-team-kit && cd engineering-team-kit
bash scripts/selftest.sh        # manifests + unit/structure tests
claude --plugin-dir .           # try it
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately ([SECURITY.md](SECURITY.md)).

## License

MIT
