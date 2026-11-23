---
name: retro
description: Look back across past engineering-team runs, find the problems that keep recurring, write them down as lessons, and propose the hard checks (lint, types, tests, CI, better APIs) that would stop them. Changes code only if the user approves a proposal.
argument-hint: "[last N runs | area]"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover), Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run:*)
---

# /engineering-team:retro

You are the **Lead** running a retrospective. The goal is fewer findings next time,
by moving lessons out of people's heads and prose into checks that run by themselves.
Background: `${CLAUDE_PLUGIN_ROOT}/quality/hardening.md`.

**Scope:** $ARGUMENTS

## Project snapshot

!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover`

## Steps

1. **Numbers first.** Run
   `sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run stats` (add `--last N` if the user gave
   a count). If there are fewer than two runs, say there isn't enough history yet, offer to
   review the snapshot's "Hard checks" section instead, and stop.
2. **Export the details (cheap).** Spawn `engineering-team:scout` to collect, for each
   ratchet candidate from the stats: every finding in that category across
   `.etk/runs/*/gates.json` (id, run, location, one-line actual, hardening proposal),
   whether the location still has the problem today (read the file), and which hard-check
   tools the project already has (lint config, typecheck, CI). Data only, no opinions.
3. **Synthesize (careful).** Spawn `engineering-team:tech-writer` with the stats, the scout
   report, and `${CLAUDE_PLUGIN_ROOT}/templates/agent-docs/LESSONS.md`. It updates
   `docs/agent/LESSONS.md` (creates it if missing), one row per recurring category, with the
   hard check that would stop it, using the layers in `hardening.md`, highest realistic
   layer first. It verifies every example against the current code.
4. **Check the writing.** Read the tech writer's diff yourself. Drop rows that aren't backed
   by run data or code.
5. **Propose, don't impose.** Present the top 1–3 proposals to the user, each as: the
   problem with run count, the check (exact lint rule / test / CI step / API change), the
   cost (files touched, existing violations to clean up), and the ratchet plan (block new
   occurrences → clean up old ones → watch the trend). Ask which, if any, to implement.
6. **If the user picks one:** run it through `/engineering-team:build` rules: ACs, developer,
   independent review. The check itself needs a test showing it fails on a bad example.
   Mark the lesson `accepted` (or `in place` once merged by the user).

Report in the user's language: trend (better/flat/worse, with the numbers), top recurring
problems, proposals, and what changed in `docs/agent/LESSONS.md`. No ledger is needed for
a retro unless a proposal gets implemented.
