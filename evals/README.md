# Evals

Behavioral checks for the plugin's commands, run with Claude Code's built-in eval
runner. They're unit tests for the skills: when you change a skill or agent prompt,
run them and see whether behavior moved.

```bash
evals/run.sh                      # all cases
evals/run.sh --case 'small-*'     # extra flags go to `claude plugin eval`
```

`run.sh` makes a temporary copy of the plugin and runs `claude plugin eval` on it with
`--scaffold --allow-tools Bash Write Edit --ablation none --judge-model sonnet --no-publish`
and a $12 cost cap. Results go to `evals/results/<timestamp>/` (git-ignored): `result.json`
and `report.html`.

**Why a copy.** The eval sandbox's temp dir is read-only for the harness's own shell
wrapper, so a skill's `` !`…` `` snapshot line counts as failed and every run ends at turn 0
with a score that looks like a result but isn't. In the copy that one line becomes "run this
with the Bash tool". Agents, hooks, scripts, workflows and graders are the real ones, and the
skills in the repo aren't touched. This was checked against the real skills first: they
reproduce the turn-0 failure, and the copy runs to completion.


Flags `run.sh` sets, and why:

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
| `init-asks-only-missing-fields` | `init` detects git, GitHub and Conventional Commits and doesn't ask about them; asks the release and deploy fields; writes nothing into the repo; no subagents, no commit or push |

A run is one sample from a model, so a single failed grader isn't automatically a bug: in
one check the agent honestly reported that its sandbox wouldn't let it create `.etk/`, so the
"ledger checked" grader failed while the behaviour was right. Read the report before
changing a skill. Use `--runs 3` for anything you rely on.

Add a case when a real run goes wrong: reproduce the situation in `scaffold.sh`,
then write graders for the behavior you wanted. Prefer deterministic graders
(`tool_used`, `regex`) and use `llm` graders only for what can't be pattern-matched.
