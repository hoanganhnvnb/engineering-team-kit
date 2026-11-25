# Project configuration

Optional. ETK works without any config by reading what the project already has
(CLAUDE.md, package scripts, CI files). Add `.claude/engineering-team.json` when
you want to pin something the team keeps getting wrong.

The discovery snapshot prints this file at the start of every command, so the Lead
always sees it.

| Key | Type | Meaning |
|---|---|---|
| `commands.test` / `lint` / `typecheck` / `e2e` / `build` | string | The commands to use for G3/G4. Beats guessing from package scripts. |
| `ui.start` | string | How to start the app for UX review. |
| `ui.url` | string | Where to open it. |
| `verify` | string[] | Commands that drive the real feature (smoke request, driver script). QA and the Lead run them and record them as `runtime` evidence. |
| `max_cycles` | int | Review/fix cycles before escalating (default 3). |
| `commit` | bool | Older setting: `true` lets the Lead commit locally at the end. Your [workflow profile](workflow.md) takes over once it exists. Push, merge and deploy are never read from this file. Default `false`. |
| `invariants` | string[] | Business rules that must hold. Reviewers and QA check them (G4). |
| `protected_paths` | string[] | Paths no agent changes without asking you first. The guard reads this file from the session's working directory and blocks ETK subagents (every role) from writing under these paths with Write/Edit or through the shell (redirects, `rm`, `mv`, `cp`, `sed -i`, `git rm`, and similar). Entries are paths, directories (`db/migrations/`) or globs (`infra/**`, `src/legacy/*.js`). It stops accidents, not a determined bypass: see [limitations](limitations.md#guard-hook). |
| `rules` | object[] | Path-scoped invariants: `{"paths": "src/domain/**", "rule": "…", "check": "<cmd>"}`. Reviewers apply each rule to changed files matching `paths` and run `check` if present. Prefer rules with a `check`: prose-only rules are the weakest kind. |
| `agents` | object | Map an ETK role to a project agent, e.g. `{"code-reviewer": "my-reviewer"}`. The guard only recognises the plugin's own agents (`engineering-team:*`), so a mapped project agent is **not** guarded: its read-only, QA and tech-writer limits, and the push/deploy/secrets rules, become whatever that agent's own tools and your permission settings allow. |
| `models` | object | Override an agent's model, e.g. `{"developer": "sonnet", "code-reviewer": "opus"}`. Defaults: scout→haiku, qa-engineer→sonnet, code-reviewer→opus, tech-writer→opus, developer/ux-reviewer→your session's model. |
| `conventions` | object | `{"disable": ["ui", "api"], "extra": ["docs/our-guide.md"]}`. `disable` drops topics of the [conventions pack](conventions.md) (`["all"]` turns it off); `extra` adds repo-relative files inside the project for agents to read. |
| `notes` | string | Anything else, in a line or two. |

Example: [`templates/engineering-team.json`](../templates/engineering-team.json).

This file is shared with everyone who clones the repo, so it can't grant push, merge or
deploy. Release keys in it (for example `push`, `deploy`, `release`) are ignored. How you
ship lives in your own [workflow profile](workflow.md), outside the repo.

## Where rules come from (priority order)

1. Safety rules (no secrets, no push/merge/deploy beyond what your workflow profile and
   your own words allow, no destructive actions, no discarding your changes). These can't be overridden by project config.
2. Your instructions in the conversation.
3. Project instructions: CLAUDE.md files, `.claude/rules/`, AGENTS.md, and this config file.
4. ETK defaults (the workflows and quality docs in this repo).

## Project memory files

`docs/agent/ARCHITECTURE.md`, `DECISIONS.md`, `CURRENT_STATE.md`. See
[workflows/project-memory.md](../workflows/project-memory.md). Templates are in
[`templates/agent-docs/`](../templates/agent-docs/). You can create them yourself. The
Lead only creates them when they're needed and never rewrites your existing docs.
