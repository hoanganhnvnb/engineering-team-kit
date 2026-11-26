#!/usr/bin/env python3
"""Run ledger for ETK: create a run, check its gates, render the report.

    etk_run.py init "<task>" [--mode small|medium|large] [--kind build|fix|review|test|improve-ui|ship]
    etk_run.py check [RUN_DIR|gates.json]     # exit 1 if the ledger is inconsistent
    etk_run.py render [RUN_DIR|gates.json]    # markdown summary for the final report
    etk_run.py stats [--json] [--last N]      # aggregate all runs: categories, ratchet candidates, trust
    etk_run.py latest                         # print the newest run dir
    etk_run.py exec G3 --type test [--run RUN_DIR] -- <cmd>   # run <cmd>, record its real exit code
    etk_run.py phase <name> [RUN]             # move the run to a phase (intake ... done)
    etk_run.py ready [RUN]                    # exit 0 only if a release step may run now (else lists why)
    etk_run.py authorize --action A --source S --quote "Q" [--target T] [--condition C] [--data DIR] [RUN]
    etk_run.py act --action A [--target T] [--ref R] [--url U] [--command C] --exit N [--production]
                   [--data DIR] [--force-record] [RUN]      # --data is required for deploy/rollback
    etk_run.py decide --id ID [--level L0..L4 --question Q] [--options "a|b"] [--recommended R]
                      [--status S] [--answer-quote Q] [RUN]     # level and question: new ids only

Without a path, the newest run under `.etk/runs/` is used. Runs that git tracks, symlinks
and future-dated run names are never picked, and explicit paths must lie inside `.etk/runs/`.

The ledger (`.etk/runs/<id>/gates.json`) is the single source of truth for
gate status and findings. `check` is deliberately strict: it is the thing that
stops "all tests pass" from being claimed when nothing ran.

Standard library only.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import etk_profile  # noqa: E402  (same directory)

GATES = {
    "G1": "Requirements & acceptance criteria",
    "G2": "Architecture & code review",
    "G3": "Automated tests",
    "G4": "Regression",
    "G5": "UI/UX & accessibility",
    "G6": "Security & compatibility",
    "G7": "Release",
}
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}
SEVERITIES = ["critical", "high", "medium", "low"]
FINDING_STATUSES = {"open", "fixed", "verified", "disputed", "accepted_risk", "wont_fix", "invalid"}
BLOCKING = {"critical", "high"}
OUTCOMES = {"COMPLETE", "INCOMPLETE", "BLOCKED", "IN_PROGRESS"}
# Gates that can only be NOT_APPLICABLE with a real reason, never skipped silently.
ALWAYS_APPLICABLE = {"G1"}
# Gates whose PASS must be backed by commands that actually ran.
COMMAND_BACKED = {"G3", "G4"}
# Gates that must be settled (not NOT_RUN) before a run of this kind is COMPLETE.
# review/test runs only own part of the picture; the rest may stay NOT_RUN.
CORE_GATES = set(GATES) - {"G7"}  # G7 (release) is owned only by ship runs
REQUIRED_BY_KIND = {
    "build": CORE_GATES,
    "fix": CORE_GATES,
    "improve-ui": CORE_GATES,
    "review": {"G2", "G6"},
    "test": {"G3", "G4"},
    # The orchestrated run: implement + review + test + release.
    "ship": set(GATES),
}
NEEDS_AC = {"build", "fix", "improve-ui", "ship"}
AC_MET = {"met", "pass"}
# The only honest reasons a code-changing run has no automated tests for the change.
G3_NA_REASONS = {"docs_only", "no_test_setup"}
FINDING_FIELDS = ["id", "severity", "location", "evidence", "expected", "actual", "remediation", "status"]
MIN_EVIDENCE = 12
COMMAND_TYPES = {"test", "lint", "typecheck", "build", "runtime", "e2e", "static", "other"}
HARDENING_LAYERS = {"architecture", "static", "runtime", "prose", "none"}
RUNTIME_TYPES = {"runtime", "e2e"}
NEEDS_RUNTIME = {"build", "fix", "improve-ui", "ship"}
# Release bookkeeping (phase, authorizations, actions, decisions). Old ledgers have none of it.
PHASES = ["intake", "implement", "review", "test", "release", "deploy", "report", "done"]
RELEASE_ACTIONS = ["commit", "push", "pr", "merge", "tag", "deploy", "rollback"]
AUTH_SOURCES = {"prompt", "answer", "profile"}
PROFILE_OK = {"commit", "push", "pr"}            # a workflow profile may pre-authorize only these
NEEDS_USER_WORDS = {"merge", "tag", "deploy", "rollback"}  # need the user's own words (prompt/answer)
GATED_ACTIONS = {"commit", "push", "pr", "merge", "tag", "deploy"}  # not before the gates pass
OUTWARD_ACTIONS = GATED_ACTIONS - {"commit"}  # leave the machine: only from runs that build something (NEEDS_AC)
# Whole words, where `-` and `_` count as part of a word: "prod" doesn't match "prod-eu" or "nonprod".
PROD_WORDS = re.compile(r"(?<![\w-])(production|prod|live)(?![\w-])", re.I)
# A negation earlier in the same clause ("don't deploy to prod", "không deploy live").
NEGATION = re.compile(r"(?<![\w-])(don['’]?t|do not|never|not|no|không|đừng)(?![\w-])", re.I)
# Where a clause ends: punctuation, or a "then" ("no errors -> deploy prod", "không lỗi thì deploy prod").
CLAUSE_END = re.compile(r"[.;,!?\n]|->|→|=>|(?<![\w-])(?:then|thì)(?![\w-])", re.I)
# How far ahead `latest` accepts a run name (clock skew); discover.previous_run uses the same.
FUTURE_SLACK = dt.timedelta(days=1)
DECISION_LEVELS = {"L0", "L1", "L2", "L3", "L4"}
DECISION_STATUSES = {"pending", "approved", "autonomous", "superseded"}
MIN_QUOTE = 3
RUN_NAME = re.compile(r"^(\d{8}-\d{6})-")


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


def refuse(msg: str):
    print(f"etk_run: {msg}", file=sys.stderr)
    sys.exit(2)


def tracked_under_etk(root: Path) -> set[str]:
    """Paths under .etk/ that git tracks. A committed ledger is someone else's claim, not this session's."""
    try:
        out = subprocess.run(["git", "-c", "core.fsmonitor=false", "--no-optional-locks", "ls-files", "-z", "--", ".etk"],
                             cwd=root, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    return {x for x in out.stdout.decode("utf-8", "surrogateescape").split("\0") if x}


def symlink_problem(root: Path) -> str | None:
    for d in (root / ".etk", root / ".etk" / "runs"):
        if d.is_symlink():
            return f"{d} is a symlink; run ledgers must live in a real directory inside the repository"
        if d.exists() and not d.is_dir():
            return f"{d} is not a directory"
    return None


def runs_area_problem(root: Path) -> str | None:
    """Why `.etk/runs` can't be trusted to hold this session's ledgers, or None."""
    problem = symlink_problem(root)
    if problem:
        return problem
    tracked = sorted(tracked_under_etk(root))
    if tracked:
        return (f"git tracks {len(tracked)} file(s) under .etk/ (e.g. {tracked[0]}); run ledgers must stay "
                "local. Untrack them (`git rm -r --cached .etk`) and retry")
    return None


def is_tracked(path: Path, root: Path, tracked: set[str]) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    return any(t == rel or t.startswith(rel + "/") for t in tracked)


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
    problem = runs_area_problem(root)
    if problem:
        refuse(f"init refused: {problem}")
    if a.max_cycles is None:
        a.max_cycles = project_config(root).get("max_cycles", 3)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run = runs_dir() / f"{stamp}-{slug(a.task)}"
    runs_dir().mkdir(parents=True, exist_ok=True)
    for n in range(2, 100):
        try:
            run.mkdir()
            break
        except FileExistsError:
            run = runs_dir() / f"{stamp}-{slug(a.task)}-{n}"
    else:
        sys.exit(f"could not create a run directory under {runs_dir()}")
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
        "phase": "intake",
        "phase_history": [{"phase": "intake", "at": now_iso()}],
        "authorizations": [],
        "actions": [],
        "decisions": [],
        "profile_hash": None,
    }
    (run / "gates.json").write_text(json.dumps(ledger, indent=2) + "\n")
    print(run)
    return 0


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def resolve(path: str | None) -> Path:
    root = git_root()
    if not path:
        problem = runs_area_problem(root)
        if problem:
            refuse(f"cannot pick the newest run: {problem}")
        latest = latest_run()
        if not latest:
            sys.exit("no ETK run found; run `etk_run.py init` first")
        return latest / "gates.json"
    p = Path(path)
    p = p / "gates.json" if p.is_dir() else p
    problem = symlink_problem(root)
    if problem:
        refuse(problem)
    rd = (root / ".etk" / "runs").resolve()
    real = p.resolve()
    if not real.is_relative_to(rd) or len(real.relative_to(rd).parts) < 2:  # <run>/gates.json at least
        refuse(f"{path} is not inside this repository's run directory {rd}")
    if is_tracked(real, root, tracked_under_etk(root)):
        refuse(f"{path} is tracked by git; a committed ledger is not this session's run")
    return p


def latest_run() -> Path | None:
    """Newest run this session could have created: a real, untracked, not future-dated run dir."""
    d = runs_dir()
    if not d.is_dir() or d.is_symlink():
        return None
    root = git_root()
    tracked = tracked_under_etk(root)
    limit = dt.datetime.now() + FUTURE_SLACK
    runs = []
    for x in d.iterdir():
        m = RUN_NAME.match(x.name)
        g = x / "gates.json"
        if not m or x.is_symlink() or not x.is_dir() or g.is_symlink() or not g.is_file():
            continue
        try:
            if dt.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S") > limit:
                continue
        except ValueError:
            continue
        if is_tracked(x, root, tracked):
            continue
        runs.append(x)
    return max(runs, default=None)


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


def validate(ledger: dict, skip: frozenset = frozenset()) -> tuple[list[str], list[str]]:
    """`skip` names gates to leave out entirely (used to ask "would the gates allow a release?")."""
    try:
        return _validate(ledger, skip)
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        return [f"ledger has a malformed field ({type(exc).__name__}: {exc}); compare it with quality/gates.md"], []


def _validate(ledger: dict, skip: frozenset = frozenset()) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    gates = ledger.get("gates") or {}
    outcome = ledger.get("outcome")
    if outcome not in OUTCOMES:
        errors.append(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")

    kind = ledger.get("kind", "build")
    if kind not in REQUIRED_BY_KIND:
        errors.append(f"kind must be one of {sorted(REQUIRED_BY_KIND)}, got {kind!r}")
    required = REQUIRED_BY_KIND.get(kind, CORE_GATES)
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
        if g in skip or (g == "G7" and g not in gates and g not in required):
            continue  # G7 arrived later: ledgers from before it (and non-release runs) may lack it
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
                if isinstance(c, dict) and c.get("cmd") and c.get("recorded_by") != "exec":
                    warnings.append(f"{g}: `{c.get('cmd')}` was not recorded by `etk_run.py exec`; "
                                    "its exit code is self-reported")
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
        if f.get("status") in {"disputed", "accepted_risk", "wont_fix", "invalid"} and not str(f.get("resolution", "")).strip():
            errors.append(f"finding {fid}: status {f.get('status')} needs a 'resolution' explaining why")

    cycles, max_cycles = ledger.get("cycles", 0), ledger.get("max_cycles", 3)
    if isinstance(cycles, int) and isinstance(max_cycles, int) and cycles > max_cycles:
        warnings.append(f"{cycles} remediation cycles exceeds max_cycles={max_cycles}; this should have been escalated")

    if outcome == "COMPLETE" and needs_runtime(ledger) and not runtime_verified(ledger):
        warnings.append("no runtime verification recorded (tests prove code; running it proves the feature) — "
                        "add a command with type runtime/e2e if the change is user-visible")

    validate_release(ledger, kind, outcome, gates, skip, errors)

    if outcome == "COMPLETE":
        for g in GATES:
            if g in skip:
                continue
            gate = gates.get(g)
            st = gate.get("status") if isinstance(gate, dict) else None
            if st in {"FAIL", "BLOCKED"} or (st == "NOT_RUN" and g in required):
                errors.append(f"COMPLETE but {g} is {st}")
        for f in findings:
            # A report-only review ends with its mediums listed as open; fix/build runs must settle them.
            if f.get("severity") == "medium" and f.get("status") in {"open", "disputed"} and kind != "review":
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


def _list_of_dicts(ledger: dict, key: str, errors: list[str]) -> list[dict]:
    items = ledger.get(key)
    if items is None:
        return []
    if not isinstance(items, list):
        errors.append(f"{key} must be a list")
        return []
    bad = [x for x in items if not isinstance(x, dict)]
    if bad:
        errors.append(f"{key} must be objects, got {bad[:2]!r}")
    return [x for x in items if isinstance(x, dict)]


def _ts(v) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None
    return t.replace(tzinfo=None) if t else None


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def word(name: str) -> re.Pattern:
    """`name` as a whole word; `-`/`_` are word characters, so "web" doesn't match "web-staging"."""
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", re.I)


def affirms(quote: str, pattern: re.Pattern) -> bool:
    """`pattern` occurs in `quote` with no negation in its clause, before or after it ("don't touch
    prod" and "prod: no" don't count). Clauses end at punctuation, `then`/`thì` and arrows."""
    for m in pattern.finditer(quote):
        before = CLAUSE_END.split(quote[:m.start()])[-1]
        # After the match only . ; , ! and newlines end the clause: "prod: don't", "web-eu? no",
        # "production thì không".
        after = re.split(r"[.;,!\n]", quote[m.end():])[0]
        if not NEGATION.search(before) and not NEGATION.search(after):
            return True
    return False


def validate_release(ledger: dict, kind, outcome, gates: dict, skip: frozenset, errors: list[str]) -> None:
    """Phase, authorizations, actions, decisions and G7. Absent fields (old ledgers) are fine."""
    if "phase" in ledger and ledger["phase"] not in PHASES:
        errors.append(f"phase must be one of {PHASES}, got {ledger['phase']!r}")
    for h in _list_of_dicts(ledger, "phase_history", errors):
        if h.get("phase") not in PHASES or not isinstance(h.get("at"), str):
            errors.append(f"phase_history entries need a phase from {PHASES} and an 'at' timestamp, got {h!r}")

    auths = []
    for n, au in enumerate(_list_of_dicts(ledger, "authorizations", errors), 1):
        act, src = au.get("action"), au.get("source")
        label = f"authorization #{n} ({act})"
        if act not in RELEASE_ACTIONS:
            errors.append(f"authorization #{n}: action must be one of {RELEASE_ACTIONS}, got {act!r}")
            continue
        if src not in AUTH_SOURCES:
            errors.append(f"{label}: source must be one of {sorted(AUTH_SOURCES)}, got {src!r}")
            continue
        if src == "profile" and act not in PROFILE_OK:
            errors.append(f"{label}: a workflow profile can only authorize {sorted(PROFILE_OK)}; "
                          f"{act} needs the user's own words (source prompt or answer)")
            continue
        if src == "profile" and not _text(au.get("profile_hash")):
            errors.append(f"{label}: source profile without the profile's hash (record it with "
                          "`authorize --source profile --data DIR`, which checks the profile says auto)")
            continue
        if src != "profile" and len(_text(au.get("quote"))) < MIN_QUOTE:
            errors.append(f"{label}: source {src} needs the user's verbatim words in 'quote'")
            continue
        if au.get("target") is not None and not isinstance(au.get("target"), str):
            errors.append(f"{label}: target must be a string")
            continue
        auths.append(au)

    acts = _list_of_dicts(ledger, "actions", errors)
    failed, succeeded = [], []
    for n, ac in enumerate(acts, 1):
        act, target = ac.get("action"), _text(ac.get("target"))
        label = f"action #{n} ({act}{' ' + target if target else ''})"
        if act not in RELEASE_ACTIONS:
            errors.append(f"action #{n}: action must be one of {RELEASE_ACTIONS}, got {act!r}")
            continue
        if type(ac.get("exit")) is not int:
            errors.append(f"{label}: exit must be an integer, got {ac.get('exit')!r}")
            continue
        if type(ac.get("gates_ok")) is not bool or type(ac.get("production", False)) is not bool:
            errors.append(f"{label}: gates_ok/production must be true or false (record actions with `act`)")
            continue
        if ac.get("target") is not None and not isinstance(ac.get("target"), str):
            errors.append(f"{label}: target must be a string")
            continue
        if ac["exit"] != 0:
            failed.append((n, act, target.lower(), label + f" exited {ac['exit']}"))
        else:
            succeeded.append((n, act, target.lower()))
        if act in GATED_ACTIONS and not ac["gates_ok"]:
            errors.append(f"{label}: released before the gates passed (gates_ok false when it ran)")
        if act in OUTWARD_ACTIONS and kind not in NEEDS_AC:
            errors.append(f"{label}: a {kind} run can't release; push, PR, merge, tag and deploy belong to "
                          f"{'/'.join(sorted(NEEDS_AC))} runs")
        at = _ts(ac.get("at"))
        match = [au for au in auths if au["action"] == act
                 and (not _text(au.get("target")) or _text(au.get("target")).lower() == target.lower())
                 and not (at and _ts(au.get("granted_at")) and _ts(au.get("granted_at")) > at)]
        if not match:
            errors.append(f"{label}: no authorization for it (record the user's permission with `authorize` first)")
            continue
        if act in NEEDS_USER_WORDS:
            match = [au for au in match if au["source"] in {"prompt", "answer"}]
            if not match:
                errors.append(f"{label}: needs the user's own words (authorization source prompt or answer), "
                              "a workflow profile is not enough")
                continue
        if act in {"deploy", "rollback"} and not target:
            errors.append(f"{label}: a {act} needs its target's name")
            continue
        if act in {"deploy", "rollback"} and (ac.get("production") or PROD_WORDS.search(target)):
            named = [au for au in match if target and _text(au.get("target")).lower() == target.lower()]
            if not named:
                errors.append(f"{label}: production {act} needs an authorization for exactly this target "
                              f"(`authorize --action {act} --target {target or '<name>'}`), not a blanket one")
                continue
            if not any(affirms(_text(au.get("quote")), PROD_WORDS) or affirms(_text(au.get("quote")), word(target))
                       for au in named):
                errors.append(f"{label}: production {act}, but no authorization quote names the target "
                              "or says production/prod/live")
    # A failed step that a later run of the same action on the same target got through is settled.
    failed = [msg for n, act, target, msg in failed
              if not any(m > n and a == act and t == target for m, a, t in succeeded)]
    if outcome == "COMPLETE":
        errors.extend(f"COMPLETE but {f}" for f in failed)

    seen = set()
    for d in _list_of_dicts(ledger, "decisions", errors):
        did = d.get("id")
        if not isinstance(did, str) or not did.strip():
            errors.append(f"decision {d!r}: needs an id")
            continue
        if did in seen:
            errors.append(f"decision {did}: duplicate id")
        seen.add(did)
        if d.get("level") not in DECISION_LEVELS or d.get("status") not in DECISION_STATUSES:
            errors.append(f"decision {did}: level must be one of {sorted(DECISION_LEVELS)} and status one of "
                          f"{sorted(DECISION_STATUSES)}")
            continue
        if not _text(d.get("question")):
            errors.append(f"decision {did}: needs a question")
        if d["level"] == "L4" and d["status"] == "autonomous":
            errors.append(f"decision {did}: L4 can't be autonomous (only the user can settle it)")
        if d["level"] == "L4" and d["status"] != "pending" and len(_text(d.get("answer_quote"))) < MIN_QUOTE:
            errors.append(f"decision {did}: a settled L4 needs the user's verbatim words in 'answer_quote'")
        if outcome == "COMPLETE" and d["level"] == "L4" and d["status"] == "pending":
            errors.append(f"COMPLETE but L4 decision {did} is still pending (only the user can settle it)")

    g7 = gates.get("G7") if "G7" not in skip else None
    st = g7.get("status") if isinstance(g7, dict) else None
    if st == "PASS" and failed:
        errors.append(f"G7: PASS but {failed[0]}; that's FAIL")
    if st == "PASS" and kind == "ship" and not acts:
        errors.append("G7: PASS without any recorded release action (record each one with `act`)")
    if st == "NOT_APPLICABLE" and acts:
        errors.append(f"G7: NOT_APPLICABLE but {len(acts)} release action(s) were recorded")


def release_blockers(ledger: dict) -> list[str]:
    """What stops a release step right now: the run could not be COMPLETE on the gates other than G7.
    That means every required gate but G7 is PASS or a justified NOT_APPLICABLE, every AC is met,
    no medium+ finding is open or disputed and no high/critical one is unverified."""
    if not isinstance(ledger, dict):
        return ["the ledger is not a JSON object"]
    probe = json.loads(json.dumps(ledger))
    probe.update(outcome="COMPLETE", authorizations=[], actions=[], decisions=[])
    if isinstance(probe.get("gates"), dict):
        probe["gates"].pop("G7", None)
    errors, _ = validate(probe, skip=frozenset({"G7"}))
    return [e.removeprefix("COMPLETE but ") for e in errors]


def gates_allow_release(ledger: dict) -> bool:
    """Would the gates other than G7 let this run be COMPLETE right now?"""
    return not release_blockers(ledger)


def load(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except FileNotFoundError:
        sys.exit(f"not found: {p}")
    except ValueError as e:
        sys.exit(f"{p}: invalid JSON: {e}")


def cmd_exec(a) -> int:
    """Run a command and write what really happened into the gate: exit code, last output line."""
    if a.gate not in GATES:
        print(f"unknown gate {a.gate!r}; expected one of {', '.join(GATES)}", file=sys.stderr)
        return 2
    cmd = a.cmd
    if not cmd:
        print("usage: etk_run.py exec <gate> --type <type> -- <command...>", file=sys.stderr)
        return 2
    p = resolve(a.run)
    led = load(p)
    gate = led.get("gates", {}).get(a.gate) if isinstance(led.get("gates"), dict) else None
    if not isinstance(gate, dict) or not isinstance(gate.get("commands", []), list):
        print(f"{p}: gate {a.gate} is malformed; fix the ledger first", file=sys.stderr)
        return 2
    before = json.loads(json.dumps(led))  # the ledger as the command found it
    run_dir = p.parent.resolve()
    last = ""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in proc.stdout:
            sys.stdout.write(line)
            if line.strip():
                last = line.strip()
        rc = proc.wait()
    except OSError as exc:
        last, rc = f"could not start: {exc}", 127
        print(last, file=sys.stderr)
    if p.parent.is_symlink() or p.parent.resolve() != run_dir:
        refuse(f"{p.parent} was replaced while the command ran; nothing recorded")
    led, changed = merge_exec(before, read_after(p), a.gate)
    if changed:
        print(f"[etk] {p}: the command changed the ledger beyond appending gate commands; those changes "
              "were discarded (only the Lead edits the ledger)", file=sys.stderr)
    led["gates"][a.gate].setdefault("commands", []).append({
        "cmd": shlex.join(cmd), "type": a.type, "exit_code": rc, "last_line": last[:300], "recorded_by": "exec",
    })
    write_ledger(p, led)
    print(f"[etk] {a.gate}: recorded `{shlex.join(cmd)}` exit {rc} in {p}", file=sys.stderr)
    return rc


def read_after(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def merge_exec(before: dict, after, gate_name: str) -> tuple[dict, bool]:
    """The ledger to write after `exec`: the snapshot taken before the command ran, plus command
    records appended to gate `commands` lists while it ran (a nested `etk exec`).

    The command is repository code (a test suite), so everything else it may have written into
    the file (gate status, findings, authorizations, actions, other fields) is dropped. Records it
    appended to any gate, this one included, are kept but marked `recorded_by: nested-exec`, so
    `check` treats their exit codes as self-reported: the command could have written them itself.
    `exec`'s own record of the command comes after them. Returns (ledger, whether anything was
    discarded)."""
    led, kept = json.loads(json.dumps(before)), json.loads(json.dumps(before))
    after_gates = after.get("gates") if isinstance(after, dict) and isinstance(after.get("gates"), dict) else {}
    for g, gate in led["gates"].items():
        if not isinstance(gate, dict):
            continue
        old = gate.get("commands") if isinstance(gate.get("commands"), list) else []
        other = after_gates.get(g)
        new = other.get("commands") if isinstance(other, dict) else None
        if not isinstance(new, list) or len(new) <= len(old) or new[:len(old)] != old:
            continue
        added = [c for c in new[len(old):] if isinstance(c, dict) and isinstance(c.get("cmd"), str)]
        kept["gates"][g]["commands"] = old + added
        added = [dict(c, recorded_by="nested-exec", nested_in=gate_name) for c in added]
        gate["commands"] = old + added
    return led, after != kept


def update_ledger(path: str | None, change) -> int:
    """Load, let `change` edit the ledger and return a confirmation line, then write it back.
    `change` calls refuse() on bad input before touching anything, so the file stays as it was."""
    p = resolve(path)
    led = load(p)
    if not isinstance(led, dict):
        refuse(f"{p}: the ledger is not a JSON object; fix it first")
    msg = change(led)
    write_ledger(p, led)
    print(f"[etk] {msg}")
    return 0


def write_ledger(p: Path, led: dict) -> None:
    """Replace the ledger atomically; a symlink planted at gates.json is replaced, never followed."""
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".gates.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(led, indent=2) + "\n")
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ledger_list(led: dict, key: str) -> list:
    items = led.setdefault(key, [])
    if not isinstance(items, list):
        refuse(f"ledger field {key} is not a list; fix the ledger first")
    return items


def cmd_phase(a) -> int:
    if a.name not in PHASES:
        refuse(f"phase must be one of {', '.join(PHASES)}, got {a.name!r}")

    def change(led):
        history = ledger_list(led, "phase_history")
        led["phase"] = a.name
        history.append({"phase": a.name, "at": now_iso()})
        return f"phase: {a.name}"
    return update_ledger(a.path, change)


def load_profile(raw_data: str | None) -> tuple[dict, Path, bytes | None, bool]:
    """The workflow profile as etk_profile would act on it here; refuses (exit 2) on a bad --data."""
    try:
        return etk_profile.load_for(raw_data)
    except etk_profile.UsageError as e:
        refuse(f"profile: {e}")


def profile_says_auto(prof: dict, action: str) -> str | None:
    """Why the profile doesn't pre-authorize `action`, or None when it does."""
    get = etk_profile.get
    if action == "pr":
        if get(prof, "release.integrate") != "pr" or get(prof, "release.push") != "auto":
            return "a PR needs release.integrate pr and release.push auto"
        return None
    if get(prof, f"release.{action}") != "auto":
        return f"release.{action} is {get(prof, f'release.{action}')!r}, not \"auto\""
    return None


def profile_unconfirmed(prof: dict) -> str | None:
    """Why the profile's settings aren't confirmed by the developer, or None when they are."""
    stored = prof.get("confirmed_hash")
    if not prof.get("confirmed_at") or not isinstance(stored, str):
        return "it was never confirmed (`profile confirm`)"
    if stored != etk_profile.settings_hash(prof):
        return "it changed after it was last confirmed; show it to the developer and run `profile confirm`"
    return None


def cmd_authorize(a) -> int:
    quote = (a.quote or "").strip()
    if a.source == "profile" and a.action not in PROFILE_OK:
        refuse(f"a workflow profile can only authorize {', '.join(sorted(PROFILE_OK))}; "
               f"{a.action} needs the user's own words (--source prompt|answer)")
    if a.source != "profile" and len(quote) < MIN_QUOTE:
        refuse(f"--source {a.source} needs --quote with the user's verbatim words")
    digest = None
    if a.source == "profile":
        if not a.data:
            refuse("--source profile needs --data DIR (the plugin data dir) so the profile can be checked")
        prof, path, raw, stale = load_profile(a.data)
        if raw is None:
            refuse(f"no workflow profile at {path}; --source profile needs one that says auto")
        try:  # what was confirmed is the stored file, not the view with hidden `auto` values removed
            stored = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            stored = {}
        why = profile_says_auto(prof, a.action) or profile_unconfirmed(stored if isinstance(stored, dict) else {})
        if why:
            refuse(f"the workflow profile doesn't pre-authorize {a.action}: {why}"
                   + (f" ({etk_profile.RECONFIRM})" if stale else ""))
        digest = hashlib.sha256(raw).hexdigest()
        bound = etk_profile.binding(etk_profile.identify())
        bound.pop("key", None)

    def change(led):
        au = {"action": a.action, "target": a.target or "", "source": a.source, "quote": quote,
              "condition": a.condition or "pass", "granted_at": now_iso()}
        if digest:
            au["profile_hash"] = digest
            au["binding"] = bound
            led["profile_hash"] = digest
        ledger_list(led, "authorizations").append(au)
        return f"authorized {a.action}{' ' + a.target if a.target else ''} ({a.source}: {quote[:60]!r})"
    return update_ledger(a.path, change)


def profile_authorization_moved(led: dict, action: str) -> str | None:
    """Why a push or PR the workflow profile pre-authorized may not go ahead now: the checkout or
    any origin or push URL differs from what the profile was confirmed for when it was authorized.
    A user's own words for the action (prompt, answer) don't depend on the profile."""
    auths = [x for x in ledger_list(led, "authorizations")
             if isinstance(x, dict) and x.get("action") == action]
    if not auths or any(x.get("source") in {"prompt", "answer"} for x in auths):
        return None
    now = etk_profile.binding(etk_profile.identify())
    now.pop("key", None)
    for x in auths:
        if x.get("source") == "profile" and x.get("binding") == now:
            return None
    return ("the checkout or the origin/push URLs changed since the profile authorized it "
            "(or the authorization has no recorded binding); authorize it again")


def profile_production(raw_data: str, target: str) -> bool | None:
    """deploy.targets[name == target].production from the profile, None when the target isn't there."""
    prof, _, _, _ = load_profile(raw_data)
    targets = etk_profile.get(prof, "deploy.targets")
    for t in targets if isinstance(targets, list) else []:
        if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip().lower() == target.lower():
            return t.get("production") is True
    return None


def kind_blocker(led: dict) -> str | None:
    kind = led.get("kind", "build") if isinstance(led, dict) else None
    if not isinstance(kind, str) or kind not in NEEDS_AC:
        return (f"a {kind} run can't release; push, PR, merge, tag and deploy belong to "
                f"{'/'.join(sorted(NEEDS_AC))} runs")
    return None


def cmd_ready(a) -> int:
    p = resolve(a.path)
    led = load(p)
    blockers = release_blockers(led) + [b for b in [kind_blocker(led)] if b]
    if blockers:
        print(f"NOT READY: {len(blockers)} thing(s) block a release step in {p}")
        for b in blockers:
            print(f"- {b}")
        return 1
    print(f"READY: {p} (every required gate but G7 settled, ACs met, no blocking finding)")
    return 0


def cmd_act(a) -> int:
    production = a.production
    if a.action in {"deploy", "rollback"} and not a.data:
        refuse(f"act --action {a.action} needs --data DIR (the plugin data dir) so the profile can say "
               "whether the target is production")
    if a.action in {"deploy", "rollback"}:
        target = (a.target or "").strip()
        if not target:
            refuse(f"act --action {a.action} needs --target, the deploy target's name in the profile")
        # The profile knows which targets are production; it can only add the flag, never drop it.
        listed = profile_production(a.data, target)
        if listed is None and not production and not PROD_WORDS.search(target):
            refuse(f"`{target}` is not a deploy target in the workflow profile under {a.data}; add it "
                   "(`profile set deploy.targets …`) or record it with --production")
        production = bool(listed) or production or bool(PROD_WORDS.search(target))

    def change(led):
        actions = ledger_list(led, "actions")
        if a.action in {"push", "pr"}:
            moved = profile_authorization_moved(led, a.action)
            if moved and not a.force_record:
                refuse(f"{a.action} refused: {moved}")
        wrong_kind = kind_blocker(led)
        if a.action in OUTWARD_ACTIONS and wrong_kind and not a.force_record:
            refuse(f"{a.action} refused: {wrong_kind}. Start a ship run for the release")
        blockers = release_blockers(led)
        ok = not blockers
        if a.action in GATED_ACTIONS and not ok and not a.force_record:
            refuse(f"{a.action} refused: the run isn't ready for release (`run ready` fails): "
                   + "; ".join(blockers[:5]) + ("; …" if len(blockers) > 5 else "")
                   + ". Settle the gates first, or record a step that already happened with --force-record")
        actions.append({"action": a.action, "target": a.target or "", "ref": a.ref or "", "url": a.url or "",
                        "command": a.command or "", "exit": a.exit, "production": production,
                        "at": now_iso(), "gates_ok": ok})
        return (f"recorded {a.action}{' ' + a.target if a.target else ''} exit {a.exit}"
                + (" (production)" if production else "") + ("" if ok else " (gates had not passed)"))
    return update_ledger(a.path, change)


def cmd_decide(a) -> int:
    if not a.id.strip() or (a.question is not None and not a.question.strip()):
        refuse("--id and --question must not be empty")

    def change(led):
        decisions = ledger_list(led, "decisions")
        d = next((x for x in decisions if isinstance(x, dict) and x.get("id") == a.id), None)
        if d is None:
            if a.level is None or a.question is None:
                refuse(f"decision {a.id} is new: it needs --level and --question")
            d = {"id": a.id, "status": "pending"}
            decisions.append(d)
        if d.get("level") == "L4" and a.level is not None and a.level != "L4":
            refuse(f"decision {a.id} is L4; only the user can settle it, so its level can't be lowered")
        for key, val in (("level", a.level), ("question", a.question)):
            if val is not None:
                d[key] = val
        d["at"] = now_iso()
        if a.options is not None:
            d["options"] = [o.strip() for o in a.options.split("|") if o.strip()]
        for key, val in (("recommended", a.recommended), ("status", a.status), ("answer_quote", a.answer_quote)):
            if val is not None:
                d[key] = val
        return f"decision {a.id} [{d.get('level')}] {d.get('status')}"
    return update_ledger(a.path, change)


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
    if "phase" in led:
        print(f"**Phase:** {led.get('phase')}\n")
    acs = led.get("acceptance_criteria")
    if isinstance(acs, list) and acs:
        print("**Acceptance criteria**")
        for i, ac in enumerate(acs, 1):
            if isinstance(ac, dict):
                text = f"{ac.get('id', '')} {ac.get('text')}: {ac.get('status', '?')}".strip()
            else:
                text = str(ac)
            print(f"{i}. {text}")
        print()
    print("| Gate | Status | Evidence |\n|---|---|---|")
    gates = led.get("gates") if isinstance(led.get("gates"), dict) else {}
    for g, name in GATES.items():
        if g == "G7" and g not in gates:
            continue  # ledgers from before G7
        gate = gates.get(g) if isinstance(gates.get(g), dict) else {}
        ev = " ".join(str(gate.get("evidence") or "—").split())
        cmd_list = gate.get("commands") if isinstance(gate.get("commands"), list) else []
        cmds = "; ".join(f"`{c.get('cmd')}`→{c.get('exit_code')}" for c in cmd_list if isinstance(c, dict))
        if cmds:
            ev = f"{ev} ({cmds})"
        if gate.get("reason_code"):
            ev = f"[{gate['reason_code']}] {ev}"
        print(f"| {g} {name} | {gate.get('status', '?')} | {ev.replace('|', '/')} |")
    findings = [f for f in (led.get("findings") if isinstance(led.get("findings"), list) else []) if isinstance(f, dict)]
    if findings:
        print("\n| ID | Sev | Status | Location | Summary |\n|---|---|---|---|---|")
        order = {s: i for i, s in enumerate(SEVERITIES)}
        for f in sorted(findings, key=lambda f: order.get(f.get("severity"), 9)):
            summary = " ".join(str(f.get("actual", "")).split())[:90]
            if f.get("status") == "invalid":
                summary = f"not a real finding: {' '.join(str(f.get('resolution', '')).split())[:90]}"
            summary = summary.replace("|", "/")
            print(f"| {f.get('id')} | {f.get('severity')} | {f.get('status')} | `{f.get('location')}` | {summary} |")
    hard = [f for f in findings if isinstance(f.get("hardening"), dict) and f.get("status") != "invalid"]
    if hard:
        print("\n**Hardening proposals**")
        for f in hard:
            print(f"- {f.get('id')} [{f['hardening'].get('layer')}] {f['hardening'].get('proposal')}")
    one_line = lambda v: " ".join(str(v).split()).replace("|", "/")
    auths = [x for x in (led.get("authorizations") if isinstance(led.get("authorizations"), list) else [])
             if isinstance(x, dict)]
    if auths:
        print("\n**Authorizations**")
        for au in auths:
            print(f"- {au.get('action')} {one_line(au.get('target') or 'any target')} ({au.get('source')}): "
                  f"\"{one_line(au.get('quote') or '')}\"")
    acts = [x for x in (led.get("actions") if isinstance(led.get("actions"), list) else []) if isinstance(x, dict)]
    if acts:
        print("\n| Action | Target | Ref / URL | Exit |\n|---|---|---|---|")
        for ac in acts:
            where = " ".join(one_line(ac.get(k)) for k in ("ref", "url") if ac.get(k)) or "—"
            print(f"| {one_line(ac.get('action'))}{' (production)' if ac.get('production') is True else ''} | "
                  f"{one_line(ac.get('target') or '—')} | {where} | {one_line(ac.get('exit'))} |")
    print(f"\nLedger check: {'OK' if not errors else 'FAILED — ' + '; '.join(errors)}")
    return 0


def cmd_latest(a) -> int:
    problem = runs_area_problem(git_root())
    if problem:
        refuse(f"cannot pick the newest run: {problem}")
    print(latest_run() or "")
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
                       for f in findings if isinstance(f, dict) and f.get("status") != "invalid"]
    return out


def cmd_stats(a) -> int:
    root = git_root()
    problem = symlink_problem(root)
    if problem:
        refuse(problem)
    d = runs_dir()
    tracked = tracked_under_etk(root)
    paths = sorted(x for x in d.glob("*/gates.json")
                   if not x.parent.is_symlink() and not x.is_symlink() and not is_tracked(x, root, tracked)) \
        if d.exists() else []
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
    i.add_argument("--kind", choices=["build", "fix", "review", "test", "improve-ui", "ship"], default="build")
    i.add_argument("--max-cycles", type=int, default=None, help="default: project config max_cycles, else 3")
    i.set_defaults(fn=cmd_init)
    for name, fn in (("check", cmd_check), ("render", cmd_render), ("ready", cmd_ready)):
        s = sub.add_parser(name)
        s.add_argument("path", nargs="?")
        s.set_defaults(fn=fn)
    ex = sub.add_parser("exec", help="run a command and record its real exit code in a gate")
    ex.add_argument("gate")
    ex.add_argument("--type", choices=sorted(COMMAND_TYPES), default="test")
    ex.add_argument("--run", default=None, metavar="RUN_DIR", help="default: the newest run")
    ex.set_defaults(fn=cmd_exec)
    st = sub.add_parser("stats")
    st.add_argument("--json", action="store_true")
    st.add_argument("--last", type=int, default=None, metavar="N")
    st.set_defaults(fn=cmd_stats)
    l = sub.add_parser("latest")
    l.set_defaults(fn=cmd_latest)
    ph = sub.add_parser("phase", help="move the run to a phase")
    ph.add_argument("name", metavar="{" + ",".join(PHASES) + "}")
    au = sub.add_parser("authorize", help="record the user's permission for a release action")
    au.add_argument("--action", required=True, choices=RELEASE_ACTIONS)
    au.add_argument("--source", required=True, choices=sorted(AUTH_SOURCES))
    au.add_argument("--quote", default="", help="the user's verbatim words (required unless --source profile)")
    au.add_argument("--target", default="")
    au.add_argument("--condition", default="pass")
    au.add_argument("--data", default=None, metavar="DIR", help="plugin data dir; required for --source profile")
    ac = sub.add_parser("act", help="record a release action that was performed")
    ac.add_argument("--action", required=True, choices=RELEASE_ACTIONS)
    for opt in ("--target", "--ref", "--url", "--command"):
        ac.add_argument(opt, default="")
    ac.add_argument("--exit", required=True, type=int)
    ac.add_argument("--production", action="store_true")
    ac.add_argument("--data", default=None, metavar="DIR",
                    help="plugin data dir, required for deploy/rollback: a target the profile marks production "
                         "is recorded as production")
    ac.add_argument("--force-record", action="store_true",
                    help="record a step that already happened although `ready` fails (gates_ok false)")
    de = sub.add_parser("decide", help="record or update a decision by id")
    de.add_argument("--id", required=True)
    de.add_argument("--level", default=None, choices=sorted(DECISION_LEVELS), help="required for a new id")
    de.add_argument("--question", default=None, help="required for a new id")
    de.add_argument("--options", default=None, help='"a|b|c"')
    de.add_argument("--recommended", default=None)
    de.add_argument("--status", default=None, choices=sorted(DECISION_STATUSES))
    de.add_argument("--answer-quote", default=None)
    for s, fn in ((ph, cmd_phase), (au, cmd_authorize), (ac, cmd_act), (de, cmd_decide)):
        s.add_argument("path", nargs="?", metavar="RUN")
        s.set_defaults(fn=fn)
    argv = sys.argv[1:]
    cmd: list[str] = []
    if argv[:1] == ["exec"] and "--" in argv:  # everything after `--` is the command, untouched by argparse
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    a.cmd = cmd
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
