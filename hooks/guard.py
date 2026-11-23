#!/usr/bin/env python3
"""PreToolUse guard for ETK subagents.

Only acts when the tool call comes from one of this plugin's agents
(`agent_type` starts with "engineering-team:"). The main session and every
other agent are left alone: the user's own permission settings already cover
them, and a plugin should not change how unrelated sessions behave.

Commands are split into segments (&&, ||, ;, |, newlines) and each segment is
judged by the program it actually runs, so `grep "git push" docs/` or a commit
message mentioning `rebase` is fine, while `git -C . push` is not.

Blocks (exit 2, reason on stderr so the agent can adapt):
  - pushing, merging PRs, publishing, deploying, infra changes
  - discarding work: reset --hard, clean -f, checkout/restore of paths, switch -f,
    stash, branch -D, worktree remove --force
  - history rewrites: rebase, commit --amend, filter-branch
  - recursive rm outside the project
  - secret files: staging, writing, or redirecting into .env / keys
  - read-only roles (code-reviewer, ux-reviewer) changing files via the shell;
    qa-engineer changing existing files (it may only create new ones)

This is a seatbelt, not a sandbox: it stops the accidents agents actually make.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

PREFIX = "engineering-team:"
READ_ONLY_ROLES = {"code-reviewer", "ux-reviewer"}

SECRET_NAME = re.compile(
    r"(^|/)(\.env(\.[\w-]+)?|id_rsa|id_ed25519|[^/]*\.pem|[^/]*\.p12|[^/]*\.key|credentials\.json"
    r"|service-account[^/]*\.json|\.npmrc|\.pypirc)$"
)
SECRET_OK = re.compile(r"\.(example|sample|template|dist)$")

GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec", "xargs"}


class Blocked(Exception):
    pass


def is_secret(path: str) -> bool:
    p = path.strip().strip("'\"")
    return bool(SECRET_NAME.search(p)) and not SECRET_OK.search(p)


def strip_heredocs(cmd: str) -> str:
    """Drop heredoc bodies: their text is data, not commands."""
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        i += 1
        if m:
            end = m.group(1)
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1
    return "\n".join(out)


def segments(cmd: str) -> list[list[str]]:
    text = strip_heredocs(cmd).replace("\n", " ; ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|<>()")
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        tokens = text.split()
    segs, cur = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|()"):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def program(words: list[str]) -> list[str]:
    """Skip env assignments and wrappers like sudo/env so we see the real program."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"^\w+=", w) or w in WRAPPERS or (i > 0 and words[i - 1] in {"env", "sudo"} and w.startswith("-")):
            i += 1
            continue
        break
    return words[i:]


def redirect_targets(words: list[str]) -> list[str]:
    return [words[i + 1] for i, w in enumerate(words) if w in {">", ">>", ">|"} and i + 1 < len(words)]


def inside(path: str, base: str) -> bool:
    real, base = os.path.realpath(path), os.path.realpath(base)
    return real == base or real.startswith(base + os.sep)


def temp_roots() -> list[str]:
    roots = {"/tmp", "/private/tmp", "/var/folders", "/private/var/folders", tempfile.gettempdir()}
    return [os.path.realpath(r) for r in roots]


def in_temp(path: str, cwd: str) -> bool:
    p = path if os.path.isabs(path) else os.path.join(cwd, path)
    return any(inside(p, t) for t in temp_roots())


def untracked_secrets(cwd: str) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=cwd,
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [f for f in out.splitlines() if is_secret(f)]


def check_git(args: list[str], cwd: str) -> None:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            cwd = os.path.join(cwd, args[i + 1])
        i += 2 if args[i] in GIT_GLOBAL_WITH_ARG else 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]
    flags = set(rest)

    def has(*names: str) -> bool:
        return any(n in flags for n in names)

    def short(letter: str) -> bool:
        return any(re.match(rf"^-[a-zA-Z]*{letter}", w) and not w.startswith("--") for w in rest)

    if sub == "push":
        raise Blocked("pushing is up to the user; leave commits local")
    if sub == "reset" and has("--hard", "--merge", "--keep"):
        raise Blocked("reset --hard discards work; ask the Lead instead")
    if sub == "clean" and (short("f") or has("--force")):
        raise Blocked("git clean deletes untracked files that may be the user's")
    if sub == "checkout" and ("--" in rest or "." in rest or has("-f", "--force", "-p", "--patch")):
        raise Blocked("checkout of paths discards uncommitted changes")
    if sub == "restore" and not (has("--staged", "-S") and not has("--worktree", "-W")):
        raise Blocked("git restore discards uncommitted changes")
    if sub == "switch" and has("-f", "--force", "--discard-changes"):
        raise Blocked("switch --force discards uncommitted changes")
    if sub == "stash" and not (rest and rest[0] in {"list", "show"}):
        raise Blocked("git stash rewrites the working tree the user is using; use a temporary worktree")
    if sub == "branch" and (has("-D") or (has("-d", "--delete") and has("-f", "--force"))):
        raise Blocked("force-deleting a branch can lose commits; leave cleanup to the Lead")
    if sub == "worktree" and rest[:1] == ["remove"] and has("-f", "--force"):
        raise Blocked("force-removing a worktree discards its changes; leave cleanup to the Lead")
    if sub == "rebase":
        raise Blocked("history rewrites are the Lead's call, not a subagent's")
    if sub == "commit" and has("--amend"):
        raise Blocked("amending rewrites history; make a new commit")
    if sub in {"filter-branch", "filter-repo"} or (sub == "update-ref" and has("-d")):
        raise Blocked("history rewrites are not allowed here")
    if sub in {"add", "commit"}:
        for w in rest:
            if not w.startswith("-") and is_secret(w):
                raise Blocked(f"`{w}` looks like a secret file and must not be committed")
        if sub == "add" and (has("-A", "--all", ".") or short("A")):
            secrets = untracked_secrets(cwd)
            if secrets:
                raise Blocked(f"`git add -A/.` would stage secret-looking files {secrets[:3]}; add paths explicitly")


def check_rm(args: list[str], cwd: str) -> None:
    opts = [a for a in args if a.startswith("-")]
    recursive = any("r" in o.lower() for o in opts if not o.startswith("--")) or "--recursive" in opts
    if not recursive:
        return
    for target in (a for a in args if not a.startswith("-")):
        if target in {"/", "~", "*", "./*", ".", ".."} or target.startswith(("~", "$HOME", "${HOME}")):
            raise Blocked(f"`rm -r {target}` is too broad")
        path = target if os.path.isabs(target) else os.path.join(cwd, target)
        if (inside(path, cwd) and os.path.realpath(path) != os.path.realpath(cwd)) or in_temp(path, cwd):
            continue
        raise Blocked(f"`rm -r {target}` is outside the project")


DEPLOY = [
    (r"^(npm|pnpm|yarn|bun) publish\b|^cargo publish\b|^twine upload\b|^gem push\b", "publishing packages needs explicit user approval"),
    (r"^shopify (app (deploy|release)|theme (push|publish|delete))\b", "deploying to a Shopify store needs explicit user approval"),
    (r"^vercel\b.*--prod|^netlify deploy\b.*--prod|^fly deploy\b|^firebase deploy\b|^(serverless|sls) deploy\b", "deploys need explicit user approval"),
    (r"^kubectl (apply|delete|replace|rollout)\b|^helm (install|upgrade|uninstall)\b|^terraform (apply|destroy)\b|^pulumi (up|destroy)\b", "infrastructure changes need explicit user approval"),
    (r"^docker push\b", "pushing images needs explicit user approval"),
    (r"^gh (pr merge|release create|repo delete)\b", "merging/releasing needs explicit user approval"),
    (r"^(psql|mysql|sqlite3|mongosh)\b.*\b(drop\s+(table|database)|truncate\s+table|dropdatabase)", "destructive SQL needs explicit user approval"),
]
SHELL_WRITERS = {"rm", "mv", "cp", "tee", "touch", "truncate", "dd", "chmod", "chown", "ln", "patch", "install"}
SAFE_SINKS = {"/dev/null", "/dev/stderr", "/dev/stdout"}


def check_bash(cmd: str, cwd: str, role: str) -> None:
    read_only = role in READ_ONLY_ROLES
    for seg in segments(cmd):
        words = program(seg)
        if not words:
            continue
        prog = os.path.basename(words[0])
        line = " ".join([prog] + words[1:])
        for pattern, reason in DEPLOY:
            if re.search(pattern, line, re.I):
                raise Blocked(reason)
        if prog == "git":
            check_git(words[1:], cwd)
        if prog == "rm":
            check_rm(words[1:], cwd)
        for target in redirect_targets(seg):
            if is_secret(target):
                raise Blocked(f"writing to `{target}` (looks like a secrets file)")
            if read_only and target not in SAFE_SINKS and not in_temp(target, cwd):
                raise Blocked(f"{role} is read-only; it reports findings and the developer changes files")
        if read_only:
            targets = [w for w in words[1:] if not w.startswith("-")]
            writes = prog in SHELL_WRITERS and not (targets and all(in_temp(t, cwd) for t in targets[-1:]))
            if writes or (prog == "sed" and any(w.startswith("-i") for w in words[1:])) \
                    or (prog == "git" and any(w in {"add", "commit", "apply", "mv", "rm", "checkout", "restore"} for w in words[1:3])):
                raise Blocked(f"{role} is read-only; it reports findings and the developer changes files")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    agent = str(data.get("agent_type") or "")
    if not agent.startswith(PREFIX):
        return 0
    role = agent[len(PREFIX):]
    tool = data.get("tool_name")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    try:
        if tool == "Bash":
            check_bash(str(inp.get("command", "")), cwd, role)
        elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
            path = str(inp.get("file_path") or inp.get("notebook_path") or "")
            if is_secret(path):
                raise Blocked(f"writing `{path}` (looks like a secrets file); edit the .example version instead")
            if role == "qa-engineer" and (tool != "Write" or os.path.exists(path)):
                raise Blocked("qa-engineer may only create new test files, not change existing ones")
    except Blocked as b:
        print(f"[engineering-team guard] blocked: {b}. If this is really needed, stop and report it "
              f"to the Lead so the user can decide.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
