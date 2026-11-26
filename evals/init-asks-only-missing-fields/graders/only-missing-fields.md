---
type: llm
---
The repository is a git repo with a GitHub origin, Conventional Commits history and an
`npm test` script, so `profile detect` and `discover` already answer the VCS, the host, the
commit style and the test command. PASS only if every question the agent put to the user
(through AskUserQuestion or in plain text) is about something detect could not know: how
changes are integrated (PR or merge), commit and push automatically or ask, the branch
model, the deploy target, or the project-start notes (docs language, how many
subagents at once, things that must never appear in commits). At least one release or deploy
question must have been asked, and no more than 2 batches of up to 4 questions for the
profile fields. FAIL if it asked whether this is a git repository, which host it uses, which
commit style the history follows, which language commit messages use (detect reads it from
the history and `commit.language` is saved from it), or which command runs the tests.
