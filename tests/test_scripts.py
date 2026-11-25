"""Unit tests for the plugin's scripts. Run: python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETK = ROOT / "scripts" / "etk_run.py"
DISCOVER = ROOT / "scripts" / "discover.py"
GUARD = ROOT / "hooks" / "guard.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def sh(args, cwd, stdin=None):
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=30)


def git_repo(path: Path) -> Path:
    sh(["git", "init", "-q", "-b", "main"], path)
    sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], path)
    return path


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = git_repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def init(self, *extra):
        r = sh([sys.executable, str(ETK), "init", "Add discount codes", *extra], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        run = Path(r.stdout.strip())
        return run, json.loads((run / "gates.json").read_text())

    def write(self, run, ledger):
        (run / "gates.json").write_text(json.dumps(ledger))

    def check(self, run):
        return sh([sys.executable, str(ETK), "check", str(run)], self.dir)

    def complete_ledger(self, ledger):
        ledger["acceptance_criteria"] = [{"id": "AC-1", "text": "code applies 10%", "status": "met"}]
        for g in ledger["gates"]:
            ledger["gates"][g] = {"status": "PASS", "evidence": "checked carefully with evidence", "commands": []}
        for g in ("G3", "G4"):
            ledger["gates"][g]["commands"] = [{"cmd": "npm test", "exit_code": 0}]
        ledger["outcome"] = "COMPLETE"
        return ledger

    def test_init_creates_ledger_and_excludes_from_git(self):
        run, ledger = self.init("--mode", "small")
        self.assertEqual(ledger["mode"], "small")
        self.assertEqual({g["status"] for g in ledger["gates"].values()}, {"NOT_RUN"})
        self.assertIn(".etk/", (self.dir / ".git" / "info" / "exclude").read_text())
        self.assertEqual(sh(["git", "status", "--porcelain"], self.dir).stdout.strip(), "")

    def test_fresh_ledger_is_valid_in_progress(self):
        run, _ = self.init()
        self.assertEqual(self.check(run).returncode, 0)

    def test_complete_ledger_passes(self):
        run, ledger = self.init()
        self.write(run, self.complete_ledger(ledger))
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_pass_without_commands_is_rejected(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["gates"]["G3"]["commands"] = []
        self.write(run, ledger)
        r = self.check(run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("tests that did not run cannot pass", r.stdout)

    def test_pass_with_nonzero_exit_is_rejected(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["gates"]["G4"]["commands"] = [{"cmd": "pytest", "exit_code": 1}]
        self.write(run, ledger)
        self.assertIn("exit_code 1", self.check(run).stdout)

    def test_g4_allows_proven_pre_existing_failures_only(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["gates"]["G4"]["commands"] = [{"cmd": "npm test", "exit_code": 1}]
        self.write(run, ledger)
        self.assertIn("pre_existing_failures", self.check(run).stdout)
        ledger["gates"]["G4"]["commands"][0].update(
            pre_existing_failures=["formats refunds"], baseline_evidence="fails on base abc123 too, exit 1")
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0)
        ledger["gates"]["G3"]["commands"][0].update(
            exit_code=1, pre_existing_failures=["x"], baseline_evidence="fails on base abc123 too, exit 1")
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 1, "G3 never accepts a red run")

    def test_complete_with_not_run_gate_is_rejected(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["gates"]["G5"] = {"status": "NOT_RUN", "evidence": "", "commands": []}
        self.write(run, ledger)
        self.assertIn("COMPLETE but G5 is NOT_RUN", self.check(run).stdout)

    def test_status_without_evidence_is_rejected(self):
        run, ledger = self.init()
        ledger["gates"]["G5"] = {"status": "NOT_APPLICABLE", "evidence": "n/a"}
        self.write(run, ledger)
        self.assertIn("G5: status NOT_APPLICABLE needs evidence", self.check(run).stdout)

    def test_g1_cannot_be_not_applicable(self):
        run, ledger = self.init()
        ledger["gates"]["G1"] = {"status": "NOT_APPLICABLE", "evidence": "no requirements here really"}
        self.write(run, ledger)
        self.assertIn("G1: cannot be NOT_APPLICABLE", self.check(run).stdout)

    def finding(self, **kw):
        f = {"id": "R1-001", "severity": "high", "location": "a.py:1", "evidence": "repro: f(0) raises",
             "expected": "returns 0", "actual": "ZeroDivisionError", "remediation": "guard zero", "status": "open"}
        f.update(kw)
        return f

    def test_open_high_finding_blocks_complete(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding()]
        self.write(run, ledger)
        self.assertIn("high finding R1-001 is open", self.check(run).stdout)

    def test_fixed_but_unverified_high_finding_blocks_complete(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding(status="fixed")]
        self.write(run, ledger)
        self.assertIn("not independently verified", self.check(run).stdout)

    def test_verified_finding_allows_complete(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding(status="verified"), self.finding(id="R1-002", severity="low")]
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0)

    def test_accepted_risk_needs_user(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding(status="accepted_risk", resolution="Lead thinks it is fine")]
        self.write(run, ledger)
        self.assertIn("accepted_by_user", self.check(run).stdout)
        ledger["findings"][0]["accepted_by_user"] = True
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0)

    def test_finding_missing_fields_and_duplicates(self):
        run, ledger = self.init()
        ledger["findings"] = [self.finding(evidence=""), self.finding()]
        self.write(run, ledger)
        out = self.check(run).stdout
        self.assertIn("missing evidence", out)
        self.assertIn("duplicate id", out)

    def test_disputed_needs_resolution(self):
        run, ledger = self.init()
        ledger["findings"] = [self.finding(status="disputed")]
        self.write(run, ledger)
        self.assertIn("needs a 'resolution'", self.check(run).stdout)

    def test_unmet_ac_blocks_complete(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["acceptance_criteria"].append({"id": "AC-2", "text": "one code per cart", "status": "not_met"})
        self.write(run, ledger)
        self.assertIn("AC-2 is not marked met", self.check(run).stdout)
        ledger["acceptance_criteria"][1] = "plain string without a status"
        self.write(run, ledger)
        self.assertIn("not marked met", self.check(run).stdout)

    def test_build_cannot_skip_review_or_tests_by_calling_them_na(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["gates"]["G2"] = {"status": "NOT_APPLICABLE", "evidence": "small change, no review needed"}
        ledger["gates"]["G3"] = {"status": "NOT_APPLICABLE", "evidence": "no tests in this repo at all"}
        self.write(run, ledger)
        out = self.check(run).stdout
        self.assertIn("G2: cannot be NOT_APPLICABLE for a build run", out)
        self.assertIn("G3: NOT_APPLICABLE on a build run needs reason_code", out)
        ledger["gates"]["G2"] = {"status": "PASS", "evidence": "self-review (small mode), 1 file"}
        ledger["gates"]["G3"]["reason_code"] = "no_test_setup"
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)

    def test_wont_fix_on_high_needs_the_user(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding(status="wont_fix", resolution="out of scope says the Lead")]
        self.write(run, ledger)
        self.assertIn("only the user can accept", self.check(run).stdout)

    def test_open_medium_blocks_complete(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding(severity="medium")]
        self.write(run, ledger)
        self.assertIn("medium finding R1-001 is open", self.check(run).stdout)
        ledger["findings"][0]["status"] = "fixed"
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0)

    def test_report_only_review_may_complete_with_open_medium(self):
        run, ledger = self.init("--kind", "review")
        ledger["gates"]["G2"] = {"status": "PASS", "evidence": "reviewed git diff main, 3 files"}
        ledger["gates"]["G6"] = {"status": "PASS", "evidence": "no secrets, authz checked on new route"}
        ledger["findings"] = [self.finding(severity="medium")]
        ledger["outcome"] = "COMPLETE"
        self.write(run, ledger)
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        ledger["findings"][0]["severity"] = "high"
        self.write(run, ledger)
        self.assertIn("high finding R1-001 is open", self.check(run).stdout)

    def test_invalid_finding_needs_evidence_but_not_the_user(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = [self.finding(status="invalid")]
        self.write(run, ledger)
        self.assertIn("status invalid needs a 'resolution'", self.check(run).stdout)
        ledger["findings"][0]["resolution"] = "f(0) returns 0: test test_zero passes on this commit"
        self.write(run, ledger)
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = sh([sys.executable, str(ETK), "render", str(run)], self.dir).stdout
        self.assertIn("| R1-001 | high | invalid |", out)
        self.assertIn("test_zero passes", out)

    def test_two_inits_in_the_same_second_get_separate_runs(self):
        stub = self.dir / "freeze.py"
        stub.write_text("import datetime as dt, sys, runpy\n"
                        "class D(dt.datetime):\n"
                        "    @classmethod\n"
                        "    def now(cls, tz=None): return cls(2026, 1, 2, 3, 4, 5)\n"
                        "dt.datetime = D\n"
                        f"sys.argv = [{str(ETK)!r}] + sys.argv[1:]\n"
                        f"runpy.run_path({str(ETK)!r}, run_name='__main__')\n")
        runs = []
        for _ in range(2):
            r = sh([sys.executable, str(stub), "init", "Same task"], self.dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            runs.append(Path(r.stdout.strip()))
        self.assertNotEqual(runs[0], runs[1])
        self.assertTrue(all((p / "gates.json").exists() for p in runs))

    def test_render_survives_malformed_acs_and_gates(self):
        run, ledger = self.init()
        for ledger_edit in ({"acceptance_criteria": [7, None, {"text": "ok"}], "gates": {"G1": "oops", "G2": None, "G3": {"commands": "x", "evidence": 5}}},
                            {"acceptance_criteria": "not a list", "gates": ["x"], "findings": "nope"},
                            {"acceptance_criteria": 5, "gates": None}):
            self.write(run, {**ledger, **ledger_edit})
            r = sh([sys.executable, str(ETK), "render", str(run)], self.dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertIn("Ledger check: FAILED", r.stdout)

    def exec_cmd(self, run, *args):
        return sh([sys.executable, str(ETK), "exec", *args], self.dir)

    def test_exec_records_the_real_exit_code_and_last_line(self):
        run, _ = self.init()
        r = self.exec_cmd(run, "G3", "--type", "test", "--run", str(run), "--", sys.executable, "-c",
                          "print('a'); print('3 passed'); raise SystemExit(4)")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("3 passed", r.stdout)
        cmds = json.loads((run / "gates.json").read_text())["gates"]["G3"]["commands"]
        self.assertEqual(len(cmds), 1)
        self.assertEqual((cmds[0]["exit_code"], cmds[0]["last_line"], cmds[0]["type"], cmds[0]["recorded_by"]),
                         (4, "3 passed", "test", "exec"))

    def test_exec_without_a_command_or_with_a_bad_gate_changes_nothing(self):
        run, _ = self.init()
        before = (run / "gates.json").read_text()
        self.assertEqual(self.exec_cmd(run, "G9", "--", "true").returncode, 2)
        self.assertEqual(self.exec_cmd(run, "G3").returncode, 2)
        self.assertEqual((run / "gates.json").read_text(), before)

    def test_exec_records_a_command_that_cannot_start(self):
        run, _ = self.init()
        r = self.exec_cmd(run, "G4", "--", "no-such-binary-etk")
        self.assertEqual(r.returncode, 127)
        cmd = json.loads((run / "gates.json").read_text())["gates"]["G4"]["commands"][0]
        self.assertEqual(cmd["exit_code"], 127)

    def test_check_warns_on_pass_commands_not_recorded_by_exec(self):
        run, ledger = self.init()
        self.write(run, self.complete_ledger(ledger))
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("warning: G3: `npm test` was not recorded by `etk_run.py exec`", r.stdout)
        ledger["gates"]["G3"]["commands"][0]["recorded_by"] = "exec"
        ledger["gates"]["G4"]["commands"][0]["recorded_by"] = "exec"
        self.write(run, ledger)
        self.assertNotIn("not recorded by", self.check(run).stdout)

    def test_launcher_exposes_exec_but_not_through_run(self):
        run, _ = self.init()
        etk_sh = str(ROOT / "scripts" / "etk.sh")
        r = sh(["sh", etk_sh, "exec", "G3", "--type", "test", "--", "true"], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(json.loads((run / "gates.json").read_text())["gates"]["G3"]["commands"]), 1)
        marker = self.dir / "ran"
        r = sh(["sh", etk_sh, "run", "exec", "G3", "--", "touch", str(marker)], self.dir)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(marker.exists(), "`etk.sh run exec` must not run commands: skills pre-approve `run:*`")

    def test_malformed_ledger_gives_messages_not_tracebacks(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["findings"] = ["oops"]
        ledger["gates"]["G3"]["commands"] = [{"cmd": "npm test", "exit_code": "0"}]
        self.write(run, ledger)
        r = self.check(run)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertIn("findings must be objects", r.stdout)
        self.assertIn("exit_code must be an integer", r.stdout)

    def test_max_cycles_comes_from_project_config(self):
        (self.dir / ".claude").mkdir()
        (self.dir / ".claude" / "engineering-team.json").write_text('{"max_cycles": 5}')
        _, ledger = self.init()
        self.assertEqual(ledger["max_cycles"], 5)

    def test_exclude_works_inside_a_worktree(self):
        sh(["git", "worktree", "add", "-q", str(self.dir / "wt"), "-b", "wt"], self.dir)
        wt = self.dir / "wt"
        r = sh([sys.executable, str(ETK), "init", "x"], wt)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(".etk", sh(["git", "status", "--porcelain"], wt).stdout)

    def test_review_kind_only_owns_g2_g6(self):
        run, ledger = self.init("--kind", "review")
        ledger["gates"]["G2"] = {"status": "PASS", "evidence": "reviewed git diff main, 3 files"}
        ledger["gates"]["G6"] = {"status": "PASS", "evidence": "no secrets, authz checked on new route"}
        ledger["outcome"] = "COMPLETE"
        self.write(run, ledger)
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_render_and_latest(self):
        run, ledger = self.init()
        ledger["findings"] = [self.finding()]
        self.write(run, ledger)
        out = sh([sys.executable, str(ETK), "render"], self.dir).stdout
        self.assertIn("| G3 Automated tests | NOT_RUN |", out)
        self.assertIn("R1-001", out)
        self.assertEqual(sh([sys.executable, str(ETK), "latest"], self.dir).stdout.strip(), str(run))

    def test_command_type_validated(self):
        run, ledger = self.init()
        ledger["gates"]["G3"]["commands"] = [{"cmd": "npm test", "exit_code": 0, "type": "bogus"}]
        self.write(run, ledger)
        self.assertIn("type must be one of", self.check(run).stdout)
        ledger["gates"]["G3"]["commands"][0]["type"] = "test"
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0)

    def test_runtime_verification_warning(self):
        run, ledger = self.init()
        ledger = self.complete_ledger(ledger)
        ledger["gates"]["G5"] = {"status": "NOT_APPLICABLE", "evidence": "no UI in this change at all"}
        self.write(run, ledger)
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("no runtime verification recorded", r.stdout)
        ledger["gates"]["G4"]["commands"].append({"cmd": "node server.js & curl :3000", "exit_code": 0, "type": "runtime"})
        self.write(run, ledger)
        self.assertNotIn("no runtime verification", self.check(run).stdout)
        ledger["gates"]["G4"]["commands"].pop()
        ledger["gates"]["G5"] = {"status": "PASS", "evidence": "walked the flow in the browser"}
        self.write(run, ledger)
        self.assertNotIn("no runtime verification", self.check(run).stdout)
        ledger["gates"]["G5"] = {"status": "NOT_APPLICABLE", "evidence": "no UI in this change at all"}
        ledger["mode"] = "small"
        self.write(run, ledger)
        self.assertNotIn("no runtime verification", self.check(run).stdout)

    def test_hardening_validation_and_render(self):
        run, ledger = self.init()
        ledger["findings"] = [self.finding(hardening={"layer": "nope", "proposal": "x"})]
        self.write(run, ledger)
        self.assertIn("hardening.layer", self.check(run).stdout)
        ledger["findings"] = [self.finding(hardening={"layer": "static", "proposal": " "})]
        self.write(run, ledger)
        self.assertIn("hardening.proposal", self.check(run).stdout)
        ledger["findings"] = [self.finding(category=3)]
        self.write(run, ledger)
        self.assertIn("category must be a string", self.check(run).stdout)
        ledger["findings"] = [self.finding(category="authz", hardening={"layer": "static", "proposal": "lint rule for route guards"})]
        self.write(run, ledger)
        self.assertEqual(self.check(run).returncode, 0)
        out = sh([sys.executable, str(ETK), "render"], self.dir).stdout
        self.assertIn("Hardening proposals", out)
        self.assertIn("- R1-001 [static] lint rule for route guards", out)

    def test_malformed_new_fields_report_instead_of_crash(self):
        run, _ = self.init()
        for bad in ({"commands": 5}, {"commands": [{"cmd": "x", "exit_code": 0, "type": ["runtime"]}]}):
            ledger = json.loads((run / "gates.json").read_text())
            ledger["gates"]["G3"].update(bad)
            self.write(run, ledger)
            r = self.check(run)
            self.assertEqual(r.returncode, 1, bad)
            self.assertNotIn("Traceback", r.stderr + r.stdout)
        ledger["gates"]["G3"]["commands"] = []
        ledger["mode"] = ["medium"]
        ledger["findings"] = [self.finding(hardening={"layer": ["static"], "proposal": "x"})]
        self.write(run, ledger)
        r = self.check(run)
        self.assertNotIn("Traceback", r.stderr + r.stdout)

    def test_stats_survives_hand_edited_ledgers(self):
        bad = {"kind": ["build"], "mode": "medium", "findings": 5, "gates": {"G3": {"commands": 5}}}
        worse = {"kind": "fix", "findings": [{"severity": ["high"], "category": 3}], "gates": []}
        for name, led in (("20260101-x", bad), ("20260102-y", worse)):
            d = self.dir / ".etk" / "runs" / name
            d.mkdir(parents=True)
            (d / "gates.json").write_text(json.dumps(led))
        r = sh([sys.executable, str(ETK), "stats", "--json"], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["runs"], 2)
        self.assertEqual(sh([sys.executable, str(ETK), "stats"], self.dir).returncode, 0)

    def make_run(self, name, findings=(), kind="build", outcome="COMPLETE", runtime=False):
        d = self.dir / ".etk" / "runs" / name
        d.mkdir(parents=True)
        cmds = [{"cmd": "run", "exit_code": 0, "type": "runtime"}] if runtime else []
        (d / "gates.json").write_text(json.dumps({
            "kind": kind, "mode": "medium", "outcome": outcome, "cycles": 1,
            "gates": {"G3": {"commands": cmds}}, "findings": list(findings)}))

    def test_stats(self):
        hard = {"layer": "static", "proposal": "lint rule for N+1"}
        self.make_run("20260101-a", [self.finding(id="a1", severity="medium", category="perf", hardening=hard),
                                     self.finding(id="a2", severity="low", category="style")])
        self.make_run("20260102-b", [self.finding(id="b1", severity="medium", category="perf")], runtime=True)
        self.make_run("20260103-c", [], outcome="INCOMPLETE")
        (self.dir / ".etk" / "runs" / "20260104-bad").mkdir()
        (self.dir / ".etk" / "runs" / "20260104-bad" / "gates.json").write_text("{nope")
        r = sh([sys.executable, str(ETK), "stats", "--json"], self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["runs"], 3)
        self.assertEqual(d["by_outcome"], {"COMPLETE": 2, "INCOMPLETE": 1})
        self.assertEqual(d["findings_by_severity"], {"medium": 2, "low": 1})
        self.assertEqual([c["category"] for c in d["ratchet_candidates"]], ["perf"])
        self.assertEqual(d["ratchet_candidates"][0]["proposals"], ["[static] lint rule for N+1"])
        self.assertEqual(d["trust"]["trend"], "down")  # older 2 findings, newer 0.5
        self.assertEqual(d["trust"]["runtime_verified_share"], 0.33)
        self.assertEqual(len(d["warnings"]), 1)
        md = sh([sys.executable, str(ETK), "stats", "--last", "3"], self.dir).stdout
        self.assertIn("2 run(s)", md)
        self.assertNotIn("Traceback", md)
        self.assertIn("Ratchet candidates", sh([sys.executable, str(ETK), "stats"], self.dir).stdout)


class GuardTests(unittest.TestCase):
    def call(self, tool, inp, agent="engineering-team:developer", cwd="/work/proj"):
        payload = {"tool_name": tool, "tool_input": inp, "cwd": cwd, "hook_event_name": "PreToolUse"}
        if agent:
            payload["agent_type"] = agent
        return sh([sys.executable, str(GUARD)], "/", stdin=json.dumps(payload))

    def blocked(self, cmd, **kw):
        return self.call("Bash", {"command": cmd}, **kw).returncode == 2

    def test_main_session_untouched(self):
        self.assertFalse(self.blocked("git push origin main", agent=None))
        self.assertFalse(self.blocked("git push", agent="other-plugin:agent"))

    def test_blocks_dangerous_git(self):
        for cmd in ["git checkout HEAD -- src/a.js", "git checkout main -- .", "git reset HEAD~1 --hard",
                    "git -C . push", "git -c x=y push origin", "git switch -f main",
                    "git worktree remove --force ../wt", "cd sub && git push", "FOO=1 git push",
                    "git push", "git push --force origin x", "git reset --hard HEAD~1", "git clean -fd",
                    "git checkout -- .", "git checkout .", "git restore src/a.ts", "git stash", "git stash pop",
                    "git branch -D feature", "git rebase main", "git commit --amend -m x"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd))

    def test_allows_normal_work(self):
        for cmd in ["git status", "git diff main...HEAD", "git log --oneline -5", "git stash list",
                    "git add src/a.ts && git commit -m 'Add discount parsing'", "git restore --staged a.ts",
                    "git checkout -b etk/feature", "npm test", "pytest -q", "rm -rf node_modules/.cache",
                    "rm -rf /work/proj/build", "git worktree add ../base HEAD", "git worktree remove ../base",
                    'grep -rn "git push" scripts/', 'rg "git rebase" docs', 'git log --grep="git restore"',
                    'git commit -m "docs: never git push --force"', "echo 'npm publish' >> /dev/null",
                    "cat > notes.md <<EOF\nrun git push and shopify app deploy later\nEOF",
                    "rm -rf /tmp/etk-base"]:
            with self.subTest(cmd=cmd):
                self.assertFalse(self.blocked(cmd), cmd)

    def test_blocks_deploy_and_publish(self):
        for cmd in ["npm publish", "shopify app deploy", "shopify theme push --live", "vercel deploy --prod",
                    "terraform apply", "kubectl apply -f k8s.yml", "gh pr merge 12", "docker push img",
                    "psql -c 'DROP TABLE users'"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd))

    def test_shopify_dev_commands_allowed(self):
        for cmd in ["shopify app dev", "shopify theme dev", "shopify theme check"]:
            with self.subTest(cmd=cmd):
                self.assertFalse(self.blocked(cmd))

    def test_rm_outside_project(self):
        for cmd in ["rm -rf /", "rm -rf ~", "rm -rf ~/projects", "rm -rf ..", "rm -rf /etc/x", "rm -fr $HOME/x",
                    "rm -rf ../sibling", "rm -rf ../../other", "rm -rf .", "rm -r -f src/../../x"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd))

    def test_secret_files(self):
        self.assertTrue(self.blocked("git add .env"))
        self.assertTrue(self.blocked("git add config/key.pem"))
        self.assertFalse(self.blocked("git add .env.example"))
        self.assertEqual(self.call("Write", {"file_path": "/work/proj/.env.local", "content": "x"}).returncode, 2)
        self.assertEqual(self.call("Edit", {"file_path": "/work/proj/.env.example"}).returncode, 0)
        self.assertEqual(self.call("Write", {"file_path": "/work/proj/src/env.ts"}).returncode, 0)

    def test_secret_redirects_and_bulk_add(self):
        self.assertTrue(self.blocked("echo SECRET=1 >> .env"))
        with tempfile.TemporaryDirectory() as tmp:
            d = git_repo(Path(tmp))
            (d / "a.js").write_text("x")
            self.assertFalse(self.blocked("git add -A", cwd=str(d)))
            (d / ".env").write_text("TOKEN=1")
            self.assertTrue(self.blocked("git add -A", cwd=str(d)))
            self.assertTrue(self.blocked("git add .", cwd=str(d)))
            self.assertFalse(self.blocked("git add a.js", cwd=str(d)))

    def test_read_only_roles_cannot_write_through_the_shell(self):
        rv = "engineering-team:code-reviewer"
        for cmd in ["echo x > src/a.js", "sed -i s/a/b/ src/a.js", "rm src/a.js", "git apply fix.patch",
                    "tee out.txt", "cp a b", "git checkout -- ."]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd, agent=rv))
        for cmd in ["git diff main", "npm test > /dev/null", "npm test 2>&1 | tail -20", "cat src/a.js",
                    "echo hi > /tmp/review-notes.txt", "grep -rn TODO src"]:
            with self.subTest(cmd=cmd):
                self.assertFalse(self.blocked(cmd, agent=rv))
        self.assertFalse(self.blocked("echo x > src/a.js", agent="engineering-team:developer"))

    def test_qa_may_only_create_new_files(self):
        qa = "engineering-team:qa-engineer"
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.test.js"
            existing.write_text("x")
            self.assertEqual(self.call("Write", {"file_path": str(existing)}, agent=qa).returncode, 2)
            self.assertEqual(self.call("Edit", {"file_path": str(existing)}, agent=qa).returncode, 2)
            self.assertEqual(self.call("Write", {"file_path": str(Path(tmp) / "new.test.js")}, agent=qa).returncode, 0)

    def test_wrapper_skips_python_for_main_session(self):
        wrapper = ROOT / "hooks" / "run-guard.sh"
        main = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}})
        sub = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"},
                          "agent_type": "engineering-team:developer", "cwd": "/"})
        self.assertEqual(sh(["sh", str(wrapper)], "/", stdin=main).returncode, 0)
        self.assertEqual(sh(["sh", str(wrapper)], "/", stdin=sub).returncode, 2)

    def test_nested_shells_are_checked(self):
        for cmd in ['bash -c "git push"', "sh -c 'cd x && git reset --hard'", 'eval "git push"',
                    'echo $(git push)', 'echo `git stash`', "bash <<EOF\ngit push origin main\nEOF",
                    'rm -rf "$TARGET"', "rm -rf $HOME/x"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd))
        self.assertFalse(self.blocked('bash -c "npm test"'))
        self.assertFalse(self.blocked('echo "$(git rev-parse HEAD)"'))

    def test_redirect_forms(self):
        rv = "engineering-team:code-reviewer"
        for cmd in ["npm test &> src/log.txt", "npm test 2> src/err.txt", "echo x >| src/a.js", "echo x &>> .env"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd, agent=rv))
        self.assertFalse(self.blocked("npm test 2>&1 | tail -5", agent=rv))
        self.assertTrue(self.blocked("echo x &> .env"))

    def test_qa_cannot_overwrite_through_the_shell(self):
        qa = "engineering-team:qa-engineer"
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src.js").write_text("x")
            for cmd in ["echo y > src.js", "sed -i s/x/y/ src.js", "cp other.js src.js"]:
                with self.subTest(cmd=cmd):
                    self.assertTrue(self.blocked(cmd, agent=qa, cwd=tmp))
            self.assertFalse(self.blocked("echo y > new.test.js", agent=qa, cwd=tmp))
            self.assertFalse(self.blocked("npm test > /tmp/qa-out.txt", agent=qa, cwd=tmp))

    def test_review_round_two_bypasses(self):
        rv, qa = "engineering-team:code-reviewer", "engineering-team:qa-engineer"
        self.assertTrue(self.blocked('bash -lc "git push"'))
        self.assertTrue(self.blocked('bash -c "npm test" > src/a.js', agent=rv))
        self.assertTrue(self.blocked("bash -c"))
        self.assertTrue(self.blocked("rm src/a.js /tmp/x", agent=rv))
        self.assertTrue(self.blocked("echo x >& src/a.js", agent=rv))
        self.assertFalse(self.blocked("npm test >&2", agent=rv))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.js").write_text("x")
            self.assertTrue(self.blocked("rm a.js new.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("mv a.js b.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("dd if=/dev/zero of=a.js", agent=qa, cwd=tmp))
            self.assertFalse(self.blocked("cp a.js new.test.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp -t . other/a.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp --target-directory=. other/a.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp -rt . other/a.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp -t. other/a.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp --target . other/a.js", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp --targ=. other/a.js", agent=qa, cwd=tmp))
            self.assertFalse(self.blocked("cp -r fixtures new-dir", agent=qa, cwd=tmp))
            self.assertTrue(self.blocked("cp -t src x.js", agent=rv))

    def test_scout_and_tech_writer_roles(self):
        sc, tw = "engineering-team:scout", "engineering-team:tech-writer"
        self.assertTrue(self.blocked("echo x > notes.md", agent=sc))
        self.assertEqual(self.call("Write", {"file_path": "/work/proj/a.md"}, agent=sc).returncode, 2)
        self.assertFalse(self.blocked("git log --oneline -20", agent=sc))
        self.assertEqual(self.call("Write", {"file_path": "/work/proj/docs/agent/FEATURES.md"}, agent=tw).returncode, 0)
        self.assertEqual(self.call("Edit", {"file_path": "/work/proj/src/app.ts"}, agent=tw).returncode, 2)
        self.assertTrue(self.blocked("sed -i s/a/b/ README.md", agent=tw))

    def test_docs_only_role_leaves_agent_instructions_alone(self):
        tw = "engineering-team:tech-writer"
        for path in ("/work/proj/CLAUDE.md", "/work/proj/CLAUDE.local.md", "/work/proj/.github/copilot-instructions.md", "/work/proj/.claude/agents/x.md", "/work/proj/skills/a/SKILL.md",
                     "/work/proj/sub/AGENTS.md", "/work/proj/.claude/rules/r.md"):
            self.assertEqual(self.call("Write", {"file_path": path}, agent=tw).returncode, 2, path)
        self.assertEqual(self.call("Write", {"file_path": "/work/proj/README.md"}, agent=tw).returncode, 0)
        self.assertEqual(self.call("Edit", {"file_path": "/work/proj/docs/guide.MD"}, agent=tw).returncode, 0)

    def test_read_only_roles_cannot_write_via_tools_or_inline_code(self):
        for agent in ("engineering-team:scout", "engineering-team:code-reviewer", "engineering-team:tech-writer"):
            for cmd in ("perl -pi -e 's/a/b/' src/app.js", "npx prettier --write src/app.js", "npx eslint --fix src",
                        "node -e \"require('fs').writeFileSync('src/a.js','x')\"",
                        "python3 -c \"open('src/a.py','w').write('x')\"",
                        "ruby -i.bak -pe 'x' src/a.rb",
                        "python3.11 -c \"open('src/a.py','w').write('x')\"",
                        "/usr/bin/nodejs -e \"require('fs').writeFileSync('a','x')\""):
                self.assertTrue(self.blocked(cmd, agent=agent), (agent, cmd))
        rv = "engineering-team:code-reviewer"
        for cmd in ("python3 -c \"import json; print(json.load(open('package.json'))['name'])\"",
                    "node -e \"console.log(require('./package.json').version)\"",
                    "npx eslint src", "npx prettier --check src", "perl -ne 'print if /TODO/' src/a.js",
                    "perl -Ilib t/test.pl", "ruby -Ilib -e 'puts 1'", "perl -mstrict -e 'print 1'",
                    "python3 -c \"print(open('x').read())\"", "python3 -c \"open('a')\"",
                    "grep -rn shutil. src && node --version", "black --check .", "ruff format --check src",
                    "git log -p | grep \"open(f, 'w')\"", "python3 -m pytest -q"):
            self.assertFalse(self.blocked(cmd, agent=rv), cmd)
        for cmd in ("/usr/bin/env python3 -c \"open('x','w')\"", "env python3 -c \"open('x', mode='a')\"",
                    "npx prettier -w src", "ruff format src", "black .", "gofmt -w main.go", "rubocop -A",
                    "sed --in-place s/a/b/ f", "python3 -c \"import os; os.replace('a','b')\"",
                    "python3 -c \"import subprocess; subprocess.run(['rm','f'])\"",
                    "node -e \"require('fs').copyFileSync('a','b')\"", "perl -e 'open(F, \">f\")'",
                    "echo \"open('x','w')\" | python3", "python3 - <<'EOF'\nopen('x','w').write('y')\nEOF"):
            self.assertTrue(self.blocked(cmd, agent=rv), cmd)

    def test_bad_input_never_blocks(self):
        r = sh([sys.executable, str(GUARD)], "/", stdin="not json")
        self.assertEqual(r.returncode, 0)


class DiscoverTests(unittest.TestCase):
    def snapshot(self, fixture):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / fixture
            subprocess.run(["cp", "-r", str(FIXTURES / fixture), str(dst)], check=True)
            git_repo(dst)
            r = sh([sys.executable, str(DISCOVER)], dst)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_node_project(self):
        out = self.snapshot("node-small-bug")
        self.assertIn("node (npm)", out)
        self.assertIn("`npm run test`", out)
        self.assertIn("`CLAUDE.md`", out)
        self.assertNotIn("Shopify", out)

    def test_shopify_theme_detected_with_project_skill(self):
        out = self.snapshot("shopify-theme")
        self.assertIn("Shopify theme (Liquid)", out)
        self.assertIn("`liquid-conventions`", out)

    def test_strict_arch_config_is_shown(self):
        out = self.snapshot("python-strict-arch")
        self.assertIn("python", out)
        self.assertIn("engineering-team.json", out)
        self.assertIn("protected_paths", out)
        self.assertNotIn("Shopify", out)

    def test_uncommitted_changes_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = git_repo(Path(tmp))
            (d / "wip.txt").write_text("user work")
            out = sh([sys.executable, str(DISCOVER)], d).stdout
            self.assertIn("Uncommitted changes (do not overwrite)", out)
            self.assertIn("wip.txt", out)

    def test_never_fails_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = sh([sys.executable, str(DISCOVER)], tmp)
            self.assertEqual(r.returncode, 0)
            self.assertIn("not a repository", r.stdout)


    def project(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = git_repo(Path(tmp.name))
        for name, content in files.items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(content)
        return d

    def test_hard_checks_strong_project(self):
        d = self.project({"eslint.config.js": "export default []", "tsconfig.json": "{}",
                          "src/a.test.ts": "x", ".github/workflows/ci.yml": "on: push"})
        out = sh([sys.executable, str(DISCOVER)], d).stdout
        self.assertIn("### Hard checks", out)
        self.assertIn("lint: ✓ `eslint.config.js`", out)
        self.assertIn("types: ✓ `tsconfig.json`", out)
        self.assertIn("ci: ✓", out)
        self.assertIn("format: ✗", out)
        self.assertNotIn("weak hard constraints", out)
        self.assertIn("constraints: ok", out)

    def test_hard_checks_weak_fixture(self):
        out = self.snapshot("ui-static")
        self.assertIn("lint: ✗", out)
        self.assertIn("weak hard constraints", out)
        self.assertIn("recommend adding lint, types, tests, ci", out)

    def test_boundaries_detected(self):
        d = self.project({"eslint.config.js": "rules: {'no-restricted-imports': 1}"})
        self.assertIn("boundaries: ✓ `eslint.config.js (import rules)`", sh([sys.executable, str(DISCOVER)], d).stdout)

    def test_path_scoped_rules_printed(self):
        d = self.project({".claude/engineering-team.json": json.dumps({"rules": [
            {"paths": ["src/api/**"], "rule": "no direct db access", "check": "npm run lint:api"},
            {"paths": ["web/"], "rule": "use tokens"}]})})
        out = sh([sys.executable, str(DISCOVER)], d).stdout
        self.assertIn("### Path-scoped rules", out)
        self.assertIn("`src/api/**` → no direct db access (check: `npm run lint:api`)", out)
        self.assertIn("`web/` → use tokens", out)


    def test_odd_composer_and_package_scripts_dont_break_snapshot(self):
        d = self.project({"composer.json": '{"scripts": ["test"]}', "package.json": '{"scripts": ["x"], "dependencies": ["react"]}',
                          ".claude/engineering-team.json": '{"rules": [{"paths": "a/**", "rule": "keep"}]}'})
        out = sh([sys.executable, str(DISCOVER)], d).stdout
        self.assertIn("### Hard checks", out)
        self.assertIn("### Path-scoped rules", out)
        self.assertNotIn("discover.py failed", out)

    def test_skills_named_like_build_output_are_found(self):
        skill = "---\nname: {n}\ndescription: does {n}\n---\n"
        files = {".claude/skills/build/SKILL.md": skill.format(n="build"),
                 "skills/test/SKILL.md": skill.format(n="test")}
        d = self.project(files)
        out = sh([sys.executable, str(DISCOVER)], d).stdout
        self.assertIn(".claude/skills/build/SKILL.md", out)
        self.assertIn("skills/test/SKILL.md", out)
        self.assertIn("tests: ✗", out)
        # same layout without git: only top-level build dirs are skipped
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in {**files, "build/out.md": "x", "vendor/skills/x/SKILL.md": skill.format(n="x")}.items():
                (Path(tmp) / name).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / name).write_text(content)
            out = sh([sys.executable, str(DISCOVER)], tmp).stdout
        self.assertIn(".claude/skills/build/SKILL.md", out)
        self.assertNotIn("vendor/skills/x/SKILL.md", out)

    def test_launcher_skips_broken_python(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bin_dir = Path(tmp.name)
        (bin_dir / "python3").write_text("#!/bin/sh\necho broken shim >&2\nexit 127\n")
        (bin_dir / "python3").chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        r = subprocess.run(["sh", str(ROOT / "scripts" / "etk.sh"), "run", "latest"], cwd=bin_dir,
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["sh", str(ROOT / "scripts" / "etk.sh"), "nope"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()


class EvalRunTests(unittest.TestCase):
    """evals/run.sh against a one-skill mini repo and a stand-in `claude`."""

    SNAPSHOT = '!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover`'

    def mini_repo(self, skill_text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        (root / "evals").mkdir(parents=True)
        (root / "skills" / "one").mkdir(parents=True)
        (root / "evals" / "run.sh").write_text((ROOT / "evals" / "run.sh").read_text())
        (root / "skills" / "one" / "SKILL.md").write_text(skill_text)
        sh(["git", "init", "-q"], root)
        bin_dir = Path(tmp.name) / "bin"
        bin_dir.mkdir()
        (bin_dir / "claude").write_text(
            "#!/bin/sh\n"
            "grep -q 'Run this first with the Bash tool' skills/one/SKILL.md || { echo unpatched; exit 9; }\n"
            "echo \"claude $*\"\n")
        (bin_dir / "xargs").write_text("#!/bin/sh\necho xargs must not be used >&2\nexit 99\n")
        for f in bin_dir.iterdir():
            f.chmod(0o755)
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", TMPDIR=tmp.name)
        return root, env

    def run_script(self, root, env, *args):
        return subprocess.run(["sh", str(root / "evals" / "run.sh"), *args], cwd=root, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_patches_every_skill_without_xargs_and_warns_about_threshold(self):
        root, env = self.mini_repo(f"---\nname: one\n---\n{self.SNAPSHOT}\n")
        r = self.run_script(root, env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("claude plugin eval", r.stdout)
        self.assertIn("--threshold 0", r.stderr)
        self.assertIn(self.SNAPSHOT, (root / "skills" / "one" / "SKILL.md").read_text(), "the real skill must stay untouched")

    def test_no_threshold_warning_when_caller_sets_one(self):
        root, env = self.mini_repo(f"---\nname: one\n---\n{self.SNAPSHOT}\n")
        r = self.run_script(root, env, "--threshold", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("exits 0 whatever", r.stderr)

    def test_fails_when_a_skill_was_not_rewritten(self):
        root, env = self.mini_repo("---\nname: one\n---\nno snapshot line here\n")
        r = self.run_script(root, env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("rewrote the snapshot line in 0 of 1 skills", r.stderr)
        self.assertNotIn("claude plugin eval", r.stdout)


class LauncherPythonTests(unittest.TestCase):
    """The launchers pick the first Python that runs and is 3.12+, and say so when none is."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for tool in ("dirname", "cat"):
            (self.bin / tool).symlink_to(next(Path(d) / tool for d in ("/usr/bin", "/bin") if (Path(d) / tool).exists()))

    def fake_python(self, name, version_ok):
        """Answers the launcher's version probe (`-c`), otherwise reports which fake ran the script."""
        (self.bin / name).write_text(
            "#!/bin/sh\n"
            f'if [ "$1" = "-c" ]; then exit {0 if version_ok else 1}; fi\n'
            f'echo "FAKE {name} $*"\n')
        (self.bin / name).chmod(0o755)

    def without_absolute_pythons(self, script):
        """Copy a launcher with the absolute-path candidates removed so the host's own Python can't be found."""
        dst = self.tmp / "copy"
        dst.mkdir(exist_ok=True)
        text = re.sub(r" /[\w/.-]*python3?\b", "", script.read_text())
        out = dst / script.name
        out.write_text(text)
        (dst / "discover.py").write_text("")
        (dst / "etk_run.py").write_text("")
        return out

    def run_launcher(self, script, *args, stdin=None):
        env = {"PATH": str(self.bin)}
        return subprocess.run(["/bin/sh", str(script), *args], input=stdin, env=env, capture_output=True, text=True, timeout=30)

    def test_etk_launcher_skips_old_python_and_uses_the_first_3_12(self):
        self.fake_python("python3", version_ok=False)
        self.fake_python("python3.12", version_ok=True)
        r = self.run_launcher(self.without_absolute_pythons(ROOT / "scripts" / "etk.sh"), "run", "latest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("FAKE python3.12", r.stdout)
        self.assertNotIn("FAKE python3 ", r.stdout)

    def test_etk_launcher_names_the_requirement_when_none_qualifies(self):
        self.fake_python("python3", version_ok=False)
        self.fake_python("python", version_ok=False)
        r = self.run_launcher(self.without_absolute_pythons(ROOT / "scripts" / "etk.sh"), "run", "latest")
        self.assertEqual(r.returncode, 127)
        self.assertIn("Python 3.12+ not found", r.stderr)

    def test_guard_wrapper_uses_a_3_12_python(self):
        self.fake_python("python3", version_ok=False)
        self.fake_python("python3.13", version_ok=True)
        r = self.run_launcher(self.without_absolute_pythons(ROOT / "hooks" / "run-guard.sh"),
                              stdin='{"agent_type":"engineering-team:developer"}')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("FAKE python3.13", r.stdout)

    def test_guard_wrapper_without_3_12_blocks_plugin_agents_and_says_why(self):
        self.fake_python("python3", version_ok=False)
        script = self.without_absolute_pythons(ROOT / "hooks" / "run-guard.sh")
        r = self.run_launcher(script, stdin='{"agent_type":"engineering-team:developer"}')
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs Python 3.12+ for its guard; install it or disable the plugin", r.stderr)

    def test_guard_wrapper_without_3_12_leaves_the_main_session_alone(self):
        self.fake_python("python3", version_ok=False)
        script = self.without_absolute_pythons(ROOT / "hooks" / "run-guard.sh")
        r = self.run_launcher(script, stdin='{"tool_name":"Bash","tool_input":{"command":"ls"}}')
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
