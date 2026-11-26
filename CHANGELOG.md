# Changelog

All notable changes to this plugin. Versions follow semver; the version in
`.claude-plugin/plugin.json` is what installed copies pin to.

## Unreleased

- Security: `etk run preflight --action push|pr --data DIR [RUN]` re-checks, right before
  `git push` and `gh pr create`, that the run is `ready` and that a profile-authorized push or
  PR still matches what the profile was confirmed for (checkout, origin and push URLs, the git
  settings that decide where a push goes, and a plain `git push` going to `origin`). It exits 1
  with the reason and nothing is sent. `workflows/ship.md` and the `team` skill run it before
  each outward push or PR. The check in `etk run act` is an audit made after the step: it now
  records `binding_ok` for push and PR, also with `--force-record`, and `etk run check` fails a
  run whose push or PR was recorded with `binding_ok: false`. A profile-authorized push or PR
  needs `--data` on `act`.
- Security: the binding also hashes the git settings that change where a push goes with the URLs
  unchanged: `remote.origin.*` (receivepack, vcs, proxy, mirror and the like; not the URLs,
  refspecs, tagopt or prune), `core.sshCommand`, `core.gitProxy`, `http.*`, `push.*`,
  `submodule.recurse` and `submodule.*.url`. A change makes the profile stale with the reason
  "git settings that decide where a push goes changed". The guard also stops subagents changing
  `http.*` and `submodule.*` through `git config`. Remaining limits are in `docs/limitations.md`.
- Security: the binding hashes are now HMAC-SHA256 under a random per-data-dir key
  (`binding.key`, mode 0600, created on first use), not a bare sha256 of the URL, so a leaked
  profile no longer allows offline guessing of a weak URL password. Upgrade effect: every
  confirmed profile is stale once (its stored hashes use the old scheme and have no settings
  hash); answer `release.commit` and `release.push` again and run `profile confirm`. Deleting or
  corrupting the key does the same.
- `etk run authorize` records the binding from the stored profile it just checked instead of a
  second look at the repository.
- A `--data` dir inside the repository (git or svn) is now refused (exit 2) by
  `etk run authorize|preflight|act` as well as by every `profile` command; `discover` reports the
  profile as unknown. These three also refuse any other invalid `--data` (not a plugin data dir,
  unsubstituted `${...}`) whenever it is given, also for an action authorized by the user's own words.
- The binding's settings hash tells a valueless boolean (`sslVerify`, true) from an empty value
  (`sslVerify =`, false), and ignores `remote.origin.gh-resolved` (written by
  `gh repo set-default`), which does not change where a push goes; it does choose the repository
  `gh pr create` targets, which is not covered (nor is `GH_REPO`). `submodule.*.url` is still hashed: the first
  `git submodule update --init` or `sync` makes a profile stale once.
- `profile set|unset|confirm|remember` warn on stderr when the binding key cannot be stored (the
  profile will be stale next time); exit codes are unchanged.

## 0.6.0

- New `/engineering-team:init`: run it once at the start of a project. It detects the VCS,
  host, branches, commit style and test commands first, then asks only the missing
  workflow fields (branching, commit, push, PR or merge, deploy) in at most two rounds,
  plus an optional round of notes (docs language, how many subagents at once,
  words that must never appear in commits). It saves to the profile outside the repository,
  marks it confirmed only after you have seen it, and never writes into the repo, commits,
  pushes, merges or deploys. Running it again first asks keep, change a field or reset, then only what is missing.
- Security: a profile remembers where it was confirmed as the checkout path plus hashes of the
  raw URL lists of `origin`: every fetch URL (`git remote get-url --all origin`) and every push
  URL (`git remote get-url --push --all origin`), in order, as `git` reports them with
  `insteadOf` and `pushInsteadOf` applied. git pushes to all push URLs, so adding, removing or
  reordering one makes the profile stale. It never stores URL text. `auto` settings count only
  while the path and both hashes still match; nothing is compared after parsing, so no spelling
  of a URL can pass for another.
- Security: `release.push: auto` also needs `origin` to have a push URL and a plain `git push`
  (`remote.pushDefault`, `branch.<name>.pushRemote`, `branch.<name>.remote`) to go to `origin`.
  Otherwise it is not in effect: `profile show --brief` says so, `authorize --source profile`
  refuses a push or PR, and the stored answer is kept. A profile saved with no `origin` never
  authorizes a push or PR. `team` pushes with `git push -u origin <branch>`, the remote the
  profile binds. `etk run authorize --source profile` records the binding, and `etk run act
  --action push|pr` refuses when the checkout or any URL changed since, unless the user
  authorized it in their own words.
- Security: `profile confirm` in another checkout, or after the push URL changed, no longer
  approves `release.commit` / `release.push` values that `show --brief` had hidden as `auto`.
  `profile set` and `unset` there drop those values and bind the profile to the current
  checkout, so you answer the release fields again, confirm once, and only then does the
  profile pre-authorize them. `set`, `unset` and `confirm` say which values they dropped, and
  `remember` no longer binds a profile without dropping them.
- `profile show --brief` prints no URL and no path for a stale profile, only the reason (push
  URLs or origin URLs changed, checkout moved). `init` runs `git remote get-url --push --all
  origin` itself and shows you each URL with everything between `://` and the last `@` of the
  authority removed, and any `?query` and `#fragment`.
- Upgrade note: profiles saved by 0.5.x are found again (the profile key still comes from the
  origin URL for plainly spelled remotes), but they hold plain-text URLs and no hashes, so
  they are treated as stale once: answer commit and push again and confirm. Remotes that are
  not plainly spelled (odd characters, a `%`, a query holding `@`) now get their own profile
  key from the raw text, so a profile saved for one of those is not found again. A local-path
  origin has its own `path:` key, so `github.com/o/r` and `https://github.com/o/r` no longer
  share a profile. The key now comes from the first fetch URL as `git` reports it (with
  `insteadOf` applied), and a profile saved with no `origin` is not found once one is added. `detect`
  shows such a remote as `(remote not shown)`.
- `profile show --brief` now says `(unconfirmed)` whenever the settings changed after the
  last `profile confirm`, and `profile remember` ignores a note that is already saved.
- Known limit: the notes are free text that the Lead reads through `profile show --json`;
  `profile show --brief` only counts them and nothing enforces them.
- `team`: when the profile is `missing`, it suggests `/engineering-team:init` in one line
  and keeps the lazy questions as a fallback. `workflows/profile.md` stays the single source
  of the question list and now tells the fallback to mention init.
- Docs: `init` in usage, workflow, README and the Vietnamese README.
- New eval case `init-asks-only-missing-fields` (written and linted, not run).

## 0.5.2

- **Security (guard):** a check that takes longer than 8 seconds now blocks with a message.
  Claude Code lets a tool call through when a hook times out (the hook limit is 10 seconds).
- **`team`:** a ledger is always opened, and `run check` must pass before any commit or push,
  even for a one-line fix. In a re-run, the request that used to skip the ledger kept it in
  3 of 3 runs.
- **Docs:** an optional sandbox and `permissions.deny` snippet for a hard limit on
  `~/.claude`, and the 0.5.1 end-to-end re-run in `docs/validation.md`.

## 0.5.1

- **Security (guard):** hardening of the `~/.claude` and Python-folder protection added in 0.5.0.
  - A wildcard with up to two wildcard parts and no `**` is expanded and every match is
    checked (at most 256), so a symlink inside the wildcard can't hide a guarded folder.
  - A deeper pattern, or one with `**`, is blocked when its fixed part leads into a guarded
    folder, so it can't stall the hook.
  - A `..` after a wildcard, or a part such as `.*` that can match it, is blocked.
  - Known gap: a symlink hidden in a deep wildcard part. See `docs/limitations.md`.

## 0.5.0

- New `/engineering-team:readme`: audits the README against the real repository,
  rewrites it with the design rules in `workflows/readme.md`, and has a fresh reviewer
  check commands, links, badges and diagrams. It leaves the changes uncommitted.
- The project README is rewritten the same way: shorter, with a diagram and a
  repository layout, and detail moved behind links.
- Python lookup is shared and wider. `scripts/find-python.sh` also checks `$ETK_PYTHON`
  and the pyenv, uv, asdf and mise version folders, so a `python3` shim that points at an
  old version no longer hides an installed 3.12. The "not found" message now says how to
  install one.
- **Security:** subagents can no longer write anything under `~/.claude` (settings, installed
  plugins including the guard hook's own code), `~/.claude.json`, or the Python folders and
  shims the launchers search. The hook also blocks the call when its Python finder is missing, in
  every shell, and a candidate interpreter must report that it is 3.12+ itself.

## 0.4.0

- **Behaviour change: the Lead can now ship.**
  - New `team` skill runs a task end to end: implement, review, test and fix until it
    passes, then commit, push, open a PR or merge, and deploy.
  - Commit, push and PR happen when your workflow profile says `auto` or you ask.
  - Merge, tag, deploy and rollback need your own words in the conversation. Production
    must be named.
  - Subagents still never push or deploy.
  - The six step commands work as before. `build` and `fix` continue into the ship flow
    only when you asked for it, or when your profile says auto.
- **Workflow profile**, one per developer and project (`etk.sh profile`).
  - Stored in the plugin's data folder, outside the repo, so it is never committed.
  - Detects git/SVN, host and CLI, default branch, commit style and language, commit
    tooling, and deploy candidates. Asks only for what it can't detect.
  - Settings in the repo can't grant push, merge or deploy.
  - The old `commit: true` key in `.claude/engineering-team.json` is ignored. The
    profile's commit setting (`release.commit`) replaces it.
- **Run ledger.**
  - New run kind `ship` and gate G7 (release).
  - New `run phase`, `run authorize`, `run act` and `run decide`.
  - `check` fails on a release action without a matching permission, one taken before
    the gates passed, a merge or deploy allowed only by the profile, or a production
    deploy you didn't name.
- **Conventions pack** (`conventions/`): commits, naming, style, API, database,
  versioning, testing and errors, security, docs and review, and UI.
  - Read on demand, under a size budget.
  - Project rules win.
  - `conventions.disable` / `conventions.extra` in the project config.
- **Decision policy** (`workflows/decisions.md`): the Lead asks rarely, in batches, with
  a recommendation. Agents can't call AskUserQuestion; they report to the Lead.
- **Reviewer and scout.**
  - The reviewer fails closed (`COULD_NOT_REVIEW`), lists what it didn't check, and
    ignores wording that leans toward a verdict.
  - The scout tries several naming styles before reporting "not found".
- **Security fixes from an audit.**
  - The guard now sees every tool: `Monitor` commands get the Bash checks, and unknown
    tools are blocked for our agents.
  - Ledger commands only act on runs this session could have created: no committed,
    symlinked or future-dated runs.
  - Subagents can't write the profile or `.etk/` run records.
  - The snapshot runs git without fsmonitor or hooks and trims repo-supplied strings.
- This repo's default branch is now `master`. See docs/install.md if
  `marketplace update` fails.

## 0.3.0

- **Breaking: Python 3.12 or newer is required.** `etk.sh`, the guard wrapper and
  `evals/run.sh` pick the first working Python that is 3.12+ (also trying `python3.12` and
  `python3.13`). If there is none, the guard blocks the plugin's subagents with a message
  instead of letting them run unguarded; the main session is not affected. CI now runs on
  Python 3.12, on Linux and macOS.
- The guard now reads shell commands with a real tokenizer and parser (quotes, heredocs,
  nested shells, `cd` tracking) instead of pattern matching. New protections: `protected_paths`
  from the project config, write-style MCP tools, read-only git for read-only roles, `.git` and
  bulk deletes, env/sudo options that change directory. It fails closed when it hits an error.
- The guard is a best-effort tripwire, not a sandbox. Known open items are in
  `docs/limitations.md`: obfuscated commands, MCP tools with neutral names, files created by
  earlier tool calls, agents mapped through the `agents` config, and the main session.
- Ledger: new `invalid` finding status (needs a `resolution`); a report-only review can finish
  `COMPLETE` with open mediums; `etk.sh exec <gate> --type test -- <cmd>` runs a command and records
  its real exit code, and `check` warns about G3/G4 passes recorded any other way. `exec` is not
  pre-approved by any skill. The guard judges the command after `--` like any other command, and
  read-only roles can't use `exec`.
- `scripts/selftest.sh` runs the tests with the first Python 3.12+ it finds (same list as
  `etk.sh`) and says so if there is none.
- Fixes: two `init` runs in the same second no longer crash; `render` copes with malformed
  criteria and gates; the project snapshot no longer hides skills named `build` or `test`;
  parallel reviewers get distinct finding ID prefixes; review and improve-ui wording matches the
  routing rules; `evals/run.sh` no longer needs GNU `xargs` and fails if its patch step misses.

## 0.2.1

- `evals/run.sh`: run the evals on a temporary copy so a harness sandbox problem with
  `!` injection doesn't end every run at turn 0. Eval results recorded in `docs/validation.md`.

## 0.2.0

- New agents: `scout` (haiku; fact gathering and data export) and `tech-writer` (opus;
  project docs, verifies every claim). Default models per role: `code-reviewer` opus,
  `qa-engineer` sonnet; `developer` and `ux-reviewer` keep the session's model. Project
  config `models` overrides.
- New command `/engineering-team:retro`: run statistics, recurring finding categories,
  and a short ratchet plan of hard checks; writes `docs/agent/LESSONS.md`.
- Runtime verification: developer and QA drive the change for real; ledger commands take
  a `type` (`runtime`, `e2e`, `test`, …); the checker warns when a medium/large build has
  no runtime evidence. New `docs/agent/FEATURES.md` template (how to reach and prove each
  feature, and what usually lies).
- Hardening: findings carry a `category` and, from medium up, a `hardening` proposal
  (`architecture` / `static` / `runtime` / `prose`), rendered in the report.
- Reviewer lenses (`correctness`, `security`, `architecture`); a second security-lens
  reviewer for sensitive changes; a tie-breaker on a different model for disputed
  critical/high findings; pattern-spread and justifying-comment checks; grounded root causes.
- Snapshot: "Hard checks" section (lint, types, format, tests, CI, pre-commit, import
  boundaries) with a warning when they're thin; path-scoped `rules` from config.
- Config: `rules`, `verify`, `models`.
- `etk_run.py stats [--json] [--last N]`.
- Evals: three `claude plugin eval` cases for skill behaviour.
- `scripts/etk.sh` launcher: skills and the hook use the first Python that actually runs,
  so a broken `python3` shim no longer kills the snapshot.
- Guard: the tech-writer can't edit agent instructions (CLAUDE.md, AGENTS.md, SKILL.md,
  `.claude/`); read-only roles can't write through in-place flags (`perl -i`, `--write`,
  `--fix`) or inline code.
- `check`, `stats` and the snapshot report malformed ledgers/config instead of crashing.

## 0.1.1

- Guard: refuse `cp`/`mv`/`install`/`ln` target-directory forms it can't parse
  (`-t.`, `-rt`, `--target`) for read-only and create-only roles.

## 0.1.0

First release.

- `/engineering-team:build`, `fix`, `review`, `test`, `improve-ui`
- Agents: `developer`, `code-reviewer`, `qa-engineer`, `ux-reviewer`
- Small / medium / large routing; worktree isolation for parallel work
- Review loop with finding IDs, severities, and a 3-cycle limit
- Quality gates G1–G6 with a ledger and a strict checker (`scripts/etk_run.py`)
- Project discovery snapshot (`scripts/discover.py`)
- Guard hook for the plugin's own subagents (push/deploy/destructive git/secret files,
  read-only reviewers, create-only QA), via a shell wrapper that skips the main session
- End-to-end scenario runner and fixtures; results in `docs/validation.md`
