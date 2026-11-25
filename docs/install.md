# Install, upgrade, roll back, uninstall

Everything here uses Claude Code's own plugin system. ETK doesn't ship an
installer script and never edits your settings files by hand. The `claude plugin`
commands add entries to your settings without overwriting what's there.

Requirements: Claude Code with plugin support (built and tested on 2.1.329), `git`, and
Python 3.12+ (the scripts and hook use the standard library only). It is found on `PATH` (`python3`, `python3.13`, `python3.12`), in the usual system folders, or in the folders pyenv, uv, asdf and mise install to. If yours lives somewhere else, set `ETK_PYTHON=/path/to/python3.12`. Without one, the plugin's subagents are blocked by the guard until you install Python or disable the plugin, and the error message says how.

## If Python 3.12+ is not found

The plugin needs it for its scripts and for the guard hook. Without it:

- The main session keeps working. Other plugins are not affected.
- The plugin's subagents are blocked (the guard fails closed), and the `team`, `build`,
  `fix` and the other commands show "Python 3.12+ not found" where the snapshot should be.

Fix it in one of these ways:

1. **Install it.** `brew install python@3.12`, `sudo apt install python3.12`,
   `uv python install 3.12` or `pyenv install 3.12`. Restart Claude Code.
2. **Point to it.** If it is installed somewhere the plugin does not look, add this to
   `~/.claude/settings.json` and restart:

   ```json
   { "env": { "ETK_PYTHON": "/full/path/to/python3.12" } }
   ```

   A path that doesn't run, or is older than 3.12, is skipped. The plugin then falls
   back to its normal search.
3. **Turn the plugin off** for now: `claude plugin disable engineering-team@engineering-team-kit`.

Limits:

- It looks only at `PATH`, the system folders, `$ETK_PYTHON` and the pyenv, uv, asdf and
  mise folders under your home. conda or a custom location needs `ETK_PYTHON`.
- It never downloads or installs Python, and never searches the project folder.
- Native Windows isn't supported (the launchers are `sh`); use WSL.
- If you can't install 3.12, there is no reduced mode. The guard is what lets subagents
  run safely, so the plugin stays off rather than run without it.

## 1. Install for yourself (all projects)

```bash
claude plugin marketplace add hoanganhnvnb/engineering-team-kit
claude plugin install engineering-team@engineering-team-kit
```

Restart Claude Code (or start a new session). Check it's there:

```bash
claude plugin list            # engineering-team@engineering-team-kit, enabled
```

In a session, type `/engineering-team:` and the eight commands should autocomplete.

## 2. Pin a version

The repository is also its own marketplace. Releases are git tags (`v0.1.0`, …).
To pin, add the marketplace at a tag:

```bash
claude plugin marketplace add hoanganhnvnb/engineering-team-kit#v0.1.1
claude plugin install engineering-team@engineering-team-kit
```

The plugin's `version` field also pins: installed copies stay on that version until a
newer release bumps it and you update.

## 3. Install for a team (one project)

Commit this to the project's `.claude/settings.json` (merge with what's already there).
Anyone who trusts the project folder gets asked to install it:

```json
{
  "extraKnownMarketplaces": {
    "engineering-team-kit": {
      "source": { "source": "github", "repo": "hoanganhnvnb/engineering-team-kit" }
    }
  },
  "enabledPlugins": {
    "engineering-team@engineering-team-kit": true
  }
}
```

Or run `claude plugin install engineering-team@engineering-team-kit --scope project`,
which writes the `enabledPlugins` entry for you.

## 4. Local development

```bash
git clone https://github.com/hoanganhnvnb/engineering-team-kit ~/src/engineering-team-kit
cd /path/to/some/project
claude --plugin-dir ~/src/engineering-team-kit
```

`--plugin-dir` loads the plugin for that session only, straight from your checkout, so
edits apply on the next session start. Don't have the marketplace copy enabled at the same
time, or you'll see the commands twice. Disable it with
`claude plugin disable engineering-team@engineering-team-kit` while developing.

You can also add your checkout as a local marketplace:
`claude plugin marketplace add ~/src/engineering-team-kit`.

## 5. Upgrade

```bash
claude plugin marketplace update engineering-team-kit
claude plugin update engineering-team@engineering-team-kit
```

**To 0.4.0.**
- From 0.2.x you also get 0.3.0's floor: Python 3.12+.
- The default branch of this repo is now `master` (was `main`). If
  `marketplace update` fails, remove the marketplace and add it again
  (`claude plugin marketplace remove engineering-team-kit`, then the `add` above).
- New: the `team` skill, a per-developer workflow profile (kept in the plugin's data
  folder, never in your repo) and the conventions pack. Nothing changes in your repo
  until you run a task. Commit, push, PR and deploy happen only as your profile and
  your own words allow.
- To stay on the old behaviour, pin `#v0.3.0`.

Restart the session. Read `CHANGELOG.md` for what changed. Breaking changes to the
ledger format or command names will only come with a minor-version bump before 1.0
and a major bump after.

## 6. Roll back

Re-add the marketplace at the tag you want and reinstall:

```bash
claude plugin uninstall engineering-team@engineering-team-kit
claude plugin marketplace remove engineering-team-kit
claude plugin marketplace add hoanganhnvnb/engineering-team-kit#v0.1.0
claude plugin install engineering-team@engineering-team-kit
```

Run ledgers (`.etk/runs/`) and project notes (`docs/agent/`) live in your projects, not in
the plugin, so rolling back doesn't lose them.

## 7. Turn off or uninstall

```bash
claude plugin disable engineering-team@engineering-team-kit     # keep installed, turn off
claude plugin uninstall engineering-team@engineering-team-kit   # remove
claude plugin marketplace remove engineering-team-kit           # forget the marketplace
```

What stays behind in your projects (delete if you like): `.etk/` (run ledgers,
git-excluded through `.git/info/exclude`), the `.etk/` line in `.git/info/exclude`, and
any `docs/agent/*.md` files the Lead created.

## Environment notes

- **Windows**: the hook runs `python3 …`. If your Python is only on `PATH` as `python` or
  `py`, add a `python3` alias or shim. Not tested on native Windows yet; WSL works like Linux.
- **No git**: works, but there is no worktree isolation (large tasks run sequentially) and
  no diff-based review of uncommitted changes. The Lead will say so.
- **Headless (`claude -p`)**: works (the end-to-end tests run this way). Browser tools are
  usually not connected there, so UI gates end up `BLOCKED`.
- **Agent teams** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`) are not used. ETK runs on
  regular subagents so it works on default settings.
