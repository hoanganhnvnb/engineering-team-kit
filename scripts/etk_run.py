#!/usr/bin/env python3
"""Run ledger for ETK: create a run, check its gates, render the report.

    etk_run.py init "<task>" [--mode small|medium|large] [--kind build|fix|review|test|improve-ui]
    etk_run.py check [RUN_DIR|gates.json]     # exit 1 if the ledger is inconsistent
    etk_run.py render [RUN_DIR|gates.json]    # markdown summary for the final report
    etk_run.py latest                         # print the newest run dir

The ledger (`.etk/runs/<id>/gates.json`) is the single source of truth for
gate status and findings. `check` is deliberately strict: it is the thing that
stops "all tests pass" from being claimed when nothing ran.

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

GATES = {
    "G1": "Requirements & acceptance criteria",
    "G2": "Architecture & code review",
    "G3": "Automated tests",
    "G4": "Regression",
    "G5": "UI/UX & accessibility",
    "G6": "Security & compatibility",
}
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}
SEVERITIES = ["critical", "high", "medium", "low"]
FINDING_STATUSES = {"open", "fixed", "verified", "disputed", "accepted_risk", "wont_fix"}
BLOCKING = {"critical", "high"}
OUTCOMES = {"COMPLETE", "INCOMPLETE", "BLOCKED", "IN_PROGRESS"}
# Gates that can only be NOT_APPLICABLE with a real reason, never skipped silently.
ALWAYS_APPLICABLE = {"G1"}
# Gates whose PASS must be backed by commands that actually ran.
COMMAND_BACKED = {"G3", "G4"}
# Gates that must be settled (not NOT_RUN) before a run of this kind is COMPLETE.
# review/test runs only own part of the picture; the rest may stay NOT_RUN.
REQUIRED_BY_KIND = {
    "build": set(GATES),
    "fix": set(GATES),
    "improve-ui": set(GATES),
    "review": {"G2", "G6"},
    "test": {"G3", "G4"},
}
NEEDS_AC = {"build", "fix", "improve-ui"}
FINDING_FIELDS = ["id", "severity", "location", "evidence", "expected", "actual", "remediation", "status"]
MIN_EVIDENCE = 12


def git_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return Path(out.stdout.strip())
    except OSError:
        pass
    return Path.cwd()


def runs_dir() -> Path:
    return git_root() / ".etk" / "runs"


def exclude_from_git(root: Path) -> None:
    """Keep run files out of `git status` without touching the tracked .gitignore."""
    git_dir = root / ".git"
    if not git_dir.is_dir():  # worktree or no git: skip quietly
        return
    excl = git_dir / "info" / "exclude"
    try:
        excl.parent.mkdir(parents=True, exist_ok=True)
        text = excl.read_text() if excl.exists() else ""
        if ".etk/" not in text.split():
            excl.write_text(text + ("" if text.endswith("\n") or not text else "\n") + ".etk/\n")
    except OSError:
        pass


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40] or "task"


def cmd_init(a) -> int:
    root = git_root()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run = runs_dir() / f"{stamp}-{slug(a.task)}"
    run.mkdir(parents=True, exist_ok=False)
    exclude_from_git(root)
    ledger = {
        "task": a.task,
        "kind": a.kind,
        "mode": a.mode,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "acceptance_criteria": [],
        "gates": {g: {"status": "NOT_RUN", "evidence": "", "commands": []} for g in GATES},
        "findings": [],
        "cycles": 0,
        "max_cycles": a.max_cycles,
        "outcome": "IN_PROGRESS",
        "notes": [],
    }
    (run / "gates.json").write_text(json.dumps(ledger, indent=2) + "\n")
    print(run)
    return 0


def resolve(path: str | None) -> Path:
    if not path:
        latest = latest_run()
        if not latest:
            sys.exit("no ETK run found; run `etk_run.py init` first")
        return latest / "gates.json"
    p = Path(path)
    return p / "gates.json" if p.is_dir() else p


def latest_run() -> Path | None:
    d = runs_dir()
    runs = sorted(x for x in d.iterdir() if (x / "gates.json").exists()) if d.exists() else []
    return runs[-1] if runs else None


def validate(ledger: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    gates = ledger.get("gates") or {}
    outcome = ledger.get("outcome")
    if outcome not in OUTCOMES:
        errors.append(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")

    kind = ledger.get("kind", "build")
    if kind not in REQUIRED_BY_KIND:
        errors.append(f"kind must be one of {sorted(REQUIRED_BY_KIND)}, got {kind!r}")
    required = REQUIRED_BY_KIND.get(kind, set(GATES))
    if not ledger.get("acceptance_criteria"):
        (errors if outcome == "COMPLETE" and kind in NEEDS_AC else warnings).append("acceptance_criteria is empty")

    for g in GATES:
        gate = gates.get(g)
        if not isinstance(gate, dict):
            errors.append(f"{g}: missing")
            continue
        st = gate.get("status")
        ev = (gate.get("evidence") or "").strip()
        if st not in STATUSES:
            errors.append(f"{g}: invalid status {st!r}")
            continue
        if st != "NOT_RUN" and len(ev) < MIN_EVIDENCE:
            errors.append(f"{g}: status {st} needs evidence or a justification (got {ev!r})")
        if st == "NOT_APPLICABLE" and g in ALWAYS_APPLICABLE:
            errors.append(f"{g}: cannot be NOT_APPLICABLE")
        if st == "PASS" and g in COMMAND_BACKED:
            cmds = gate.get("commands") or []
            if not cmds:
                errors.append(f"{g}: PASS without any recorded command — tests that did not run cannot pass")
            for c in cmds:
                if not isinstance(c, dict) or not c.get("cmd"):
                    errors.append(f"{g}: each command needs a 'cmd'")
                elif c.get("exit_code") != 0:
                    # G4 only: a red suite can still mean "no regression" if every failure is
                    # proven to fail on the base commit too. Both lists must be spelled out.
                    proven = (g == "G4" and c.get("pre_existing_failures")
                              and len(str(c.get("baseline_evidence", "")).strip()) >= MIN_EVIDENCE)
                    if not proven:
                        errors.append(f"{g}: PASS but `{c.get('cmd')}` has exit_code {c.get('exit_code')!r}"
                                      + (" (for G4, list pre_existing_failures + baseline_evidence)" if g == "G4" else ""))

    ids = set()
    for f in ledger.get("findings") or []:
        fid = f.get("id", "?")
        missing = [k for k in FINDING_FIELDS if not str(f.get(k, "")).strip()]
        if missing:
            errors.append(f"finding {fid}: missing {', '.join(missing)}")
        if fid in ids:
            errors.append(f"finding {fid}: duplicate id")
        ids.add(fid)
        if f.get("severity") not in SEVERITIES:
            errors.append(f"finding {fid}: severity must be one of {SEVERITIES}")
        if f.get("status") not in FINDING_STATUSES:
            errors.append(f"finding {fid}: status must be one of {sorted(FINDING_STATUSES)}")
        if f.get("status") in {"disputed", "accepted_risk", "wont_fix"} and not str(f.get("resolution", "")).strip():
            errors.append(f"finding {fid}: status {f.get('status')} needs a 'resolution' explaining why")

    cycles, max_cycles = ledger.get("cycles", 0), ledger.get("max_cycles", 3)
    if isinstance(cycles, int) and isinstance(max_cycles, int) and cycles > max_cycles:
        warnings.append(f"{cycles} remediation cycles exceeds max_cycles={max_cycles}; this should have been escalated")

    if outcome == "COMPLETE":
        for g, gate in gates.items():
            st = gate.get("status") if isinstance(gate, dict) else None
            if st in {"FAIL", "BLOCKED"} or (st == "NOT_RUN" and g in required):
                errors.append(f"COMPLETE but {g} is {st}")
        for f in ledger.get("findings") or []:
            if f.get("severity") in BLOCKING:
                if f.get("status") in {"open", "disputed"}:
                    errors.append(f"COMPLETE but {f.get('severity')} finding {f.get('id')} is {f.get('status')}")
                elif f.get("status") == "fixed":
                    errors.append(f"COMPLETE but {f.get('severity')} finding {f.get('id')} is fixed and not independently verified")
                elif f.get("status") == "accepted_risk" and not f.get("accepted_by_user"):
                    errors.append(f"COMPLETE but {f.get('id')} is accepted_risk without accepted_by_user: true")
    return errors, warnings


def load(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        sys.exit(f"not found: {p}")
    except ValueError as e:
        sys.exit(f"{p}: invalid JSON: {e}")


def cmd_check(a) -> int:
    p = resolve(a.path)
    errors, warnings = validate(load(p))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        print(f"\nFAILED: {len(errors)} problem(s) in {p}")
        return 1
    print(f"OK: {p}")
    return 0


def cmd_render(a) -> int:
    p = resolve(a.path)
    led = load(p)
    errors, _ = validate(led)
    print(f"**Task:** {led.get('task')}  \n**Mode:** {led.get('mode')} · **Kind:** {led.get('kind')} · "
          f"**Cycles:** {led.get('cycles')}/{led.get('max_cycles')} · **Outcome:** {led.get('outcome')}\n")
    if led.get("acceptance_criteria"):
        print("**Acceptance criteria**")
        for i, ac in enumerate(led["acceptance_criteria"], 1):
            text = ac if isinstance(ac, str) else f"{ac.get('text')} — {ac.get('status', '?')}"
            print(f"{i}. {text}")
        print()
    print("| Gate | Status | Evidence |\n|---|---|---|")
    for g, name in GATES.items():
        gate = led.get("gates", {}).get(g, {})
        ev = " ".join((gate.get("evidence") or "—").split())
        cmds = "; ".join(f"`{c.get('cmd')}`→{c.get('exit_code')}" for c in gate.get("commands") or [] if isinstance(c, dict))
        if cmds:
            ev = f"{ev} ({cmds})"
        print(f"| {g} {name} | {gate.get('status', '?')} | {ev.replace('|', '/')} |")
    findings = led.get("findings") or []
    if findings:
        print("\n| ID | Sev | Status | Location | Summary |\n|---|---|---|---|---|")
        order = {s: i for i, s in enumerate(SEVERITIES)}
        for f in sorted(findings, key=lambda f: order.get(f.get("severity"), 9)):
            summary = " ".join(str(f.get("actual", "")).split())[:90].replace("|", "/")
            print(f"| {f.get('id')} | {f.get('severity')} | {f.get('status')} | `{f.get('location')}` | {summary} |")
    print(f"\nLedger check: {'OK' if not errors else 'FAILED — ' + '; '.join(errors)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("task")
    i.add_argument("--mode", choices=["small", "medium", "large"], default="medium")
    i.add_argument("--kind", choices=["build", "fix", "review", "test", "improve-ui"], default="build")
    i.add_argument("--max-cycles", type=int, default=3)
    i.set_defaults(fn=cmd_init)
    for name, fn in (("check", cmd_check), ("render", cmd_render)):
        s = sub.add_parser(name)
        s.add_argument("path", nargs="?")
        s.set_defaults(fn=fn)
    l = sub.add_parser("latest")
    l.set_defaults(fn=lambda a: print(latest_run() or "") or 0)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
