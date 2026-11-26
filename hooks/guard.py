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
(`bash -c`, `eval`, `$(...)`, backticks outside single quotes) are checked recursively. A
heredoc or here-string is text unless it feeds a shell; an unquoted heredoc still runs
the `$(...)` inside it. Shell
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

import fnmatch
import glob
import itertools
import json
import os
import re
import shlex
import signal
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
                   ("clang-format", "-i"), ("php-cs-fixer", "fix"), ("go", "fmt"), ("cargo", "fmt"), ("deno", "fmt"),
                   ("terraform", "fmt"), ("dprint", "fmt"), ("shfmt", "-w"), ("gofumpt", "-w"), ("goimports", "-w"),
                   ("autopep8", "--in-place"), ("autopep8", "-i"), ("yapf", "-i"), ("yapf", "--in-place"),
                   ("stylua", None), ("swiftformat", None)}

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


class Quoted(str):
    """A word that had quotes or escapes in the source (so `'{'` is not a brace group)."""


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
                cur.words.append(Quoted(tok.text) if tok.quoted else tok.text)
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


ASSIGN_RE = re.compile(r"^\w+(\[[^\]]*\])?\+?=", re.S)


def program_ex(words: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Words of the real command, files the wrappers write (`time -o FILE`), and the NAME=VALUE
    words that set variables ahead of it (leading assignments and `env NAME=VALUE`).

    Skip shell keywords, env assignments and wrappers like sudo/timeout to see the real program."""
    words = list(words)
    outputs: list[str] = []
    assigns: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        base = os.path.basename(w)
        if w == "coproc":
            ahead = words[i + 1:i + 3]
            brace = next((n for n, x in enumerate(ahead) if x == "{" and not isinstance(x, Quoted)), None)
            if brace == 0 or (brace == 1 and re.match(r"^[A-Za-z_]\w*$", ahead[0]) and not isinstance(ahead[0], Quoted)):
                i += brace + 2  # `coproc { ...; }` or `coproc NAME { ...; }`
            elif "{" in ahead:
                raise Blocked("`coproc` with a quoted brace or an odd name can't be checked")
            else:
                i += 1
        elif w in SHELL_KEYWORDS:
            i += 1
        elif ASSIGN_RE.match(w):
            assigns.append(w)
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
                    if "\\" in value or "${" in value or re.search(r"(^|\s)#", value):
                        raise Blocked("`env -S` value uses env's own escapes, comments or expansions; can't be checked")
                    try:
                        words[i:i] = shlex.split(value)
                    except ValueError:
                        raise Blocked("`env -S` value can't be parsed")
                    continue
                if base == "time" and (opt in {"-o", "--output"} and i < len(words)):
                    outputs.append(words[i])
                elif base == "time" and opt.startswith("--output="):
                    outputs.append(opt.split("=", 1)[1])
                elif base == "time" and opt.startswith("-o") and len(opt) > 2:
                    outputs.append(opt[2:])
                if (base == "env" and (opt in {"-C", "--chdir"} or opt.startswith(("--chdir=", "-C")))) \
                        or (base == "sudo" and (opt in {"-D", "-R", "--chdir", "--chroot"}
                                                or opt.startswith(("--chdir=", "--chroot=", "-D", "-R")))):
                    raise Blocked(f"`{base} {opt}` changes directory where the guard can't follow; use `cd` instead")
                if not known_wrapper_option(base, opt):
                    raise Blocked(f"`{base} {opt}` is an option the guard doesn't know; can't tell what it runs")
                if opt in takes_arg and i < len(words):
                    i += 1
            i += WRAPPER_POSITIONALS.get(base, 0)
        else:
            break
    return words[i:], outputs, assigns


def program(words: list[str]) -> list[str]:
    return program_ex(words)[0]


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
        raise Blocked("couldn't list untracked files to look for secrets (git failed or timed out); "
                      "add paths explicitly")
    return [f for f in out.splitlines() if is_secret(f)]


CHECKOUT_OK_FLAGS = {"-b", "-B", "--detach", "-q", "--quiet", "--track", "-t", "--no-track"}


def is_ref(name: str, cwd: str) -> bool:
    if name == "-":
        return True
    for cmd in (["git", "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"],
                ["git", "for-each-ref", "--count=1", "--format=%(refname)", f"refs/remotes/*/{name}"]):
        try:
            out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if out.returncode == 0 and out.stdout.strip():
            return True
    return False


def check_checkout(rest: list[str], cwd: str) -> None:
    """Only switching branches or creating one is safe; anything with a path overwrites files."""
    flags = [a for a in rest if a.startswith("-") and a != "-"]
    operands = [a for a in rest if not a.startswith("-") or a == "-"]
    if "--" in rest or [f for f in flags if f not in CHECKOUT_OK_FLAGS]:
        raise Blocked("`git checkout` with paths or force/patch/merge flags discards uncommitted changes")
    if "-b" in flags or "-B" in flags:
        if len(operands) > 2:
            raise Blocked("`git checkout -b NAME` takes a branch name and an optional start point only")
        return
    if len(operands) > 1 or (operands and not is_ref(operands[0], cwd)):
        raise Blocked("`git checkout` of anything but a single branch or commit overwrites files; "
                      "use `git switch` for branches")


# Config that decides where a push goes or which programs git runs. A subagent changing it could
# redirect the Lead's next push (or select another developer's workflow profile), so only reads pass.
GIT_CONFIG_GUARDED = re.compile(r"^((remote|url|filter|diff|credential|include|includeif|branch|alias|pager|"
                                r"sequence|gpg|merge|http|submodule)(\.|$)|core\.(hookspath|sshcommand|fsmonitor|pager|"
                                r"editor|askpass|gitproxy|attributesfile|excludesfile|worktree)$|"
                                r"commit\.gpgsign$|push\.)", re.I)
GIT_CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool",
                    "--list", "-l"}
GIT_CONFIG_WRITES = {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section", "--remove-section"}
GIT_CONFIG_WITH_VALUE = {"-f", "--file", "--blob", "--type", "--default", "--comment", "--value"}
GIT_REMOTE_WRITES = {"add", "set-url", "rename", "remove", "rm", "set-branches"}


def git_config_writes(rest: list[str]) -> list[str] | None:
    """Names (keys or sections) a `git config` call writes, [""] for one that can't be told (`--edit`),
    or None for a read. Knows the classic flags and the `git config set|unset|...` verbs (git 2.46+)."""
    words, flags, i = [], set(), 0
    while i < len(rest):
        w = rest[i]
        if w == "--":
            words += rest[i + 1:]
            break
        if w.startswith("-") and w != "-":
            name = w.split("=", 1)[0]
            flags.add(name)
            i += 2 if name in GIT_CONFIG_WITH_VALUE and "=" not in w else 1
            continue
        words.append(w)
        i += 1
    verb = words[0] if words else ""
    if verb in {"get", "list"}:
        return None
    if verb in {"set", "unset", "rename-section", "remove-section", "edit"}:
        args = words[1:]
        return [""] if verb == "edit" or not args else args[:2] if verb == "rename-section" else args[:1]
    if flags & {"--edit", "-e"}:
        return [""]
    if flags & GIT_CONFIG_WRITES:
        return (words[:2] if "--rename-section" in flags else words[:1]) or [""]
    if flags & GIT_CONFIG_READS or len(words) < 2:
        return None
    return words[:1]


def check_git(args: list[str], cwd: str, cur: str | None) -> None:
    root = cwd
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
    if sub == "config":
        names = git_config_writes(rest)
        if names is not None and any(n == "" or GIT_CONFIG_GUARDED.match(n) for n in names):
            raise Blocked("changing remotes, URL rewrites, hooks, filters, diff drivers, credentials or includes "
                          "in git config is the Lead's call (it decides where pushes go and what git runs); "
                          "reads like `git config --get` are fine")
    if sub == "remote":
        verb = next((w for w in rest if not w.startswith("-")), "")
        if verb in GIT_REMOTE_WRITES:
            raise Blocked(f"`git remote {verb}` changes where the Lead pushes; leave remotes to the Lead")
    if sub == "reset" and has("--hard", "--merge", "--keep"):
        raise Blocked("reset --hard discards work; ask the Lead instead")
    if sub == "clean" and not (short("n") or has("--dry-run")):
        raise Blocked("git clean deletes untracked files that may be the user's; only a dry run (-n) is allowed")
    if sub == "rm" and not (has("--cached") and not (short("f") or has("--force"))):
        broad = {".", "*", "./", ":/", "./*"}
        if short("r") or short("f") or has("--force") or any(w in broad for w in rest):
            raise Blocked("`git rm` with -r/-f or a broad pathspec deletes work from the tree")
    if sub == "checkout":
        check_checkout(rest, cwd)
    if sub in {"rm", "mv", "restore", "apply", "checkout"}:
        for w in rest:
            if not w.startswith("-"):
                check_protected(w, root, cur)
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


def git_dir_path(path: str, cur: str | None) -> bool:
    """A path inside a `.git` directory, or inside this repository's git directory."""
    if ".git" in path.replace("\\", "/").split("/"):
        return True
    if cur is None:
        return False
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=cur, capture_output=True,
                             text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(out) and inside(absjoin(path, cur), os.path.join(cur, out))


def check_rm(args: list[str], root: str, cur: str | None) -> None:
    for target in (a for a in args if not a.startswith("-")):
        if git_dir_path(target, cur):
            raise Blocked(f"`rm {target}` would damage the repository's .git directory")
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


SQL_DESTRUCTIVE = re.compile(r"\b(drop\s+(table|database)|truncate\s+table|dropdatabase)", re.I)
PKG_OPTS = {"--prefix", "--workspace", "-w", "--filter", "-C", "--registry", "--cwd", "--userconfig", "--cache"}
KUBE_OPTS = {"-n", "--namespace", "--context", "--cluster", "--user", "--kubeconfig", "-s", "--server", "--token",
             "--as", "--as-group", "--cache-dir", "--certificate-authority", "--client-certificate", "--client-key",
             "--request-timeout", "--tls-server-name", "--username", "--password"}
HELM_OPTS = {"-n", "--namespace", "--kube-context", "--kubeconfig", "--kube-token", "--kube-as-user",
             "--kube-apiserver", "--registry-config", "--repository-config", "--repository-cache"}
DOCKER_OPTS = {"-H", "--host", "--context", "-c", "-l", "--log-level", "--config", "--tlscacert", "--tlscert", "--tlskey"}
# tool -> (global options that take a value, {first subcommand(s)}, reason)
DEPLOY_TOOLS = {
    "npm": (PKG_OPTS, {("publish",), ("unpublish",)}, "publishing packages needs explicit user approval"),
    "pnpm": (PKG_OPTS, {("publish",), ("unpublish",)}, "publishing packages needs explicit user approval"),
    "yarn": (PKG_OPTS, {("publish",), ("npm", "publish")}, "publishing packages needs explicit user approval"),
    "bun": (PKG_OPTS, {("publish",)}, "publishing packages needs explicit user approval"),
    "cargo": ({"-Z", "--config", "--manifest-path"}, {("publish",)}, "publishing packages needs explicit user approval"),
    "twine": (set(), {("upload",)}, "publishing packages needs explicit user approval"),
    "gem": (set(), {("push",)}, "publishing packages needs explicit user approval"),
    "shopify": ({"--path", "--store", "-s"}, {("app", "deploy"), ("app", "release"), ("theme", "push"),
                                              ("theme", "publish"), ("theme", "delete")},
                "deploying to a Shopify store needs explicit user approval"),
    "fly": (set(), {("deploy",)}, "deploys need explicit user approval"),
    "flyctl": (set(), {("deploy",)}, "deploys need explicit user approval"),
    "firebase": (set(), {("deploy",)}, "deploys need explicit user approval"),
    "serverless": (set(), {("deploy",)}, "deploys need explicit user approval"),
    "sls": (set(), {("deploy",)}, "deploys need explicit user approval"),
    "wrangler": (set(), {("deploy",), ("publish",)}, "deploys need explicit user approval"),
    "cdk": (set(), {("deploy",), ("destroy",)}, "deploys need explicit user approval"),
    "kubectl": (KUBE_OPTS, {(v,) for v in ("apply", "delete", "replace", "rollout", "patch", "scale", "create", "edit",
                                           "drain")}, "infrastructure changes need explicit user approval"),
    "helm": (HELM_OPTS, {(v,) for v in ("install", "upgrade", "uninstall", "rollback", "delete")},
             "infrastructure changes need explicit user approval"),
    "terraform": (set(), {("apply",), ("destroy",)}, "infrastructure changes need explicit user approval"),
    "tofu": (set(), {("apply",), ("destroy",)}, "infrastructure changes need explicit user approval"),
    "pulumi": ({"--cwd", "-C", "--stack", "-s"}, {("up",), ("destroy",)}, "infrastructure changes need explicit user approval"),
    "docker": (DOCKER_OPTS, {("push",), ("image", "push"), ("manifest", "push"), ("compose", "push")},
               "pushing images needs explicit user approval"),
    "gh": ({"-R", "--repo"}, {("pr", "merge"), ("release", "create"), ("repo", "delete")},
           "merging/releasing needs explicit user approval"),
}
RUNNERS = {"npx", "bunx", "pnpx", "pnpm", "yarn", "npm", "uvx", "pipx", "python", "python3"}


def positionals(args: list[str], takes_value: set) -> list[str]:
    """Words that aren't options, skipping the values of options known to take one."""
    out, i = [], 0
    while i < len(args):
        w = args[i]
        if w.startswith("+") and len(w) > 1:  # cargo +nightly
            i += 1
        elif w.startswith("-") and w != "-":
            i += 2 if w in takes_value else 1
        else:
            out.append(w)
            i += 1
    return out


def gh_api_mutates(args: list[str]) -> bool:
    method, fields = None, False
    for i, a in enumerate(args):
        if a in {"-X", "--method"} and i + 1 < len(args):
            method = args[i + 1]
        elif a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif a in {"-f", "-F", "--field", "--raw-field", "--input"} or a.startswith(("-f", "-F")) and "=" in a:
            fields = True
    mutating = (method or "").upper() in {"POST", "PUT", "PATCH", "DELETE"} or (method is None and fields)
    if mutating and "graphql" in args:
        return "mutation" in " ".join(args).lower()
    return mutating


def check_deploy(words: list[str]) -> None:
    """Publishing, deploys, infra changes: judged on the real tool, after its global options."""
    starts = [words]
    if os.path.basename(words[0]) in RUNNERS:  # npx vercel, pnpm dlx x, python -m twine, ...
        starts += [words[k:] for k in range(1, len(words))]
    for w in starts:
        tool = os.path.basename(w[0]).lower()
        args = w[1:]
        if tool in {"psql", "mysql", "sqlite3", "mongosh"} and SQL_DESTRUCTIVE.search(" ".join(args)):
            raise Blocked("destructive SQL needs explicit user approval")
        if tool in {"vercel", "netlify"}:
            prod = any(a in {"--prod", "--production"} or a.startswith("--prod=") for a in args)
            if prod or (tool == "netlify" and positionals(args, set())[:1] == ["deploy"] and "-p" in args):
                raise Blocked("deploys need explicit user approval")
        if tool == "gh" and positionals(args, {"-R", "--repo"})[:1] == ["api"] and gh_api_mutates(args):
            raise Blocked("`gh api` calls that change things (merge, release, delete) need explicit user approval")
        spec = DEPLOY_TOOLS.get(tool)
        if spec:
            pos = positionals(args, spec[0])
            if any(tuple(pos[:len(sub)]) == sub for sub in spec[1]):
                raise Blocked(spec[2])
            if tool == "docker" and pos[:1] == ["buildx"] and "--push" in args:
                raise Blocked(spec[2])


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


def dest_operands(prog: str, args: list[str]) -> list[str]:
    """Files a shell writer creates or overwrites (not the ones it only reads or removes)."""
    write_operands(prog, args)  # raises on target-directory spellings it can't follow
    ops = [a for a in args if not a.startswith("-")]
    if prog == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if prog in {"cp", "install", "ln", "mv"}:
        for i, a in enumerate(args):
            d = args[i + 1] if a in {"-t", "--target-directory"} and i + 1 < len(args) else (
                a.split("=", 1)[1] if a.startswith("--target-directory=") else None)
            if d is not None:
                return [d] + [os.path.join(d, os.path.basename(x)) for x in ops if x != d]
        return ops[-1:]
    if prog in {"tee", "touch", "patch", "truncate"}:
        return ops
    return []


def writes_existing(target: str, root: str, cur: str | None) -> bool:
    path = absjoin(target, cur)
    return path is None or (os.path.exists(path) and not scratch(path, root, cur))


def real_tool(words: list[str]) -> list[str]:
    """See through package-runner wrappers: `npx prettier -w` is prettier, `python -m black` is black."""
    prog = os.path.basename(words[0]) if words else ""
    rest = words[1:]
    if re.match(r"^python[\d.]*$", prog) and "-m" in rest and rest.index("-m") + 1 < len(rest):
        k = rest.index("-m")
        return rest[k + 1:]
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


HOOK_NAMES = "BASH_ENV|PS0|PS4|PROMPT_COMMAND"
HOOK_VAR = re.compile(rf"^({HOOK_NAMES})(\[[^\]]*\])?(\+?=.*)?$", re.S)
DECLARERS = {"export", "declare", "typeset", "readonly", "local"}


def variables_set(assigns: list[str], words: list[str]) -> list[str]:
    """Variables this command sets: leading and `env` assignments, what export/declare/typeset/local/readonly
    assign, and the names `read` / `printf -v` fill. Words that merely look like assignments in
    other arguments (`grep ENV= src`, `make ENV=ci`) are not included."""
    out = list(assigns)
    first = os.path.basename(words[0]) if words else ""
    args = words[1:]
    if first in DECLARERS:
        out += [a.split("=", 1)[0] + ("=" + a.split("=", 1)[1] if "=" in a else "")
                for a in args if not a.startswith("-") and ASSIGN_RE.match(a)]
    elif first == "read":
        out += [a for a in args if not a.startswith("-") and re.match(r"^\w+(\[[^\]]*\])?$", a)]
    elif first == "printf" and "-v" in args and args.index("-v") + 1 < len(args):
        out.append(args[args.index("-v") + 1])
    return out


def check_startup_hook_vars(assigned: list[str]) -> None:
    """Variables the shell evaluates as code (BASH_ENV, PS0, PS4, PROMPT_COMMAND)."""
    named = [w for w in assigned if HOOK_VAR.match(w)]
    if named:
        raise Blocked(f"`{named[0].split('=')[0]}` makes the shell run code later; can't be checked")


def safe_home(cmd: str) -> str | None:
    """$HOME for expanding `cd ~` / `cd $HOME/x`, or None when the command could change HOME first
    (any mention of HOME other than reading `$HOME`/`${HOME}`), or HOME isn't an absolute path."""
    home = os.environ.get("HOME", "")
    # Quotes and backslashes are dropped first so `H"OME"=x` or `HO\\ME=x` still count as a mention.
    flat = re.sub(r"[\"'\\]", "", cmd)
    if not os.path.isabs(home) or re.search(r"\bHOME\b", re.sub(r"\$(\{HOME\}|HOME\b)", "", flat)):
        return None
    return os.path.normpath(home)


def expand_home(target: str, home: str | None) -> str:
    """`~`, `~/x`, `$HOME`, `${HOME}/x` with HOME filled in; anything else unchanged."""
    if home is None:
        return target
    m = re.match(r"^(~|\$HOME\b|\$\{HOME\})(/.*)?$", target)
    return home + (m.group(2) or "") if m else target


# HOME as the current top-level command may use it (set per check at depth 0; None = don't expand).
_CD_HOME: str | None = None


def next_dir(words: list[str], cur: str | None, dirs: list, cdpath_unknown: bool = False) -> str | None:
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
    if target is not None and not cdpath_unknown:
        target = expand_home(target, _CD_HOME)
    if target is None or target == "-" or target.startswith("~") or re.search(r"[$`*?\[(]", target):
        return None
    if (cdpath_unknown or os.environ.get("CDPATH")) and not target.startswith(("/", "./", "../")) and target not in {".", ".."}:
        return None  # an inherited CDPATH can send a bare `cd x` anywhere
    joined = absjoin(target, cur)
    return None if joined is None else os.path.normpath(joined)


def reads_stdin(operand: str, cur: str | None) -> bool:
    """`-`, or anything that resolves under /dev or /proc from where the shell is (symlinks included)."""
    if operand == "-":
        return True
    path = absjoin(re.sub(r"/{2,}", "/", operand), cur)
    if path is None:
        return True  # relative to a directory we can't know
    return any(p.startswith(("/dev/", "/proc/")) for p in (os.path.normpath(path), os.path.realpath(path)))


SHELL_OPT_WITH_ARG = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}


def shell_input(prog: str, args: list[str], cur: str | None) -> tuple[str, str | None]:
    """Where a shell gets its commands: ("script", text) for -c, ("stdin", None), or ("file", None)."""
    if prog in {"source", "."}:
        if args[:1] and reads_stdin(args[0], cur):
            return "stdin", None
        return "file", args[0] if args else None
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
            wants = sum(c in "oO" for c in w[1:])  # each o/O in the cluster takes the next argument
            if i + wants >= len(args) and wants:
                raise Blocked(f"`{prog} {w}` is missing its value; can't tell what it runs")
            i += 1 + wants
        else:
            break
    operands = args[i:]
    if c_flag:
        if not operands:
            raise Blocked(f"`{prog} -c` without a script can't be checked")
        return "script", operands[0]
    if s_flag or not operands or reads_stdin(operands[0], cur):
        return "stdin", None
    return "file", operands[0]


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
        if e in {"-fprint", "-fprint0", "-fprintf", "-fls"} and j + 1 < len(exprs):
            check_write_target(exprs[j + 1], role, root, cur)
        if e not in {"-exec", "-execdir", "-ok", "-okdir"}:
            continue
        end = next((k for k in range(j + 1, len(exprs)) if exprs[k] in {";", "+"}), len(exprs))
        for r in roots:
            words, outputs, assigns = program_ex([w.replace("{}", r) for w in exprs[j + 1:end]])
            check_words(words, root, role, depth + 1, cur, None, outputs, assigns=assigns)


def load_protected(root: str) -> list[str]:
    """`protected_paths` from <cwd>/.claude/engineering-team.json (a missing or unreadable file protects nothing)."""
    try:
        with open(os.path.join(root, ".claude", "engineering-team.json")) as f:
            value = json.load(f).get("protected_paths")
    except (OSError, ValueError, AttributeError):
        return []
    if isinstance(value, str):
        value = [value]
    return [v for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def glob_regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def is_protected(path: str, root: str, cur: str | None) -> bool:
    patterns = load_protected(root)
    if not patterns:
        return False
    full = absjoin(path, cur)
    if full is None:
        return True  # can't tell where a relative path lands, and something here is protected
    real_root = os.path.realpath(root)
    rel = os.path.relpath(os.path.realpath(full), real_root).replace(os.sep, "/")
    if rel == ".." or rel.startswith("../"):
        return False
    parts = rel.split("/")
    prefixes = ["/".join(parts[:n]) for n in range(1, len(parts) + 1)]
    for pat in patterns:
        pat = pat.strip()
        while pat.startswith("./"):
            pat = pat[2:]
        pat = pat.rstrip("/")
        if pat in {"", "."}:
            return True
        for variant in {pat, pat[:-3] if pat.endswith("/**") else pat}:  # `dir/**` protects `dir` itself too
            rx = glob_regex(variant)
            if any(rx.match(pre) for pre in prefixes):
                return True
    return False


def in_plugin_data(path: str, cur: str | None) -> bool:
    """A path inside the plugin's data dir (the developer's workflow profile lives there).

    The hook gets CLAUDE_PLUGIN_DATA in its environment; the agent's shell doesn't, so a path that
    spells the variable or the data dir's usual location is treated as inside it too."""
    p = path.strip().strip("'\"")
    if "CLAUDE_PLUGIN_DATA" in p or re.search(r"(^|/)\.claude/plugins/data(/|$)", p):
        return True
    full = absjoin(p, cur)
    if full is not None and re.search(r"/\.claude/plugins/data(/|$)", os.path.normpath(full)):
        return True  # a relative path after `cd ~/.claude/plugins` lands there too
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if not data or not os.path.isabs(data):
        return False
    if p == "~" or p.startswith("~/"):
        p = os.path.expanduser(p)
    return inside(absjoin(p, cur), data)


TOOL_HOME_DIRS = (".claude", ".pyenv/versions", ".pyenv/shims", ".local/share/uv/python", ".asdf/installs/python",
                  ".asdf/shims", ".local/share/mise/installs/python", ".local/share/mise/shims")
TOOL_HOME_FILES = (".claude.json",)
GLOB_CAP = 256


def in_tool_home(path: str, cur: str | None) -> bool:
    """User-level files that decide what runs for the Lead and for this hook: Claude Code's own
    config (`~/.claude`, `~/.claude.json`, $CLAUDE_CONFIG_DIR), installed plugins (this hook's code
    included), the folders `find-python.sh` picks an interpreter from and the shim folders on PATH.
    A subagent never needs to write there.

    Compared case-insensitively (macOS), with shell globs expanded the way the shell will, and a
    relative path into a Python or `.local` folder is blocked when the directory is unknown."""
    home = os.environ.get("HOME", "")
    if not os.path.isabs(home):
        return False
    p = path.strip().strip("'\"")
    full = absjoin(expand_home(p, home), cur)
    if full is None:
        return re.match(r"^(\./)?\.(pyenv|asdf|local)(/|$)", p) is not None
    h = os.path.realpath(home).lower()
    whole = [os.path.join(h, d.lower()) for d in TOOL_HOME_DIRS]  # nothing in these is a subagent's
    for var in ("PYENV_ROOT", "UV_PYTHON_INSTALL_DIR", "CLAUDE_CONFIG_DIR"):
        v = os.environ.get(var, "")
        if os.path.isabs(v):
            whole.append(os.path.realpath(v).lower())
    # Folders on PATH under HOME (`~/.local/bin`): only an interpreter name there can hijack the hook.
    on_path = {os.path.realpath(x).lower() for x in os.environ.get("PATH", "").split(os.pathsep)
               if os.path.isabs(x)} | {os.path.join(h, ".local", "bin")}
    on_path = {d for d in on_path if d.startswith(h + os.sep)}
    cands = [full]
    if re.search(r"[*?\[]", full):  # the shell expands these; look at every file they could name
        parts = full.split(os.sep)  # as written: normpath would fold a `..` that follows a wildcard
        wild = [i for i, c in enumerate(parts) if re.search(r"[*?\[]", c)]
        # `..`, or a part that can match it (`.*`, `.[.]`): where it lands depends on the matches.
        if any(c == ".." or (c.startswith((".", "[")) and fnmatch.fnmatchcase("..", c)) for c in parts[wild[0]:]):
            return True
        if "**" in full or len(wild) > 2:
            # Too deep to expand inside the hook's time limit. Block it when its fixed part (symlinks
            # resolved) is, or leads into, a guarded folder. A symlink inside a deep wildcard part is a
            # known gap (docs/limitations.md).
            prefix = os.path.realpath(os.sep.join(parts[:wild[0]]) or os.sep).lower()
            guarded = whole + [os.path.join(h, f) for f in TOOL_HOME_FILES] + sorted(on_path)
            if any(g == prefix or g.startswith(prefix.rstrip(os.sep) + os.sep) or prefix.startswith(g + os.sep)
                   for g in guarded):
                return True
        else:  # at most two wildcard parts: expand, and judge every file they name
            found = list(itertools.islice(glob.iglob(full), GLOB_CAP + 1))
            if len(found) > GLOB_CAP:
                return True  # too many to judge: block rather than guess
            cands += found
    for cand in cands:
        real = os.path.realpath(cand).lower()
        if any(real == w or real.startswith(w + os.sep) for w in whole) or real in {
                os.path.join(h, f) for f in TOOL_HOME_FILES}:
            return True
        if os.path.dirname(real) in on_path and os.path.basename(real).startswith("python"):
            return True
    return False


def in_run_records(path: str, cur: str | None) -> bool:
    """A path inside `.etk/` (run ledgers: gates, permissions, release actions). Only the Lead writes them."""
    p = path.strip().strip("'\"")
    # Case-insensitive filesystems (macOS, Windows) treat `.ETK` as `.etk`; a glob such as
    # `.e*` can expand to it too.
    if re.search(r"(^|/)\.etk(/|$)", p, re.I) or any(
            part.startswith(".") and re.search(r"[*?\[]", part) and fnmatch.fnmatch(".etk", part.lower())
            for part in p.split("/")):  # a bare `*` doesn't match dotfiles in the shell
        return True
    full = absjoin(p, cur)
    return full is not None and re.search(r"/\.etk(/|$)", os.path.realpath(full), re.I) is not None


def in_git_control(path: str, cur: str | None) -> bool:
    """`.git/config` or a file under `.git/hooks/`: writing them changes where pushes go or what runs on
    the Lead's next commit/push, the same as the `git config` keys check_git refuses."""
    p = path.strip().strip("'\"")
    for spelled in (p, absjoin(p, cur)):
        if spelled is None:
            continue
        parts = os.path.normpath(spelled).replace("\\", "/").split("/")
        if any(a == ".git" and b in {"config", "config.worktree", "hooks", "info"}
               for a, b in zip(parts, parts[1:])):
            return True
        if any(a == ".git" and b == "worktrees" and c in {"config", "config.worktree"}
               for a, b, c in zip(parts, parts[1:], parts[3:])):
            return True
        if parts[-1:] == [".gitconfig"] or any(a == "git" and b in {"config", "attributes", "ignore"}
                                               and i > 0 and parts[i - 1] == ".config"
                                               for i, (a, b) in enumerate(zip(parts, parts[1:]))):
            return True
    return False


def check_protected(path: str, root: str, cur: str | None) -> None:
    if in_git_control(path, cur):
        raise Blocked(f"`{path}` is git's config or hooks; only the Lead changes where pushes go or what git runs")
    if in_run_records(path, cur):
        raise Blocked(f"`{path}` is an ETK run record; only the Lead writes the ledger")
    if in_plugin_data(path, cur):
        raise Blocked(f"`{path}` is in the plugin data dir (the developer's workflow profile); only the Lead "
                      f"records workflow profile / release decisions")
    if in_tool_home(path, cur):
        raise Blocked(f"`{path}` is Claude Code's settings, an installed plugin or a Python install; "
                      "only the user changes those")
    if is_protected(path, root, cur):
        raise Blocked(f"`{path}` is listed in protected_paths (.claude/engineering-team.json); ask the user first")


def check_write_target(target: str, role: str, root: str, cur: str | None) -> None:
    """A file a redirect (or `time -o`) will write."""
    check_protected(target, root, cur)
    if is_secret(target):
        raise Blocked(f"writing to `{target}` (looks like a secrets file)")
    if role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES:
        if target not in SAFE_SINKS and not scratch(target, root, cur):
            raise Blocked(f"{role} is read-only; it reports findings and the developer changes files")
    elif role == "qa-engineer" and target not in SAFE_SINKS and writes_existing(target, root, cur):
        raise Blocked("qa-engineer may only create new files, not change existing ones")


def callback_scripts(prog: str, args: list[str]) -> list[str]:
    """Command strings handed to builtins that run them later (mapfile -C, complete -C, bind -x)."""
    flag = {"mapfile": "C", "readarray": "C", "complete": "C", "bind": "x"}.get(prog)
    out = []
    for i, w in enumerate(args):
        if flag is None or not w.startswith("-") or w.startswith("--") or flag not in w[1:]:
            continue
        if w.endswith(flag) and i + 1 < len(args):
            out.append(args[i + 1])
        elif not w.endswith(flag):
            out.append(w[w.index(flag) + 1:])
    if prog == "bind":
        out = [v[v.rfind('":') + 2:] if '":' in v else v.split(":", 1)[-1] for v in out]
    return out


ETK_ENTRYPOINTS = {"etk.sh", "etk_run.py"}
PROFILE_WRITES = {"set", "unset", "confirm", "remember"}
LEDGER_WRITES = {"init", "phase", "authorize", "act", "decide"}


def check_etk_state(words: list[str]) -> None:
    """Only the Lead changes the workflow profile or records release decisions in the ledger."""
    for k, w in enumerate(words):
        base = os.path.basename(w)
        if k and words[k - 1] == "-m":  # python -m etk_profile
            base += ".py"
        rest = words[k + 1:]
        if base == "etk.sh" and rest[:1] in (["profile"], ["run"]):
            base, rest = ("etk_profile.py" if rest[0] == "profile" else "etk_run.py"), rest[1:]
        if base == "etk_profile.py":
            hit = any(x in PROFILE_WRITES for x in rest)  # `--data DIR` can sit anywhere: any write verb counts
        elif base == "etk_run.py":
            sub = next((x for x in rest if not x.startswith("-")), "")
            hit = sub in LEDGER_WRITES
        else:
            continue
        if hit:
            raise Blocked("only the Lead records workflow profile / release decisions; report what you found "
                          "to the Lead instead")


def etk_exec_command(words: list[str]) -> list[str] | None:
    """The command `etk.sh exec GATE --type T -- CMD...` will run, or None if this isn't that.

    The entry point can sit behind interpreter options (`python3 -u etk_run.py exec ...`). An `exec`
    that isn't right after it can't be told apart from the real thing, so that is blocked too."""
    for k, w in enumerate(words):
        if os.path.basename(w) not in ETK_ENTRYPOINTS:
            continue
        rest = words[k + 1:]
        if rest[:1] == ["exec"]:
            rest = rest[1:]
            if "--" not in rest:
                raise Blocked("`etk exec` without `-- <command>` can't be checked")
            return rest[rest.index("--") + 1:]
        if "exec" in rest:
            raise Blocked("`etk exec` with options before `exec` can't be checked; put `exec` right after the script")
    return None


def check_words(words: list[str], root: str, role: str, depth: int, cur: str | None, seg: Seg | None = None,
                outputs: list[str] | None = None, created: set | None = None,
                assigns: list[str] | None = None) -> None:
    """Judge one simple command (already stripped of wrappers and shell keywords).

    `assigns` are the NAME=VALUE words program_ex() stripped from in front of it."""
    read_only = role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES
    create_only = role == "qa-engineer"
    check_assigned(assigns or [], words, role)
    if not words:
        return
    redirs = seg.redirs if seg else []
    outputs = outputs or []
    created = created or set()
    prog = os.path.basename(words[0])
    if prog == "eval":
        check_bash(" ".join(words[1:]), root, role, depth + 1, cur)
        return
    check_etk_state(words)
    inner = etk_exec_command(words)
    if inner is not None:
        if read_only:
            raise Blocked(f"{role} is read-only; it can't run gate commands through `etk exec`")
        inner_words, _, inner_assigns = program_ex(inner)
        check_words(inner_words, root, role, depth + 1, cur, assigns=inner_assigns)
    if prog == "trap":
        ops = [w for w in words[1:] if w != "--"]
        if ops[:1] not in (["-l"], ["-p"]):
            if any(re.sub(r"^SIG", "", x.upper()) in {"DEBUG", "RETURN", "ERR", "EXIT", "0"} for x in ops[1:]):
                raise Blocked("`trap` on EXIT/ERR/DEBUG/RETURN runs code later that can't be checked")
            if ops and ops[0] != "-":
                check_bash(ops[0], root, role, depth + 1, None)  # runs later, from wherever we are then
    for script in callback_scripts(prog, words[1:]):
        check_bash(script, root, role, depth + 1, cur)
    if prog in SHELLS or prog in {"source", "."}:
        mode, script = shell_input(prog, words[1:], cur)
        if mode == "file" and script is not None and os.path.normpath(script) in created:
            raise Blocked(f"`{script}` is created earlier in this command; it could be a link to stdin, so the "
                          f"guard can't tell what it runs")
        if mode == "script":
            check_bash(script, root, role, depth + 1, cur)
        elif mode == "stdin":
            if seg is None or not (seg.heredocs or seg.herestrings):
                raise Blocked(f"`{prog}` reading commands from stdin can't be checked; pass a script file or use -c")
            for text in seg.herestrings + [body for body, _ in seg.heredocs]:
                check_bash(text, root, role, depth + 1, cur)
    if prog == "find":
        check_find(words[1:], root, role, depth, cur)
    check_deploy(words)
    targets = dest_operands(prog, words[1:]) if prog in SHELL_WRITERS else []
    if prog == "sed" and any(w == "--in-place" or w.startswith(("--in-place=", "-i")) for w in words[1:]) \
            or (re.match(r"^(perl|ruby)[\d.]*$", prog) and any(PERL_INPLACE.match(w) for w in words[1:])):
        targets = [w for w in words[1:] if not w.startswith("-")]
    for t in targets:
        if is_secret(t):
            raise Blocked(f"writing to `{t}` (looks like a secrets file)")
    if prog in SHELL_WRITERS:
        for t in write_operands(prog, words[1:]) + targets:
            check_protected(t, root, cur)
    else:
        for t in targets:
            check_protected(t, root, cur)
    if prog == "git":
        check_git(words[1:], root, cur)
    if prog == "rm":
        check_rm(words[1:], root, cur)
    if prog == "mv" and any(git_dir_path(w, cur) for w in words[1:] if not w.startswith("-")):
        raise Blocked("moving a .git directory would damage the repository")
    for target in redirect_targets(redirs) + outputs:
        check_write_target(target, role, root, cur)
    if create_only:
        if (prog in SHELL_WRITERS and any(writes_existing(t, root, cur) for t in write_operands(prog, words[1:]))) \
                or (prog == "sed" and any(w.startswith("-i") for w in words[1:])):
            raise Blocked("qa-engineer may only create new files, not change existing ones")
        qa_reason = rewrites_files(words) or (
            git_read_only_reason(words[1:], qa=True) if prog == "git" else None)
        if qa_reason:
            raise Blocked(f"qa-engineer may only create new files ({qa_reason})")
    if read_only:
        words = real_tool(words)
        prog = os.path.basename(words[0])
        ops = write_operands(prog, words[1:])
        writes = prog in SHELL_WRITERS and not (ops and all(scratch(t, root, cur) for t in ops))
        extra = rewrites_files(words) or read_only_extra_reason(words, root, cur)
        if writes or extra:
            raise Blocked(f"{role} is read-only; it reports findings and the developer changes files"
                          + (f" ({extra})" if extra else ""))


GIT_READ = {"diff", "log", "show", "status", "grep", "blame", "rev-parse", "ls-files", "ls-tree", "merge-base",
            "rev-list", "shortlog", "describe", "cat-file", "show-ref", "for-each-ref", "name-rev", "diff-tree",
            "diff-files", "diff-index", "count-objects", "check-ignore", "ls-remote", "version", "help",
            "whatchanged", "show-branch", "range-diff", "cherry", "verify-commit", "verify-tag"}
LIST_FLAGS = {"-a", "-r", "-v", "-vv", "-l", "--list", "--show-current", "--all", "--remotes", "--verbose", "-n", "-i",
              "--contains", "--no-contains", "--merged", "--no-merged", "--sort", "--format", "--points-at",
              "--column", "--no-column", "--color", "--no-color", "--ignore-case"}
INSTALL_SUBS = {
    "npm": {"install", "i", "ci", "add", "remove", "rm", "uninstall", "update", "upgrade", "link", "unlink", "dedupe",
            "prune", "rebuild", "init", "version", "patch", "install-test"},
    "pip": {"install", "uninstall", "download"}, "poetry": {"add", "install", "remove", "update", "lock", "init"},
    "uv": {"add", "sync", "remove", "lock", "init", "venv"}, "bundle": {"install", "update", "add", "remove"},
    "composer": {"install", "update", "require", "remove"}, "cargo": {"install", "add", "remove", "update", "fix"},
    "go": {"get", "install", "generate"}, "gem": {"install", "uninstall", "update"},
    "brew": {"install", "uninstall", "remove", "upgrade", "update"},
    "apt": {"install", "remove", "upgrade", "update", "purge"}, "apk": {"add", "del", "upgrade", "update"},
}
for _alias, _base in {"pnpm": "npm", "yarn": "npm", "bun": "npm", "pip3": "pip", "apt-get": "apt", "dnf": "apt",
                      "yum": "apt"}.items():
    INSTALL_SUBS[_alias] = INSTALL_SUBS[_base]


QA_GIT = {"add", "commit"}


GIT_ENV_HOOKS = re.compile(r"^(GIT_CONFIG_COUNT|GIT_CONFIG_KEY_\d+|GIT_CONFIG_VALUE_\d+|GIT_CONFIG_PARAMETERS|"
                           r"GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_EXTERNAL_DIFF|GIT_SSH|GIT_SSH_COMMAND|GIT_PAGER|"
                           r"GIT_ASKPASS|GIT_PROXY_COMMAND|GIT_EDITOR|GIT_SEQUENCE_EDITOR|GIT_EXEC_PATH|"
                           r"HOME|XDG_CONFIG_HOME|GIT_DIR|GIT_WORK_TREE|GIT_CONFIG|GIT_CONFIG_NOSYSTEM|GIT_COMMON_DIR|"
                           r"GIT_INDEX_FILE|GIT_OBJECT_DIRECTORY|GIT_ALTERNATE_OBJECT_DIRECTORIES)(=|$)")


_DIFF = """--stat --shortstat --numstat --name-only --name-status --summary --patch --no-patch --raw --cached --staged
--no-index --check --quiet --exit-code --color --no-color --color-words --color-moved --word-diff --word-diff-regex
--minimal --patience --histogram --diff-algorithm --ignore-space-change --ignore-all-space --ignore-blank-lines
--ignore-space-at-eol --ignore-cr-at-eol --find-renames --find-copies --find-copies-harder --no-renames
--diff-filter --function-context --unified --abbrev --full-index --binary --src-prefix --dst-prefix --no-prefix
--relative --text --submodule --dirstat --compact-summary --stat-width --stat-name-width --stat-count
--inter-hunk-context --merge-base --cc --combined --dense-combined --no-ext-diff --indent-heuristic
--no-indent-heuristic --irreversible-delete --pickaxe-all --pickaxe-regex --break-rewrites --find-object
--ws-error-highlight --line-prefix --no-color-moved --skip-to --rotate-to
-p -u -s -z -a -b -w -M -C -B -R -S -G -U -l -q -W -1 -2 -3 --""".split()
_LOG = """--oneline --graph --decorate --no-decorate --all --branches --tags --remotes --first-parent --merges --no-merges
--max-count --skip --since --until --after --before --author --committer --grep --invert-grep --all-match
--regexp-ignore-case --extended-regexp --fixed-strings --perl-regexp --format --pretty --date --reverse --follow
--simplify-by-decoration --simplify-merges --abbrev-commit --no-abbrev-commit --topo-order --date-order
--author-date-order --ancestry-path --left-right --cherry-pick --cherry-mark --cherry --boundary --walk-reflogs
--children --parents --show-signature --notes --no-notes --source --use-mailmap --no-use-mailmap --encoding
--log-size --relative-date --count --exclude --glob --not --no-walk --do-walk --full-history --sparse --dense
--show-pulls --max-parents --min-parents --left-only --right-only --objects --header --timestamp
-n -i -E -F -P -g -m -c -L --decorate-refs --decorate-refs-exclude --bisect --stdin --remove-empty""".split()
GIT_OPTION_ALLOW: dict = {}
GIT_OPTION_ALLOW.update({
    "diff": set(_DIFF), "diff-tree": set(_DIFF) | {"-r", "-t", "--root", "--stdin", "--no-commit-id", "-c"},
    "diff-files": set(_DIFF), "diff-index": set(_DIFF), "range-diff": set(_DIFF),
    "log": set(_DIFF) | set(_LOG), "show": set(_DIFF) | set(_LOG), "whatchanged": set(_DIFF) | set(_LOG),
    "rev-list": set(_LOG),
    "shortlog": set(_LOG) | {"-s", "-e", "--summary", "--numbered", "--email", "--group"},
    "status": set("""--short --branch --porcelain --long --untracked-files --ignored --ignore-submodules --no-renames
        --find-renames --column --no-column --show-stash --ahead-behind --no-ahead-behind --verbose -s -b -u -v -z
        --renames""".split()),
    "grep": set("""--count --line-number --ignore-case --word-regexp --invert-match --files-with-matches
        --files-without-match --name-only --extended-regexp --basic-regexp --perl-regexp --fixed-strings --no-index
        --untracked --cached --no-color --color --heading --break --full-name --max-depth --recursive
        --no-recursive --context --after-context --before-context --function-context --show-function --null --and
        --or --not --all-match --threads --quiet --only-matching --text --column --no-exclude-standard
        --exclude-standard -c -n -i -w -v -l -L -h -H -E -G -P -F -I -a -z -o -q -e -f -A -B -C -W -p -r --""".split()),
    "blame": set("""--porcelain --line-porcelain --incremental --show-name --show-number --show-email --date --abbrev
        --root --reverse --first-parent --since --ignore-rev --ignore-revs-file --show-stats --score-debug
        --minimal -L -p -s -e -w -M -C -b -f -n -t -l -c --""".split()),
    "rev-parse": set("""--short --verify --abbrev-ref --show-toplevel --git-dir --git-common-dir --absolute-git-dir
        --is-inside-work-tree --is-inside-git-dir --is-bare-repository --show-prefix --show-cdup --symbolic
        --symbolic-full-name --quiet --revs-only --no-revs --flags --no-flags --all --branches --tags --remotes
        --default --sq --path-format --show-superproject-working-tree --git-path --is-shallow-repository
        --show-object-format --prefix -q --""".split()),
    "ls-files": set("""--cached --deleted --modified --others --ignored --stage --unmerged --killed --exclude-standard
        --full-name --error-unmatch --directory --no-empty-directory --eol --abbrev --deduplicate --format --sparse
        --recurse-submodules --exclude -x -c -d -m -o -i -s -u -k -t -v -z -f --""".split()),
    "ls-tree": set("-r -d -t -l -z --name-only --name-status --full-name --full-tree --abbrev --long --object-only --".split()),
    "merge-base": set("--is-ancestor --octopus --independent --fork-point --all -a --".split()),
    "describe": set("""--tags --all --long --abbrev --always --contains --match --exclude --first-parent --dirty
        --candidates --exact-match --broken --debug""".split()),
    "cat-file": set("""-p -t -s -e --batch --batch-check --batch-all-objects --allow-unknown-type --follow-symlinks
        --batch-command --buffer -Z --""".split()),
    "show-ref": set("--heads --tags --verify --hash --abbrev --head --dereference --quiet --exists -d -s -q --".split()),
    "for-each-ref": set("""--format --sort --count --contains --no-contains --merged --no-merged --points-at --shell
        --perl --python --tcl --stdin --include-root-refs --ignore-case --omit-empty""".split()),
    "name-rev": set("--tags --refs --name-only --no-undefined --always --all --exclude".split()),
    "count-objects": set("-v -H --verbose --human-readable".split()),
    "check-ignore": set("-v -n --verbose --non-matching --stdin -z -q --quiet --no-index --".split()),
    "ls-remote": set("--heads --tags --refs --get-url --symref --sort -q --quiet -h -t --".split()),
    "version": {"--build-options"},
    "help": {"-a", "-g", "--all", "--guides"},
    "show-branch": set("""-a -r --all --remotes --topics --current --more --list --merge-base --independent --sha1-name
        --no-name --sparse --date-order --topo-order""".split()),
    "cherry": {"-v"}, "verify-commit": set("-v --verbose --raw".split()), "verify-tag": set("-v --verbose --raw".split()),
    "config": set("""--get --get-all --get-regexp --list -l --local --global --system --worktree --show-origin
        --show-scope --name-only -z --null --type --bool --int --default --includes --no-includes -f --file""".split()),
})
GIT_OPTION_ALLOW.update({
    "branch": LIST_FLAGS, "tag": LIST_FLAGS,
    "remote": {"-v", "--verbose", "--push", "--all"}, "worktree": {"--porcelain", "-z", "--verbose", "--detach", "--quiet", "-q", "-b", "-B"},
    "stash": set(_DIFF) | {"--include-untracked", "--only-untracked"},
    "reflog": set(_LOG) | {"--date"}, "submodule": {"--cached", "--recursive", "--quiet", "-q"},
    "add": set("""-A --all -u --update -N --intent-to-add -v --verbose -n --dry-run --ignore-errors --renormalize
        --no-warn-embedded-repo --""".split()),
    "commit": set("""-m --message -F --file -a --all -q --quiet --allow-empty --no-verify -s --signoff --author --date
        -v --verbose --no-edit --allow-empty-message --""".split()),
})
SHORT_WITH_VALUE = {"-n", "-U", "-S", "-G", "-L", "-M", "-C", "-x", "-A", "-B", "-e", "-f", "-m", "-u", "-l", "-c"}


def unknown_git_option(sub: str, rest: list[str]) -> str | None:
    """The first option that isn't on the subcommand's list of known read-only ones."""
    allowed = GIT_OPTION_ALLOW.get(sub)
    if allowed is None:  # no list for this subcommand: any option is unknown
        before_paths = rest[:rest.index("--")] if "--" in rest else rest
        return next((a for a in before_paths if a.startswith("-") and a != "-"), None)
    for a in rest:
        if a == "--":
            break
        if not a.startswith("-") or a == "-":
            continue
        name = a.split("=", 1)[0]
        if name in allowed or re.match(r"^-\d+$", a):
            continue
        if not a.startswith("--") and (name[:2] in allowed and name[:2] in SHORT_WITH_VALUE
                                       or all(f"-{c}" in allowed for c in a[1:])):
            continue
        return a
    return None


def git_read_only_reason(args: list[str], qa: bool = False) -> str | None:
    """Why this git command isn't read-only, or None. Subcommands outside an allowlist are refused."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C":
            i += 2
        elif args[i] in {"--no-pager", "--no-optional-locks"}:
            i += 1
        else:
            return f"`git {args[i]}` can run programs or change which repository is read"
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    bad = unknown_git_option(sub, rest)
    if bad:
        return f"`git {sub} {bad}` isn't an option the guard knows to be read-only"
    if sub in GIT_READ or (qa and sub in QA_GIT):
        return None
    if qa and sub == "worktree" and rest[:1] in (["add"], ["remove"], ["list"]):
        return None
    if sub == "branch" and all(a in LIST_FLAGS or not a.startswith("-") for a in rest) \
            and (not [a for a in rest if not a.startswith("-")] or set(rest) & {"-l", "--list", "--contains", "--merged",
                                                                                "--no-merged", "--points-at"}):
        return None
    if sub == "tag" and all(a.split("=", 1)[0] in LIST_FLAGS for a in rest):
        return None
    if sub == "remote" and rest[:1] in ([], ["-v"], ["-vv"], ["show"], ["get-url"]):
        return None
    if sub == "worktree" and rest[:1] == ["list"]:
        return None
    if sub == "stash" and rest[:1] in (["list"], ["show"]):
        return None
    if sub == "reflog" and rest[:1] in ([], ["show"], ["exists"]):
        return None
    if sub == "submodule" and rest[:1] in ([], ["status"], ["summary"]):
        return None
    if sub == "config" and len(rest) == 1 and not rest[0].startswith("-"):
        return None  # `git config user.name` only reads
    if sub == "config" and set(rest) & {"--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin"} \
            and not set(rest) & {"--add", "--unset", "--unset-all", "--replace-all", "--edit", "-e"}:
        return None
    return f"`git {sub}` can change the repository or working tree"


SNAPSHOT_FLAGS = {"--updateSnapshot", "--update-snapshot", "--update-snapshots", "--snapshot-update", "-update",
                  "--update-snapshots=all", "--update-snapshots=changed", "--update-snapshots=missing"}
SNAPSHOT_ENV = re.compile(r"^(UPDATE_SNAPSHOTS?|SNAPSHOT_UPDATE|INSTA_UPDATE|UPDATE_GOLDEN|GOLDEN_UPDATE)(=|$)", re.I)


def rewrites_files(words: list[str]) -> str | None:
    """In-place editors, formatters that write, and test runs that rewrite snapshots."""
    words = real_tool(words)
    prog = os.path.basename(words[0])
    args = words[1:]
    rest = [w for w in args if not w.startswith("-") and w not in {"exec", "dlx", "run"}]
    tool = os.path.basename(rest[0]) if prog in {"npx", "pnpx", "bunx", "pnpm", "yarn", "uvx", "pipx"} and rest else prog
    if (prog == "sed" and any(w.startswith("-i") or w.startswith("--in-place") for w in args)) \
            or (re.match(r"^(perl|ruby)[\d.]*$", prog) and any(PERL_INPLACE.match(w) for w in args)) \
            or any(w in {"--write", "--fix", "--apply", "--apply-unsafe"} or w.startswith(("--write=", "--fix="))
                   for w in args) \
            or (any(tool == name and (flag is None or flag in args) for name, flag in FORMATTER_WRITE)
                and not any(w in {"--check", "-check", "--diff", "--check-only", "-l", "--list-different"} for w in args)):
        return "it edits files in place"
    if any(w in SNAPSHOT_FLAGS or w.startswith("--update-snapshots=") for w in args) \
            or ("-u" in args and (tool in {"jest", "vitest", "ava", "tap"} or prog in {"npm", "pnpm", "yarn", "bun", "npx"})):
        return "it rewrites test snapshots"
    return None


def read_only_extra_reason(words: list[str], root: str, cur: str | None) -> str | None:
    """Mutations a read-only role must not make that the generic writer checks don't see."""
    prog = os.path.basename(words[0])
    args = words[1:]
    if prog == "git":
        return git_read_only_reason(args)
    pos = positionals(args, PKG_OPTS)
    if prog == "yarn" and not pos and not any(a in {"--version", "-v", "--help", "-h"} for a in args):
        return "bare `yarn` installs dependencies"
    if pos and pos[0] in INSTALL_SUBS.get(prog, set()):
        return f"`{prog} {pos[0]}` installs or changes packages"
    if prog == "go" and pos[:1] == ["mod"] and pos[1:2] and pos[1] != "graph" and pos[1] != "why":
        return "`go mod` rewrites go.mod"
    if prog == "uv" and pos[:2] == ["pip", "install"]:
        return "`uv pip install` installs packages"
    if prog in {"awk", "gawk", "mawk"} and ("inplace" in args or "-iinplace" in args):
        return "`awk -i inplace` edits files"
    if prog == "curl":
        outs = []
        for k, a in enumerate(args):
            if a in {"-o", "--output"} or (re.match(r"^-[a-zA-Z]+$", a) and a.endswith("o")):
                outs += args[k + 1:k + 2]  # -o FILE, or a cluster ending in o like -sSLo FILE
            elif a.startswith("--output="):
                outs.append(a.split("=", 1)[1])
        if any(o != "-" and o not in SAFE_SINKS and not scratch(o, root, cur) for o in outs):
            return "`curl -o` writes a file"
        if any(a in {"-O", "--remote-name", "--remote-name-all", "-T", "--upload-file"}
               or (re.match(r"^-[a-zA-Z]+$", a) and ("O" in a or "T" in a)) for a in args):
            return "`curl -O`/`-T` writes or uploads files"
    if prog == "wget":
        outs = [args[k + 1] for k, a in enumerate(args) if k + 1 < len(args) and (
            a in {"-O", "--output-document", "-P", "--directory-prefix"}
            or (re.match(r"^-[a-zA-Z]+$", a) and a[-1] in "OP"))]  # -qO FILE
        outs += [a.split("=", 1)[1] for a in args if a.startswith(("--output-document=", "--directory-prefix="))]
        outs += [m.group(1) for m in (re.match(r"^-[a-zA-Z]*[OP](.+)$", a) for a in args) if m]  # -O- / -qO-
        if "--spider" not in args and (not outs or any(
                o != "-" and o not in SAFE_SINKS and not scratch(o, root, cur) for o in outs)):
            return "`wget` saves files"
    if prog in {"tar", "bsdtar"}:
        first = args[0] if args else ""
        modes = set(first.lstrip("-")) if first and not first.startswith("--") else set()
        if modes & set("xcruA") or any(a in {"--extract", "--get", "--create", "--append", "--update", "--delete"}
                                       for a in args):
            return "`tar` extracts or creates archives"
    if prog == "unzip" and not any(a in {"-l", "-p", "-t", "-Z", "-v"} for a in args):
        d = [args[k + 1] for k, a in enumerate(args) if a == "-d" and k + 1 < len(args)]
        if not d or any(not scratch(x, root, cur) for x in d):
            return "`unzip` extracts files"
    return None


def files_created(seg: Seg) -> list[str]:
    """Paths this command may create or replace: link/copy/move destinations, tee, redirect targets."""
    words = program(seg.words)
    out = redirect_targets(seg.redirs)
    if words and os.path.basename(words[0]) in {"ln", "mv", "cp", "install", "tee", "touch", "dd"}:
        out += [w for w in words[1:] if not w.startswith("-")] + [w[3:] for w in words[1:] if w.startswith("of=")]
    return out


def check_assigned(assigns: list[str], words: list[str], role: str) -> None:
    """Variables a command sets that run code, redirect git, or rewrite snapshots."""
    assigned = variables_set(assigns, words)
    check_startup_hook_vars(assigned)
    if role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES or role == "qa-engineer":
        if any(GIT_ENV_HOOKS.match(w) for w in assigned):
            raise Blocked(f"{role} may not set git environment that runs programs or changes config")
        if any(SNAPSHOT_ENV.match(w) for w in assigned):
            raise Blocked(f"{role} may not rewrite test snapshots")


def check_bash(cmd: str, root: str, role: str, depth: int = 0, cur: str | None = UNSET) -> None:
    if depth > MAX_DEPTH:
        raise Blocked("command nests shells too deeply to check")
    if cur is UNSET:
        cur = root
    if depth == 0:
        global _CD_HOME
        _CD_HOME = safe_home(cmd)
    events = parse(cmd)
    read_only = role in READ_ONLY_ROLES or role in DOCS_ONLY_ROLES
    if (read_only or role == "qa-engineer") and WRITE_CODE.search(cmd) and any(runs_inline_code(program(e.words)) for e in events if isinstance(e, Seg)):
        raise Blocked(f"{role} may not change existing files; inline code that writes files isn't allowed")
    created = {os.path.normpath(t) for e in events if isinstance(e, Seg) for t in files_created(e)}
    dirs: list = []
    groups: list = []
    pending = False  # a cd whose success we assumed; a later `;`/`||` may run where it failed
    taint = False  # something may have set CDPATH through an expansion
    trapped = False  # a trap handler is installed: it can fire from any directory
    for seg in events:
        if seg is PUSH:
            groups.append((cur, list(dirs), pending))
            continue
        if seg is POP:
            if groups:
                cur, dirs, pending = groups.pop()
            continue
        if trapped:
            cur = None
        for body in seg.subs:
            check_bash(body, root, role, depth + 1, cur)
        for body, expands in seg.heredocs:
            if expands:  # an unquoted heredoc still runs $(...) and backticks; the rest is text
                for inner in find_subs(body):
                    check_bash(inner, root, role, depth + 1, cur)
        words, outputs, assigns = program_ex(seg.words)
        in_pipe = seg.sep in {"|", "|&"} or seg.after in {"|", "|&", "&"}
        bg_reset = pending and seg.after == "&"  # a backgrounded list runs in a subshell
        if pending and not in_pipe and seg.sep in {";", "||"}:
            cur, dirs[:], pending = None, ["?"], False
        first = os.path.basename(words[0]) if words else ""
        assignish = any(re.match(r"^\w+\+?=", w) for w in seg.words) or first in {
            "export", "declare", "typeset", "local", "readonly"}
        if (assignish and (seg.subs or any(re.search(r"[$`]", w) for w in seg.words))) \
                or first == "read" or (first == "printf" and "-v" in words):
            taint = True
        if any(re.search(r"\bCDPATH\b", w) for w in seg.words) and not in_pipe:
            cur = None  # `cd x` may land somewhere else entirely
        if words and os.path.basename(words[0]) in {"cd", "pushd", "popd"}:
            check_assigned(assigns, words, role)
            for t in [w for w in words[1:] if not w.startswith(("-", "+"))]:
                for spelled in {t, expand_home(t, _CD_HOME)}:
                    if in_run_records(spelled, cur) or in_plugin_data(spelled, cur):
                        raise Blocked(f"`cd {t}` goes into ETK run records or the plugin data dir; only the Lead "
                                      "works there (read files by their full path instead)")
            new = next_dir(words, cur, list(dirs) if in_pipe else dirs, taint)
            if not in_pipe:
                if seg.after in {";", "||"}:  # the cd may have failed, leaving us where we were
                    cur, dirs[:], pending = None, ["?"], False
                else:
                    cur, pending = new, True
            if bg_reset:
                cur, dirs[:], pending = None, ["?"], False
            continue
        if not in_pipe and any(os.path.basename(w) in {"cd", "pushd", "popd"} for w in words[1:]):
            cur = None  # a cd we can't attribute (find -exec cd, xargs cd): stay strict
        check_words(words, root, role, depth, cur, seg, outputs, created, assigns)
        if bg_reset:
            cur, dirs[:], pending = None, ["?"], False
        if words and os.path.basename(words[0]) == "trap" and not in_pipe:
            trapped = True
        if words and os.path.basename(words[0]) in {"eval", "source", ".", "trap"} and not in_pipe:
            cur, dirs[:] = None, ["?"]  # whatever it did to the directory isn't visible to us


# Browser tools act on pages, not on the project; everything else is judged by what its name says it does.
MCP_BROWSER = re.compile(r"^mcp__(claude-in-chrome|[\w-]*chrome-devtools[\w-]*|[\w-]*playwright[\w-]*)__")
MCP_WRITE_VERBS = {"push", "merge", "create", "delete", "write", "update", "publish", "deploy", "remove", "edit",
                   "commit", "upload", "send", "post", "promote", "put", "patch", "insert", "add", "set", "move",
                   "rename", "resolve", "reopen"}
MCP_READ = re.compile(r"^mcp__([\w-]*context7[\w-]*)__(resolve-library-id|get-library-docs)$")


def check_mcp(tool: str) -> None:
    if MCP_BROWSER.match(tool) or MCP_READ.match(tool):
        return
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", tool.split("__")[-1]).lower()
    verbs = MCP_WRITE_VERBS & set(re.split(r"[_\-\s]+", name))
    if verbs:
        raise Blocked(f"MCP tool `{tool}` looks like it changes something outside the project ({sorted(verbs)[0]}); "
                      f"the user decides that")


# Tools that only read, plan or report. Any other tool not checked in decide() is
# blocked for our agents, so a new shell-capable tool can't slip past the policy.
SAFE_TOOLS = {"Read", "Glob", "Grep", "LS", "NotebookRead", "LSP", "WebFetch", "WebSearch",
              "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskOutput",
              "BashOutput", "KillShell", "KillBash", "TaskStop", "ToolSearch", "Skill",
              "ListMcpResourcesTool", "ReadMcpResourceTool", "SendMessage"}
SHELL_TOOLS = {"Bash", "Monitor"}


def decide(data: dict) -> str | None:
    """Reason to block this tool call, or None to allow it."""
    if not isinstance(data, dict):
        return None  # nothing says this is one of our agents
    agent = str(data.get("agent_type") or "")
    if not agent.startswith(PREFIX):
        return None
    role = agent[len(PREFIX):]
    tool = data.get("tool_name")
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    try:
        if tool in SHELL_TOOLS:
            check_bash(str(inp.get("command", "")), cwd, role)
        elif isinstance(tool, str) and tool.startswith("mcp__"):
            check_mcp(tool)
        elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
            path = str(inp.get("file_path") or inp.get("notebook_path") or "")
            check_protected(path, cwd, cwd)
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
        elif tool not in SAFE_TOOLS:
            raise Blocked(f"the guard doesn't know the `{tool}` tool, so it can't check it; "
                          f"use Bash or the file tools")
    except Blocked as b:
        return str(b)
    except Exception as e:  # a guard that can't decide must not wave the call through
        return f"guard error ({type(e).__name__}: {e}); treating the call as unsafe"
    return None


# hooks.json gives the hook 10 s. Claude Code lets the tool call proceed when a hook times out, so the
# guard stops itself a little earlier and blocks: a slow check never counts as an allow.
BUDGET_SECONDS = 8


def _out_of_time(signum, frame):
    print("[engineering-team guard] blocked: the check ran out of time and couldn't be completed. "
          "Report it to the Lead.", file=sys.stderr)
    sys.stderr.flush()
    os._exit(2)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _out_of_time)
        signal.alarm(BUDGET_SECONDS)
    reason = decide(data)
    if reason is not None:
        print(f"[engineering-team guard] blocked: {reason}. If this is really needed, stop and report it "
              f"to the Lead so the user can decide.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
