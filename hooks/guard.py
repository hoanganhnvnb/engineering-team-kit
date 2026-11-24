#!/usr/bin/env python3
"""PreToolUse guard for ETK subagents.

Only acts when the tool call comes from one of this plugin's agents
(`agent_type` starts with "engineering-team:"). The main session and every
other agent are left alone: the user's own permission settings already cover
them, and a plugin should not change how unrelated sessions behave.

Commands are split into segments (&&, ||, ;, |, newlines) and each segment is
judged by the program it actually runs, so `grep "git push" docs/` or a commit
message mentioning `rebase` is fine, while `git -C . push` is not. Nested shells
(`bash -c`, `eval`, `$(...)`, backticks) are checked recursively, and heredoc
bodies are checked line by line like any other command text (fail closed).

Blocks (exit 2, reason on stderr so the agent can adapt):
  - pushing, merging PRs, publishing, deploying, infra changes
  - discarding work: reset --hard, clean -f, checkout/restore of paths, switch -f,
    stash, branch -D, worktree remove --force
  - history rewrites: rebase, commit --amend, filter-branch
  - recursive rm outside the project
  - secret files: staging, writing, or redirecting into .env / keys
  - read-only roles (code-reviewer, ux-reviewer, scout) changing files at all, and the
    tech-writer writing anything but Markdown (or writing through the shell);
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
READ_ONLY_ROLES = {"code-reviewer", "ux-reviewer", "scout"}
# Writes files only through Write/Edit, and only Markdown. No shell writes either.
DOCS_ONLY_ROLES = {"tech-writer"}
# Markdown that steers agents is config, not docs: the tech-writer doesn't touch it.
INSTRUCTION_MD = re.compile(r"(^|/)(CLAUDE(\.local)?|AGENTS|SKILL)\.md$|(^|/)\.claude/|(^|/)\.github/copilot-instructions\.md$", re.I)
# Interpreters running inline code, and markers of that code writing files.
INLINE_CODE = re.compile(r"^(python[\d.]*|pypy[\d.]*|node(js)?|ruby[\d.]*|perl[\d.]*|php[\d.]*|deno|bun|osascript)$")
WRITE_CODE = re.compile(
    r"writeFile|appendFile|writeSync|createWriteStream|copyFile|rmSync|unlinkSync|renameSync|"
    r"\.write_(text|bytes)\(|open\([^)]*,\s*(mode\s*=\s*)?['\"](r\+|[wax])|"
    r"os\.(remove|unlink|rename|replace|system|popen)|shutil\.|subprocess|child_process|"
    r"file_put_contents|File\.write|open\s*\(?\s*\w+\s*,\s*['\"]\s*\+?>|print\s*>\s*['\"]", re.I)
# Flags that make an interpreter run code given on the command line, or read it from stdin.
INLINE_FLAG = re.compile(r"^(-[a-zA-Z]*[ceEpr]|--eval|--print|-)$")
# perl/ruby -i (in place): `-i`, `-i.bak`, `-pi`, `-pie`; not `-Ilib`, `-Mstrict`, `-mstrict`.
PERL_INPLACE = re.compile(r"^-[pnlawsTtWXU0-9]*i")  # only switches that take no argument may precede i
FORMATTER_WRITE = {("prettier", "-w"), ("gofmt", "-w"), ("rubocop", "-a"), ("rubocop", "-A"), ("standardrb", "--fix"),
                   ("sed", "--in-place"), ("black", None), ("ruff", "format"), ("isort", None), ("rustfmt", None),
                   ("clang-format", "-i"), ("php-cs-fixer", "fix")}

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


SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
MAX_DEPTH = 4


def substitutions(cmd: str) -> list[str]:
    """Bodies of $(...) and `...` so they get checked as commands too."""
    out = re.findall(r"`([^`]*)`", cmd)
    i = 0
    while True:
        start = cmd.find("$(", i)
        if start < 0:
            break
        depth, j = 1, start + 2
        while j < len(cmd) and depth:
            depth += {"(": 1, ")": -1}.get(cmd[j], 0)
            j += 1
        out.append(cmd[start + 2:j - 1])
        i = start + 2
    return out


def segments(cmd: str) -> list[list[str]]:
    text = cmd.replace("\n", " ; ")
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
        base = os.path.basename(w)
        if re.match(r"^\w+=", w) or base in WRAPPERS or (i > 0 and os.path.basename(words[i - 1]) in {"env", "sudo"}
                                                         and w.startswith("-")):
            i += 1
            continue
        break
    return words[i:]


def redirect_targets(words: list[str]) -> list[str]:
    """Targets of >, >>, >|, &>, &>>, N> (fd duplications like 2>&1 are skipped)."""
    out = []
    for i, w in enumerate(words[:-1]):
        if ">" in w and set(w) <= set("<>&|"):
            target = words[i + 1]
            if w.endswith("&") and (target.isdigit() or target == "-"):
                continue  # fd duplication like 2>&1 or >&-
            out.append(target)
    return out


def inside(path: str, base: str) -> bool:
    real, base = os.path.realpath(path), os.path.realpath(base)
    return real == base or real.startswith(base + os.sep)


def temp_roots() -> list[str]:
    roots = {"/tmp", "/private/tmp", "/var/folders", "/private/var/folders", tempfile.gettempdir()}
    return [os.path.realpath(r) for r in roots]


def in_temp(path: str, cwd: str) -> bool:
    p = path if os.path.isabs(path) else os.path.join(cwd, path)
    return any(inside(p, t) for t in temp_roots())


def scratch(path: str, cwd: str) -> bool:
    """A temp path that is not part of the project (projects can live under /tmp too)."""
    p = path if os.path.isabs(path) else os.path.join(cwd, path)
    return in_temp(p, cwd) and not inside(p, cwd)


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
        if target in {"/", "~", "*", "./*", ".", ".."} or target.startswith("~"):
            raise Blocked(f"`rm -r {target}` is too broad")
        if "$" in target or "`" in target:
            raise Blocked(f"`rm -r {target}` uses a variable; spell the path out so it can be checked")
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


def write_operands(prog: str, args: list[str]) -> list[str]:
    """Paths a shell-writer command would modify."""
    ops = [a for a in args if not a.startswith("-")]
    if prog == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if prog in {"cp", "install", "ln", "mv"}:
        for i, a in enumerate(args):
            d = None
            if a in {"-t", "--target-directory"} and i + 1 < len(args):
                d = args[i + 1]
            elif a.startswith("--target-directory="):
                d = a.split("=", 1)[1]
            elif (a.startswith("-") and not a.startswith("--") and "t" in a and a != "-t") \
                    or (a.startswith("--t") and a != "--target-directory"):
                # attached (-t.), clustered (-rt) or abbreviated (--target) forms: fail closed
                raise Blocked(f"`{prog} {a}` can't be checked; use `-t DIR` or spell the destination out")
            if d is not None:
                srcs = [x for x in ops if x != d]
                written = [d] + [os.path.join(d, os.path.basename(s)) for s in srcs]
                return written + (srcs if prog == "mv" else [])
        if prog != "mv":
            return ops[-1:]  # only the destination is written
    return ops  # rm, mv (sources disappear too), chmod, chown, touch, truncate, tee, patch


def writes_existing(target: str, cwd: str) -> bool:
    path = target if os.path.isabs(target) else os.path.join(cwd, target)
    return os.path.exists(path) and not scratch(path, cwd)


def real_tool(words: list[str]) -> list[str]:
    """See through package-runner wrappers: `npx prettier -w` is prettier."""
    prog = os.path.basename(words[0]) if words else ""
    rest = words[1:]
    if prog in {"pnpm", "yarn", "npm"} and rest and rest[0] in {"exec", "dlx", "x"}:
        rest = rest[1:]
    elif prog not in {"npx", "bunx", "pnpx"}:
        return words
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    return rest or words


def runs_inline_code(words: list[str]) -> bool:
    """An interpreter given code inline (-c/-e/--eval) or on stdin (`-`, or no arguments at all)."""
    if not words or not INLINE_CODE.match(os.path.basename(words[0])):
        return False
    args = words[1:]
    if args and all(a in {"--version", "-v", "-V", "--help", "-h"} for a in args):
        return False
    return not args or any(INLINE_FLAG.match(a) for a in args)


def check_bash(cmd: str, cwd: str, role: str, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise Blocked("command nests shells too deeply to check")
    for inner in substitutions(cmd):
        check_bash(inner, cwd, role, depth + 1)
    read_only = role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES
    create_only = role == "qa-engineer"
    if read_only and WRITE_CODE.search(cmd) and any(runs_inline_code(program(seg)) for seg in segments(cmd)):
        raise Blocked(f"{role} is read-only; inline code that writes files isn't allowed")
    for seg in segments(cmd):
        words = program(seg)
        if not words:
            continue
        prog = os.path.basename(words[0])
        if prog == "eval":
            check_bash(" ".join(words[1:]), cwd, role, depth + 1)
            continue
        if prog in SHELLS:
            idx = next((i for i, w in enumerate(words[1:], 1) if re.match(r"^-[a-zA-Z]*c[a-zA-Z]*$", w)), None)
            if idx is not None:
                if idx + 1 >= len(words):
                    raise Blocked(f"`{prog} -c` without a script can't be checked")
                check_bash(words[idx + 1], cwd, role, depth + 1)
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
            if read_only and target not in SAFE_SINKS and not scratch(target, cwd):
                raise Blocked(f"{role} is read-only; it reports findings and the developer changes files")
        if create_only:
            targets = [w for w in words[1:] if not w.startswith("-")]
            if any(writes_existing(t, cwd) for t in redirect_targets(seg)) \
                    or (prog in SHELL_WRITERS and any(writes_existing(t, cwd) for t in write_operands(prog, words[1:]))) \
                    or (prog == "sed" and any(w.startswith("-i") for w in words[1:])):
                raise Blocked("qa-engineer may only create new files, not change existing ones")
        if read_only:
            words = real_tool(words)
            prog = os.path.basename(words[0])
            ops = write_operands(prog, words[1:])
            writes = prog in SHELL_WRITERS and not (ops and all(scratch(t, cwd) for t in ops))
            rest = [w for w in words[1:] if not w.startswith("-") and w not in {"exec", "dlx", "run"}]
            tool = os.path.basename(rest[0]) if prog in {"npx", "pnpx", "bunx", "pnpm", "yarn", "uvx", "pipx"} and rest else prog
            inplace = (prog == "sed" and any(w.startswith("-i") or w.startswith("--in-place") for w in words[1:])) \
                or (re.match(r"^(perl|ruby)[\d.]*$", prog) and any(PERL_INPLACE.match(w) for w in words[1:])) \
                or any(w in {"--write", "--fix"} or w.startswith(("--write=", "--fix=")) for w in words[1:]) \
                or (any(tool == name and (flag is None or flag in words[1:]) for name, flag in FORMATTER_WRITE)
                    and not any(w in {"--check", "--diff", "--check-only", "-l", "--list-different"} for w in words[1:]))
            if writes or inplace \
                    or (prog == "git" and any(w in {"add", "commit", "apply", "mv", "rm", "checkout", "restore"} for w in words[1:3])):
                raise Blocked(f"{role} is read-only; it reports findings and the developer changes files")


def decide(data: dict) -> str | None:
    """Reason to block this tool call, or None to allow it."""
    agent = str(data.get("agent_type") or "")
    if not agent.startswith(PREFIX):
        return None
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
            if role in DOCS_ONLY_ROLES and not path.lower().endswith((".md", ".mdx")):
                raise Blocked(f"{role} writes Markdown only; `{path}` is not a .md file")
            if role in DOCS_ONLY_ROLES and INSTRUCTION_MD.search(os.path.relpath(os.path.join(cwd, path), cwd).replace(os.sep, "/")):
                raise Blocked(f"{role} doesn't edit agent instructions or config (`{path}`); ask the Lead")
            if role in READ_ONLY_ROLES:
                raise Blocked(f"{role} is read-only")
            if role == "qa-engineer" and (tool != "Write" or os.path.exists(path)):
                raise Blocked("qa-engineer may only create new test files, not change existing ones")
    except Blocked as b:
        return str(b)
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    reason = decide(data)
    if reason is not None:
        print(f"[engineering-team guard] blocked: {reason}. If this is really needed, stop and report it "
              f"to the Lead so the user can decide.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
