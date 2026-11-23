"""Unit tests for the plugin's scripts. Run: python3 -m unittest discover -s tests -v"""
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
            self.assertTrue(self.blocked("cp -t src x.js", agent=rv))

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


if __name__ == "__main__":
    unittest.main()
