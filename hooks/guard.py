#!/usr/bin/env python3
"""PreToolUse guard for ETK subagents.

Only acts when the tool call comes from one of this plugin's agents
(`agent_type` starts with "engineering-team:"). The main session and every
other agent are left alone: the user's own permission settings already cover
them, and a plugin should not change how unrelated sessions behave.

Blocks (exit 2, reason on stderr so the agent can adapt):
  - pushing, merging PRs, publishing, deploying
  - discarding work: reset --hard, clean -f, checkout/restore of paths, stash, branch -D
  - history rewrites: rebase, commit --amend, push --force
  - rm -rf on /, ~, .., or absolute paths outside the project
  - staging or writing obvious secret files (.env, *.pem, id_rsa, ...)

This is a seatbelt, not a sandbox. A determined command can get around regex
checks; the point is to stop the common accidents agents actually make.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

PREFIX = "engineering-team:"

BASH_RULES: list[tuple[str, str]] = [
    (r"\bgit\s+push\b", "pushing is up to the user; leave commits local"),
    (r"\bgit\s+reset\s+(--hard|--merge|--keep)\b", "reset --hard discards work; ask the Lead instead"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*f", "git clean deletes untracked files that may be the user's"),
    (r"\bgit\s+checkout\s+(--\s|\.(\s|$)|-f\b|--force\b)", "checkout of paths discards uncommitted changes"),
    (r"\bgit\s+restore\b(?!.*--staged\b)", "git restore discards uncommitted changes"),
    (r"\bgit\s+stash\b(?!\s+(list|show)\b)", "git stash rewrites the working tree the user is using; use a temporary worktree for base comparisons"),
    (r"\bgit\s+branch\s+(-D|--delete\s+--force)\b", "force-deleting a branch can lose commits"),
    (r"\bgit\s+rebase\b", "history rewrites are the Lead's call, not a subagent's"),
    (r"\bgit\s+commit\b.*--amend\b", "amending rewrites history; make a new commit"),
    (r"\bgit\s+(filter-branch|filter-repo|update-ref\s+-d)\b", "history rewrites are not allowed here"),
    (r"\bgh\s+(pr\s+merge|release\s+create|repo\s+delete)\b", "merging/releasing needs explicit user approval"),
    (r"\b(npm|pnpm|yarn)\s+publish\b|\bcargo\s+publish\b|\btwine\s+upload\b|\bgem\s+push\b", "publishing packages needs explicit user approval"),
    (r"\bshopify\s+(app\s+(deploy|release)|theme\s+(push|publish|delete))\b", "deploying to a Shopify store needs explicit user approval"),
    (r"\b(vercel\s+.*--prod|netlify\s+deploy\s+.*--prod|fly\s+deploy|firebase\s+deploy|serverless\s+deploy|sls\s+deploy)\b", "deploys need explicit user approval"),
    (r"\b(kubectl\s+(apply|delete|replace|rollout)|helm\s+(install|upgrade|uninstall)|terraform\s+(apply|destroy)|pulumi\s+(up|destroy))\b", "infrastructure changes need explicit user approval"),
    (r"\bdocker\s+push\b", "pushing images needs explicit user approval"),
    (r"\b(psql|mysql|sqlite3|mongosh)\b.*\b(drop\s+(table|database)|truncate\s+table|dropDatabase)", "destructive SQL needs explicit user approval"),
]

SECRET_NAME = re.compile(
    r"(^|/)(\.env(\.[\w-]+)?|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.key|credentials\.json|service-account.*\.json|\.npmrc|\.pypirc)$"
)
SECRET_OK = re.compile(r"\.(example|sample|template|dist)$")


def deny(reason: str) -> None:
    print(f"[engineering-team guard] blocked: {reason}. If this is really needed, stop and report it "
          f"to the Lead so the user can decide.", file=sys.stderr)
    sys.exit(2)


def is_secret(path: str) -> bool:
    p = path.strip().strip("'\"")
    return bool(SECRET_NAME.search(p)) and not SECRET_OK.search(p)


def check_rm(cmd: str, cwd: str) -> None:
    for segment in re.split(r"&&|\|\||;|\|", cmd):
        try:
            words = shlex.split(segment)
        except ValueError:
            words = segment.split()
        if not words or os.path.basename(words[0]) != "rm":
            continue
        flags = "".join(w[1:] for w in words[1:] if w.startswith("-") and not w.startswith("--"))
        recursive = "r" in flags.lower() or "--recursive" in words
        if not recursive:
            continue
        for target in (w for w in words[1:] if not w.startswith("-")):
            t = os.path.expanduser(target)
            if target in {"/", "~", "..", ".", "*", "./*"} or target.startswith("~") or target.startswith("$HOME"):
                deny(f"`rm -r {target}` is too broad")
            if os.path.isabs(t):
                real = os.path.realpath(t)
                base = os.path.realpath(cwd)
                if not (real == base or real.startswith(base + os.sep)) and not real.startswith(("/tmp/", "/var/folders/")):
                    deny(f"`rm -r {target}` is outside the project")


def check_bash(cmd: str, cwd: str) -> None:
    for pattern, reason in BASH_RULES:
        if re.search(pattern, cmd, re.I if "psql" in pattern else 0):
            deny(reason)
    check_rm(cmd, cwd)
    if re.search(r"\bgit\s+(add|commit)\b", cmd):
        try:
            words = shlex.split(cmd)
        except ValueError:
            words = cmd.split()
        for w in words:
            if is_secret(w):
                deny(f"`{w}` looks like a secret file and must not be committed")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not str(data.get("agent_type") or "").startswith(PREFIX):
        return 0
    tool = data.get("tool_name")
    inp = data.get("tool_input") or {}
    if tool == "Bash":
        check_bash(str(inp.get("command", "")), data.get("cwd") or os.getcwd())
    elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = str(inp.get("file_path") or inp.get("notebook_path") or "")
        if is_secret(path):
            deny(f"writing `{path}` (looks like a secrets file); edit the .example version instead")
    return 0


if __name__ == "__main__":
    sys.exit(main())
