# Known limitations

Honest list. If one of these bites you, an issue is welcome.

## Verification

- **UI checks need a browser tool.** Without Claude in Chrome, a Playwright MCP server, or
  similar in the session, G5 ends up `BLOCKED` and the report says "static review only".
  That's by design, but it means UI tasks can't reach `COMPLETE` in such sessions.
  To add one:
  - Playwright MCP (headless, works in CI and over SSH):
    `claude mcp add playwright -- npx @playwright/mcp@latest`
    (needs Node 18+; the first run downloads a browser, or run `npx playwright install chromium`).
  - Claude in Chrome (your real browser, with your logins): install the extension and
    start Claude Code with `claude --chrome`, or enable it in `/chrome`.
  The `ux-reviewer` inherits MCP tools from your session, so no plugin change is needed.
- **Runtime verification needs a way to run the thing.** The checker only *warns* when a
  medium/large build has no `runtime`/`e2e` evidence: some changes (a library function,
  a migration you can't run locally) have no reasonable way to be driven. Add `verify`
  commands to the project config so the team knows how.
- **No tests, no G3 PASS.** Projects without automated tests (many Liquid themes, small
  scripts) get G3 `NOT_APPLICABLE` with `reason_code: no_test_setup` at best, and the report
  says so. The team may write ad-hoc checks (e.g. rendering a Liquid snippet with
  `liquidjs` in a scratch dir), which count as evidence but aren't a test suite.
- **The ledger checker checks consistency, not truth.** It refuses a `PASS` without a
  command and exit code, but it can't prove the command really ran. That rests on the
  Lead following the protocol, on reviewers re-running things, and on you reading the
  report. In the end-to-end runs the Lead did re-run claimed tests and opened screenshots
  itself, but a model can still make mistakes.

## Learning and evals

- **`retro` is only as good as the ledgers.** It reads `.etk/runs/`, which is local and
  git-excluded. A fresh clone or another machine starts with no history. Categories are
  set by reviewers and can be inconsistent; the stats are a prompt for judgement, not a
  metric to optimise.
- **Hardening proposals aren't applied automatically.** A new lint rule or CI step is a
  project change. The team proposes; you decide.
- **Evals run on a patched copy.** In Claude Code 2.1.329 the eval sandbox makes the
  harness's own shell wrapper fail (`read-only file system: …/tmp/claude-<uid>/cwd-…`), which
  aborts any skill that has a `` !`…` `` injection line, from a plain terminal as well. Nothing
  in the docs mentions it. `evals/run.sh` works around it by evaluating a temporary copy where
  that line is a Bash instruction, so the evals don't exercise the injection itself; the e2e
  runner (`tests/e2e/run.py`) does. Worth reporting upstream (`/feedback`).
- **Evals cost money and are noisy.** Each case is a real model run plus an LLM judge
  (roughly $0.5–3 per case). Run them when you change a skill or agent, not on every
  commit. One run is a sample, not proof: use `--runs` for anything you rely on.
- **Model aliases depend on your plan.** `haiku`/`sonnet`/`opus` resolve to whatever your
  account maps them to. If a model isn't available the agent falls back per Claude Code's
  rules; set `models` in the project config to pin something else.

## Guard hook

- **It's a seatbelt, not a sandbox.** It parses commands and blocks the destructive things
  agents actually do (push, deploy, reset/stash/clean, `rm -rf` outside the project,
  secret files, writes by reviewers). A deliberately obfuscated command, or code inside a
  test file that `npm test` then runs, can still get past it. Use your normal Claude Code
  permission settings and, for untrusted code, a container.
- **It is a best-effort tripwire built on a static shell parse, not a sandbox.** It reads the
  command text and guesses what the shell will do (which directory later segments run in,
  what a wrapper or option swallows, what `eval`, `trap` or a here-string will execute).
  Shells have more ways to surprise a static reader than any list covers, so expect the
  occasional bypass and the occasional false block. Where the parse is ambiguous the guard
  blocks rather than guesses, but it can't promise to catch everything. Real isolation
  needs OS-level controls: a container or VM, a read-only mount or separate user for the
  read-only roles, and credentials that can't push or deploy.
- **Unknown tools are blocked for engineering-team agents.** The hook sees every tool call.
  `Bash` and `Monitor` commands go through the same shell checks; file tools and `mcp__*`
  tools have their own rules; a short list of read-only tools (Read, Grep, Glob, WebFetch…)
  passes. Anything else is blocked for our agents. If Claude Code adds a harmless tool and
  an agent needs it, add it to `SAFE_TOOLS` in `hooks/guard.py`. The main session only pays
  for a `sh` start per tool call; the wrapper exits before Python runs.
- **Profile and release records are protected by name, not by a secret.** Subagents can't
  write into the plugin data dir or `.etk/` (or `cd` into them), and can't run `profile set…`
  or `run init|authorize|act|decide|phase`. They also can't change remotes, URL rewrites,
  hooks, filters, diff drivers, credentials or includes through `git config`/`git remote`, or
  write `.git/config` and `.git/hooks/`, because those decide where the Lead pushes. The
  profile is looked up by the origin URL; its `auto` settings only count in the checkout and
  for the push URL it was confirmed with. A copy of the scripts, or inline code that builds the
  path at runtime, gets past that, like any other guard gap. `run check` still requires
  every release action to match a permission that quotes your words, and the Lead,
  not a subagent, runs every outward step.
- **`etk exec` keeps the command's hands off the ledger, not off the file.** The command
  `exec` runs is repository code (a test suite). `exec` snapshots the ledger first and
  afterwards restores everything but appended gate command records, so a test can't add
  authorizations or flip a gate. Same-uid code can still write `.etk/runs/<id>/gates.json`
  directly outside `exec` (a background process it leaves behind, a later build step); only
  OS-level isolation stops that.
- **A cd the guard can't follow hides where relative paths land.** `cd ~/…` and `cd $HOME/…`
  are expanded from the hook's own HOME, unless the command mentions `HOME` in any other way
  (`HOME=/x cd ~/…`, `export HOME=…`); then, like `cd $X`, later relative writes can't be
  placed and aren't attributed to the plugin data dir.
- **`etk.sh exec` is only as guarded as the guard's wrapper handling.** `exec <gate> --type t
  -- <cmd>` runs `<cmd>` itself, so for a guarded role the command text is only checked to
  the extent the guard looks through that wrapper. It refuses an empty command, and no skill
  pre-approves it in `allowed-tools`, so the main session is asked before it runs. Treat it
  like any other command runner.
- **MCP tools are judged by name only.** For the plugin's subagents the guard blocks MCP
  tools whose name contains a write-style word (`push`, `merge`, `create`, `delete`,
  `write`, `update`, `publish`, `deploy` and a few more), and lets browser tools
  (`mcp__claude-in-chrome__*`, Chrome DevTools, Playwright) through. Words that are usually
  reads, such as `resolve` in context7's `resolve-library-id`, are not on the list. A tool with a neutral name that
  changes things anyway (`mcp__x__run`, `mcp__x__execute`) passes, and so does anything a
  browser tool does on a page (submitting a form on a deploy dashboard). Only permissions
  you set in Claude Code, or leaving the server out of the session, close that gap.
- **`git -c` is refused for the read-only roles and QA**, even for display-only keys like
  `git -c color.ui=never log`: a `-c` can also set aliases and pagers that run programs, and
  the guard can't tell them apart. Use `git log --no-color` or set the config in the repo.
- **Known gaps in the guard** (found in review, not fixed):
  - `protected_paths` is matched against the paths a command names, so an operation on an
    ancestor (`rm -rf .`, moving a parent directory) isn't caught, and the match is
    case-sensitive (`LICENSE` doesn't protect `license` on a case-insensitive filesystem).
  - A shell script created earlier in the command through a symlinked parent directory isn't
    recognised as "created in this command".
  - `cp`/`mv` into a directory (`cp .env somedir/`) isn't resolved to the file it creates, so
    the secret-file check misses it when the destination is only a directory.
  - `gh api` and npm option spellings beyond the common ones (abbreviated or unusual
    forms) can slip past the publish/merge checks.
- **It judges the filesystem as it is before the command runs.** A script created earlier
  in the same command line (`ln -s /dev/stdin x && bash x`) is blocked when the guard can
  see it being created. A script or link made by an earlier tool call, or by a program the
  command runs, is read as an ordinary file: the guard can't tell what it will do.
- **Agents mapped through the `agents` config aren't guarded.** The guard matches the
  `engineering-team:` agent prefix only. If you map a role to your own agent (for example
  `{"code-reviewer": "my-reviewer"}`), that agent runs without the guard's role limits, deploy
  rules and `protected_paths`. Give it matching tool restrictions and permission settings of
  your own.
- **It only covers the plugin's subagents.** The main session (the Lead) runs under your
  own permission settings. The Lead is told not to push, deploy, or discard work, and the
  skills say so, but no hook enforces it for the main session. A plugin shouldn't change
  how your other sessions behave.
- Needs `sh` and Python 3.12+. `scripts/etk.sh` and the hook wrapper try `python3`,
  `python3.13`, `python3.12`, `/usr/bin/python3`, `/usr/local/bin/python3`,
  `/opt/homebrew/bin/python3`, then `python`, skipping any that don't run or are older than
  3.12 (a pyenv/asdf shim without its root, a deleted venv, an old system Python). Without
  a suitable Python, calls from the plugin's subagents are blocked with "engineering-team
  needs Python 3.12+ for its guard; install it or disable the plugin" (the guard fails
  closed); the main session is unaffected. The snapshot step fails visibly.
- Inline-code detection for read-only roles (`node -e`, `python -c` writing files) is a
  pattern match on common write calls, not an interpreter. It catches mistakes, not intent.
  Blocking inline code outright wouldn't close the gap (a script in the temp dir runs the
  same code) and would take away reviewers' quickest way to check behaviour, so the
  boundary that holds is your permission settings or a container.

## Cost and time

From the end-to-end runs on small fixtures (see [validation.md](validation.md)): a small
fix took about 1 minute and $0.35. A medium feature with reviewer and QA took 6–7 minutes
and $1–2. A large three-stream task with two fix cycles took 12 minutes and about $4. Real
codebases cost more because there's more to read. Use `fix`/`build` for work that's worth
it, and plain prompts for trivial edits.

## Platform

- Built and tested on Claude Code 2.1.329, Linux. macOS should work (temp paths under
  `/private/var/folders` are handled) but hasn't been run end to end. Native Windows is
  untested. WSL behaves like Linux.
- Parallel workstreams need git worktrees. Without git, large tasks run sequentially.
- Agent teams (experimental) aren't used. Everything runs on regular subagents.
- Headless runs (`claude -p`) work, but browser tools are usually not connected there.

## Scope

- Only the Lead commits, pushes, merges or deploys, following your workflow profile and
  the permission you gave in this conversation; subagents never do. Merge and deploy always
  need your words, and production must be named. Bitbucket PRs are link-only (no CLI),
  and SVN gets commit only. ETK doesn't talk to issue trackers.
- The Lead decides the task size. It can be wrong in either direction. Tell it ("treat this
  as large", "no review needed") and it will follow you.
- Project memory (`docs/agent/`) is only as good as what gets written there. Agents are told
  to record facts and keep files short, but you should still read the diff of those files
  like any other change.
