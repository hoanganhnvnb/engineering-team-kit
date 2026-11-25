"""Release bookkeeping in the run ledger (phase/authorize/act/decide, G7) and run-selection safety."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETK = ROOT / "scripts" / "etk_run.py"


def sh(args, cwd, stdin=None):
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=30)


def git(cwd, *args):
    return sh(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd)


class ReleaseLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        git(self.dir, "init", "-q", "-b", "main")
        git(self.dir, "commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def etk(self, *args):
        return sh([sys.executable, str(ETK), *args], self.dir)

    def init(self, *extra):
        r = self.etk("init", "Ship discount codes", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        run = Path(r.stdout.strip())
        return run, json.loads((run / "gates.json").read_text())

    def ledger(self, run):
        return json.loads((run / "gates.json").read_text())

    def write(self, run, ledger):
        (run / "gates.json").write_text(json.dumps(ledger))

    def check(self, run):
        return self.etk("check", str(run))

    def passing(self, ledger, g7=True):
        ledger["acceptance_criteria"] = [{"id": "AC-1", "text": "code applies 10%", "status": "met"}]
        for g in ledger["gates"]:
            ledger["gates"][g] = {"status": "PASS", "evidence": "checked carefully with evidence", "commands": []}
        for g in ("G3", "G4"):
            ledger["gates"][g]["commands"] = [{"cmd": "npm test", "exit_code": 0, "type": "test", "recorded_by": "exec"}]
        ledger["gates"]["G4"]["commands"].append({"cmd": "curl :3000", "exit_code": 0, "type": "runtime",
                                                  "recorded_by": "exec"})
        if not g7:
            ledger["gates"]["G7"] = {"status": "NOT_RUN", "evidence": "", "commands": []}
        return ledger

    def ship_run(self):
        """A ship run whose G1-G6 pass, G7 not yet run, outcome still IN_PROGRESS."""
        run, ledger = self.init("--kind", "ship")
        self.write(run, self.passing(ledger, g7=False))
        return run

    def complete(self, run, g7="PASS"):
        led = self.ledger(run)
        led["gates"]["G7"] = {"status": g7, "evidence": "pushed and merged, see actions", "commands": []}
        led["outcome"] = "COMPLETE"
        self.write(run, led)
        return self.check(run)

    # --- new fields -----------------------------------------------------------------------

    def test_init_writes_release_fields(self):
        run, led = self.init("--kind", "ship")
        self.assertEqual(led["kind"], "ship")
        self.assertEqual(led["phase"], "intake")
        self.assertEqual([h["phase"] for h in led["phase_history"]], ["intake"])
        for key in ("authorizations", "actions", "decisions"):
            self.assertEqual(led[key], [])
        self.assertIsNone(led["profile_hash"])
        self.assertIn("G7", led["gates"])
        self.assertEqual(self.check(run).returncode, 0)

    def test_old_ledger_without_new_fields_still_passes(self):
        run, led = self.init()
        led = self.passing(led)
        for key in ("phase", "phase_history", "authorizations", "actions", "decisions", "profile_hash"):
            led.pop(key)
        del led["gates"]["G7"]
        led["outcome"] = "COMPLETE"
        self.write(run, led)
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = self.etk("render", str(run)).stdout
        self.assertNotIn("G7", out)
        self.assertNotIn("Phase", out)
        self.assertNotIn("Authorizations", out)

    def test_ship_requires_g7(self):
        run = self.ship_run()
        led = self.ledger(run)
        del led["gates"]["G7"]
        led["outcome"] = "COMPLETE"
        self.write(run, led)
        self.assertIn("G7: missing", self.check(run).stdout)

    def test_phase_transitions(self):
        run, _ = self.init("--kind", "ship")
        for name in ("implement", "review", "test", "release"):
            r = self.etk("phase", name, str(run))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        led = self.ledger(run)
        self.assertEqual(led["phase"], "release")
        self.assertEqual([h["phase"] for h in led["phase_history"]],
                         ["intake", "implement", "review", "test", "release"])
        before = (run / "gates.json").read_text()
        self.assertEqual(self.etk("phase", "shipping", str(run)).returncode, 2)
        self.assertEqual((run / "gates.json").read_text(), before)
        self.assertIn("**Phase:** release", self.etk("render", str(run)).stdout)

    def test_authorize_validation(self):
        run, _ = self.init("--kind", "ship")
        before = (run / "gates.json").read_text()
        for args in (["--action", "merge", "--source", "profile"],
                     ["--action", "deploy", "--source", "profile", "--quote", "profile says deploy"],
                     ["--action", "push", "--source", "prompt", "--quote", "  "],
                     ["--action", "push", "--source", "answer"],
                     ["--action", "publish", "--source", "prompt", "--quote", "go ahead"],
                     ["--action", "push", "--source", "email", "--quote", "go ahead"]):
            r = self.etk("authorize", *args, str(run))
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("Traceback", r.stderr)
        self.assertEqual((run / "gates.json").read_text(), before)
        r = self.etk("authorize", "--action", "push", "--source", "profile", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.etk("authorize", "--action", "merge", "--source", "prompt", "--quote", "merge it when green",
                     "--target", "main", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        auths = self.ledger(run)["authorizations"]
        self.assertEqual([(a["action"], a["source"], a["target"], a["condition"]) for a in auths],
                         [("push", "profile", "", "pass"), ("merge", "prompt", "main", "pass")])
        self.assertTrue(all(a["granted_at"] for a in auths))

    def test_hand_written_profile_merge_authorization_is_rejected(self):
        run, led = self.init("--kind", "ship")
        led["authorizations"] = [{"action": "merge", "source": "profile", "quote": "", "target": ""}]
        self.write(run, led)
        self.assertIn("profile can only authorize", self.check(run).stdout)

    # --- actions --------------------------------------------------------------------------

    def test_action_without_authorization_fails_check(self):
        run = self.ship_run()
        r = self.etk("act", "--action", "push", "--target", "origin/feat", "--exit", "0", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.check(run).stdout
        self.assertIn("no authorization", out)
        led = self.ledger(run)
        led["actions"][0]["at"] = "2000-01-01T00:00:00"
        self.write(run, led)
        self.etk("authorize", "--action", "push", "--source", "prompt", "--quote", "push it to feat",
                 "--target", "ORIGIN/FEAT", str(run))
        r = self.check(run)
        # the authorization came after the push, so it still doesn't cover it
        self.assertIn("no authorization", r.stdout)

    def test_authorized_push_after_gates_completes(self):
        run = self.ship_run()
        self.etk("authorize", "--action", "push", "--source", "profile", str(run))
        r = self.etk("act", "--action", "push", "--target", "origin/feat", "--ref", "abc123", "--exit", "0", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.ledger(run)["actions"][0]["gates_ok"])
        r = self.complete(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = self.etk("render", str(run)).stdout
        self.assertIn("**Authorizations**", out)
        self.assertIn("| push | origin/feat | abc123 | 0 |", out)

    def test_push_before_gates_pass_fails_check(self):
        run, _ = self.init("--kind", "ship")
        self.etk("authorize", "--action", "push", "--source", "prompt", "--quote", "push when ready", str(run))
        r = self.etk("act", "--action", "push", "--exit", "0", str(run))
        self.assertIn("gates had not passed", r.stdout)
        self.assertFalse(self.ledger(run)["actions"][0]["gates_ok"])
        out = self.check(run).stdout
        self.assertIn("released before the gates passed", out)
        # an open medium finding also means the gates have not passed
        run2 = self.ship_run()
        led = self.ledger(run2)
        led["findings"] = [{"id": "R1-001", "severity": "medium", "location": "a.py:1", "evidence": "repro: f(0) raises",
                            "expected": "0", "actual": "error", "remediation": "guard", "status": "open"}]
        self.write(run2, led)
        self.etk("act", "--action", "commit", "--exit", "0", str(run2))
        self.assertFalse(self.ledger(run2)["actions"][0]["gates_ok"])

    def test_rollback_is_exempt_from_gates_but_needs_user_words(self):
        run, _ = self.init("--kind", "ship")
        self.etk("act", "--action", "rollback", "--target", "prod", "--exit", "0", str(run))
        led = self.ledger(run)
        led["authorizations"] = [{"action": "rollback", "source": "profile", "quote": "", "target": ""}]
        self.write(run, led)
        out = self.check(run).stdout
        self.assertNotIn("released before the gates passed", out)
        self.assertIn("profile can only authorize", out)
        self.etk("authorize", "--action", "rollback", "--source", "answer", "--quote", "yes roll back", str(run))
        led = self.ledger(run)
        led["authorizations"].pop(0)
        led["actions"][0]["at"] = led["authorizations"][0]["granted_at"]
        self.write(run, led)
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)

    def test_merge_needs_users_words_not_profile(self):
        run = self.ship_run()
        led = self.ledger(run)
        led["authorizations"] = [{"action": "merge", "source": "profile", "quote": "", "target": "",
                                  "granted_at": "2000-01-01T00:00:00"}]
        self.write(run, led)
        self.etk("act", "--action", "merge", "--exit", "0", str(run))
        out = self.check(run).stdout
        self.assertIn("profile can only authorize", out)
        self.assertIn("no authorization", out)

    def test_production_deploy_needs_the_word(self):
        run = self.ship_run()
        self.etk("authorize", "--action", "deploy", "--source", "prompt", "--quote", "go ahead and deploy", str(run))
        self.etk("act", "--action", "deploy", "--target", "web-eu", "--exit", "0", "--production", str(run))
        self.assertIn("production deploy", self.check(run).stdout)
        for quote in ("deploy it to PROD please", "ship to web-eu", "push it live"):
            led = self.ledger(run)
            led["authorizations"][0]["quote"] = quote
            self.write(run, led)
            r = self.check(run)
            self.assertEqual(r.returncode, 0, (quote, r.stdout))
        led["authorizations"][0]["quote"] = "deploy to the productive box"
        self.write(run, led)
        self.assertIn("production deploy", self.check(run).stdout)

    def test_failed_action_blocks_complete(self):
        run = self.ship_run()
        self.etk("authorize", "--action", "push", "--source", "profile", str(run))
        self.etk("act", "--action", "push", "--exit", "1", str(run))
        out = self.complete(run, g7="FAIL").stdout
        self.assertIn("COMPLETE but action #1 (push) exited 1", out)
        out = self.complete(run, g7="PASS").stdout
        self.assertIn("G7: PASS but action #1 (push) exited 1", out)

    def test_pending_l4_decision_blocks_complete(self):
        run = self.ship_run()
        self.etk("authorize", "--action", "push", "--source", "profile", str(run))
        self.etk("act", "--action", "push", "--exit", "0", str(run))
        r = self.etk("decide", "--id", "D1", "--level", "L4", "--question", "Drop the legacy table?",
                     "--options", "yes|no", "--recommended", "no", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("still pending", self.complete(run).stdout)
        r = self.etk("decide", "--id", "D1", "--level", "L4", "--question", "Drop the legacy table?",
                     "--status", "approved", "--answer-quote", "no, keep it", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        d = self.ledger(run)["decisions"]
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["status"], d[0]["options"], d[0]["recommended"], d[0]["answer_quote"]),
                         ("approved", ["yes", "no"], "no", "no, keep it"))
        led = self.ledger(run)
        led["outcome"] = "COMPLETE"
        self.write(run, led)
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)
        self.assertEqual(self.etk("decide", "--id", "D2", "--level", "L9", "--question", "x", str(run)).returncode, 2)

    def test_g7_rules_for_ship(self):
        run = self.ship_run()
        self.assertIn("G7: PASS without any recorded release action", self.complete(run).stdout)
        self.assertIn("COMPLETE but G7 is NOT_RUN", self.complete(run, g7="NOT_RUN").stdout)
        led = self.ledger(run)
        led["gates"]["G7"] = {"status": "NOT_APPLICABLE", "evidence": "n/a"}
        self.write(run, led)
        self.assertIn("G7: status NOT_APPLICABLE needs evidence", self.check(run).stdout)
        led["gates"]["G7"]["evidence"] = "user said to leave the change uncommitted"
        self.write(run, led)
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)
        self.etk("authorize", "--action", "commit", "--source", "profile", str(run))
        self.etk("act", "--action", "commit", "--exit", "0", str(run))
        self.assertIn("G7: NOT_APPLICABLE but 1 release action", self.check(run).stdout)

    def test_malformed_release_fields_report_instead_of_crash(self):
        run, led = self.init("--kind", "ship")
        for edit in ({"actions": 5}, {"actions": ["x", {"action": "push", "exit": "0"}]},
                     {"authorizations": [{"action": ["push"]}]}, {"decisions": [{"id": 3}, {"id": "D", "level": "L4"}]},
                     {"phase": "nope", "phase_history": [{"phase": 1}]}):
            self.write(run, {**led, **edit})
            r = self.check(run)
            self.assertEqual(r.returncode, 1, edit)
            self.assertNotIn("Traceback", r.stdout + r.stderr)
            r = self.etk("render", str(run))
            self.assertEqual(r.returncode, 0, r.stderr)
        self.write(run, {**led, "actions": 5})
        before = (run / "gates.json").read_text()
        self.assertEqual(self.etk("act", "--action", "push", "--exit", "0", str(run)).returncode, 2)
        self.assertEqual((run / "gates.json").read_text(), before)

    # --- which run gets picked ------------------------------------------------------------

    def test_committed_future_dated_ledger_is_not_selected(self):
        run, _ = self.init()
        forged = self.dir / ".etk" / "runs" / "99991231-235959-forged"
        forged.mkdir()
        (forged / "gates.json").write_text(json.dumps({"outcome": "IN_PROGRESS", "gates": {}}))
        # untracked but future-dated: skipped
        self.assertEqual(self.etk("latest").stdout.strip(), str(run))
        # committed: no-path resolution refuses outright, init too
        git(self.dir, "add", "-f", str(forged / "gates.json"))
        git(self.dir, "commit", "-q", "-m", "forged")
        for args in (("latest",), ("check",), ("render",), ("init", "again")):
            r = self.etk(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("git tracks", r.stderr)
            self.assertNotIn("forged", r.stdout)
        self.assertEqual(self.etk("check", str(forged)).returncode, 2)
        self.assertEqual(self.etk("check", str(run)).returncode, 0)
        self.assertEqual(json.loads(self.etk("stats", "--json").stdout)["runs"], 1)

    def test_latest_skips_symlinked_runs(self):
        run, _ = self.init()
        outside = self.dir / "elsewhere"
        outside.mkdir()
        (outside / "gates.json").write_text("{}")
        os.symlink(outside, self.dir / ".etk" / "runs" / "20990101-000000-link")
        # future check would also skip a 2099 name; use a plausible one
        os.symlink(outside, self.dir / ".etk" / "runs" / (run.name[:15] + "-zzz"))
        self.assertEqual(self.etk("latest").stdout.strip(), str(run))
        self.assertEqual(self.etk("check", str(self.dir / ".etk" / "runs" / (run.name[:15] + "-zzz"))).returncode, 2)

    def test_symlinked_runs_dir_is_refused(self):
        real = self.dir / "real-runs"
        real.mkdir()
        (self.dir / ".etk").mkdir()
        os.symlink(real, self.dir / ".etk" / "runs")
        r = self.etk("init", "x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("symlink", r.stderr)
        self.assertEqual(list(real.iterdir()), [])
        self.assertEqual(self.etk("check").returncode, 2)

    def test_explicit_path_outside_runs_dir_is_refused(self):
        run, led = self.init()
        outside = self.dir / "elsewhere"
        outside.mkdir()
        (outside / "gates.json").write_text(json.dumps(led))
        for target in (outside, outside / "gates.json", self.dir / ".etk" / "runs", run / ".." / ".." / ".."):
            r = self.etk("check", str(target))
            self.assertEqual(r.returncode, 2, target)
            self.assertIn("not inside", r.stderr)
        self.assertEqual(self.etk("render", str(outside)).returncode, 2)
        self.assertEqual(self.etk("check", str(run / "gates.json")).returncode, 0)

    def test_exec_run_writes_into_the_given_run(self):
        first, _ = self.init()
        second, _ = self.init()
        self.assertNotEqual(first, second)
        r = self.etk("exec", "G3", "--type", "test", "--run", str(first), "--", "true")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.ledger(first)["gates"]["G3"]["commands"]), 1)
        self.assertEqual(self.ledger(second)["gates"]["G3"]["commands"], [])
        outside = self.dir / "elsewhere"
        outside.mkdir()
        self.assertEqual(self.etk("exec", "G3", "--run", str(outside), "--", "true").returncode, 2)


if __name__ == "__main__":
    unittest.main()
