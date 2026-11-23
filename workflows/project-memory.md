# Project memory (`docs/agent/`)

Goal: the next session (or the next person) can pick up without rediscovering
everything, **without** creating a second copy of documentation the project
already has. Agents pay for every token they re-read, so keep these files short.

## Files

| File | What goes in | When to create |
|---|---|---|
| `docs/agent/CURRENT_STATE.md` | What's in progress, what's done, what's blocked, latest run ledger path | Large tasks, or any task that won't finish in this session |
| `docs/agent/DECISIONS.md` | Dated decisions with the reason and who made them | When the user makes a decision worth keeping, or a large task fixes a contract |
| `docs/agent/ARCHITECTURE.md` | A map: main modules, how a request flows, where things live, what usually surprises people | Only if the project has no equivalent doc and discovery took real effort |

Templates are in `templates/agent-docs/`.

## Rules

- **Read existing docs first.** If `ARCHITECTURE.md`, an ADR folder, or a good README
  already covers it, link to it instead of copying.
- **Facts only.** Write what the code does today, with file paths. Not what an
  agent thinks it should do.
- **Agents don't change architecture by writing docs.** Proposals go into
  `DECISIONS.md` as `Status: proposed` and stay proposed until the user agrees.
- **Fix drift in the same change.** If your change makes a line in these files wrong,
  update that line.
- **Keep it small.** CURRENT_STATE is overwritten, not appended forever. Move finished
  items out. Aim for under ~60 lines per file.
- These are project files: they show up in `git status` and the user decides
  whether to commit them. ETK's own run files live in `.etk/` (git-excluded locally).
