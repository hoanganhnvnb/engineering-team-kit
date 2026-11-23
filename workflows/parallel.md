# Large mode: parallel workstreams

Only parallelize when the pieces are independent. Parallel agents on coupled
code produce merge conflicts and inconsistent designs, and fixing that costs more
than they saved. Trust comes before parallelism: if one developer + review
isn't producing clean results on this codebase yet, more developers won't help.

## 1. Design first (Lead)

Write into the run dir (`.etk/runs/<id>/plan.md`), short:

- ACs (also in the ledger)
- **Contract**: the interfaces between pieces: function signatures, API request/response
  shapes, DB schema, event payloads. Commit-ready, not hand-wavy.
- **Workstreams**: for each: goal, files it owns (disjoint from the others), files it
  may read, tests it must add, which contract parts it implements or consumes.
- Order: which can run in parallel, which depend on others.

If the contract itself is code (types, schema, interface file), have one developer
(or the Lead) land it first, then branch the parallel work from there.

## 2. Isolate

- Spawn each parallel developer with the Agent tool's `isolation: "worktree"`.
  Each gets its own checkout and branch from the current HEAD.
- **Uncommitted changes in the main checkout are not in the worktree.** If the work
  depends on them, either do that stream in the main checkout (sequentially) or ask
  the user before committing anything.
- Without git or worktree support: run workstreams sequentially in the main checkout.

## 3. Integrate (Lead)

Each worktree developer commits on its own branch and reports the branch name.
Bring the changes into the main checkout **without** creating commits on the user's
branch (unless the user allowed commits), and without touching the index:

```bash
git diff HEAD...<branch> --binary > .etk/runs/<id>/<stream>.patch
git diff --name-only HEAD...<branch>        # make sure none of these have uncommitted user edits:
git diff --quiet -- <those paths>           #   non-zero exit → stop and ask the user
git apply --check .etk/runs/<id>/<stream>.patch && git apply .etk/runs/<id>/<stream>.patch
```

Plain `git apply` changes only the working tree. If it doesn't apply cleanly, the
breakdown had overlap: apply by hand (read the patch, edit the files), note it in the
ledger. Avoid `--3way` here: it stages files in the user's index.

Do it one stream at a time. Run the tests after each.

Then clean up worktrees you created (`git worktree remove <path>`, `git branch -D
<branch>` for the temporary branch only, after its changes are applied and verified).
That cleanup is the Lead's job. The guard blocks subagents from deleting branches.

## 4. Verify as a whole

Review and QA run on the **integrated** diff, not per stream. Integration bugs
live between the pieces.
