# Changelog

All notable changes to this plugin. Versions follow semver; the version in
`.claude-plugin/plugin.json` is what installed copies pin to.

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
