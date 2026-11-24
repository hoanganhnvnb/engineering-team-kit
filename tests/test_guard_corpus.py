"""Table-driven adversarial corpus for hooks/guard.py.

Each row is (role, command, verdict). `verdict` is "allow" or "block". Commands run
with the project fixture below as the hook's cwd. Every bypass found in review gets a
row here next to the benign commands that must keep working, so a fix can't quietly
turn into over-blocking.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("etk_guard", ROOT / "hooks" / "guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

ROLES = {
    "dev": "engineering-team:developer",
    "rev": "engineering-team:code-reviewer",
    "ux": "engineering-team:ux-reviewer",
    "qa": "engineering-team:qa-engineer",
    "scout": "engineering-team:scout",
    "tw": "engineering-team:tech-writer",
}
RO = ("rev", "ux", "scout", "tw")


def each(roles, cmd, verdict):
    return [(r, cmd, verdict) for r in roles]


# Commands every role may run.
BENIGN = (
    each(ROLES, "git status", "allow")
    + each(ROLES, "git diff main...HEAD", "allow")
    + each(ROLES, "git log --oneline -5", "allow")
    + each(ROLES, "grep -rn 'git push' src", "allow")
    + each(ROLES, "ls -la | head", "allow")
    + each(ROLES, "npm test 2>&1 | tail -20", "allow")
    + each(["dev", "rev", "ux", "scout", "tw"], "npm test > /dev/null", "allow")
    + each(ROLES, "echo hi > /tmp/etk-notes.txt", "allow")
    + each(ROLES, "cat src/a.js", "allow")
    + each(ROLES, "python3 -m pytest -q", "allow")
    + each(ROLES, "npx eslint src", "allow")
    + each(ROLES, "npx prettier --check src", "allow")
    + each(ROLES, "black --check .", "allow")
    + each(ROLES, "git log --grep='git restore'", "allow")
    + [
        ("dev", "git checkout -b etk/feature", "allow"),
        ("dev", "git commit -m 'handle git push errors'", "allow"),
        ("dev", "rm -rf node_modules/.cache", "allow"),
        ("dev", "rm -rf build", "allow"),
        ("dev", "echo x > src/a.js", "allow"),
        ("dev", "FOO=1 npm run build", "allow"),
        ("dev", "docker build -t img .", "allow"),
        ("dev", "kubectl get pods", "allow"),
        ("dev", "terraform plan", "allow"),
        ("dev", "helm list", "allow"),
        ("dev", "gh pr view 12", "allow"),
        ("dev", "shopify theme dev", "allow"),
        ("dev", "git add src/a.js && git commit -m 'Add parsing'", "allow"),
        ("qa", "echo y > tests/new.test.js", "allow"),
        ("qa", "npm test > /tmp/qa-out.txt", "allow"),
        ("qa", "cp src/a.js tests/fresh-copy.test.js", "allow"),
        ("qa", "git worktree add ../base HEAD", "allow"),
        ("tw", "git diff --stat", "allow"),
    ]
)

# Baseline blocks that already held before the review; they must not regress.
BASELINE_BLOCKS = (
    each(ROLES, "git push", "block")
    + each(ROLES, "git push --force origin x", "block")
    + each(ROLES, "git -C . push", "block")
    + each(ROLES, "git reset --hard HEAD~1", "block")
    + each(ROLES, "git stash", "block")
    + each(ROLES, "npm publish", "block")
    + each(ROLES, "echo SECRET=1 >> .env", "block")
    + each(ROLES, "bash -c 'git push'", "block")
    + each(ROLES, "rm -rf /etc/x", "block")
    + each(RO, "echo x > src/a.js", "block")
    + each(RO, "sed -i s/a/b/ src/a.js", "block")
    + [("qa", "echo y > src/a.js", "block"), ("qa", "sed -i s/a/b/ src/a.js", "block")]
)

# R1-1: `cd`, `pushd` and `git -C` change where later parts of the same command run.
R1_1_CD = (
    [("dev", "cd .. && rm -rf other", "block"),
     ("dev", "cd / && rm -rf home", "block"),
     ("dev", "pushd .. && rm -rf other", "block"),
     ("dev", "cd src; cd ../.. && rm -rf other", "block"),
     ("dev", "cd $X && rm -rf out", "block"),
     ("dev", "cd - && rm -rf out", "block"),
     ("dev", "cd /tmp && git push", "block"),
     ("dev", "(cd .. && rm -rf other)", "block"),
     ("dev", "cd src && rm -rf build", "allow"),
     ("dev", "cd /tmp && rm -rf scratch", "allow"),
     ("dev", "cd src && npm test", "allow"),
     ("dev", "(cd .. && ls); rm -rf build", "allow"),
     ("dev", "cd .. | cat; rm -rf build", "allow"),
     ("rev", "cd /tmp && echo x > z", "allow"),
     ("rev", "cd src && echo x > z", "block"),
     ("rev", "cd .. && echo x > z", "block"),
     ("rev", "cd $X && echo x > z", "block"),
     ("rev", "(cd /tmp && echo x > z); echo y > src/a.js", "block"),
     ("rev", "pushd /tmp && echo x > z && popd && echo y > z", "block"),
     ("qa", "cd tests && echo x > existing.test.js", "block"),
     ("qa", "cd tests && echo x > fresh.test.js", "allow"),
     ("qa", "cd src && echo y > a.js", "block"),
     ("scout", "cd /tmp && echo x > z", "allow")]
)

CASES = BENIGN + BASELINE_BLOCKS + R1_1_CD


def make_project(base: Path) -> Path:
    def run(*args):
        subprocess.run(args, cwd=base, check=True, capture_output=True)

    base.mkdir(parents=True, exist_ok=True)
    run("git", "init", "-q", "-b", "main")
    (base / "src").mkdir()
    (base / "tests").mkdir()
    (base / "src" / "a.js").write_text("a\n")
    (base / "tests" / "existing.test.js").write_text("t\n")
    (base / "README.md").write_text("r\n")
    run("git", "add", "-A")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    run("git", "branch", "feature")
    return base


class GuardCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Outside the system temp dir, which the guard treats as scratch space.
        cls.tmp = tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix=".corpus-")
        cls.project = make_project(Path(cls.tmp.name) / "proj")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def verdict(self, role, cmd):
        data = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.project),
                "agent_type": ROLES[role]}
        with contextlib.redirect_stderr(io.StringIO()):
            return "block" if guard.decide(data) is not None else "allow"

    def test_corpus(self):
        for role, cmd, want in CASES:
            with self.subTest(role=role, cmd=cmd):
                self.assertEqual(self.verdict(role, cmd), want)


if __name__ == "__main__":
    unittest.main()
