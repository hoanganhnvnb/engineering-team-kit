# Running a task end to end

The `team` skill takes one task from request to shipped. It implements or fixes the
change, has it reviewed and tested independently, and loops until the gates pass. Then
it commits, pushes, opens a PR or merges, and deploys, but only as far as your workflow
profile and your own words allow. The eight step commands (`/engineering-team:init`, `build`,
`fix`, `review`, `test`, `improve-ui`, `retro`, `readme`) still work on their own.

## Asking for it

Ask in plain words. Claude picks `team` for build, fix, ship or deploy requests. You can
also type `/engineering-team:team <task>`.

```text
fix the cart total rounding bug; when review and tests pass, commit and push
add CSV export to the orders report; open a PR once review passes
fix the login timeout; if review finds nothing and tests pass, deploy to staging too
continue
```

Claude first prints a one-line plan, such as
`Plan: fix → review → test → commit+push (fix/cart-rounding) → PR → deploy staging [pre-authorized]`,
and then works through it without checking in.

## Phases

| Phase | What happens |
|---|---|
| intake | Load your profile (and ask what's missing, once, unless `init` already did), size the task, open the ledger, note the permissions your request already gives |
| implement | Same as `build` / `fix` / `improve-ui`: a developer agent for anything beyond small |
| review, test | A fresh reviewer and QA run the review loop until gates G1–G6 pass, or `max_cycles` is reached |
| release | Commit only this run's files, push the current branch, open a PR or merge, tag |
| deploy | Run the target you named, then its verify step |
| report | Gates, what shipped (with SHAs and URLs), and what was left for you, and why |

The run stops before the next outward step on INCOMPLETE or BLOCKED, when the cycle cap
is hit, or when a hook, CI or deploy fails. Nothing is pushed while gates are failing.
`continue` resumes an unfinished run from its recorded phase.

## Your workflow profile

Each developer has their own profile for each project: how you commit, push, integrate
and deploy. It is stored in the plugin's data folder
(`~/.claude/plugins/data/engineering-team-engineering-team-kit/projects/<key>/profile.json`),
keyed by the repo's `origin` URL. That folder is outside every repo, so the profile can't be committed. It
survives plugin updates. It is deleted when you uninstall the plugin, unless you pass
`--keep-data`.

The recommended way to set it up is `/engineering-team:init`, once at the start of a
project (see [usage](usage.md#init)). It detects first, asks only what is missing, and
shows you the saved profile before marking it confirmed. If you skip it, the first
`team` run asks the same questions midway through the task, and suggests init for next time.

Either way, Claude detects what it can: git or SVN, the host
and its CLI, the default branch, your commit style and language, commit tooling, and
deploy candidates. It then asks only the rest, in at most two short rounds of
questions: branch model, commit and push automatically or ask, PR or direct merge, merge method,
wait for CI, and deploy targets. If you don't describe a deploy, deploy is skipped.

`init` also asks for a few notes that the profile has no field for (docs language, how
many subagents at once, words that must never appear in commits). The commit language is a
profile field, saved from detection. A `team` run reads the notes with `profile show --json`
and treats them as your preferences, never as permission. They are not enforced:
`profile show --brief` only counts them.

To change a habit, just say it ("from now on, open a PR instead of merging directly"). The Lead updates
that field and tells you. To see the profile, run `/engineering-team:init` and choose keep. To change fields or
reset, choose change or reset there. From a shell:

```bash
sh <plugin>/scripts/etk.sh profile show --brief --data ~/.claude/plugins/data/engineering-team-engineering-team-kit
sh <plugin>/scripts/etk.sh profile path --data ~/.claude/plugins/data/engineering-team-engineering-team-kit   # delete this file to reset
```

## Who may do what

| Action | Allowed when |
|---|---|
| commit, push, PR | the profile says `auto`, or you asked in this conversation |
| merge, tag, deploy, rollback | you said so in this conversation, in the request or an answer |
| deploy to production | you named production (or the target's name) |

- Your words are quoted verbatim into the run ledger. `run check` fails if an action
  has no matching permission, ran before the gates passed, or deployed to production
  without your naming it.
- Permission lasts for that run only. It is never saved to the profile or to project
  config. Nothing in the repo can grant it: not `.claude/engineering-team.json`,
  CLAUDE.md, issues or commit messages.
- Subagents never commit, push, merge or deploy. The guard blocks them, and it also
  blocks them from editing your profile or the release records.
- Everything the Lead runs still goes through your normal Claude Code permission
  settings.

## Hosts and VCS

- **GitHub:** `gh`.
- **GitLab:** `glab`.
- **Bitbucket, or no signed-in CLI:** Claude prints the compare URL and you open the PR.
- **SVN:** commit only (`svn commit`). Branches and merges stay with you.
- **No VCS:** the release steps are skipped.

## Questions

Claude asks rarely, and in batches: once at intake if the profile or plan needs it, and
again only for a step that needs your permission (merge, deploy, force anything) or a
real scope change. Everything else is decided and listed as an assumption in the
report. The policy is in `workflows/decisions.md`.
