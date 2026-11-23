# Implementation progress

Running log of building ETK itself. Newest state at the top of each phase.

| Phase | Status | Notes |
|---|---|---|
| 1. Environment & docs research | done | Claude Code 2.1.329; plugin manifest/marketplace/skills/agents/hooks specs checked against code.claude.com docs. Verified empirically that PreToolUse hook input includes `agent_type` (`<plugin>:<agent>`) for subagent calls and omits it for the main session. |
| 2. Architecture & design | done | Main session = Lead; skills for commands; 4 subagents; no MCP; no agent teams (experimental, not in `-p`). Ledger + checker instead of prose-only rules. See [architecture.md](architecture.md). |
| 3. Plugin skeleton | done | `.claude-plugin/plugin.json` + `marketplace.json` (source `./`), `claude plugin validate --strict` passes. |
| 4. Agents & skills | done | build / fix / review / test / improve-ui; developer / code-reviewer / qa-engineer / ux-reviewer. |
| 5. Collaboration & quality | done | Review loop with finding IDs + lifecycle; gates G1–G6; `etk_run.py check` enforces evidence rules; kind-aware (review/test own only their gates); G4 accepts proven pre-existing failures only. |
| 6. Install & compatibility | done | Marketplace install, tag pinning, project-scope team setup, local `--plugin-dir`, upgrade/rollback/uninstall docs; discovery snapshot; guard hook scoped to ETK agents. |
| 7. End-to-end validation | done | Scenarios A–H on throwaway fixture copies; results in [validation.md](validation.md). The runs found one real bug (snapshot injection denied outside bypass mode), fixed and re-verified. |
| 8. Docs & report | done | README, install, usage, architecture, principles, configuration, limitations. |

## Decisions made along the way

- **`disable-model-invocation: true` on all five skills.** Team workflows cost real
  tokens; they should start because the user asked, not because a prompt said "fix".
- **Guard only for `engineering-team:*` agents.** A plugin shouldn't change how unrelated
  sessions behave. The main session already has the user's permission settings.
- **`git stash` blocked for subagents.** It rewrites the working tree the user is using.
  Base comparisons use a temporary worktree instead.
- **Integration without commits.** Large-mode worktree branches are applied with
  `git diff … | git apply --3way`, so the user's branch gets no surprise commits.
- **Ledger in `.etk/`, excluded via `.git/info/exclude`.** Keeps `git status` clean without
  editing the project's tracked `.gitignore`.

## Review rounds

- **Independent adversarial review** (fresh subagent, given only the code): 15 findings.
  The serious ones: the checker let `wont_fix` and all-N/A ledgers through as COMPLETE, and
  the guard both over-blocked (`grep "git push"`) and under-blocked (`git checkout HEAD -- f`,
  `rm -rf ../x`). All fixed with regression tests.
- **Automated security review** on each commit: e2e runner bypassed permissions by default
  (now opt-in, narrow allowlist), plus several guard bypasses (nested shells, heredocs,
  redirect forms, multi-operand writers, `cp -t`). All fixed with regression tests.
