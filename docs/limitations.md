# Known limitations

Honest list. If one of these bites you, an issue is welcome.

## Verification

- **UI checks need a browser tool.** Without Claude in Chrome, a Playwright MCP server, or
  similar in the session, G5 ends up `BLOCKED` and the report says "static review only".
  That's by design, but it means UI tasks can't reach `COMPLETE` in such sessions.
- **No tests, no G3 PASS.** Projects without automated tests (many Liquid themes, small
  scripts) get G3 `NOT_APPLICABLE` with `reason_code: no_test_setup` at best, and the report
  says so. The team may write ad-hoc checks (e.g. rendering a Liquid snippet with
  `liquidjs` in a scratch dir), which count as evidence but aren't a test suite.
- **The ledger checker checks consistency, not truth.** It refuses a `PASS` without a
  command and exit code, but it can't prove the command really ran. That rests on the
  Lead following the protocol, on reviewers re-running things, and on you reading the
  report. In the end-to-end runs the Lead did re-run claimed tests and opened screenshots
  itself, but a model can still make mistakes.

## Guard hook

- **It's a seatbelt, not a sandbox.** It parses commands and blocks the destructive things
  agents actually do (push, deploy, reset/stash/clean, `rm -rf` outside the project,
  secret files, writes by reviewers). A deliberately obfuscated command, or code inside a
  test file that `npm test` then runs, can still get past it. Use your normal Claude Code
  permission settings and, for untrusted code, a container.
- **It only covers the plugin's subagents.** The main session (the Lead) runs under your
  own permission settings. The Lead is told not to push, deploy, or discard work, and the
  skills say so, but no hook enforces it for the main session. A plugin shouldn't change
  how your other sessions behave.
- Needs `sh` and `python3` (or `python`). Without Python the guard prints a notice and lets
  the call through.

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

- ETK doesn't deploy, open PRs, or talk to issue trackers. It stops at "changes ready in your
  working tree, with a report". Commit, push, and PR stay with you.
- The Lead decides the task size. It can be wrong in either direction. Tell it ("treat this
  as large", "no review needed") and it will follow you.
- Project memory (`docs/agent/`) is only as good as what gets written there. Agents are told
  to record facts and keep files short, but you should still read the diff of those files
  like any other change.
