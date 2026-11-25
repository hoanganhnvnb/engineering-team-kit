# Contributing

Thanks for helping. Issues and pull requests are welcome. For anything bigger than a
small fix, open an issue first so we can agree on the approach.

## Setup

Requirements: Claude Code 2.1.329 or newer and Python 3.12+. Node is optional; it is
only used by the e2e fixtures.

```bash
git clone https://github.com/hoanganhnvnb/engineering-team-kit
cd engineering-team-kit
bash scripts/selftest.sh        # plugin validation + all unit and structure tests
claude --plugin-dir .           # try your changes in a session
```

Run the tests from a clone outside `/tmp`, because the guard treats the system temp
directory as scratch space. `tests/e2e/run.py` and `evals/run.sh` spend real model
tokens. Run them when you change a skill or an agent, not on every commit.

## Changes

- Keep each change small and focused. Add a test for new behaviour in `tests/`.
- Skills, agents and workflows are prompts, so every line costs tokens on every run.
  Keep them short, and put detail in the reference file the step reads.
- The guard (`hooks/guard.py`) is a seatbelt. If you add a rule, add rows to
  `tests/test_guard_corpus.py` for both the blocked and the allowed case.
- Update `CHANGELOG.md` under the next version.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):
`type(scope): description`, in the imperative and lowercase, with no trailing period.
Make one logical change per commit, and use the body to explain why. Don't add
AI co-author trailers. Details: [conventions/git.md](conventions/git.md).

## Pull requests

Describe what changed and why, and how you tested it (commands and results). Link
the issue if there is one. CI runs the same `scripts/selftest.sh` on Linux and macOS.
