"""Release bookkeeping in the run ledger (phase/authorize/act/decide, G7) and run-selection safety."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ETK = ROOT / "scripts" / "etk_run.py"
PROFILE = ROOT / "scripts" / "etk_profile.py"


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
        datatmp = tempfile.TemporaryDirectory()
        self.addCleanup(datatmp.cleanup)
        self.data = Path(datatmp.name) / "plugins" / "data" / "etk"
        self.data.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def etk(self, *args):
        return sh([sys.executable, str(ETK), *args], self.dir)

    def profile(self, *args, cwd=None):
        r = sh([sys.executable, str(PROFILE), *args, "--data", str(self.data)], cwd or self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def auth_profile(self, run, action="push"):
        """Set release.<action>: auto in the workflow profile and authorize `action` from it."""
        self.profile("set", f"release.{action}", "auto")
        self.profile("confirm")
        r = self.etk("authorize", "--action", action, "--source", "profile", "--data", str(self.data), str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

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
        self.auth_profile(run, "push")
        r = self.etk("authorize", "--action", "merge", "--source", "prompt", "--quote", "merge it when green",
                     "--target", "main", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        auths = self.ledger(run)["authorizations"]
        self.assertEqual([(a["action"], a["source"], a["target"], a["condition"]) for a in auths],
                         [("push", "profile", "", "pass"), ("merge", "prompt", "main", "pass")])
        self.assertTrue(all(a["granted_at"] for a in auths))

    def test_profile_authorization_is_checked_against_the_profile(self):
        run, _ = self.init("--kind", "ship")
        before = (run / "gates.json").read_text()
        data = ("--data", str(self.data))
        # no --data, no profile yet, a profile that says confirm, a PR without integrate pr
        r = self.etk("authorize", "--action", "push", "--source", "profile", str(run))
        self.assertEqual(r.returncode, 2)
        self.assertIn("--data", r.stderr)
        self.assertEqual(self.etk("authorize", "--action", "push", "--source", "profile", *data, str(run)).returncode, 2)
        self.profile("set", "release.push", "confirm")
        r = self.etk("authorize", "--action", "push", "--source", "profile", *data, str(run))
        self.assertEqual(r.returncode, 2)
        self.assertIn("not \"auto\"", r.stderr)
        self.profile("set", "release.push", "auto")
        self.assertEqual(self.etk("authorize", "--action", "pr", "--source", "profile", *data, str(run)).returncode, 2)
        self.assertEqual((run / "gates.json").read_text(), before)
        self.profile("set", "release.integrate", "pr")
        self.profile("confirm")
        for action in ("push", "pr"):
            r = self.etk("authorize", "--action", action, "--source", "profile", *data, str(run))
            self.assertEqual(r.returncode, 0, r.stderr)
        path = Path(self.profile("path").strip())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        led = self.ledger(run)
        self.assertEqual(led["profile_hash"], digest)
        self.assertEqual([a["profile_hash"] for a in led["authorizations"]], [digest, digest])
        # a hand-written profile authorization (no hash) doesn't count
        led["authorizations"].append({"action": "commit", "source": "profile", "quote": "", "target": ""})
        self.write(run, led)
        self.assertIn("source profile without the profile's hash", self.check(run).stdout)

    def test_profile_authorizes_only_after_confirm(self):
        run, _ = self.init("--kind", "ship")
        before = (run / "gates.json").read_text()
        data = ("--data", str(self.data))
        self.profile("set", "release.push", "auto")
        r = self.etk("authorize", "--action", "push", "--source", "profile", *data, str(run))
        self.assertEqual(r.returncode, 2)
        self.assertIn("never confirmed", r.stderr)
        self.profile("confirm")
        self.profile("set", "release.commit", "auto")  # a change after confirm needs a new confirm
        for action in ("push", "commit"):
            r = self.etk("authorize", "--action", action, "--source", "profile", *data, str(run))
            self.assertEqual(r.returncode, 2)
            self.assertIn("changed after it was last confirmed", r.stderr)
        self.assertEqual((run / "gates.json").read_text(), before)
        self.profile("confirm")
        self.profile("remember", "QA resets nightly")  # a note grants nothing: no new confirm needed
        for action in ("push", "commit"):
            r = self.etk("authorize", "--action", action, "--source", "profile", *data, str(run))
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_profile_from_another_checkout_or_push_url_does_not_authorize(self):
        git(self.dir, "remote", "add", "origin", "https://github.com/victim/prod.git")
        run, _ = self.init("--kind", "ship")
        self.profile("set", "release.push", "auto")
        self.profile("confirm")
        data = ("--data", str(self.data))
        # repository code points the push somewhere else: the stored auto no longer applies
        git(self.dir, "config", "remote.origin.pushurl", "https://evil.example/x.git")
        r = self.etk("authorize", "--action", "push", "--source", "profile", *data, str(run))
        self.assertEqual(r.returncode, 2)
        self.assertIn("different checkout/remote", r.stderr)
        self.assertIn("different checkout/remote", self.profile("show", "--brief"))
        self.assertIn("release.push", self.profile("missing"))
        git(self.dir, "config", "--unset", "remote.origin.pushurl")
        self.assertEqual(self.etk("authorize", "--action", "push", "--source", "profile", *data, str(run)).returncode, 0)
        # another checkout claiming the same origin finds the profile but can't use its auto values
        othertmp = tempfile.TemporaryDirectory()
        self.addCleanup(othertmp.cleanup)
        other = Path(othertmp.name)
        git(other, "init", "-q", "-b", "main")
        git(other, "commit", "-q", "--allow-empty", "-m", "init")
        git(other, "remote", "add", "origin", "git@github.com:victim/prod.git")
        self.assertEqual(self.profile("path", cwd=other), self.profile("path"))
        r = sh([sys.executable, str(ETK), "init", "x", "--kind", "ship"], other)
        orun = Path(r.stdout.strip())
        r = sh([sys.executable, str(ETK), "authorize", "--action", "push", "--source", "profile", *data, str(orun)],
               other)
        self.assertEqual(r.returncode, 2)
        self.assertIn("different checkout/remote", r.stderr)

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
        self.auth_profile(run, "push")
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
        before = (run / "gates.json").read_text()
        r = self.etk("act", "--action", "push", "--exit", "0", str(run))
        self.assertEqual(r.returncode, 2)
        self.assertIn("run ready", r.stderr)
        self.assertEqual((run / "gates.json").read_text(), before)
        # a push that already happened is still recorded, as released before the gates passed
        r = self.etk("act", "--action", "push", "--exit", "0", "--force-record", str(run))
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
        self.assertEqual(self.etk("act", "--action", "commit", "--exit", "0", str(run2)).returncode, 2)
        self.etk("act", "--action", "commit", "--exit", "0", "--force-record", str(run2))
        self.assertFalse(self.ledger(run2)["actions"][0]["gates_ok"])

    def test_ready_needs_settled_gates_not_just_a_consistent_ledger(self):
        run = self.ship_run()
        led = self.ledger(run)
        led["gates"]["G3"]["status"] = "FAIL"
        led["gates"]["G4"]["status"] = "FAIL"
        self.write(run, led)
        self.assertEqual(self.check(run).returncode, 0)  # an in-progress run with failing gates is consistent
        r = self.etk("ready", str(run))
        self.assertEqual(r.returncode, 1)
        self.assertIn("G3 is FAIL", r.stdout)
        self.assertIn("G4 is FAIL", r.stdout)
        self.assertEqual(self.etk("act", "--action", "push", "--exit", "0", str(run)).returncode, 2)
        led = self.passing(led, g7=False)
        led["gates"]["G5"] = {"status": "NOT_APPLICABLE", "evidence": "no UI in this change at all"}
        led["findings"] = [{"id": "R1", "severity": "high", "location": "a.py:1", "evidence": "repro: f(0) raises",
                            "expected": "0", "actual": "error", "remediation": "guard", "status": "fixed"}]
        self.write(run, led)
        r = self.etk("ready", str(run))
        self.assertEqual(r.returncode, 1)
        self.assertIn("not independently verified", r.stdout)
        led["findings"][0]["status"] = "verified"
        self.write(run, led)
        r = self.etk("ready", str(run))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.etk("act", "--action", "commit", "--exit", "0", str(run)).returncode, 0)
        self.assertTrue(self.ledger(run)["actions"][0]["gates_ok"])

    def test_review_and_test_runs_cannot_release(self):
        for kind, gates in (("review", ("G2", "G6")), ("test", ("G3", "G4"))):
            run, led = self.init("--kind", kind)
            led = self.passing(led, g7=False)
            self.write(run, led)
            r = self.etk("ready", str(run))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(f"a {kind} run can't release", r.stdout)
            self.etk("authorize", "--action", "push", "--source", "prompt", "--quote", "push it", str(run))
            before = (run / "gates.json").read_text()
            for action in ("push", "pr", "merge", "tag", "deploy"):
                r = self.etk("act", "--action", action, "--exit", "0", "--data", str(self.data), str(run))
                self.assertEqual(r.returncode, 2, (kind, action))
                self.assertIn("can't release", r.stderr)
            self.assertEqual((run / "gates.json").read_text(), before)
            r = self.etk("act", "--action", "push", "--exit", "0", "--force-record", str(run))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"action #1 (push): a {kind} run can't release", self.check(run).stdout)
        run, led = self.init("--kind", "fix")
        self.write(run, self.passing(led, g7=False))
        self.assertEqual(self.etk("ready", str(run)).returncode, 0)

    def test_rollback_is_exempt_from_gates_but_needs_user_words(self):
        run, _ = self.init("--kind", "ship")
        self.etk("act", "--action", "rollback", "--target", "prod", "--exit", "0", "--data", str(self.data), str(run))
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
        self.etk("authorize", "--action", "deploy", "--source", "prompt", "--quote", "go ahead and deploy",
                 "--target", "web-eu", str(run))
        self.etk("act", "--action", "deploy", "--target", "web-eu", "--exit", "0", "--production",
                 "--data", str(self.data), str(run))
        self.assertIn("production deploy", self.check(run).stdout)
        for quote in ("deploy it to PROD please", "ship to web-eu", "push it live", "không test nữa, deploy prod",
                      "review không lỗi thì deploy prod luôn", "no errors -> deploy prod",
                      "tests pass and no regressions then ship to production"):
            led = self.ledger(run)
            led["authorizations"][0]["quote"] = quote
            self.write(run, led)
            r = self.check(run)
            self.assertEqual(r.returncode, 0, (quote, r.stdout))
        for quote in ("deploy to the productive box", "deploy to web-eu-staging", "deploy to nonprod_live",
                      "deploy staging, don't touch prod", "never deploy live", "không deploy production",
                      "don't deploy prod", "không deploy prod", "deploy staging, not production", "never touch prod"):
            led["authorizations"][0]["quote"] = quote
            self.write(run, led)
            self.assertIn("production deploy", self.check(run).stdout, quote)

    def test_production_deploy_needs_a_target_specific_authorization(self):
        run = self.ship_run()
        self.etk("authorize", "--action", "deploy", "--source", "prompt", "--quote", "deploy it to production", str(run))
        self.etk("act", "--action", "deploy", "--target", "web", "--exit", "0", "--production",
                 "--data", str(self.data), str(run))
        self.assertIn("exactly this target", self.check(run).stdout)
        led = self.ledger(run)
        led["authorizations"][0]["target"] = "web-staging"
        self.write(run, led)
        self.assertIn("no authorization", self.check(run).stdout)
        led["authorizations"][0]["target"] = "WEB"
        self.write(run, led)
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)

    def test_act_takes_production_from_the_profile(self):
        run = self.ship_run()
        self.profile("set", "deploy.targets", json.dumps([
            {"name": "web-eu", "kind": "manual", "production": True},
            {"name": "staging", "kind": "manual", "production": False}]))
        data = ("--data", str(self.data))
        self.etk("authorize", "--action", "deploy", "--source", "prompt", "--quote", "deploy staging and web-eu",
                 "--target", "web-eu", str(run))
        self.etk("authorize", "--action", "deploy", "--source", "prompt", "--quote", "deploy staging and web-eu",
                 "--target", "staging", str(run))
        for target, flag in (("web-eu", ()), ("staging", ()), ("staging", ("--production",))):
            r = self.etk("act", "--action", "deploy", "--target", target, "--exit", "0", *flag, *data, str(run))
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([a["production"] for a in self.ledger(run)["actions"]], [True, False, True])
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)

    def test_deploy_and_rollback_need_data(self):
        run = self.ship_run()
        before = (run / "gates.json").read_text()
        for action in ("deploy", "rollback"):
            r = self.etk("act", "--action", action, "--target", "web-eu", "--exit", "0", str(run))
            self.assertEqual(r.returncode, 2)
            self.assertIn("needs --data", r.stderr)
        self.assertEqual((run / "gates.json").read_text(), before)

    def test_production_rollback_needs_the_target_and_the_word(self):
        run = self.ship_run()
        self.profile("set", "deploy.targets", json.dumps([{"name": "web-eu", "kind": "manual", "production": True}]))
        self.etk("authorize", "--action", "rollback", "--source", "answer", "--quote", "yes roll it back", str(run))
        r = self.etk("act", "--action", "rollback", "--target", "web-eu", "--exit", "0", "--data", str(self.data),
                     str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.ledger(run)["actions"][0]["production"])
        self.assertIn("production rollback needs an authorization for exactly this target", self.check(run).stdout)
        led = self.ledger(run)
        led["authorizations"][0]["target"] = "web-eu"
        self.write(run, led)
        self.assertIn("production rollback, but no authorization quote", self.check(run).stdout)
        led["authorizations"][0]["quote"] = "yes roll back prod"
        self.write(run, led)
        self.assertEqual(self.check(run).returncode, 0, self.check(run).stdout)

    def test_failed_action_blocks_complete(self):
        run = self.ship_run()
        self.auth_profile(run, "push")
        self.etk("act", "--action", "push", "--exit", "1", str(run))
        out = self.complete(run, g7="FAIL").stdout
        self.assertIn("COMPLETE but action #1 (push) exited 1", out)
        out = self.complete(run, g7="PASS").stdout
        self.assertIn("G7: PASS but action #1 (push) exited 1", out)

    def test_successful_retry_settles_a_failed_action(self):
        run = self.ship_run()
        self.auth_profile(run, "push")
        self.etk("act", "--action", "push", "--target", "origin", "--exit", "1", str(run))
        self.etk("act", "--action", "push", "--target", "other", "--exit", "0", str(run))
        out = self.complete(run).stdout
        self.assertIn("action #1 (push origin) exited 1", out)  # a different target doesn't settle it
        self.etk("act", "--action", "push", "--target", "origin", "--exit", "0", str(run))
        r = self.complete(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.etk("act", "--action", "push", "--target", "origin", "--exit", "1", str(run))
        self.assertIn("action #4 (push origin) exited 1", self.complete(run).stdout)  # a later failure counts

    def test_pending_l4_decision_blocks_complete(self):
        run = self.ship_run()
        self.auth_profile(run, "push")
        self.etk("act", "--action", "push", "--exit", "0", str(run))
        r = self.etk("decide", "--id", "D1", "--level", "L4", "--question", "Drop the legacy table?",
                     "--options", "yes|no", "--recommended", "no", str(run))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("still pending", self.complete(run).stdout)
        r = self.etk("decide", "--id", "D1", "--status", "approved", "--answer-quote", "no, keep it", str(run))
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
        before = (run / "gates.json").read_text()
        for args in (("--id", "D2", "--status", "approved"), ("--id", "D2", "--level", "L3"),
                     ("--id", "D2", "--question", "x"), ("--id", "D1", "--question", " ")):
            r = self.etk("decide", *args, str(run))
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("Traceback", r.stderr)
        self.assertEqual((run / "gates.json").read_text(), before)
        self.assertEqual((d[0]["level"], d[0]["question"]), ("L4", "Drop the legacy table?"))

    def test_l4_decision_needs_the_users_answer(self):
        run, _ = self.init("--kind", "ship")
        q = ("--id", "D1", "--level", "L4", "--question", "Drop the legacy table?")
        self.etk("decide", *q, "--status", "autonomous", str(run))
        self.assertIn("L4 can't be autonomous", self.check(run).stdout)
        for quote in ((), ("--answer-quote", " y ")):
            self.etk("decide", *q, "--status", "approved", *quote, str(run))
            self.assertIn("approved L4 needs the user's verbatim words", self.check(run).stdout)
        self.etk("decide", *q, "--status", "approved", "--answer-quote", "yes, drop it", str(run))
        r = self.check(run)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.etk("decide", "--id", "D2", "--level", "L3", "--question", "Which cache?", "--status", "autonomous",
                 str(run))
        self.assertEqual(self.check(run).returncode, 0)

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
        self.auth_profile(run, "commit")
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

    def test_exec_command_cannot_rewrite_the_ledger(self):
        run, _ = self.init("--kind", "ship")
        gates = run / "gates.json"
        forge = (
            "import json, pathlib; p = pathlib.Path(%r); led = json.loads(p.read_text()); "
            "led['authorizations'].append({'action': 'push', 'source': 'prompt', 'quote': 'push it all', 'target': ''}); "
            "led['actions'].append({'action': 'push', 'exit': 0}); led['outcome'] = 'COMPLETE'; led['extra'] = 1; "
            "led['gates']['G1']['status'] = 'PASS'; led['gates']['G3']['status'] = 'PASS'; "
            "led['gates']['G3']['commands'].append({'cmd': 'pytest', 'exit_code': 0, 'type': 'test', "
            "'recorded_by': 'exec'}); "
            "led['gates']['G4']['commands'].append({'cmd': 'forged', 'exit_code': 0, 'type': 'test', "
            "'recorded_by': 'exec'}); "
            "p.write_text(json.dumps(led)); raise SystemExit(3)" % str(gates))
        before = self.ledger(run)
        r = self.etk("exec", "G3", "--type", "test", "--run", str(run), "--", sys.executable, "-c", forge)
        self.assertEqual(r.returncode, 3)
        self.assertIn("discarded", r.stderr)
        led = self.ledger(run)
        for key in ("authorizations", "actions", "outcome", "acceptance_criteria", "findings"):
            self.assertEqual(led[key], before[key], key)
        self.assertNotIn("extra", led)
        self.assertEqual((led["gates"]["G1"]["status"], led["gates"]["G3"]["status"]), ("NOT_RUN", "NOT_RUN"))
        # appended command records survive (nested exec); the real one comes last, another gate's is marked
        self.assertEqual([(c["cmd"], c["exit_code"]) for c in led["gates"]["G3"]["commands"]],
                         [("pytest", 0), (shlex.join([sys.executable, "-c", forge]), 3)])
        self.assertEqual(led["gates"]["G4"]["commands"][0]["recorded_by"], "nested-exec")
        # a ledger the command corrupted or replaced with a symlink is restored, not followed
        victim = self.dir / "victim.txt"
        victim.write_text("keep me")
        clobber = "import os; p = %r; os.remove(p); os.symlink(%r, p)" % (str(gates), str(victim))
        r = self.etk("exec", "G3", "--type", "test", "--run", str(run), "--", sys.executable, "-c", clobber)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(victim.read_text(), "keep me")
        self.assertFalse(gates.is_symlink())
        self.assertEqual(len(self.ledger(run)["gates"]["G3"]["commands"]), 3)

    def test_future_date_limits_match(self):
        mods = {}
        for name in ("etk_run", "discover"):
            spec = importlib.util.spec_from_file_location(f"_t_{name}", ROOT / "scripts" / f"{name}.py")
            mods[name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mods[name])
        self.assertEqual(mods["etk_run"].FUTURE_SLACK, mods["discover"].FUTURE_SLACK)

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
