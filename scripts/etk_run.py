#!/usr/bin/env python3
"""Run ledger for ETK: create a run, check its gates, render the report.

    etk_run.py init "<task>" [--mode small|medium|large] [--kind build|fix|review|test|improve-ui]
    etk_run.py check [RUN_DIR|gates.json]     # exit 1 if the ledger is inconsistent
    etk_run.py render [RUN_DIR|gates.json]    # markdown summary for the final report
    etk_run.py stats [--json] [--last N]      # aggregate all runs: categories, ratchet candidates, trust
    etk_run.py latest                         # print the newest run dir

The ledger (`.etk/runs/<id>/gates.json`) is the single source of truth for
gate status and findings. `check` is deliberately strict: it is the thing that
stops "all tests pass" from being claimed when nothing ran.

Standard library only.
"""
from __future__ import annotations

import argparse
from collections import Counter
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
AC_MET = {"met", "pass"}
# The only honest reasons a code-changing run has no automated tests for the change.
G3_NA_REASONS = {"docs_only", "no_test_setup"}
FINDING_FIELDS = ["id", "severity", "location", "evidence", "expected", "actual", "remediation", "status"]
MIN_EVIDENCE = 12
COMMAND_TYPES = {"test", "lint", "typecheck", "build", "runtime", "e2e", "static", "other"}
HARDENING_LAYERS = {"architecture", "static", "runtime", "prose", "none"}
RUNTIME_TYPES = {"runtime", "e2e"}
NEEDS_RUNTIME = {"build", "fix", "improve-ui"}


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
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root,
                             capture_output=True, text=True, timeout=5)
    except OSError:
        return
    if out.returncode != 0:  # not a git repo
        return
    common = Path(out.stdout.strip())
    excl = (common if common.is_absolute() else root / common) / "info" / "exclude"
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


def project_config(root: Path) -> dict:
    try:
        cfg = json.loads((root / ".claude" / "engineering-team.json").read_text())
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def cmd_init(a) -> int:
    root = git_root()
    if a.max_cycles is None:
        a.max_cycles = project_config(root).get("max_cycles", 3)
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


def has_runtime_evidence(ledger: dict) -> bool:
    gates = ledger.get("gates")
    for gate in gates.values() if isinstance(gates, dict) else []:
        cmds = gate.get("commands") if isinstance(gate, dict) else None
        for c in cmds if isinstance(cmds, list) else []:
            if isinstance(c, dict) and isinstance(c.get("type"), str) and c["type"] in RUNTIME_TYPES:
                return True
    return False


def runtime_verified(ledger: dict) -> bool:
    """What the runtime warning accepts: a runtime/e2e command, or a G5 that passed in a browser."""
    g5 = (ledger.get("gates") or {}).get("G5") if isinstance(ledger.get("gates"), dict) else None
    return has_runtime_evidence(ledger) or (isinstance(g5, dict) and g5.get("status") == "PASS")


def needs_runtime(ledger: dict) -> bool:
    return isinstance(ledger.get("kind"), str) and ledger["kind"] in NEEDS_RUNTIME \
        and isinstance(ledger.get("mode"), str) and ledger["mode"] in {"medium", "large"}


def validate(ledger: dict) -> tuple[list[str], list[str]]:
    try:
        return _validate(ledger)
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        return [f"ledger has a malformed field ({type(exc).__name__}: {exc}); compare it with quality/gates.md"], []


def _validate(ledger: dict) -> tuple[list[str], list[str]]:
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
    acs = ledger.get("acceptance_criteria") or []
    if not isinstance(acs, list):
        errors.append("acceptance_criteria must be a list")
        acs = []
    if not acs:
        (errors if outcome == "COMPLETE" and kind in NEEDS_AC else warnings).append("acceptance_criteria is empty")
    for n, ac in enumerate(acs, 1):
        status = str(ac.get("status", "")).lower() if isinstance(ac, dict) else ""
        if outcome == "COMPLETE" and kind in NEEDS_AC and status not in AC_MET:
            label = ac.get("id", f"#{n}") if isinstance(ac, dict) else f"#{n}"
            errors.append(f"COMPLETE but acceptance criterion {label} is not marked met (status {status or 'missing'!r})")
    if not isinstance(gates, dict):
        errors.append("gates must be an object")
        gates = {}

    for g in GATES:
        gate = gates.get(g)
        if not isinstance(gate, dict):
            errors.append(f"{g}: missing")
            continue
        if not isinstance(gate.get("commands") or [], list):
            errors.append(f"{g}: commands must be a list")
            continue
        for c in gate.get("commands") or []:
            if isinstance(c, dict) and "type" in c and (not isinstance(c["type"], str) or c["type"] not in COMMAND_TYPES):
                errors.append(f"{g}: command `{c.get('cmd')}` type must be one of {sorted(COMMAND_TYPES)}, got {c['type']!r}")
        st = gate.get("status")
        ev = (gate.get("evidence") or "").strip()
        if st not in STATUSES:
            errors.append(f"{g}: invalid status {st!r}")
            continue
        if st != "NOT_RUN" and len(ev) < MIN_EVIDENCE:
            errors.append(f"{g}: status {st} needs evidence or a justification (got {ev!r})")
        if st == "NOT_APPLICABLE" and (g in ALWAYS_APPLICABLE or (g == "G2" and kind in NEEDS_AC)):
            errors.append(f"{g}: cannot be NOT_APPLICABLE" + (f" for a {kind} run" if g == "G2" else ""))
        if st == "NOT_APPLICABLE" and g == "G3" and kind in NEEDS_AC and gate.get("reason_code") not in G3_NA_REASONS:
            errors.append(f"G3: NOT_APPLICABLE on a {kind} run needs reason_code {sorted(G3_NA_REASONS)}; "
                          "if tests exist but can't run, that's BLOCKED")
        if st == "PASS" and g in COMMAND_BACKED:
            cmds = gate.get("commands") or []
            if not cmds:
                errors.append(f"{g}: PASS without any recorded command — tests that did not run cannot pass")
            for c in cmds:
                if not isinstance(c, dict) or not c.get("cmd"):
                    errors.append(f"{g}: each command needs a 'cmd'")
                elif type(c.get("exit_code")) is not int:
                    errors.append(f"{g}: `{c.get('cmd')}` exit_code must be an integer, got {c.get('exit_code')!r}")
                elif c.get("exit_code") != 0:
                    # G4 only: a red suite can still mean "no regression" if every failure is
                    # proven to fail on the base commit too. Both lists must be spelled out.
                    proven = (g == "G4" and c.get("pre_existing_failures")
                              and len(str(c.get("baseline_evidence", "")).strip()) >= MIN_EVIDENCE)
                    if not proven:
                        errors.append(f"{g}: PASS but `{c.get('cmd')}` has exit_code {c.get('exit_code')!r}"
                                      + (" (for G4, list pre_existing_failures + baseline_evidence)" if g == "G4" else ""))

    ids = set()
    findings = ledger.get("findings") or []
    if not isinstance(findings, list):
        errors.append("findings must be a list")
        findings = []
    bad = [f for f in findings if not isinstance(f, dict)]
    if bad:
        errors.append(f"findings must be objects, got {bad[:2]!r}")
    findings = [f for f in findings if isinstance(f, dict)]
    for f in findings:
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
        if "category" in f and not isinstance(f["category"], str):
            errors.append(f"finding {fid}: category must be a string")
        if "hardening" in f:
            h = f["hardening"]
            if not isinstance(h, dict) or not isinstance(h.get("layer"), str) or h["layer"] not in HARDENING_LAYERS:
                errors.append(f"finding {fid}: hardening.layer must be one of {sorted(HARDENING_LAYERS)}")
            elif not isinstance(h.get("proposal"), str) or not h["proposal"].strip():
                errors.append(f"finding {fid}: hardening.proposal must be a non-empty string")
        if f.get("status") in {"disputed", "accepted_risk", "wont_fix"} and not str(f.get("resolution", "")).strip():
            errors.append(f"finding {fid}: status {f.get('status')} needs a 'resolution' explaining why")

    cycles, max_cycles = ledger.get("cycles", 0), ledger.get("max_cycles", 3)
    if isinstance(cycles, int) and isinstance(max_cycles, int) and cycles > max_cycles:
        warnings.append(f"{cycles} remediation cycles exceeds max_cycles={max_cycles}; this should have been escalated")

    if outcome == "COMPLETE" and needs_runtime(ledger) and not runtime_verified(ledger):
        warnings.append("no runtime verification recorded (tests prove code; running it proves the feature) — "
                        "add a command with type runtime/e2e if the change is user-visible")

    if outcome == "COMPLETE":
        for g in GATES:
            gate = gates.get(g)
            st = gate.get("status") if isinstance(gate, dict) else None
            if st in {"FAIL", "BLOCKED"} or (st == "NOT_RUN" and g in required):
                errors.append(f"COMPLETE but {g} is {st}")
        for f in findings:
            if f.get("severity") == "medium" and f.get("status") in {"open", "disputed"}:
                errors.append(f"COMPLETE but medium finding {f.get('id')} is {f.get('status')} (fix it or record why not)")
            if f.get("severity") in BLOCKING:
                if f.get("status") in {"open", "disputed"}:
                    errors.append(f"COMPLETE but {f.get('severity')} finding {f.get('id')} is {f.get('status')}")
                elif f.get("status") == "fixed":
                    errors.append(f"COMPLETE but {f.get('severity')} finding {f.get('id')} is fixed and not independently verified")
                elif f.get("status") in {"accepted_risk", "wont_fix"} and f.get("accepted_by_user") is not True:
                    errors.append(f"COMPLETE but {f.get('severity')} finding {f.get('id')} is {f.get('status')} "
                                  "without accepted_by_user: true (only the user can accept that)")
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
            text = ac if isinstance(ac, str) else f"{ac.get('id', '')} {ac.get('text')}: {ac.get('status', '?')}".strip()
            print(f"{i}. {text}")
        print()
    print("| Gate | Status | Evidence |\n|---|---|---|")
    for g, name in GATES.items():
        gate = led.get("gates", {}).get(g, {})
        ev = " ".join((gate.get("evidence") or "—").split())
        cmds = "; ".join(f"`{c.get('cmd')}`→{c.get('exit_code')}" for c in gate.get("commands") or [] if isinstance(c, dict))
        if cmds:
            ev = f"{ev} ({cmds})"
        if gate.get("reason_code"):
            ev = f"[{gate['reason_code']}] {ev}"
        print(f"| {g} {name} | {gate.get('status', '?')} | {ev.replace('|', '/')} |")
    findings = [f for f in (led.get("findings") or []) if isinstance(f, dict)]
    if findings:
        print("\n| ID | Sev | Status | Location | Summary |\n|---|---|---|---|---|")
        order = {s: i for i, s in enumerate(SEVERITIES)}
        for f in sorted(findings, key=lambda f: order.get(f.get("severity"), 9)):
            summary = " ".join(str(f.get("actual", "")).split())[:90].replace("|", "/")
            print(f"| {f.get('id')} | {f.get('severity')} | {f.get('status')} | `{f.get('location')}` | {summary} |")
    hard = [f for f in findings if isinstance(f.get("hardening"), dict)]
    if hard:
        print("\n**Hardening proposals**")
        for f in hard:
            print(f"- {f.get('id')} [{f['hardening'].get('layer')}] {f['hardening'].get('proposal')}")
    print(f"\nLedger check: {'OK' if not errors else 'FAILED — ' + '; '.join(errors)}")
    return 0


def clean_run(led: dict) -> dict:
    """Keep only well-typed fields so one hand-edited ledger can't break the aggregate."""
    text = lambda v: v if isinstance(v, str) else None
    findings = led.get("findings") if isinstance(led.get("findings"), list) else []
    out = {k: text(led.get(k)) for k in ("kind", "mode", "outcome")}
    out["cycles"] = led.get("cycles") if type(led.get("cycles")) is int else None
    out["gates"] = led.get("gates") if isinstance(led.get("gates"), dict) else {}
    out["findings"] = [{"severity": text(f.get("severity")), "category": text(f.get("category")),
                        "hardening": f.get("hardening") if isinstance(f.get("hardening"), dict) else None}
                       for f in findings if isinstance(f, dict)]
    return out


def cmd_stats(a) -> int:
    d = runs_dir()
    paths = sorted(d.glob("*/gates.json")) if d.exists() else []
    if a.last is not None:
        if a.last < 1:
            print("--last must be >= 1", file=sys.stderr)
            return 2
        paths = paths[-a.last:]
    runs, warns = [], []
    for p in paths:
        try:
            led = json.loads(p.read_text())
            if not isinstance(led, dict):
                raise ValueError("not an object")
            runs.append(clean_run(led))
        except (OSError, ValueError, TypeError, AttributeError) as e:
            warns.append(f"skipped {p.parent.name}: {e}")
    cnt = lambda key: dict(Counter(str(r.get(key)) for r in runs))
    cycles = [r["cycles"] for r in runs if type(r.get("cycles")) is int]
    per_run = [[f for f in (r.get("findings") or []) if isinstance(f, dict)] for r in runs]
    sev = Counter(f.get("severity") for fs in per_run for f in fs)
    cats: dict = {}
    for i, fs in enumerate(per_run):
        for f in fs:
            c = f.get("category")
            if not isinstance(c, str) or not c.strip():
                continue
            e = cats.setdefault(c, {"findings": 0, "runs": set(), "sev": set(), "proposals": []})
            e["findings"] += 1
            e["runs"].add(i)
            e["sev"].add(f.get("severity"))
            h = f.get("hardening")
            if isinstance(h, dict) and h.get("proposal"):
                pr = f"[{h.get('layer')}] {h['proposal']}"
                if pr not in e["proposals"]:
                    e["proposals"].append(pr)
    ranked = sorted(cats.items(), key=lambda kv: (-kv[1]["findings"], kv[0]))
    top = [{"category": c, "findings": e["findings"], "runs": len(e["runs"])} for c, e in ranked[:8]]
    ratchet = [{"category": c, "runs": len(e["runs"]), "proposals": e["proposals"]} for c, e in ranked
               if len(e["runs"]) >= 2 and e["sev"] & {"medium", "high", "critical"}]
    n = len(runs)
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
    half = n // 2
    old, new = avg([len(x) for x in per_run[:half]]), avg([len(x) for x in per_run[half:]])
    trend = "n/a" if old is None or new is None else "down" if new < old - 0.25 else "up" if new > old + 0.25 else "flat"
    bf = [r for r in runs if needs_runtime(r)]
    out = {
        "runs": n, "by_kind": cnt("kind"), "by_mode": cnt("mode"), "by_outcome": cnt("outcome"),
        "avg_cycles": avg(cycles),
        "findings_by_severity": {s: sev[s] for s in SEVERITIES if sev[s]},
        "top_categories": top, "ratchet_candidates": ratchet,
        "trust": {
            "complete_share": round(sum(r.get("outcome") == "COMPLETE" for r in runs) / n, 2) if n else None,
            "blocking_per_run": avg([sum(f.get("severity") in BLOCKING for f in fs) for fs in per_run]),
            "findings_per_run_older": old, "findings_per_run_newer": new, "trend": trend,
            "runtime_verified_share": round(sum(map(runtime_verified, bf)) / len(bf), 2) if bf else None,
        },
        "warnings": warns,
    }
    if a.json:
        print(json.dumps(out, indent=2))
        return 0
    for w in warns:
        print(f"warning: {w}", file=sys.stderr)
    fmt = lambda m: ", ".join(f"{k} {v}" for k, v in m.items()) or "—"
    t = out["trust"]
    pct = lambda x: "n/a" if x is None else f"{round(x * 100)}%"
    print(f"## ETK stats ({n} run(s))\n")
    if not n:
        return 0
    print(f"- kind: {fmt(out['by_kind'])}\n- mode: {fmt(out['by_mode'])}\n- outcome: {fmt(out['by_outcome'])}\n"
          f"- avg cycles: {out['avg_cycles']}\n- findings by severity: {fmt(out['findings_by_severity'])}")
    print("\n**Top categories** (findings / runs)")
    print("\n".join(f"- {c['category']}: {c['findings']} / {c['runs']}" for c in top) or "- none")
    print("\n**Ratchet candidates** (>=2 runs, severity >= medium)")
    for r in ratchet:
        print(f"- {r['category']} ({r['runs']} runs)" + "".join(f"\n  - proposal: {p}" for p in r["proposals"]))
    if not ratchet:
        print("- none")
    print(f"\n**Trust indicators**\n- complete: {pct(t['complete_share'])}\n- blocking findings/run: {t['blocking_per_run']}\n"
          f"- findings/run older half {t['findings_per_run_older']} -> newer half {t['findings_per_run_newer']}: {t['trend']}\n"
          f"- medium/large build/fix/improve-ui runs verified by running: {pct(t['runtime_verified_share'])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("task")
    i.add_argument("--mode", choices=["small", "medium", "large"], default="medium")
    i.add_argument("--kind", choices=["build", "fix", "review", "test", "improve-ui"], default="build")
    i.add_argument("--max-cycles", type=int, default=None, help="default: project config max_cycles, else 3")
    i.set_defaults(fn=cmd_init)
    for name, fn in (("check", cmd_check), ("render", cmd_render)):
        s = sub.add_parser(name)
        s.add_argument("path", nargs="?")
        s.set_defaults(fn=fn)
    st = sub.add_parser("stats")
    st.add_argument("--json", action="store_true")
    st.add_argument("--last", type=int, default=None, metavar="N")
    st.set_defaults(fn=cmd_stats)
    l = sub.add_parser("latest")
    l.set_defaults(fn=lambda a: print(latest_run() or "") or 0)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
