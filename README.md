# Engineering Team Kit

A small engineering team for Claude Code, packaged as a plugin.

You type one command in any project:

```
/engineering-team:build add discount codes to the cart
```

and the main Claude session acts as the **Lead**: it reads your project's rules,
decides how much team the task actually needs, hands work to a **developer**, has
it checked by an independent **reviewer** (plus **QA** and **UX** when they're
worth it), loops on real findings until they're fixed, and gives you a report
where every "passed" has a command and an exit code behind it.

It's built for solo developers and small teams: most tasks stay small and
cheap, and the process scales up only when the change does. Installed, it adds about
600 tokens to a session; the workflows load only when you run a command.

[Tiếng Việt](docs/README.vi.md)

## Commands

| Command | What it does |
|---|---|
| `/engineering-team:build <feature>` | Full loop: understand → plan → implement → review → fix → test → gates → report |
| `/engineering-team:fix <bug>` | Reproduce with a failing test first, fix the root cause, prove no regression |
| `/engineering-team:review [ref\|PR\|path] [--fix]` | Independent read-only review with verified findings; `--fix` runs the fix loop |
| `/engineering-team:test [scope\|regression]` | QA pass: run the real suites, probe edge cases, split new vs pre-existing failures |
| `/engineering-team:improve-ui <screen> [problem]` | Before/after UX review with browser evidence, then implement and re-verify |
| `/engineering-team:retro [last N]` | Look back over past runs: recurring findings, trust trend, and the 1–3 hard checks worth adding |

You don't call the developer, reviewer, or QA yourself during a normal build. The Lead does.

## Install

Requires Claude Code with plugin support (built and tested on 2.1.329) and `python3` (3.12+).

```bash
claude plugin marketplace add hoanganhnvnb/engineering-team-kit
claude plugin install engineering-team@engineering-team-kit
```

Or inside a session: `/plugin marketplace add hoanganhnvnb/engineering-team-kit`, then
`/plugin install engineering-team@engineering-team-kit`. Restart the session afterwards.

Pinning a version, team-wide setup, upgrades, rollback, and uninstall:
[docs/install.md](docs/install.md).

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
                gates G1–G6 in a ledger → `etk_run.py check` → report
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

- Commit, push, merge, or deploy unless you ask.
- Touch uncommitted changes it didn't make.
- Mark tests as passed that didn't run, or call anything "bug-free".
- Claim it looked at your UI without a browser tool actually showing it.
  Without one, G5 is `BLOCKED` and the report says "static review only".

## Docs

- [Usage examples](docs/usage.md), including Shopify and non-Shopify projects
- [Architecture and design decisions](docs/architecture.md)
- [Principles](docs/principles.md): where the ideas come from
- [Validation results](docs/validation.md): the scenarios this was tested against
- [Known limitations](docs/limitations.md)
- [Configuration](docs/configuration.md)
- [Evals](evals/README.md): behaviour tests for the skills, run with `claude plugin eval`

## Development

```bash
git clone https://github.com/hoanganhnvnb/engineering-team-kit
cd engineering-team-kit
bash scripts/selftest.sh                    # manifests + unit/structure tests
claude --plugin-dir . # try it in any project: cd there and run with --plugin-dir <path>
python3 tests/e2e/run.py node-small-bug "/engineering-team:fix …" --check "npm test"   # real model run
```

Issues and PRs welcome. Keep changes small, and when you add a rule, consider
whether it can be a check in a script instead of another sentence in a prompt.

## License

MIT
