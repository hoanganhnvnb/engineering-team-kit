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
| `max_cycles` | int | Review/fix cycles before escalating (default 3). |
| `commit` | bool | `true` lets the Lead commit locally at the end (never push). Default `false`. |
| `invariants` | string[] | Business rules that must hold. Reviewers and QA check them (G4). |
| `protected_paths` | string[] | Paths no agent changes without asking you first. |
| `agents` | object | Map an ETK role to a project agent, e.g. `{"code-reviewer": "my-reviewer"}`. |
| `notes` | string | Anything else, in a line or two. |

Example: [`templates/engineering-team.json`](../templates/engineering-team.json).

## Where rules come from (priority order)

1. Safety rules (no secrets, no push/deploy/destructive actions without you, no
   discarding your changes). These can't be overridden by project config.
2. Your instructions in the conversation.
3. Project instructions: CLAUDE.md files, `.claude/rules/`, AGENTS.md, and this config file.
4. ETK defaults (the workflows and quality docs in this repo).

## Project memory files

`docs/agent/ARCHITECTURE.md`, `DECISIONS.md`, `CURRENT_STATE.md`. See
[workflows/project-memory.md](../workflows/project-memory.md). Templates are in
[`templates/agent-docs/`](../templates/agent-docs/). You can create them yourself. The
Lead only creates them when they're needed and never rewrites your existing docs.
