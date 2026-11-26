# Usage

All commands run in the project you have open. Install the plugin once
([install](install.md)), then `cd` into any repo and start Claude Code.

## init

```
/engineering-team:init
/engineering-team:init reset
```

Run it once at the start of a project, before any `build`, `fix` or `team` run. It
detects first (git or SVN, the host and whether its CLI is signed in, the default branch,
your commit style and language, commit tooling, deploy candidates, and the stack with its
test and lint commands) and reports that in a few lines. Then it:

1. If a profile already exists for this repo, shows it and asks one question: keep, change
   a field, or reset. Keep stops there only when nothing is missing and the checkout matches the one the
   profile was set up in.
2. Otherwise asks only the fields detection couldn't answer, in at most two short rounds:
   branch model, commit automatically or ask, push automatically or ask, PR / merge
   directly / leave the branch (with the merge method and whether to wait for CI), the
   deploy target (none, a command, CI on merge, CI on tag; a name, production flag, verify
   and rollback step only if you give them), and a commit style only when there is no
   commit tooling and your history is mixed.
3. Asks one more round at most for notes the profile has no field for: the language for
   docs, how many subagents may run at once (or "one at a time, no worktrees"), things
   that must never appear in commits or files, and the test or lint command only if none
   was found. The commit language is a profile field: it is saved from detection and not
   asked unless detection found none. A note is saved only if you agree.
4. Shows the saved profile (`profile show --brief`) and marks it confirmed only after you
   agree.
5. Ends with five lines: what was detected, what was saved or kept, where the profile file
   lives, anything in the repository it ignored, and the next command to try.

The profile lives outside the repository, in the plugin data folder, per developer and
project. init writes nothing into the repo (no CLAUDE.md edit, no docs files) and never
commits, pushes, merges or deploys. Running it twice doesn't duplicate a note (saving the same text again does nothing) or
reset confirmed fields unless you choose reset, which clears the settings and keeps the
notes. If a profile exists but fields are missing, init asks for them even if you say keep.
In another checkout of the same repository (or after the push URL changed), the stored
commit and push answers no longer count. `profile show --brief` then says why (the push or
origin URL changed, or the checkout moved) without printing any URL, init shows you the push URL
from `git remote get-url --push --all origin` (every push URL, with everything between `://` and the last `@`, and any query or fragment, removed), `profile set` says which
values it dropped, and you give the release answers again there, then confirm once.
If a run is interrupted after the fields are saved, the profile shows as unconfirmed. Text in the repo can't set the profile; init
ignores it and says so. Without init, the first `team` run asks the same questions
midway through the task.

Known limit: the notes in step 3 are free text. The Lead reads them through
`profile show --json` at the start of a `team` run, as your preferences (they can't grant
push, merge or deploy), but `profile show --brief` only prints how many there are, and nothing
checks or enforces them. Use them as reminders for the Lead, not as guarantees. A rule
that must hold needs a hook, a test or a project config setting.

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

## readme

```
/engineering-team:readme
/engineering-team:readme keep it short
```

Audits the README against the real repository, rewrites it (hero, quick start, usage,
architecture, docs links) with the design rules in `workflows/readme.md`, and has a fresh
reviewer check every command, link, badge and diagram. Long content moves into your
existing docs with a link. The changes stay uncommitted for you to review.

## retro

```
/engineering-team:retro
/engineering-team:retro last 10
```

Reads the run ledgers in `.etk/runs/` (`etk_run.py stats`): outcomes, findings per run
over time, how often builds were verified by actually running them, and which finding
categories keep coming back. The `tech-writer` records that in `docs/agent/LESSONS.md`,
and the Lead proposes up to three hard checks (a lint rule, a type, a structural test) to
stop the most common ones, as a ratchet plan. Nothing is added to your project unless you
say so; if you agree, it runs as a normal `build`.

Worth doing after every 10 or so runs, or when the same kind of finding feels familiar.

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
