#!/usr/bin/env python3
"""PreToolUse guard for ETK subagents.

Only acts when the tool call comes from one of this plugin's agents
(`agent_type` starts with "engineering-team:"). The main session and every
other agent are left alone: the user's own permission settings already cover
them, and a plugin should not change how unrelated sessions behave.

Commands are split into segments (&&, ||, ;, |, newlines) and each segment is
judged by the program it actually runs, so `grep "git push" docs/` or a commit
message mentioning `rebase` is fine, while `git -C . push` is not. A `cd`/`pushd` earlier in
the same command moves the directory later segments are judged in; when the target can't
be known (`cd $X`, `cd -`) relative paths are judged as if they were outside the project.
Nested shells
(`bash -c`, `eval`, `$(...)`, backticks) are checked recursively, and heredoc
bodies are checked line by line like any other command text (fail closed). Shell
keywords (`then`, `do`, `{`, `!`), wrappers (`timeout`, `nice`, `sudo -u x`) and
`find -exec/-delete` are seen through; a shell reading commands from a pipe can't be
checked and is blocked.

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
from typing import Any

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
WRAPPERS = {"sudo", "doas", "env", "command", "builtin", "nohup", "time", "exec", "xargs", "setsid", "timeout",
            "nice", "ionice", "stdbuf", "caffeinate", "unbuffer"}
# Options that take a value, and the plain flags we know for each wrapper. An option we
# don't know could swallow the next word, so the command can't be attributed: block.
WRAPPER_OPTS_WITH_ARG = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-T", "-r", "-t", "-U", "-D", "-R"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "caffeinate": {"-t", "-w"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "--max-args", "--max-procs", "--delimiter"},
    "exec": {"-a"},
    "time": {"-f", "-o", "--format", "--output"},
}
def dash(letters: str) -> set:
    return {f"-{c}" for c in letters}


WRAPPER_FLAGS = {
    "sudo": dash("EHnSsibAkKPelv"), "doas": dash("ns"), "env": dash("i0v"), "command": dash("pvV"),
    "timeout": {"--preserve-status", "--foreground", "-v", "--verbose"}, "ionice": {"-t"},
    "caffeinate": dash("dimsu"), "time": dash("pva") | {"--append", "--portability", "--verbose"},
    "exec": dash("cl"), "setsid": dash("cfw"), "unbuffer": {"-p"}, "builtin": set(), "nohup": set(), "stdbuf": set(),
    "xargs": dash("0rtpxo") | {"--null", "--no-run-if-empty", "--verbose", "--interactive"}, "nice": set(),
}
WRAPPER_POSITIONALS = {"timeout": 1}  # the duration
# Words that start a command inside compound syntax (`if x; then y; fi`, `{ y; }`, `! y`).
SHELL_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "{", "}", "!", "fi", "done", "case", "in",
                  "esac", "select", "coproc"}


class Blocked(Exception):
    pass


def is_secret(path: str) -> bool:
    p = path.strip().strip("'\"")
    return bool(SECRET_NAME.search(p)) and not SECRET_OK.search(p)


SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
MAX_DEPTH = 4
UNSET: Any = object()  # "not given", as opposed to None (= directory unknown)


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


class Tok:
    __slots__ = ("kind", "text", "subs", "quoted", "body")

    def __init__(self, kind, text, subs=None, quoted=False):
        self.kind, self.text, self.subs, self.quoted, self.body = kind, text, subs or [], quoted, None


class Seg:
    """One simple command: argv without redirections, plus what hangs off it."""

    def __init__(self, sep: str):
        self.words: list[str] = []
        self.subs: list[str] = []  # $(...) and `...` bodies that are live (not single-quoted)
        self.redirs: list[tuple[str, str]] = []  # (operator, target)
        self.heredocs: list[tuple[str, bool]] = []  # (body, body expands $(...))
        self.herestrings: list[str] = []
        self.sep = sep  # operator before this command
        self.after = ""  # operator after it


OPERATORS = ["&>>", "<<<", "<<-", ">>", "&&", "||", ";;", "|&", "&>", ">&", "<&", ">|", "<<", "<>",
             ";", "&", "|", "(", ")", "<", ">"]
REDIRECTS = {"<", ">", ">>", ">|", "&>", "&>>", ">&", "<&", "<>", "<<", "<<-", "<<<"}
PUSH, POP = "push", "pop"


def _balanced(text: str, i: int) -> int:
    """Index just past the `)` closing a `(` that was opened right before text[i]."""
    depth, quote = 1, None
    while i < len(text) and depth:
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = None
        elif c == "\\":
            i += 1
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return i


def _backtick(text: str, i: int) -> int:
    """Index of the closing backtick for one opened right before text[i]."""
    while i < len(text) and text[i] != "`":
        i += 2 if text[i] == "\\" else 1
    return i


def find_subs(text: str) -> list[str]:
    """$(...) and `...` bodies in text that is not single-quoted (heredoc bodies)."""
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
        elif text.startswith("$((", i):
            i = _balanced(text, i + 2)
        elif text.startswith("$(", i):
            end = _balanced(text, i + 2)
            out.append(text[i + 2:end - 1])
            i = end
        elif c == "`":
            end = _backtick(text, i + 1)
            out.append(text[i + 1:end])
            i = end + 1
        else:
            i += 1
    return out


def tokenize(text: str) -> list[Tok]:
    toks: list[Tok] = []
    buf: list[str] = []
    subs: list[str] = []
    state = {"has": False, "quoted": False, "delim": None}
    pending: list[tuple[Tok, bool]] = []
    i, n = 0, len(text)

    def flush() -> None:
        if state["has"]:
            tok = Tok("w", "".join(buf), subs[:], state["quoted"])
            toks.append(tok)
            if state["delim"] is not None:
                pending.append((tok, state["delim"]))
                state["delim"] = None
        buf.clear()
        subs.clear()
        state["has"] = state["quoted"] = False

    while i < n:
        c = text[i]
        if c in " \t":
            flush()
            i += 1
        elif c == "\n":
            flush()
            toks.append(Tok("op", ";"))
            i += 1
            for tok, strip in pending:
                body, found = [], False
                while i < n and not found:
                    end = text.find("\n", i)
                    end = n if end < 0 else end
                    line = text[i:end]
                    i = end + 1
                    if (line.lstrip("\t") if strip else line) == tok.text:
                        found = True
                    else:
                        body.append(line)
                tok.body = "\n".join(body)
            pending.clear()
        elif c == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            buf.append(text[i + 1] if i + 1 < n else "")
            state["has"] = state["quoted"] = True
            i += 2
        elif c == "'":
            end = text.find("'", i + 1)
            end = n if end < 0 else end
            buf.append(text[i + 1:end])
            state["has"] = state["quoted"] = True
            i = end + 1
        elif c == '"':
            state["has"] = state["quoted"] = True
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1] if text[i + 1] in '"\\$`' else text[i:i + 2])
                    i += 2
                elif text.startswith("$((", i):
                    end = _balanced(text, i + 2)
                    buf.append(text[i:end])
                    i = end
                elif text.startswith("$(", i):
                    end = _balanced(text, i + 2)
                    subs.append(text[i + 2:end - 1])
                    buf.append(text[i:end])
                    i = end
                elif text[i] == "`":
                    end = _backtick(text, i + 1)
                    subs.append(text[i + 1:end])
                    buf.append(text[i:end + 1])
                    i = end + 1
                else:
                    buf.append(text[i])
                    i += 1
            i += 1
        elif text.startswith("$((", i):
            end = _balanced(text, i + 2)
            buf.append(text[i:end])
            state["has"] = True
            i = end
        elif text.startswith("$(", i) or (c in "<>" and text.startswith("(", i + 1)):
            end = _balanced(text, i + 2)
            subs.append(text[i + 2:end - 1])
            buf.append(text[i:end])
            state["has"] = True
            i = end
        elif c == "`":
            end = _backtick(text, i + 1)
            subs.append(text[i + 1:end])
            buf.append(text[i:end + 1])
            state["has"] = True
            i = end + 1
        else:
            op = next((o for o in OPERATORS if text.startswith(o, i)), None)
            if op is None:
                buf.append(c)
                state["has"] = True
                i += 1
                continue
            if op in REDIRECTS and state["has"] and "".join(buf).isdigit() and not state["quoted"]:
                buf.clear()  # fd prefix like the 2 in 2>
                state["has"] = False
            else:
                flush()
            toks.append(Tok("op", op))
            if op in {"<<", "<<-"}:
                state["delim"] = op == "<<-"
            i += len(op)
    flush()
    return toks


def parse(text: str) -> list:
    """Events in execution order: Seg objects, plus PUSH/POP around ( ... ) groups."""
    events: list = []
    cur = Seg("")
    want = None  # redirect operator waiting for its target

    def close(next_sep: str) -> None:
        nonlocal cur
        if cur.words or cur.redirs or cur.subs:
            cur.after = next_sep
            events.append(cur)
        cur = Seg(next_sep)

    for tok in tokenize(text):
        if tok.kind == "w":
            cur.subs.extend(tok.subs)
            if want is None:
                cur.words.append(tok.text)
                continue
            if want in {"<<", "<<-"}:
                cur.heredocs.append((tok.body or "", not tok.quoted))
            elif want == "<<<":
                cur.herestrings.append(tok.text)
            cur.redirs.append((want, tok.text))
            want = None
        elif tok.text in REDIRECTS:
            want = tok.text
        elif tok.text in {"(", ")"}:
            close(tok.text)
            events.append(PUSH if tok.text == "(" else POP)
        else:
            close(tok.text)
    close("")
    return events


def known_wrapper_option(base: str, opt: str) -> bool:
    takes = WRAPPER_OPTS_WITH_ARG.get(base, set())
    flags = WRAPPER_FLAGS.get(base, set())
    if opt in flags or opt in takes:
        return True
    if opt.startswith("--"):
        return "=" in opt and opt.split("=", 1)[0] in takes
    if base == "nice" and re.match(r"^-\d+$", opt):
        return True
    if base == "env" and opt == "-":
        return True
    if opt[:2] in takes:
        return True  # attached value, like -n5 or -oL
    return len(opt) > 2 and all(f"-{c}" in flags for c in opt[1:])


def program(words: list[str]) -> list[str]:
    """Skip shell keywords, env assignments and wrappers like sudo/timeout to see the real program."""
    words = list(words)
    i = 0
    while i < len(words):
        w = words[i]
        base = os.path.basename(w)
        if w == "coproc" and "{" in words[i:]:
            i = words.index("{", i) + 1
        elif w in SHELL_KEYWORDS or re.match(r"^\w+=", w):
            i += 1
        elif w == "function" and i + 1 < len(words):
            i += 2
        elif base in WRAPPERS:
            i += 1
            takes_arg = WRAPPER_OPTS_WITH_ARG.get(base, set())
            while i < len(words) and words[i].startswith("-") and words[i] != "-":
                opt = words[i]
                i += 1
                if opt == "--":
                    break
                if base == "env" and (opt in {"-S", "--split-string"} or opt.startswith(("--split-string=", "-S"))):
                    value = opt.split("=", 1)[1] if opt.startswith("--split-string=") else (opt[2:] or None)
                    if value is None:
                        if i >= len(words):
                            raise Blocked("`env -S` without a value can't be checked")
                        value, i = words[i], i + 1
                    try:
                        words[i:i] = shlex.split(value)
                    except ValueError:
                        raise Blocked("`env -S` value can't be parsed")
                    continue
                if not known_wrapper_option(base, opt):
                    raise Blocked(f"`{base} {opt}` is an option the guard doesn't know; can't tell what it runs")
                if opt in takes_arg and i < len(words):
                    i += 1
            i += WRAPPER_POSITIONALS.get(base, 0)
        else:
            break
    return words[i:]


def redirect_targets(redirs: list[tuple[str, str]]) -> list[str]:
    """Targets of >, >>, >|, &>, &>>, N> (fd duplications like 2>&1 are skipped)."""
    out = []
    for op, target in redirs:
        if op not in {">", ">>", ">|", "&>", "&>>", ">&", "<>"}:
            continue
        if op == ">&" and (target.isdigit() or target == "-"):
            continue  # fd duplication like 2>&1 or >&-
        out.append(target)
    return out


def absjoin(path: str, cur: str | None) -> str | None:
    """Absolute form of path, or None when it is relative to a directory we can't know."""
    if os.path.isabs(path):
        return path
    return None if cur is None else os.path.join(cur, path)


def inside(path: str | None, base: str) -> bool:
    if path is None:
        return False
    real, base = os.path.realpath(path), os.path.realpath(base)
    return real == base or real.startswith(base + os.sep)


def temp_roots() -> list[str]:
    roots = {"/tmp", "/private/tmp", "/var/folders", "/private/var/folders", tempfile.gettempdir()}
    return [os.path.realpath(r) for r in roots]


def in_temp(path: str, cur: str | None) -> bool:
    p = absjoin(path, cur)
    return p is not None and any(inside(p, t) for t in temp_roots())


def scratch(path: str, root: str, cur: str | None) -> bool:
    """A temp path that is not part of the project (projects can live under /tmp too)."""
    p = absjoin(path, cur)
    return p is not None and in_temp(p, cur) and not inside(p, root)


def untracked_secrets(cwd: str) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=cwd,
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [f for f in out.splitlines() if is_secret(f)]


def check_git(args: list[str], cwd: str, cur: str | None) -> None:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            cur = absjoin(args[i + 1], cur)
        i += 2 if args[i] in GIT_GLOBAL_WITH_ARG else 1
    cwd = cur or cwd
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


def check_rm(args: list[str], root: str, cur: str | None) -> None:
    opts = [a for a in args if a.startswith("-")]
    recursive = any("r" in o.lower() for o in opts if not o.startswith("--")) or "--recursive" in opts
    if not recursive:
        return
    for target in (a for a in args if not a.startswith("-")):
        if target in {"/", "~", "*", "./*", ".", ".."} or target.startswith("~"):
            raise Blocked(f"`rm -r {target}` is too broad")
        if "$" in target or "`" in target:
            raise Blocked(f"`rm -r {target}` uses a variable; spell the path out so it can be checked")
        path = absjoin(target, cur)
        if path is None:
            raise Blocked(f"`rm -r {target}` runs after a `cd` that can't be resolved; use absolute paths")
        if (inside(path, root) and os.path.realpath(path) != os.path.realpath(root)) or in_temp(path, cur):
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


def writes_existing(target: str, root: str, cur: str | None) -> bool:
    path = absjoin(target, cur)
    return path is None or (os.path.exists(path) and not scratch(path, root, cur))


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


def next_dir(words: list[str], cur: str | None, dirs: list) -> str | None:
    """Working directory after `cd`/`pushd`/`popd`; None once it can't be known.

    `dirs` is the pushd stack; a "?" entry means a stack operation we didn't model.
    """
    prog, args = words[0], words[1:]
    odd = [a for a in args if a.startswith(("-", "+")) and a not in {"-", "--"}]
    operands = [a for a in args if not a.startswith(("-", "+")) or a == "-"]
    if prog == "cd":
        if [a for a in odd if a != "-L"] or len(operands) > 1:
            return None  # -P/-e/-@ resolve symlinks differently; extra operands are an error
    elif odd or (prog == "pushd" and len(operands) != 1) or (prog == "popd" and args):
        dirs[:] = ["?"]  # rotations, -n, bare swap, odd shapes
        return None
    if prog == "popd":
        return None if "?" in dirs or not dirs else dirs.pop()
    target = operands[0] if operands else None
    if prog == "pushd":
        dirs.append(cur)
    if target is None or target == "-" or target.startswith("~") or re.search(r"[$`*?\[(]", target):
        return None
    if os.environ.get("CDPATH") and not target.startswith(("/", "./", "../")) and target not in {".", ".."}:
        return None  # an inherited CDPATH can send a bare `cd x` anywhere
    joined = absjoin(target, cur)
    return None if joined is None else os.path.normpath(joined)


STDIN_PATHS = {"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}
SHELL_OPT_WITH_ARG = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}


def shell_input(prog: str, args: list[str]) -> tuple[str, str | None]:
    """Where a shell gets its commands: ("script", text) for -c, ("stdin", None), or ("file", None)."""
    if prog in {"source", "."}:
        return ("stdin", None) if args[:1] and args[0] in STDIN_PATHS else ("file", None)
    i, c_flag, s_flag = 0, False, False
    while i < len(args):
        w = args[i]
        if w == "--":
            i += 1
            break
        if w == "-":
            break
        if w.startswith("--"):
            i += 2 if w in SHELL_OPT_WITH_ARG else 1
        elif w[0] in "-+" and len(w) > 1:
            if w[0] == "-":
                c_flag = c_flag or "c" in w[1:]
                s_flag = s_flag or "s" in w[1:]
            if w[-1] in "oO":
                if i + 1 >= len(args):
                    raise Blocked(f"`{prog} {w}` is missing its value; can't tell what it runs")
                i += 1
            i += 1
        else:
            break
    operands = args[i:]
    if c_flag:
        if not operands:
            raise Blocked(f"`{prog} -c` without a script can't be checked")
        return "script", operands[0]
    if s_flag or not operands or operands[0] in STDIN_PATHS:
        return "stdin", None
    return "file", None


def check_find(args: list[str], root: str, role: str, depth: int, cur: str | None) -> None:
    """`find -delete` is an rm -r over the start points; `-exec CMD {} ;` runs CMD on them."""
    i = 0
    while i < len(args) and re.match(r"^-([HLP]|[DO]\w*)$", args[i]):
        i += 1
    roots = []
    while i < len(args) and not args[i].startswith(("-", "(", "!")):
        roots.append(args[i])
        i += 1
    roots = [r.rstrip("/") + "/__match__" if r != "/" else "/__match__" for r in roots or ["."]]
    exprs = args[i:]
    if "-delete" in exprs:
        for r in roots:
            check_words(["rm", "-r", r], root, role, depth + 1, cur)
        if role == "qa-engineer" and not all(scratch(r, root, cur) for r in roots):
            raise Blocked("qa-engineer may only create new files, not delete existing ones")
    for j, e in enumerate(exprs):
        if e not in {"-exec", "-execdir", "-ok", "-okdir"}:
            continue
        end = next((k for k in range(j + 1, len(exprs)) if exprs[k] in {";", "+"}), len(exprs))
        for r in roots:
            check_words(program([w.replace("{}", r) for w in exprs[j + 1:end]]), root, role, depth + 1, cur)


def check_words(words: list[str], root: str, role: str, depth: int, cur: str | None, seg: Seg | None = None) -> None:
    """Judge one simple command (already stripped of wrappers and shell keywords)."""
    if not words:
        return
    redirs = seg.redirs if seg else []
    read_only = role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES
    create_only = role == "qa-engineer"
    prog = os.path.basename(words[0])
    if prog == "eval":
        check_bash(" ".join(words[1:]), root, role, depth + 1, cur)
        return
    if prog in SHELLS or prog in {"source", "."}:
        mode, script = shell_input(prog, words[1:])
        if mode == "script":
            check_bash(script, root, role, depth + 1, cur)
        elif mode == "stdin":
            if seg is None or not (seg.heredocs or seg.herestrings):
                raise Blocked(f"`{prog}` reading commands from stdin can't be checked; pass a script file or use -c")
            for text in seg.herestrings:
                check_bash(text, root, role, depth + 1, cur)
    if prog == "find":
        check_find(words[1:], root, role, depth, cur)
    line = " ".join([prog] + words[1:])
    for pattern, reason in DEPLOY:
        if re.search(pattern, line, re.I):
            raise Blocked(reason)
    if prog == "git":
        check_git(words[1:], root, cur)
    if prog == "rm":
        check_rm(words[1:], root, cur)
    for target in redirect_targets(redirs):
        if is_secret(target):
            raise Blocked(f"writing to `{target}` (looks like a secrets file)")
        if read_only and target not in SAFE_SINKS and not scratch(target, root, cur):
            raise Blocked(f"{role} is read-only; it reports findings and the developer changes files")
    if create_only:
        if any(writes_existing(t, root, cur) for t in redirect_targets(redirs)) \
                or (prog in SHELL_WRITERS and any(writes_existing(t, root, cur) for t in write_operands(prog, words[1:]))) \
                or (prog == "sed" and any(w.startswith("-i") for w in words[1:])):
            raise Blocked("qa-engineer may only create new files, not change existing ones")
    if read_only:
        words = real_tool(words)
        prog = os.path.basename(words[0])
        ops = write_operands(prog, words[1:])
        writes = prog in SHELL_WRITERS and not (ops and all(scratch(t, root, cur) for t in ops))
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


def check_bash(cmd: str, root: str, role: str, depth: int = 0, cur: str | None = UNSET) -> None:
    if depth > MAX_DEPTH:
        raise Blocked("command nests shells too deeply to check")
    if cur is UNSET:
        cur = root
    for inner in substitutions(cmd):
        check_bash(inner, root, role, depth + 1, cur)
    events = parse(cmd)
    read_only = role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES
    if read_only and WRITE_CODE.search(cmd) and any(runs_inline_code(program(e.words)) for e in events if isinstance(e, Seg)):
        raise Blocked(f"{role} is read-only; inline code that writes files isn't allowed")
    dirs: list = []
    groups: list = []
    for seg in events:
        if seg is PUSH:
            groups.append((cur, list(dirs)))
            continue
        if seg is POP:
            if groups:
                cur, dirs = groups.pop()
            continue
        for body in seg.subs:
            check_bash(body, root, role, depth + 1, cur)
        for body, _ in seg.heredocs:
            check_bash(body, root, role, depth + 1, cur)
        words = program(seg.words)
        in_pipe = seg.sep in {"|", "|&"} or seg.after in {"|", "|&", "&"}
        if any(re.search(r"\bCDPATH\b", w) for w in seg.words) and not in_pipe:
            cur = None  # `cd x` may land somewhere else entirely
        if words and os.path.basename(words[0]) in {"cd", "pushd", "popd"}:
            new = next_dir(words, cur, list(dirs) if in_pipe else dirs)
            if not in_pipe:
                # after `;` or `||` the cd may have failed, leaving us where we were
                cur = None if seg.after in {";", "||"} else new
            continue
        if not in_pipe and any(os.path.basename(w) in {"cd", "pushd", "popd"} for w in words[1:]):
            cur = None  # a cd we can't attribute (find -exec cd, xargs cd): stay strict
        check_words(words, root, role, depth, cur, seg)
        if words and os.path.basename(words[0]) in {"eval", "source", "."} and not in_pipe:
            cur, dirs[:] = None, ["?"]  # whatever it did to the directory isn't visible to us


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
