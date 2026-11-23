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

### 0.2.0: smarter collaboration

| Phase | Status | Notes |
|---|---|---|
| 9. Research | done | Two public talks on agent workflows: auto-captions pulled with `yt-dlp` (json3), slides sampled as frames every 20 s. Takeaways: verification first, strength order of checks, correction ratchet, agents copy patterns, feature maps, evals as skill tests, trust before fleets. |
| 10. Roles & models | done | `scout` (haiku) and `tech-writer` (opus) added; per-role default models; `models` override; reviewer lenses; tie-breaker on a different model. |
| 11. Verification & hardening | done | `runtime` command type + checker warning; FEATURES.md; `hardening` on findings; hard-checks section in the snapshot; path-scoped rules. |
| 12. Learning loop | done | `etk_run.py stats`, `/engineering-team:retro`, LESSONS.md. |
| 13. Evals | done | Three `claude plugin eval` cases with scaffold scripts. All load and grade; agent runs couldn't execute inside a nested session (eval sandbox failed to start), see limitations. Running them found two real problems: a broken `python3` shim kills the snapshot (→ `etk.sh` launcher) and an invalid grader key. |
| 14. Review | done | Fresh adversarial reviewer: 9 findings (1 high: `stats` crashed on hand-edited ledgers; 4 medium: `check` tracebacks, a `composer.json` crash in the snapshot, the tech-writer could edit CLAUDE.md/agent files, a SQL grader that false-failed safe code). All fixed with regression tests. |

## Decisions made along the way

- **`disable-model-invocation: true` on all five skills.** Team workflows cost real
  tokens; they should start because the user asked, not because a prompt said "fix".
- **Guard only for `engineering-team:*` agents.** A plugin shouldn't change how unrelated
  sessions behave. The main session already has the user's permission settings.
- **`git stash` blocked for subagents.** It rewrites the working tree the user is using.
  Base comparisons use a temporary worktree instead.
- **Integration without commits.** Large-mode worktree branches are applied with
  plain `git apply` (working tree only, never the index), so the user's branch gets no
  surprise commits or staged files.
- **Propose hardening, don't apply it.** A lint rule or CI step changes the user's
  project; the team writes the proposal and the user decides.
- **Runtime evidence is a warning, not an error.** Some changes can't reasonably be
  driven (a pure library function); a hard error would push agents to fake it.
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
