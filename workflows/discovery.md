# Discovery: understand the project before touching it

The skill injects a snapshot from `scripts/discover.py` (paths, stack, commands,
git state). The snapshot tells you **where** things are. Read only what the task needs.

## Read, in this order

1. **Instructions**: every CLAUDE.md / AGENTS.md / rules file in the snapshot that
   applies to the paths you'll touch (root + nested ones in those directories).
   These are authoritative for the project. Where they conflict with ETK defaults,
   follow the project, unless that would break a safety rule (secrets, destructive ops,
   unauthorized deploys).
2. **Project memory**: `docs/agent/CURRENT_STATE.md`, `DECISIONS.md`, `ARCHITECTURE.md`
   if they exist, and the latest `.etk/runs/*` if the user is continuing a task.
3. **Architecture docs** listed in the snapshot, skimmed for the area you're changing.
4. **Project config**: `.claude/engineering-team.json` (commands, invariants, protected
   paths, UI URL, max cycles).
5. **The code around the change**: the module, one or two similar features (copy their
   patterns), and the existing tests for that area.
6. **CI config**: the real list of checks a PR must pass. Use it for G3/G4 commands.

## Extract (keep it in a few lines, it goes into every brief)

- Stack and versions that matter
- The specific rules that apply to this change (quote them)
- Skills worth using: project skills from the snapshot + installed skills relevant to
  the stack (Shopify project → the installed Shopify skill, etc.). Only list a skill
  that is actually available in this session.
- Test / lint / typecheck / build commands, confirmed (run the test command once
  early. A broken baseline changes the plan.)
- Invariants and things that must keep working
- Uncommitted user changes to leave alone

## Baseline

Before changing anything in medium/large mode, run the main test command once and
record the result in the ledger notes. Failing tests before you start are a fact
about the project, not your fault. Write them down so they can't be confused
with regressions later, and don't "fix" them unless that's the task.

## Domain rules stay in their domain

Apply platform-specific rules only when the snapshot shows the platform. No Shopify
conventions in a Django app, no React rules in a Go service. When a project has its
own skill for something (migrations, API clients, theming), use it instead of
generic advice.
