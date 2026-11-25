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

**How it was verified** (artifacts first: what was run and seen, then the code)
- Ran for real: `curl -s localhost:3000/api/coupons/SAVE10` → 200 `{"percent":10}`; browser: /checkout at 1280px and 375px, screenshots taken, error state checked
- `npm test`: exit 0, 214 passed (was 211 before; 3 new)
- `npm run lint`: exit 0
- Failures: NEW 0 · PRE-EXISTING 1 (`formats refunds`, also fails on base abc123)
- For state-heavy changes, an optional Mermaid `stateDiagram-v2` of the flow as the user sees it

**Not verified / limits**
- <anything not run and why, e.g. "e2e suite needs STRIPE_KEY: BLOCKED">

**Make it stick** (hardening proposals from findings, only if any)
- R1-002 → static: eslint `no-restricted-syntax` for `setTimeout(…, 0)` in `src/ui/**`. Want me to add it?
- Snapshot says hard checks are weak (no lint/CI): recommend adding them before larger features.

**Needs your decision** (only if any)
- <decision with a recommendation>

**Shipped** (only what actually happened, from the ledger's actions)
- commit `<sha>` · pushed `<branch>` · PR <url> · deployed `<target>` (verify: <result>)

**Left for you** (what wasn't done, and why)
- e.g. Not pushed: no push permission and profile says `confirm`. / Deploy skipped: no target in the profile.
- Run ledger: `.etk/runs/<id>/gates.json`
```

Rules:
- Say "INCOMPLETE" or "BLOCKED" plainly when it is. Don't bury it.
- Numbers come from command output, not from memory.
- No "bug-free", "fully tested", "production ready".
