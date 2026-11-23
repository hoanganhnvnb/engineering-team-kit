# Evals

Behavioral checks for the plugin's commands, run with Claude Code's built-in eval
runner. They're unit tests for the skills: when you change a skill or agent prompt,
run them and see whether behavior moved.

```bash
claude plugin eval . --scaffold --allow-tools Bash Write Edit --ablation none --judge-model sonnet -j 3 --no-publish
```

- `--scaffold` runs each case's `scaffold.sh` to build a tiny throwaway project.
- `--allow-tools`: Bash/Write/Edit are gated in eval runs; the cases need them.
- `--no-publish`: keep the HTML report local (it contains paths from your machine).
- `--ablation none` skips the no-plugin baseline (the commands don't exist without the plugin).
- `--judge-model`: grade with a *different* model than the one under test, so the
  judge doesn't share the worker's blind spots.
- Each case runs once (`runs: 1`) to keep cost down. Raise `runs` locally when you
  want to see variance. Expect roughly $3–8 for the whole suite.

| Case | What it protects |
|---|---|
| `small-fix-stays-small` | Small work isn't over-delegated; repro test first; ledger checked; honest report |
| `ui-without-browser-is-honest` | No visual claims without a browser; G5 BLOCKED, not PASS |
| `security-change-gets-independent-review` | SQL + user input → independent reviewer; no string-built SQL; LIKE wildcards handled |

Run them from a normal terminal, not from inside a Claude Code session: the eval
runner starts its own OS sandbox, and nested inside another session it can fail to start
(we saw `Failed to create bridge sockets` and a read-only temp dir, which make the
snapshot step fail at turn 0). Results go to `evals/results/` (git-ignored).

Add a case when a real run goes wrong: reproduce the situation in `scaffold.sh`,
then write graders for the behavior you wanted. Prefer deterministic graders
(`tool_used`, `regex`) and use `llm` graders only for what can't be pattern-matched.
