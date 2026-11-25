# Ship: commit, push, integrate, deploy

Read this file when a run reaches release. That happens in two cases: the `team` skill
drives the run, or a build/fix run finishes and the workflow profile says
`release.commit: auto`. Only the Lead does any of this. Subagents never commit, push,
merge or deploy.

Below, `etk` is short for `sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh"` and `RUN` is the
run directory that `run init` printed. Pass `RUN` to every ledger command.

## 0. Is it a pass?

Release only when all of these hold. If any fails, stop before the first outward step,
report what is missing, and ask.

- `etk run check RUN` exits 0 with every required gate settled.
- G3/G4 were recorded through `etk exec`, not typed by hand.
- No open or disputed finding of medium severity or above, and no high/critical one left
  unverified. `run act` records whether this held at that moment.
- A user-visible change was driven for real once (a `runtime` command or a G5 PASS).
- `release.wait_ci` is set: CI on the pushed commit is green before merging or deploying.

## 1. Permission

Each outward action needs a reason to happen, recorded before it runs:

```bash
etk run authorize --action push --source profile --quote "release.push: auto" RUN
etk run authorize --action deploy --target staging --source prompt \
  --quote "<the user's exact words>" --condition pass RUN
```

| Action | Allowed source |
|---|---|
| commit, push, pr | the profile says `auto`, or the user's words |
| merge, tag, deploy, rollback | the user's words only: this prompt (`prompt`) or an answer to your question (`answer`) |

- Quote the user verbatim. "review xong không lỗi, pass thì deploy staging luôn" is
  permission to deploy staging, on the condition that the run passes.
- A bare "deploy" means the single non-production target. Production needs the user
  to name it.
- Permission lasts for this run. Never copy it into the profile or a config file.
- Permission from an earlier conversation must be shown to the user and confirmed
  again before you rely on it.
- Missing permission for an L4 action means one question at the exception gate
  (`workflows/decisions.md`). Until the user answers, do everything else.

## 2. Commit

- Stage by name only the files this run changed. Compare against the snapshot's
  "Uncommitted changes" and never stage the user's own edits. Never `git add -A` or
  `git add .`.
- Make one commit per logical change. Use the project's commit convention; if there is
  none, use Conventional Commits `type(scope): description`. No AI co-author trailers.
- Feature or gitflow model: create the branch from `branches.base` with
  `branches.name_pattern` before the first commit. If the user has uncommitted work on
  that base, ask before switching.
- Hooks must pass. Never `--no-verify`. If a hook fails, fix the cause and commit again.
- Record each commit: `etk run act --action commit --ref <sha> --exit 0 RUN`.

## 3. Push and integrate

- Push only the current branch to its upstream: `git push -u origin <branch>`. Never
  `--force`. If the branch has no upstream, or you would push to a protected or
  default branch while the model isn't trunk, ask first (L4).
- `integrate: pr`:
  - GitHub: `gh pr create --base <base> --title … --body …` (add `--draft`,
    reviewers and labels if the profile sets them).
  - GitLab: `glab mr create` with the same fields.
  - Bitbucket, or no signed-in CLI: print the compare URL for the user to open.
- `integrate: merge`: only with merge permission, using `merge.method`, after CI if
  `wait_ci` is set. Delete the branch only if `merge.delete_branch` is set.
- Tag only when a deploy target is `ci-on-tag` or the user asked. Pick the version
  per SemVer from the change.
- Record each step with `etk run act --action push|pr|merge|tag --target … --ref …
  --url … --exit <code> RUN`.

## 4. Deploy

- Skip if the profile has `deploy.none` or no targets, and say so.
- Run the target's `command` with
  `etk exec G7 --type runtime --run RUN -- <command>`. Then run its `verify` step the
  same way.
- Record it with `etk run act --action deploy --target <name> [--production] --exit
  <code> RUN`.
- On failure: stop, report, and show the rollback command. Run the rollback only if
  rollback was authorized too.

## 5. Close

Set G7 (PASS, FAIL, or NOT_APPLICABLE with the reason) and run `etk run check RUN`.
Then report with `quality/report-template.md`. The "Left for you" section lists only
the steps not done, and why: no permission, failed CI, skipped deploy.
