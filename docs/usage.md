# Usage

All commands run in the project you have open. Install the plugin once
([install](install.md)), then `cd` into any repo and start Claude Code.

## build

```
/engineering-team:build add CSV export to the orders page, admin only
```

What you'll see:

1. A short restatement of the goal and 2–7 acceptance criteria (with any assumptions).
2. The size it picked and why ("medium: new endpoint + UI + permission check").
3. Progress as the developer, reviewer and QA/UX agents report back, plus the findings
   the Lead accepted or rejected and why.
4. A final report: what changed, ACs met or not, a gate table, findings, the commands
   that ran with exit codes, and what wasn't verified.

Changes are left uncommitted unless you said otherwise. The run ledger is in
`.etk/runs/<id>/gates.json`.

Tips:
- Put constraints in the request: "no new dependencies", "keep the API backward compatible",
  "commit when done".
- If you want it bigger or smaller than it picked, say so: "treat this as large" or "just do
  it yourself, no review".

## fix

```
/engineering-team:fix checkout total is off by one cent when two discounts apply, see issue #142
```

The Lead reproduces it with a failing test before changing code. If it can't reproduce
the bug, it tells you what it tried and asks for more information instead of guessing.

## review

```
/engineering-team:review                  # uncommitted changes (or branch vs main)
/engineering-team:review main             # current branch vs main
/engineering-team:review 128              # GitHub PR #128 (read-only, needs gh)
/engineering-team:review src/billing/     # a path, as it is now
/engineering-team:review main --fix       # review, then fix confirmed findings
```

Without `--fix`, nothing in your working tree changes.

## test

```
/engineering-team:test                    # the current changes
/engineering-team:test regression         # full suite, separate new vs pre-existing failures
/engineering-team:test the coupon flow
```

## improve-ui

```
/engineering-team:improve-ui /settings page: the form is cramped on mobile and errors are unclear
```

For real visual verification, a browser tool needs to be available in the session (e.g.
Claude in Chrome, or a Playwright MCP server). Set `ui.start` and `ui.url` in
`.claude/engineering-team.json` so the UX reviewer knows how to open the app.

## Example: a Shopify repository

In a Shopify theme or app repo (say, a theme with its own `liquid-conventions` skill):

```
cd ~/work/acme-theme
claude
> /engineering-team:build show a Sale badge on product cards when compare_at_price > price
```

What's different here, and why:
- The snapshot flags `Shopify theme (Liquid)` (or `Shopify app` from `shopify.app.toml`), so
  the Lead tells the agents to use the Shopify skill installed in your session (for
  example `shopify-plugin:shopify`) for Liquid objects, filters, and API details.
- Project skills like `liquid-conventions` are listed in the snapshot and named in the
  developer's brief, so the badge goes through `snippets/badge.liquid`, uses a locale key,
  and gets its CSS from tokens.
- The guard blocks `shopify theme push/publish` and `shopify app deploy` for subagents.
  `shopify theme dev` and `theme check` are fine.
- If `shopify theme check` isn't installed, G3 is reported as `BLOCKED` or
  `NOT_APPLICABLE` with that reason, not as passed.

## Example: a non-Shopify repository

In a Python service with strict layering rules in CLAUDE.md:

```
cd ~/work/accounts-service
claude
> /engineering-team:build add an admin search for users by email prefix, max 50 results
```

- No Shopify guidance appears, because the snapshot found no Shopify signals.
- The CLAUDE.md rules ("domain must not import infra", "SQL uses `?` binding") are quoted
  in the briefs. The reviewer treats a violation as at least `high`.
- Touching SQL and user data makes this security-sensitive, so it runs at least medium,
  with an independent reviewer and G6 covering injection and data exposure.
- `protected_paths` from `.claude/engineering-team.json` (e.g. `schema.sql`) mean the
  team asks before changing the schema.

## Continuing later

The ledger and `docs/agent/CURRENT_STATE.md` (for longer tasks) let a new session pick
up: "continue the last engineering-team run". The snapshot shows the latest run directory.
