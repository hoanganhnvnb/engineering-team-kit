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
import os
import subprocess
import tempfile
import unittest
from unittest import mock
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

# R1-2: compound syntax, wrappers, find, and shells fed from stdin.
R1_2_COMPOUND = (
    [("dev", c, "block") for c in [
        "if true; then git push; fi",
        "if git push; then echo ok; fi",
        "for f in a b; do git push; done",
        "while true; do git push; done",
        "until false; do git push; done",
        "{ git push; }",
        "! git push",
        "if true; then echo a; else git push; fi",
        "if false; then echo a; elif true; then git push; fi",
        "timeout 5 git push",
        "timeout -s KILL 5 git push",
        "nice git push",
        "nice -n 5 git push",
        "ionice -c 3 git push",
        "stdbuf -oL git push",
        "caffeinate git push",
        "caffeinate -i git push",
        "setsid git push",
        "sudo -u root git push",
        "env -i FOO=1 git push",
        "find .. -delete",
        "find / -exec rm -rf {} +",
        "find ../x -exec rm -rf {} \\;",
        "find . -name x -execdir git push \\;",
        "find . -name x -ok git push \\;",
        "bash -c -- 'git push'",
        "bash -x -c 'git push'",
        "echo 'git push' | sh",
        "echo 'git push' | bash -s",
        "cat script.sh | sh",
        "bash <<< 'git push'",
        "bash",
        "sh <<EOF\ngit push\nEOF",
    ]]
    + [("rev", c, "block") for c in [
        "if true; then echo x > src/a.js; fi",
        "for f in a; do rm src/a.js; done",
        "timeout 5 sed -i s/a/b/ src/a.js",
        "nice -n 5 tee src/a.js",
        "find src -name '*.js' -delete",
        "find src -exec rm {} +",
        "find . -exec sed -i s/a/b/ {} +",
    ]]
    + [("qa", c, "block") for c in [
        "find tests -name '*.js' -delete",
        "timeout 5 sed -i s/a/b/ src/a.js",
    ]]
    + [("dev", c, "allow") for c in [
        "if true; then npm test; fi",
        "for f in a b; do echo $f; done",
        "while read l; do echo $l; done < list.txt",
        "{ echo a; echo b; } > /tmp/out.txt",
        "! git diff --quiet",
        "timeout 5 npm test",
        "timeout -s KILL 5 npm test",
        "nice -n 5 npm test",
        "caffeinate -i npm test",
        "sudo -u root npm test",
        "find . -name '*.pyc' -delete",
        "find . -name x -exec rm -rf {} +",
        "find src -name '*.js' -exec grep -l foo {} \\;",
        "bash scripts/run.sh",
        "bash -c 'npm test'",
        "bash <<< 'npm test'",
        "sh <<EOF\nnpm test\nEOF",
        "echo hi | cat",
    ]]
    + [("rev", c, "allow") for c in [
        "timeout 5 npm test",
        "if true; then npm test; fi",
        "find src -name '*.js' -exec grep -l foo {} \\;",
        "find /tmp/etk-scratch -delete",
        "for f in a b; do echo $f; done",
    ]]
)

# Process substitution bodies run as commands too.
PROCESS_SUBST = (
    [("dev", c, "block") for c in ["cat <(rm -rf /)", "cat <(git push)", "diff <(git push) x", "echo hi | tee >(git push)"]]
    + [("rev", "cat <(echo x > src/a.js)", "block")]
    + [("dev", "diff <(git show HEAD:a) <(git show HEAD~1:a)", "allow"),
       ("rev", "diff <(git show HEAD:a) <(git show HEAD~1:a)", "allow")]
)

# cd/pushd/popd forms whose target can't be known must make later paths strict.
CD_UNKNOWN = (
    [("dev", c, "block") for c in [
        "pushd +1 && rm -rf out",
        "pushd && rm -rf out",
        "pushd -n .. && rm -rf out",
        "pushd src && popd +0 && rm -rf out",
        "pushd src && pushd +1 && popd && rm -rf out",
        "cd -P .. && rm -rf other",
        "cd -e .. && rm -rf other",
        "find . -exec cd .. \\; ; rm -rf other",
        "CDPATH=/ cd src && rm -rf build",
        "export CDPATH=/etc; cd x && rm -rf y",
        "command cd .. && rm -rf other",
        "builtin cd .. && rm -rf other",
        "{ cd ..; rm -rf other; }",
        "if true; then cd ..; rm -rf other; fi",
        "true && cd .. && rm -rf other",
        "false || cd .. ; rm -rf other",
        "time cd .. && rm -rf other",
    ]]
    + [("rev", "pushd +1 && echo x > z", "block"), ("rev", "cd -P /tmp && echo x > z", "block")]
    + [("dev", c, "allow") for c in [
        "pushd src && popd && rm -rf build",
        "cd -L src && rm -rf build",
        "cd -- src && rm -rf build",
        "echo cd",
    ]]
)

# How a shell is told where its commands come from: -c script, stdin, or a file.
SHELL_ARGV = (
    [("dev", c, "block") for c in [
        "echo 'git push' | bash -es",
        "echo 'git push' | bash -s -- a",
        "echo 'git push' | bash -",
        "echo 'git push' | bash /dev/stdin",
        "echo 'git push' | bash /dev/fd/0",
        "echo 'git push' | sh -o pipefail",
        "echo 'git push' | bash -O extglob",
        "echo 'git push' | bash +x",
        "echo 'git push' | bash --norc",
        "bash -s script.sh",
        "bash -o pipefail",
        "bash --rcfile x -c 'git push'",
        "bash -o pipefail -c 'git push'",
        "bash +o pipefail -c 'git push'",
        "bash -O extglob -c 'git push'",
        "bash +x -c 'git push'",
        "bash -e -c -- 'git push'",
        "bash -o pipefail -c 'rm -rf /'",
        "bash -o pipefail -c",
        "bash -c -o",
        "source /dev/stdin",
    ]]
    + [("dev", c, "allow") for c in [
        "bash -o pipefail scripts/run.sh",
        "bash -O extglob -c 'npm test'",
        "bash +x scripts/run.sh",
        "bash -o pipefail -c 'npm test'",
        "bash --norc scripts/run.sh",
        "bash -e scripts/run.sh arg",
        "bash -o pipefail <<< 'npm test'",
        "source scripts/env.sh",
    ]]
)

# Wrapper options with values, env -S, unknown wrapper options, and more compound keywords.
WRAPPER_OPTS = (
    [("dev", c, "block") for c in [
        "env -S 'git push'",
        "env --split-string='git push'",
        "env -i -S 'git push'",
        "exec -a x git push",
        "time -f %e git push",
        "time -o /tmp/t git push",
        "time --format x git push",
        "timeout --weird 5 git push",
        "sudo --weird git push",
        "case x in a) git push;; esac",
        "function f { git push; }",
        "f() { git push; }; f",
        "coproc git push",
        "coproc NAME { git push; }",
        "select x in a b; do git push; done",
        "{ ! git push; }",
        "if ! git push; then echo no; fi",
    ]]
    + [("dev", c, "allow") for c in [
        "timeout --preserve-status 5 npm test",
        "env -i FOO=1 npm test",
        "env -S 'npm test'",
        "xargs -n1 echo",
        "echo a b | xargs -I {} echo {}",
        "nice -5 npm test",
        "sudo -E npm test",
        "case x in a) echo hi;; esac",
        "f() { echo hi; }; f",
        "function f { echo hi; }",
        "time -p npm test",
    ]]
)

# cd tracking must fail closed when the shell could end up somewhere else.
CD_FAIL_CLOSED = (
    [("dev", c, "block") for c in [
        "eval 'cd ..' && rm -rf other",
        "eval 'pushd ..'; rm -rf other",
        "source ./env.sh && rm -rf out",
        ". ./env.sh && rm -rf out",
        "export CDPATH=/etc && cd x && rm -rf y",
        "declare -x CDPATH=/etc; cd x && rm -rf y",
        "env CDPATH=/etc cd x && rm -rf y",
        "CDPATH+=:/etc cd x && rm -rf y",
        "cd a b && rm -rf other",
        "pushd a b && rm -rf x",
        "pushd src && popd x && rm -rf out",
        "cd src; rm -rf build",
        "cd src || rm -rf build",
        "pushd src; rm -rf build",
        "pushd src && pushd .. | cat; popd && rm -rf ../x",
    ]]
    + [("rev", "cd /tmp; echo y > z", "block")]
    + [("dev", c, "allow") for c in [
        "eval 'echo hi' | cat; rm -rf build",
        "cd src && rm -rf build",
        "pushd src && popd && rm -rf build",
    ]]
)

CASES = (BENIGN + BASELINE_BLOCKS + R1_1_CD + R1_2_COMPOUND + PROCESS_SUBST + CD_UNKNOWN + SHELL_ARGV
         + WRAPPER_OPTS + CD_FAIL_CLOSED)


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

    def test_inherited_cdpath_makes_relative_cd_unknown(self):
        with mock.patch.dict(os.environ, {"CDPATH": "/etc"}):
            self.assertEqual(self.verdict("dev", "cd src && rm -rf build"), "block")
            self.assertEqual(self.verdict("dev", "cd ./src && rm -rf build"), "allow")
            self.assertEqual(self.verdict("dev", "cd /tmp && rm -rf scratch"), "allow")

    def test_corpus(self):
        for role, cmd, want in CASES:
            with self.subTest(role=role, cmd=cmd):
                self.assertEqual(self.verdict(role, cmd), want)


if __name__ == "__main__":
    unittest.main()
