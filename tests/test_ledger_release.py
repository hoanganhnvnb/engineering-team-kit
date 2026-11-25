"""Run-selection safety: ledger commands act only on runs this session could have created."""
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
