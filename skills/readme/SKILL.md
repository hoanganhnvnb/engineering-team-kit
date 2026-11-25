---
name: readme
description: Audit and redesign the project's README.md into a clean, accurate, developer-first entry point. Discovers the real repository, checks every command and link, rewrites the README, and has an independent reviewer verify it. Leaves the changes uncommitted.
argument-hint: "[focus, e.g. 'keep it short' | 'library, not an app']"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover)
---

# /engineering-team:readme

You are the **Lead**. You redesign this project's README so a first-time visitor
understands within 30 seconds what it is, who it is for, how to start and where the
docs are. The repository is the only source of truth: nothing is invented.
Design rules, structure and checks: `${CLAUDE_PLUGIN_ROOT}/workflows/readme.md`. Read it first.

**Focus:** $ARGUMENTS

## Project snapshot

!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover`

## Steps

1. **Discover (cheap).** Spawn `engineering-team:scout` to collect facts only: project
   type, stack, manifests, real scripts and commands, config and env vars, CI workflows,
   license, existing assets (logo, screenshots, diagrams), the docs tree, and what the
   current README claims. Never ask the user what the repository can answer.
2. **Audit.** Compare the README with those facts, as in the audit list of the workflow
   file. List what is wrong, outdated, duplicated or missing. Keep it short.
3. **Decide the structure.** Pick sections for this repository type and say where any
   long content moves (an existing doc, never a new empty page). One decision checkpoint
   at most, and only for something the repository can't settle, asked the way
   `${CLAUDE_PLUGIN_ROOT}/workflows/decisions.md` says, recommended option first.
4. **Rewrite.** Spawn `engineering-team:tech-writer` with the facts, the audit, the chosen
   structure and the workflow file. It edits `README.md` and, when content moves, the
   target doc. It runs or checks every command it documents without side effects, and
   marks anything it couldn't verify as `unverified`.
5. **Independent check.** Spawn a fresh `engineering-team:code-reviewer` with the diff and
   the workflow's validation list, not your summary. It checks accuracy against the code,
   links and local assets, badges, Mermaid syntax, heading hierarchy, duplication and
   sensitive data. Light and dark mode and phone width can only be judged from the source
   (no fixed-width tables, images that work on both backgrounds, small diagrams); it
   lists them as "not rendered" rather than claiming them. Fix what it finds yourself
   for small edits, otherwise with a fresh `tech-writer`, then have the reviewer verify
   the fixes. At most 3 rounds.
6. **Report** in the user's language: problems found, what changed, files touched,
   anything relocated, how it was validated, what stays unverified, and the decisions
   you made on your own.

## Rules

- Change documentation only: never source, dependencies, CI or behaviour.
- Keep credits, attribution and legal text.
- Don't commit or push. Leave the changes in the working tree for the user.
- Don't create placeholder pages or brand assets the project doesn't have.
