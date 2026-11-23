# Final report template

Write in the user's language. Keep it short. The user should be able to tell in ten
seconds whether it's done and what to check. Paste the output of
`etk_run.py render` for the tables rather than retyping them.

```markdown
## <Goal in one line>: <COMPLETE | INCOMPLETE | BLOCKED>

**What changed**
- `path/file.ext`: one line on what and why
- …

**Acceptance criteria**
1. <AC>: met ✔ (evidence: `test name` / screenshot / command)
2. <AC>: not met ✘ (why, what's next)

**Gates**
<table from `etk_run.py render`>

**Findings**
<table from render, or "none above low">
Disputed/accepted items with the reason.

**How it was verified**
- `npm test`: exit 0, 214 passed (was 211 before; 3 new)
- `npm run lint`: exit 0
- Browser: /checkout at 1280px and 375px, screenshots taken, error state checked

**Not verified / limits**
- <anything not run and why, e.g. "e2e suite needs STRIPE_KEY: BLOCKED">

**Needs your decision** (only if any)
- <decision with a recommendation>

**Left for you**
- Changes are uncommitted on branch `<branch>` (or: committed locally as `<sha>`, not pushed).
- Run ledger: `.etk/runs/<id>/gates.json`
```

Rules:
- Say "INCOMPLETE" or "BLOCKED" plainly when it is. Don't bury it.
- Numbers come from command output, not from memory.
- No "bug-free", "fully tested", "production ready".
