#!/usr/bin/env python3
"""Per-developer workflow profile: how *this* developer commits, pushes, integrates and deploys here.

    etk_profile.py <sub> --data DIR [args]       (--data may come before or after <sub>)
      path                         print the profile file path (even if it doesn't exist yet)
      show [--brief|--json]        the profile (pretty JSON by default; --brief: at most 5 lines)
      detect                       facts read from the repository, as JSON (never writes, never prompts)
      set <dotted.path> <json>     e.g. set release.integrate '"pr"'   (a bare word counts as a string)
      unset <dotted.path>
      missing                      required facts still unknown, one per line (nothing when complete)
      confirm                      record that the developer reviewed the profile
      remember "<fact>" [--source user|detected]

The profile lives in Claude Code's per-plugin data dir (`${CLAUDE_PLUGIN_DATA}`), never in the
repository: `<data>/projects/<key>/profile.json`, where <key> hashes the normalized origin URL (so
https and ssh clones of one repo share it) or, without a remote, the repository root. The env var
isn't set for the model's Bash commands, so every call passes `--data` explicitly.

Repository content can never grant anything: release and deploy settings come only from `set`;
`detect` reports facts (names of files and branches, commit-subject statistics) and runs no
repository code. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

SCHEMA = 1
# Read-only git: no fsmonitor daemon, no hooks, no gpg for signatures, no lock files.
GIT = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "log.showSignature=false",
       "--no-optional-locks"]
UNSUBSTITUTED = {"${CLAUDE_PLUGIN_DATA}", "$CLAUDE_PLUGIN_DATA", "${CLAUDE_PLUGIN_DATA:-}"}
MAX_STR = 120
MAX_LIST = 10
MAX_MEMORY = 50
MAX_FACT = 300
CONVENTIONAL = re.compile(r"^[a-z]+(\(([^)]+)\))?!?: ")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]")
DEPLOY_WORD = re.compile(r"deploy|release|publish|ship", re.I)
CONTROL = re.compile(r"[\x00-\x1f\x7f]")

ENUMS = {
    "vcs.type": {"git", "svn", "none"},
    "host.type": {"github", "gitlab", "bitbucket", "azure", "other", "none"},
    "host.cli": {"gh", "glab", None},
    "branches.model": {"trunk", "feature", "gitflow"},
    "commit.style": {"conventional", "project"},
    "release.commit": {"auto", "confirm"},
    "release.push": {"auto", "confirm"},
    "release.integrate": {"pr", "merge", "none"},
    "release.merge.method": {"squash", "merge", "rebase"},
}
BOOLS = {"host.cli_authed", "commit.sign_off", "commit.gpg", "release.pr.draft", "release.merge.delete_branch",
         "release.wait_ci", "deploy.none"}
STRING_LISTS = {"branches.protected", "release.pr.reviewers", "release.pr.labels"}
STRINGS = {"branches.default", "branches.base", "branches.name_pattern", "commit.ticket_pattern", "release.pr.base",
           "commit.language"}
OBJECTS = {"vcs", "host", "branches", "commit", "release", "release.pr", "release.merge", "deploy"}
TARGET_KINDS = {"command", "ci-on-merge", "ci-on-tag", "manual"}
READ_ONLY_KEYS = {"schema", "project", "updated_at", "confirmed_at"}
SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class UsageError(Exception):
    """Bad input: exit 2 with the message, never a traceback."""


# ---------------------------------------------------------------- small helpers

def clip(s, n: int = MAX_STR) -> str:
    s = " ".join(CONTROL.sub(" ", str(s)).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], cwd, timeout: int = 10) -> str | None:
    """stdout on success, None on failure or timeout."""
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                             stdin=subprocess.DEVNULL, errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git(args: list[str], cwd, timeout: int = 10) -> str | None:
    return run(GIT + args, cwd, timeout)


def read_text(p: Path, limit: int = 200_000) -> str:
    try:
        if not p.is_file():
            return ""
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def read_json(p: Path):
    try:
        return json.loads(read_text(p) or "null")
    except ValueError:
        return None


# ---------------------------------------------------------------- data dir

def data_dir(raw: str | None) -> Path:
    """The validated plugin data dir. Refuses anything that isn't `.../plugins/data/<id>[/...]`."""
    if raw is None or not raw.strip():
        raise UsageError("--data DIR is required: the plugin data dir (${CLAUDE_PLUGIN_DATA} in skill text)")
    raw = raw.strip()
    if raw in UNSUBSTITUTED or "${" in raw or raw.startswith("$"):
        raise UsageError(f"--data {raw!r} was not substituted; pass the real plugin data dir "
                         "(~/.claude/plugins/data/<plugin-id>)")
    real = Path(os.path.realpath(os.path.expanduser(raw)))
    parts = real.parts
    if not any(parts[i] == "plugins" and parts[i + 1] == "data" for i in range(len(parts) - 2)):
        raise UsageError(f"--data {raw!r} is not a plugin data dir (expected a path like "
                         "~/.claude/plugins/data/<plugin-id>)")
    return real


# ---------------------------------------------------------------- project identity

def split_url(url: str) -> tuple[str, str, str, str] | None:
    """(scheme, userinfo, hostport, path) for URL and scp-like forms, None for local paths."""
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://([^/]*)(.*)$", url)
    if m:
        scheme, authority, path = m.group(1).lower(), m.group(2), m.group(3)
        if scheme == "file":
            return None
        user, _, hostport = authority.rpartition("@")
        return scheme, user, hostport, path
    m = re.match(r"^(?:([^@/:]+)@)?([^/:]+):(?!//)(.*)$", url)
    if m and not re.match(r"^[A-Za-z]$", m.group(2)):  # `C:\repo` is a path, not a host
        return "scp", m.group(1) or "", m.group(2), m.group(3)
    return None


def redact_remote(url: str | None) -> str | None:
    """The remote URL with credentials removed (an ssh user like `git@` is kept, passwords never)."""
    if not url:
        return None
    url = url.strip()
    parts = split_url(url)
    if parts is None:
        return clip(url, 300)
    scheme, user, hostport, path = parts
    if scheme == "scp":
        return clip(f"{user + '@' if user else ''}{hostport}:{path}", 300)
    keep = user if user and ":" not in user and scheme in {"ssh", "git+ssh", "ssh+git"} else ""
    return clip(f"{scheme}://{keep + '@' if keep else ''}{hostport}{path}", 300)


def normalize_remote(url: str) -> str:
    """`git@host:o/r.git`, `ssh://git@host:22/o/r`, `https://u:p@HOST/o/r/` -> `host/o/r`."""
    url = url.strip()
    parts = split_url(url)
    if parts is None:
        return url.rstrip("/")
    _, _, hostport, path = parts
    host = hostport.lower()
    m = re.match(r"^(\[[^\]]+\]|[^:]+)(?::(\d*))?$", host)
    if m:
        host = m.group(1)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    return f"{host}/{path}" if path else host


def host_type(remote: str | None) -> str:
    if not remote:
        return "none"
    parts = split_url(remote)
    if parts is None:
        return "other"
    host = re.sub(r":\d*$", "", parts[2].lower())
    if host == "github.com" or host.endswith(".github.com") or host == "ssh.github.com":
        return "github"
    if "gitlab" in host:
        return "gitlab"
    if host == "bitbucket.org" or host.endswith(".bitbucket.org"):
        return "bitbucket"
    if host in {"dev.azure.com", "ssh.dev.azure.com"} or host.endswith(".visualstudio.com"):
        return "azure"
    return "other"


def svn_root(cwd: Path) -> Path | None:
    if shutil.which("svn"):
        out = run(["svn", "info", "--non-interactive", "--show-item", "wc-root"], cwd, timeout=10)
        if out:
            return Path(out)
    for d in [cwd, *cwd.parents]:
        if (d / ".svn").is_dir():
            return d
    return None


def identify(cwd: Path | None = None) -> dict:
    """vcs type, root, raw origin URL and the profile key for the project at cwd."""
    cwd = Path(os.path.realpath(cwd or Path.cwd()))
    top = git(["rev-parse", "--show-toplevel"], cwd)
    if top:
        root = Path(os.path.realpath(top))
        remote = git(["config", "--get", "remote.origin.url"], root) or None
        vcs = "git"
    else:
        root, remote = svn_root(cwd), None
        vcs = "svn" if root else "none"
        root = Path(os.path.realpath(root)) if root else cwd
        if vcs == "svn" and shutil.which("svn"):
            remote = run(["svn", "info", "--non-interactive", "--show-item", "repos-root-url"], root) or None
    basis = "remote:" + normalize_remote(remote) if remote else "root:" + str(root)
    return {"vcs": vcs, "root": str(root), "remote": remote,
            "key": hashlib.sha256(basis.encode()).hexdigest()[:16]}


# ---------------------------------------------------------------- detection

def branch_facts(root: Path) -> tuple[str | None, bool]:
    default = None
    head = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], root)
    if head and head.startswith("refs/remotes/origin/"):
        default = head[len("refs/remotes/origin/"):]
    refs = (git(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin"], root) or "").splitlines()
    names = {r.split("/", 2)[2] if r.startswith("refs/heads/") else r.split("/", 3)[-1] for r in refs if r.count("/") >= 2}
    if not default:
        default = next((b for b in ("main", "master", "trunk", "develop") if b in names), None)
    if not default:
        default = git(["symbolic-ref", "--quiet", "--short", "HEAD"], root)  # fresh repo, nothing committed yet
    return (clip(default) if default else None), "develop" in names


def commit_facts(subjects: list[str]) -> tuple[str | None, str | None, list[str]]:
    if not subjects:
        return None, None, []
    matches = [CONVENTIONAL.match(s) for s in subjects]
    style = "conventional" if sum(1 for m in matches if m) >= 0.7 * len(subjects) else "project"
    language = "vi" if sum(1 for s in subjects if VIETNAMESE.search(s.lower())) >= 0.5 * len(subjects) else "en"
    scopes = Counter(m.group(2) for m in matches if m and m.group(2))
    return style, language, [clip(s, 40) for s, _ in scopes.most_common(8)]


def commit_tools(root: Path, git_dir: Path | None) -> list[str]:
    found = []
    try:
        top = sorted(p.name for p in root.iterdir())
    except OSError:
        top = []
    pkg = read_json(root / "package.json")
    pkg = pkg if isinstance(pkg, dict) else {}
    cfg = pkg.get("config") if isinstance(pkg.get("config"), dict) else {}
    lint = [n for n in top if re.match(r"^(commitlint\.config\.|\.commitlintrc)", n)]
    if lint or "commitlint" in pkg:
        found.append("commitlint (" + (lint[0] if lint else "package.json") + ")")
    cz = [n for n in top if n in {".czrc", ".cz.toml", ".cz.json", "cz.json"}]
    if not cz and "[tool.commitizen]" in read_text(root / "pyproject.toml"):
        cz = ["pyproject.toml"]
    if not cz and "commitizen" in cfg:
        cz = ["package.json"]
    if cz:
        found.append(f"commitizen ({cz[0]})")
    moji = [n for n in top if n.startswith(".gitmojirc")]
    if moji:
        found.append(f"gitmoji ({moji[0]})")
    hooks = []
    if (root / ".husky" / "commit-msg").is_file():
        hooks.append(".husky/commit-msg")
    hooks += [n for n in top if re.match(r"^\.?lefthook.*\.ya?ml$", n) and "commit-msg" in read_text(root / n)]
    if git_dir and (git_dir / "hooks" / "commit-msg").is_file():
        hooks.append(".git/hooks/commit-msg")
    if re.search(r"commit-msg", read_text(root / ".pre-commit-config.yaml")):
        hooks.append(".pre-commit-config.yaml")
    if hooks:
        found.append(f"commit-msg hook ({hooks[0]})")
    return [clip(x) for x in found][:MAX_LIST]


def deploy_candidates(root: Path) -> list[str]:
    """Names only. Nothing here is ever executed."""
    out = []
    for t in re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", read_text(root / "Makefile"), re.M):
        if DEPLOY_WORD.search(t):
            out.append(f"make {t}")
    pkg = read_json(root / "package.json")
    scripts = pkg.get("scripts") if isinstance(pkg, dict) and isinstance(pkg.get("scripts"), dict) else {}
    out += [f"package.json script `{clip(k, 60).replace('`', '')}`" for k in scripts if DEPLOY_WORD.search(str(k))]
    wf = root / ".github" / "workflows"
    try:
        flows = sorted(p for p in wf.iterdir() if p.suffix in {".yml", ".yaml"}) if wf.is_dir() else []
    except OSError:
        flows = []
    out += [f".github/workflows/{p.name}" for p in flows if re.search(r"deploy", read_text(p), re.I)]
    out += [n for n in (".gitlab-ci.yml", "bitbucket-pipelines.yml", "Jenkinsfile") if (root / n).is_file()]
    return [clip(x) for x in dict.fromkeys(out)][:MAX_LIST]


def cli_status(host: str) -> tuple[str | None, bool]:
    cli = {"github": "gh", "gitlab": "glab"}.get(host)
    if not cli or not shutil.which(cli):
        return None, False
    try:  # outside the repo: the CLI's auth lives in the user's config, not in the project
        r = subprocess.run([cli, "auth", "status"], cwd=os.path.expanduser("~"), capture_output=True, text=True,
                           timeout=5, stdin=subprocess.DEVNULL)
        return cli, r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return cli, False


def detect(cwd: Path | None = None, ident: dict | None = None) -> dict:
    ident = ident or identify(cwd)
    root = Path(ident["root"])
    remote = redact_remote(ident["remote"])
    host = host_type(ident["remote"]) if ident["vcs"] == "git" else ("other" if ident["remote"] else "none")
    cli, authed = cli_status(host)
    facts = {"vcs": ident["vcs"], "root": clip(ident["root"], 300), "remote": remote, "key": ident["key"],
             "host": host, "cli": cli, "cli_authed": authed, "default_branch": None, "has_develop": False,
             "commit_style": None, "commit_language": None, "scopes": [], "commit_tools": [],
             "deploy_candidates": []}
    git_dir = None
    if ident["vcs"] == "git":
        facts["default_branch"], facts["has_develop"] = branch_facts(root)
        log = git(["log", "-20", "--no-merges", "--format=%s"], root)
        subjects = [s for s in (log or "").splitlines() if s.strip()]
        facts["commit_style"], facts["commit_language"], facts["scopes"] = commit_facts(subjects)
        gd = git(["rev-parse", "--git-common-dir"], root)
        git_dir = (root / gd) if gd else None
    facts["commit_tools"] = commit_tools(root, git_dir)
    facts["deploy_candidates"] = deploy_candidates(root)
    return facts


# ---------------------------------------------------------------- store

def profile_path(data: Path, ident: dict) -> Path:
    return data / "projects" / ident["key"] / "profile.json"


def load(path: Path) -> dict:
    """The stored profile, {} when absent. A corrupt file is moved aside to profile.json.bak."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise UsageError(f"can't read {path}: {e}")
    try:
        prof = json.loads(text)
    except ValueError:
        prof = None
    if isinstance(prof, dict):
        return prof
    try:
        os.replace(path, path.with_name(path.name + ".bak"))
    except OSError:
        pass
    print(f"warning: {path} was not a JSON object; moved it to {path.name}.bak and started empty", file=sys.stderr)
    return {}


def save(path: Path, prof: dict, data: Path) -> None:
    if not data.exists():
        os.makedirs(data, mode=0o700, exist_ok=True)
    for d in (path.parent.parent, path.parent):
        d.mkdir(mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".profile.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(json.dumps(prof, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def stamp(prof: dict, ident: dict) -> dict:
    prof["schema"] = SCHEMA
    prof["project"] = {"remote": redact_remote(ident["remote"]), "root": ident["root"], "key": ident["key"]}
    prof["updated_at"] = now()
    return prof


# ---------------------------------------------------------------- dotted paths + validation

def split_path(dotted: str) -> list[str]:
    segs = dotted.split(".")
    if not dotted or not all(SEGMENT.match(s) for s in segs):
        raise UsageError(f"bad path {dotted!r}: use dotted names like release.integrate")
    if segs[0] in READ_ONLY_KEYS:
        raise UsageError(f"`{segs[0]}` is written by the script, not by `set`/`unset`")
    return segs


def get(prof, dotted: str):
    cur = prof
    for s in dotted.split("."):
        if not isinstance(cur, dict) or s not in cur:
            return None
        cur = cur[s]
    return cur


def validate(prof: dict) -> list[str]:
    errs = []
    for p in OBJECTS:
        v = get(prof, p)
        if v is not None and not isinstance(v, dict):
            errs.append(f"{p} must be an object")
    for p, allowed in ENUMS.items():
        v = get(prof, p)
        if _present(prof, p) and v not in allowed:
            errs.append(f"{p} must be one of " + ", ".join(sorted("null" if a is None else a for a in allowed)))
    for p in BOOLS:
        v = get(prof, p)
        if v is not None and not isinstance(v, bool):
            errs.append(f"{p} must be true or false")
    for p in STRINGS:
        v = get(prof, p)
        if v is not None and not isinstance(v, str):
            errs.append(f"{p} must be a string")
    lang = get(prof, "commit.language")
    if isinstance(lang, str) and not re.match(r"^(auto|[a-z]{2,3}(-[A-Za-z0-9]{2,8})?)$", lang):
        errs.append("commit.language must be en, auto or a language code like vi")
    for p in STRING_LISTS:
        v = get(prof, p)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            errs.append(f"{p} must be a list of strings")
    targets = get(prof, "deploy.targets")
    if targets is not None:
        if not isinstance(targets, list):
            errs.append("deploy.targets must be a list")
        else:
            for i, t in enumerate(targets):
                where = f"deploy.targets[{i}]"
                if not isinstance(t, dict):
                    errs.append(f"{where} must be an object")
                    continue
                if not isinstance(t.get("name"), str) or not t["name"].strip():
                    errs.append(f"{where}.name must be a non-empty string")
                if "production" in t and not isinstance(t["production"], bool):
                    errs.append(f"{where}.production must be true or false")
                if t.get("kind") not in TARGET_KINDS:
                    errs.append(f"{where}.kind must be one of {', '.join(sorted(TARGET_KINDS))}")
                for k in ("command", "verify", "rollback"):
                    if t.get(k) is not None and not isinstance(t[k], str):
                        errs.append(f"{where}.{k} must be a string or null")
                if t.get("kind") == "command" and not t.get("command"):
                    errs.append(f"{where}.command is required when kind is command")
    memory = prof.get("memory")
    if memory is not None and not (isinstance(memory, list) and all(
            isinstance(m, dict) and isinstance(m.get("fact"), str) for m in memory)):
        errs.append("memory must be a list of {fact, source, date} objects")
    return errs


def _present(prof: dict, dotted: str) -> set:
    """{dotted} when the key exists (even with a null value), else empty."""
    *parents, last = dotted.split(".")
    cur = prof
    for s in parents:
        if not isinstance(cur, dict) or s not in cur:
            return set()
        cur = cur[s]
    return {dotted} if isinstance(cur, dict) and last in cur else set()


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        if re.match(r"^[A-Za-z0-9_.:/@+-]+$", raw):
            return raw  # `set release.integrate pr` is fine too
        raise UsageError(f"value {clip(raw, 60)!r} is not valid JSON (quote strings: '\"pr\"')")


def set_value(prof: dict, dotted: str, value) -> dict:
    segs = split_path(dotted)
    new = json.loads(json.dumps(prof))
    cur = new
    for s in segs[:-1]:
        nxt = cur.setdefault(s, {})
        if not isinstance(nxt, dict):
            raise UsageError(f"can't set {dotted}: {s} is not an object")
        cur = nxt
    cur[segs[-1]] = value
    errs = [e for e in validate(new) if e not in set(validate(prof))]
    if errs:
        raise UsageError("; ".join(errs))
    return new


def unset_value(prof: dict, dotted: str) -> bool:
    segs = split_path(dotted)
    cur = prof
    for s in segs[:-1]:
        cur = cur.get(s) if isinstance(cur, dict) else None
    if isinstance(cur, dict) and segs[-1] in cur:
        del cur[segs[-1]]
        return True
    return False


# ---------------------------------------------------------------- reports

def missing(prof: dict, ident: dict) -> list[str]:
    out = []
    vcs = get(prof, "vcs.type")
    if vcs is None:
        if ident["vcs"] == "none":
            return []  # no version control here: nothing to commit, push or integrate
        out.append("vcs.type")
        vcs = ident["vcs"]
    decided = get(prof, "deploy.none") is True or bool(get(prof, "deploy.targets"))
    if vcs == "git":
        out += [p for p in ("branches.model", "release.push") if get(prof, p) is None]
        if ident["remote"] and get(prof, "release.integrate") is None:
            out.append("release.integrate")
        if get(prof, "commit.style") is None:
            out.append("commit.style")
        if not decided:
            out.append("deploy")
    elif vcs == "svn":
        if get(prof, "release.commit") is None:
            out.append("release.commit")
        if not decided:
            out.append("deploy")
    return out


def brief(prof: dict, path: Path) -> list[str]:
    if not prof:
        return ["no workflow profile yet"]
    first = [str(get(prof, "vcs.type") or "vcs ?")]
    host = get(prof, "host.type")
    if host and host != "none":
        cli = get(prof, "host.cli")
        first.append(f"{host} ({cli}, {'signed in' if get(prof, 'host.cli_authed') else 'not signed in'})" if cli else host)
    model = get(prof, "branches.model")
    base = get(prof, "branches.base") or get(prof, "branches.default")
    if model == "trunk":
        first.append("trunk-based" + (f" on {base}" if base else ""))
    elif model == "feature":
        first.append("feature branches" + (f" from {base}" if base else ""))
    elif model == "gitflow":
        first.append("gitflow" + (f" from {base}" if base else ""))
    style, lang = get(prof, "commit.style"), get(prof, "commit.language")
    if style or lang:
        first.append(", ".join(str(x) for x in (style, lang) if x))
    lines = [" · ".join(clip(x, 60) for x in first)]
    rel = []
    for k in ("commit", "push"):
        if get(prof, f"release.{k}"):
            rel.append(f"{k} {get(prof, f'release.{k}')}")
    integrate = get(prof, "release.integrate")
    method = get(prof, "release.merge.method")
    if integrate == "pr":
        rel.append("PR" + (" draft" if get(prof, "release.pr.draft") else "") + (f" ({method})" if method else ""))
    elif integrate == "merge":
        rel.append("merge" + (f" ({method})" if method else ""))
    elif integrate == "none":
        rel.append("no PR/merge")
    if get(prof, "release.wait_ci"):
        rel.append("wait for CI")
    lines.append("release: " + (" · ".join(rel) if rel else "not decided"))
    targets = get(prof, "deploy.targets")
    if get(prof, "deploy.none") is True:
        lines.append("deploy: none")
    elif isinstance(targets, list) and targets:
        shown = [f"{clip(t.get('name', '?'), 30)} ({t.get('kind', '?')}{', production' if t.get('production') else ''})"
                 for t in targets[:4] if isinstance(t, dict)]
        lines.append("deploy: " + ", ".join(shown) + (f", … {len(targets) - 4} more" if len(targets) > 4 else ""))
    else:
        lines.append("deploy: not decided")
    mem = prof.get("memory")
    if isinstance(mem, list) and mem:
        lines.append(f"memory: {len(mem)} note{'s' if len(mem) != 1 else ''}")
    lines.append(f"file: {path}" + ("" if prof.get("confirmed_at") else " (unconfirmed)"))
    return lines[:5]


def snapshot(raw_data: str | None, cwd: Path | None = None) -> tuple[list[str], list[str], Path]:
    """(brief lines, missing facts, profile path) for discover.py. Raises UsageError on a bad --data."""
    data = data_dir(raw_data)
    ident = identify(cwd)
    path = profile_path(data, ident)
    prof = load(path)
    return brief(prof, path), missing(prof, ident), path


# ---------------------------------------------------------------- CLI

def pop_data(argv: list[str]) -> tuple[str | None, list[str]]:
    data, rest, i = None, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--data" or a.startswith("--data="):
            if data is not None:
                raise UsageError("--data given twice")
            if a == "--data":
                if i + 1 >= len(argv):
                    raise UsageError("--data needs a directory")
                data, i = argv[i + 1], i + 2
            else:
                data, i = a.split("=", 1)[1], i + 1
            continue
        rest.append(a)
        i += 1
    return data, rest


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    ap = Parser(prog="etk.sh profile", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    sub.add_parser("path")
    show = sub.add_parser("show")
    g = show.add_mutually_exclusive_group()
    g.add_argument("--brief", action="store_true")
    g.add_argument("--json", action="store_true")
    sub.add_parser("detect")
    s = sub.add_parser("set")
    s.add_argument("dotted")
    s.add_argument("value")
    u = sub.add_parser("unset")
    u.add_argument("dotted")
    sub.add_parser("missing")
    sub.add_parser("confirm")
    r = sub.add_parser("remember")
    r.add_argument("fact")
    r.add_argument("--source", choices=["user", "detected"], default="user")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        raw, rest = pop_data(argv)
        a = build_parser().parse_args(rest)
        data = data_dir(raw)
        ident = identify()
        root = Path(ident["root"])
        if ident["vcs"] != "none" and (data == root or root in data.parents):
            raise UsageError(f"--data {data} is inside the repository; the profile must live outside it")
        path = profile_path(data, ident)
        if a.cmd == "path":
            print(path)
        elif a.cmd == "detect":
            print(json.dumps(detect(ident=ident), indent=2, ensure_ascii=False))
        elif a.cmd == "show":
            prof = load(path)
            if a.brief:
                print("\n".join(brief(prof, path)))
            elif not prof:
                print("no workflow profile yet" if not a.json else "{}")
            else:
                print(json.dumps(prof, indent=2, ensure_ascii=False))
        elif a.cmd == "missing":
            for m in missing(load(path), ident):
                print(m)
        elif a.cmd == "set":
            prof = set_value(load(path), a.dotted, parse_value(a.value))
            save(path, stamp(prof, ident), data)
            print(f"set {a.dotted}")
        elif a.cmd == "unset":
            prof = load(path)
            if unset_value(prof, a.dotted):
                save(path, stamp(prof, ident), data)
                print(f"unset {a.dotted}")
            else:
                print(f"{a.dotted} was not set", file=sys.stderr)
        elif a.cmd == "confirm":
            prof = stamp(load(path), ident)
            prof["confirmed_at"] = prof["updated_at"]
            save(path, prof, data)
            print(f"confirmed {path}")
        elif a.cmd == "remember":
            fact = clip(a.fact, MAX_FACT)
            if not fact:
                raise UsageError("remember needs a non-empty fact")
            prof = load(path)
            mem = prof.get("memory") if isinstance(prof.get("memory"), list) else []
            mem.append({"fact": fact, "source": a.source, "date": dt.date.today().isoformat()})
            prof["memory"] = mem[-MAX_MEMORY:]
            save(path, stamp(prof, ident), data)
            print(f"remembered ({len(prof['memory'])} note(s))")
        return 0
    except UsageError as e:
        print(f"etk profile: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"etk profile: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
