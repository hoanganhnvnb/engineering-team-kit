#!/usr/bin/env python3
"""Run one end-to-end scenario against a throwaway copy of a fixture.

    python3 tests/e2e/run.py <fixture> "<slash command + args>" [--out DIR] [--check "<cmd>"]
                             [--model M] [--overlay NAME] [--keep] [--bypass] [--ship]

What it does:
  1. copies tests/fixtures/<fixture> to a temp dir, `git init` + commit (clean baseline)
  2. runs `claude -p --plugin-dir <this repo> --output-format stream-json` there
  3. collects evidence: which subagents/skills were used, the diff, the ETK ledger
     check, and (optionally) re-runs the project's tests itself instead of trusting
     the transcript
  4. writes transcript.jsonl + summary.json to --out

--ship sets the project up for the release flow: a local bare repo as `origin`, a
`deploy.sh` that writes a marker next to the project, and a workflow profile (push auto,
no PR, one staging target) in the data dir Claude Code uses for --plugin-dir plugins.
The summary then shows what reached origin and whether the deploy ran.

This spends real model tokens. By default it runs with acceptEdits and a short
shell allowlist (ALLOWED_TOOLS); commands outside it are denied, which can make a
scenario fail rather than run something unexpected. --bypass removes that limit and
should only be used in a disposable VM or container.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
ETK_SCRIPT = REPO / "scripts" / "etk_run.py"
ETK_SH = REPO / "scripts" / "etk.sh"
ETK_PROFILE = REPO / "scripts" / "etk_profile.py"
# Claude Code's data dir for a plugin loaded with --plugin-dir.
INLINE_DATA = Path.home() / ".claude" / "plugins" / "data" / "engineering-team-inline"
SHIP_PROFILE = {
    "vcs": {"type": "git"}, "branches": {"model": "trunk", "default": "main"},
    "commit": {"style": "conventional", "language": "en"},
    "release": {"commit": "auto", "push": "auto", "integrate": "none", "wait_ci": False},
    "deploy": {"targets": [{"name": "staging", "production": False, "kind": "command",
                            "command": "sh deploy.sh", "verify": "test -f ../deployed.txt"}]},
}
SHIP_TOOLS = ["Bash(git push:*)", f'Bash(sh "{ETK_SH}" exec:*)', f"Bash(sh {ETK_SH} exec:*)",
              f'Bash(sh "{ETK_SH}" profile:*)', f"Bash(sh {ETK_SH} profile:*)",
              f'Bash(sh "{ETK_SH}" discover:*)', f"Bash(sh {ETK_SH} discover:*)",
              "Bash(git checkout -b:*)", "Bash(git switch -c:*)", "Bash(echo:*)", "Bash(sh deploy.sh)",
              "Bash(test -f ../deployed.txt)"]
ALLOWED_TOOLS = [
    # Narrow, fixed prefixes only: no bare interpreters, no find -exec, no arbitrary npm scripts.
    # This limits accidents. It is NOT an isolation boundary: a test file the agent writes
    # still runs under `npm test`. Use a container/VM for anything you don't trust.
    "Read", "Edit", "Write", "Glob", "Grep", "Agent", "Skill",
    "Bash(npm test)", "Bash(npm test:*)", "Bash(node --test:*)",
    "Bash(python3 -m unittest:*)",
    f"Bash(python3 {ETK_SCRIPT}:*)", f'Bash(python3 "{ETK_SCRIPT}":*)',
    f'Bash(sh "{ETK_SH}" run:*)', f"Bash(sh {ETK_SH} run:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git worktree:*)", "Bash(git apply:*)",
    "Bash(git rev-parse:*)", "Bash(git ls-files:*)", "Bash(git branch:*)", "Bash(git merge-base:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)", "Bash(grep:*)",
    "Bash(curl -s http://localhost:*)", "Bash(shopify theme check:*)",
]


def sh(cmd, cwd, timeout=600, shell=False):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=shell)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("prompt")
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", default=None, help="command to re-run in the result dir (e.g. 'npm test')")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--model", default=None)
    ap.add_argument("--keep", action="store_true", help="keep the temp project dir")
    ap.add_argument("--overlay", default=None,
                    help="dir under tests/fixtures/overlays copied over the project after the baseline commit")
    ap.add_argument("--ship", action="store_true", help="local origin + deploy marker + a ship profile")
    ap.add_argument("--bypass", action="store_true",
                    help="run with --permission-mode bypassPermissions. The agent can then run ANY command "
                         "as you, not only inside the temp dir. Use only in a disposable VM/container.")
    a = ap.parse_args()

    src = FIXTURES / a.fixture
    if not src.is_dir():
        sys.exit(f"no fixture {src}")
    out = Path(a.out or REPO / "tests" / "e2e" / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-{a.fixture}")
    out.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix=f"etk-{a.fixture}-")) / a.fixture
    shutil.copytree(src, work)
    if a.ship:
        (work / "deploy.sh").write_text("#!/bin/sh\n# e2e stand-in for a deploy: leave a marker beside the project\n"
                                        "date > ../deployed.txt\n")
    sh(["git", "init", "-q", "-b", "main"], work)
    sh(["git", "add", "-A"], work)
    sh(["git", "-c", "user.email=e2e@example.com", "-c", "user.name=e2e", "commit", "-q", "-m", "fixture baseline"], work)

    profile_path = None
    if a.ship:
        origin = work.parent / "origin.git"
        sh(["git", "init", "-q", "--bare", "-b", "main", str(origin)], work)
        sh(["git", "remote", "add", "origin", str(origin)], work)
        sh(["git", "push", "-q", "-u", "origin", "main"], work)
        INLINE_DATA.mkdir(parents=True, exist_ok=True)
        r = sh([sys.executable, str(ETK_PROFILE), "path", "--data", str(INLINE_DATA)], work)
        profile_path = Path(r.stdout.strip())
        profile_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile_path.write_text(json.dumps({"schema": 1, **SHIP_PROFILE}, indent=2))
        # Bind it to this checkout and push URL, as onboarding would; an unbound profile's
        # `auto` settings don't count.
        r = sh([sys.executable, str(ETK_PROFILE), "confirm", "--data", str(INLINE_DATA)], work)
        if r.returncode:
            raise SystemExit(f"profile confirm failed: {r.stderr}")
    if a.overlay:
        shutil.copytree(FIXTURES / "overlays" / a.overlay, work, dirs_exist_ok=True)
    cmd = ["claude", "-p", a.prompt, "--plugin-dir", str(REPO), "--output-format", "stream-json", "--verbose"]
    if a.bypass:
        print("warning: --bypass gives the agent unrestricted shell access as your user", file=sys.stderr)
        cmd += ["--permission-mode", "bypassPermissions"]
    else:
        # File edits are auto-accepted; shell access is limited to what the scenarios need.
        cmd += ["--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS, *(SHIP_TOOLS if a.ship else [])]
    if a.model:
        cmd += ["--model", a.model]
    started = time.time()
    proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=a.timeout, stdin=subprocess.DEVNULL)
    elapsed = round(time.time() - started)
    (out / "transcript.jsonl").write_text(proc.stdout)
    if proc.stderr:
        (out / "stderr.txt").write_text(proc.stderr)

    agents, skills, bash, final, cost = [], [], [], "", None
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") != "tool_use":
                    continue
                inp = block.get("input", {})
                if block["name"] in ("Agent", "Task"):
                    agents.append({"type": inp.get("subagent_type"), "description": inp.get("description"),
                                   "isolation": inp.get("isolation"),
                                   "nested": ev.get("parent_tool_use_id") is not None})
                elif block["name"] == "Skill":
                    skills.append(inp.get("skill"))
                elif block["name"] == "Bash" and ev.get("parent_tool_use_id") is None:
                    bash.append(inp.get("command", "")[:200])
        elif ev.get("type") == "result":
            final = ev.get("result", "")
            cost = ev.get("total_cost_usd")

    diff_stat = sh(["git", "diff", "--stat", "HEAD"], work).stdout.strip()
    untracked = sh(["git", "ls-files", "--others", "--exclude-standard"], work).stdout.split()
    (out / "diff.patch").write_text(sh(["git", "diff", "HEAD"], work).stdout)
    ledger = sh([sys.executable, str(REPO / "scripts" / "etk_run.py"), "check"], work)
    render = sh([sys.executable, str(REPO / "scripts" / "etk_run.py"), "render"], work)
    latest = sh([sys.executable, str(REPO / "scripts" / "etk_run.py"), "latest"], work).stdout.strip()
    if latest and Path(latest, "gates.json").exists():
        shutil.copy(Path(latest, "gates.json"), out / "gates.json")
    check = None
    if a.check:
        r = sh(a.check, work, shell=True)
        check = {"cmd": a.check, "exit_code": r.returncode, "tail": (r.stdout + r.stderr)[-1500:]}

    ship = None
    if a.ship:
        base = sh(["git", "--git-dir", str(work.parent / "origin.git"), "log", "--format=%h %s", "main"], work)
        ship = {"origin_log": base.stdout.strip().splitlines()[:10],
                "pushed": len(base.stdout.strip().splitlines()) > 1,
                "deployed": (work.parent / "deployed.txt").exists(),
                "local_ahead": sh(["git", "rev-list", "--count", "origin/main..HEAD"], work).stdout.strip()}
        if profile_path:
            shutil.rmtree(profile_path.parent, ignore_errors=True)

    summary = {
        "fixture": a.fixture, "prompt": a.prompt, "exit_code": proc.returncode, "seconds": elapsed,
        "cost_usd": cost, "subagents": agents, "skills": skills, "lead_bash": bash,
        "diff_stat": diff_stat, "untracked": untracked,
        "ledger_check": {"exit_code": ledger.returncode, "output": ledger.stdout.strip()[-1500:]},
        "independent_check": check, "ship": ship, "workdir": str(work) if a.keep else None,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "report.md").write_text(final + "\n\n---\n\n## Ledger render\n\n" + render.stdout)
    print(json.dumps({k: summary[k] for k in ("fixture", "exit_code", "seconds", "cost_usd", "subagents", "skills",
                                              "diff_stat", "untracked", "ledger_check", "independent_check", "ship")}, indent=2))
    print(f"\nresults: {out}")
    if not a.keep:
        shutil.rmtree(work.parent, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
