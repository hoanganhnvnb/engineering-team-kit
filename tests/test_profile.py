"""Workflow profile (scripts/etk_profile.py), its discover block, and the guard rules around it."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / "scripts" / "etk_profile.py"
DISCOVER = ROOT / "scripts" / "discover.py"
GUARD = ROOT / "hooks" / "guard.py"
sys.path.insert(0, str(ROOT / "scripts"))
import etk_profile  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(os.path.realpath(tmp.name))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.data = self.tmp / "plugins" / "data" / "etk-test"
        self.data.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
                        GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                        PATH=self.safe_path())
        self.env.pop("CLAUDE_PLUGIN_DATA", None)

    def safe_path(self) -> str:
        """PATH with git/svn/sh but without gh/glab, so detection never waits on a CLI's auth check."""
        return self.bin_dir("bin", ("git", "svn", "svnadmin", "sh", "dirname"))

    def bin_dir(self, name: str, tools) -> str:
        d = self.tmp / name
        d.mkdir(exist_ok=True)
        for tool in tools:
            found = shutil.which(tool)
            if found and not (d / tool).exists():
                (d / tool).symlink_to(found)
        if not (d / "python3").exists():
            (d / "python3").symlink_to(sys.executable)
        return str(d)

    def git(self, cwd: Path, *args: str) -> str:
        r = subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def repo(self, name: str = "repo", remote: str | None = None, subjects=("init",)) -> Path:
        d = self.tmp / name
        d.mkdir(parents=True)
        self.git(d, "init", "-q", "-b", "main")
        if remote:
            self.git(d, "remote", "add", "origin", remote)
        for s in subjects:
            self.git(d, "commit", "-q", "--allow-empty", "-m", s)
        return d

    def prof(self, cwd: Path, *args: str, data: str | None = "default"):
        cmd = [sys.executable, str(PROFILE), *args]
        if data is not None:
            cmd += ["--data", str(self.data) if data == "default" else data]
        return subprocess.run(cmd, cwd=cwd, env=self.env, capture_output=True, text=True, timeout=60)

    def ok(self, cwd: Path, *args: str) -> str:
        r = self.prof(cwd, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def detect(self, cwd: Path) -> dict:
        return json.loads(self.ok(cwd, "detect"))


class IdentityTests(Base):
    def test_ssh_and_https_clones_share_a_key(self):
        a = self.repo("a", "git@github.com:Acme/Shop.git")
        b = self.repo("b", "https://user:secret@GitHub.com/Acme/Shop/")
        c = self.repo("c", "ssh://git@github.com:22/Acme/Shop.git")
        keys = {self.detect(d)["key"] for d in (a, b, c)}
        self.assertEqual(len(keys), 1)
        self.assertEqual(self.ok(a, "path"), self.ok(b, "path"))
        self.assertNotEqual(self.detect(self.repo("d", "git@github.com:Acme/Other.git"))["key"], keys.pop())

    def test_normalize_and_redact(self):
        for url in ("git@github.com:o/r.git", "ssh://git@github.com:2222/o/r", "https://u:p@github.com/o/r.git/",
                    "https://token@GITHUB.COM/o/r"):
            self.assertEqual(etk_profile.normalize_remote(url), "github.com/o/r", url)
        self.assertEqual(etk_profile.redact_remote("https://u:p@github.com/o/r.git"), "https://github.com/o/r.git")
        self.assertEqual(etk_profile.redact_remote("https://ghp_tok@github.com/o/r"), "https://github.com/o/r")
        self.assertEqual(etk_profile.redact_remote("git@github.com:o/r.git"), "git@github.com:o/r.git")
        self.assertEqual(etk_profile.redact_remote("ssh://git:pw@h.com/o/r"), "ssh://h.com/o/r")

    def test_query_and_fragment_never_kept(self):
        url = "https://github.com/o/r.git?access_token=SECRET#frag"
        self.assertEqual(etk_profile.redact_remote(url), "https://github.com/o/r.git")
        self.assertEqual(etk_profile.redact_remote("git@github.com:o/r.git?x=SECRET"), "git@github.com:o/r.git")
        self.assertEqual(etk_profile.normalize_remote(url), "github.com/o/r")
        d = self.repo("q", url)
        plain = self.repo("plain", "https://github.com/o/r.git")
        self.assertEqual(self.detect(d)["key"], self.detect(plain)["key"])
        self.ok(d, "set", "commit.style", "project")
        for args in (("detect",), ("show",), ("show", "--brief")):
            self.assertNotIn("SECRET", self.ok(d, *args))

    def test_invisible_and_bidi_characters_are_stripped(self):
        evil = "a\u202eb\u200bc\u2066d\x85e\x9bf\u200fg"
        self.assertEqual(etk_profile.clip(evil), "a b c d e f g")
        # a remote that isn't plainly spelled is not shown at all (it used to be shown with the character blanked)
        self.assertEqual(etk_profile.redact_remote("https://h.com/o/r\u202e.git"), etk_profile.NOT_SHOWN)

    def test_hosts(self):
        cases = {"git@gitlab.com:o/r.git": "gitlab", "https://gitlab.acme.io/o/r": "gitlab",
                 "git@bitbucket.org:o/r.git": "bitbucket", "https://dev.azure.com/o/p/_git/r": "azure",
                 "https://acme.visualstudio.com/p/_git/r": "azure", "https://git.acme.io/o/r": "other",
                 "git@github.com:o/r.git": "github"}
        for url, host in cases.items():
            self.assertEqual(etk_profile.host_type(url), host, url)
        self.assertEqual(self.detect(self.repo("gl", "git@gitlab.com:o/r.git"))["host"], "gitlab")
        self.assertEqual(self.detect(self.repo("bb", "https://bitbucket.org/o/r.git"))["host"], "bitbucket")

    def test_credentials_never_printed(self):
        d = self.repo(remote="https://alice:s3cr3t@github.com/o/r.git")
        for args in (("detect",), ("show",)):
            self.assertNotIn("s3cr3t", self.ok(d, *args))
        self.ok(d, "set", "commit.style", "conventional")
        stored = json.loads(Path(self.ok(d, "path").strip()).read_text())
        self.assertEqual(self.detect(d)["remote"], "https://github.com/o/r.git")
        self.assertEqual(stored["project"]["origin_hash"], etk_profile.url_hash("https://alice:s3cr3t@github.com/o/r.git"))
        self.assertNotIn("remote", stored["project"])  # no URL text in the profile, only hashes
        self.assertNotIn("s3cr3t", json.dumps(stored))

    def test_no_remote_keys_on_root(self):
        d = self.repo()
        (d / "sub").mkdir()
        facts = self.detect(d / "sub")
        self.assertEqual((facts["vcs"], facts["remote"], facts["host"]), ("git", None, "none"))
        self.assertEqual(facts["root"], str(d))
        self.assertEqual(self.ok(d / "sub", "path"), self.ok(d, "path"))
        self.assertNotEqual(self.ok(d, "path"), self.ok(self.repo("other"), "path"))

    def test_non_vcs_dir(self):
        d = self.tmp / "plain"
        d.mkdir()
        facts = self.detect(d)
        self.assertEqual((facts["vcs"], facts["host"], facts["default_branch"]), ("none", "none", None))
        self.assertEqual(self.ok(d, "missing"), "")

    def test_svn_walk_up_fallback(self):
        wc = self.tmp / "wc"
        (wc / ".svn").mkdir(parents=True)
        (wc / "trunk" / "src").mkdir(parents=True)
        self.env["PATH"] = self.bin_dir("nosvn", ("git",))  # no `svn` binary: walk up for .svn
        facts = self.detect(wc / "trunk" / "src")
        self.assertEqual((facts["vcs"], facts["root"], facts["host"]), ("svn", str(wc), "none"))
        self.assertEqual(sorted(self.ok(wc / "trunk", "missing").split()), ["deploy", "release.commit", "vcs.type"])

    @unittest.skipUnless(shutil.which("svn") and shutil.which("svnadmin"), "svn not installed")
    def test_real_svn_checkout(self):
        repo = self.tmp / "svnrepo"
        subprocess.run(["svnadmin", "create", str(repo)], check=True, env=self.env)
        wc = self.tmp / "checkout"
        subprocess.run(["svn", "checkout", "-q", f"file://{repo}", str(wc)], check=True, env=self.env)
        (wc / "a").mkdir()
        facts = self.detect(wc / "a")
        self.assertEqual((facts["vcs"], facts["root"]), ("svn", str(wc)))
        self.assertEqual(sorted(self.ok(wc, "missing").split()), ["deploy", "release.commit", "vcs.type"])


class DetectTests(Base):
    def test_conventional_english(self):
        d = self.repo(subjects=["feat(api): add x", "fix(api): y", "chore: z", "feat(ui)!: w", "docs: v"])
        facts = self.detect(d)
        self.assertEqual((facts["commit_style"], facts["commit_language"]), ("conventional", "en"))
        self.assertEqual(facts["scopes"][0], "api")
        self.assertEqual(facts["default_branch"], "main")
        self.assertFalse(facts["has_develop"])

    def test_project_style_vietnamese(self):
        d = self.repo(subjects=["Sửa lỗi đăng nhập", "Thêm trang thanh toán", "Cập nhật README", "fix: typo"])
        facts = self.detect(d)
        self.assertEqual((facts["commit_style"], facts["commit_language"]), ("project", "vi"))

    def test_default_branch_and_develop(self):
        d = self.repo(subjects=["init"])
        self.git(d, "branch", "develop")
        self.git(d, "branch", "-m", "main", "trunk")
        facts = self.detect(d)
        self.assertEqual((facts["default_branch"], facts["has_develop"]), ("trunk", True))

    def test_commit_tools(self):
        d = self.repo()
        (d / "commitlint.config.js").write_text("module.exports = {}")
        (d / ".czrc").write_text("{}")
        (d / ".husky").mkdir()
        (d / ".husky" / "commit-msg").write_text("npx commitlint --edit $1")
        (d / ".git" / "hooks" / "commit-msg.sample").write_text("x")
        tools = self.detect(d)["commit_tools"]
        self.assertTrue(any(t.startswith("commitlint") for t in tools), tools)
        self.assertTrue(any(t.startswith("commitizen") for t in tools), tools)
        self.assertIn("commit-msg hook (.husky/commit-msg)", tools)
        e = self.repo("e")
        (e / "package.json").write_text(json.dumps({"commitlint": {}, "config": {"commitizen": {}}}))
        tools = self.detect(e)["commit_tools"]
        self.assertIn("commitlint (package.json)", tools)
        self.assertIn("commitizen (package.json)", tools)
        self.assertEqual(self.detect(self.repo("f"))["commit_tools"], [])  # a .sample hook is not a hook

    def test_deploy_candidates_are_names_only(self):
        d = self.repo()
        marker = d / "ran"
        (d / "Makefile").write_text(f"test:\n\tpytest\ndeploy-prod:\n\ttouch {marker}\nrelease: build\n\techo\n")
        scripts = {f"deploy{i}": f"touch {marker}" for i in range(12)} | {"test": "jest", "ship`x": "y"}
        (d / "package.json").write_text(json.dumps({"scripts": scripts}))
        (d / ".github" / "workflows").mkdir(parents=True)
        (d / ".github" / "workflows" / "cd.yml").write_text("jobs:\n  deploy:\n    runs-on: x")
        (d / ".github" / "workflows" / "ci.yml").write_text("jobs:\n  test: {}")
        (d / "Jenkinsfile").write_text("pipeline {}")
        cands = self.detect(d)["deploy_candidates"]
        self.assertLessEqual(len(cands), 10)
        self.assertIn("make deploy-prod", cands)
        self.assertIn("make release", cands)
        self.assertNotIn("make test", cands)
        self.assertFalse(marker.exists())
        self.assertTrue(all(len(c) <= 120 for c in cands))
        e = self.repo("e")
        (e / ".github" / "workflows").mkdir(parents=True)
        (e / ".github" / "workflows" / "cd.yml").write_text("deploy")
        (e / ".gitlab-ci.yml").write_text("x")
        self.assertEqual(self.detect(e)["deploy_candidates"], [".github/workflows/cd.yml", ".gitlab-ci.yml"])

    def test_detect_never_writes(self):
        d = self.repo()
        self.detect(d)
        self.assertEqual(list(self.data.iterdir()), [])


class StoreTests(Base):
    def test_data_dir_refusals(self):
        d = self.repo()
        inside_repo = d / "plugins" / "data" / "x"
        inside_repo.mkdir(parents=True)
        for data in (None, "", "   ", "${CLAUDE_PLUGIN_DATA}", "$CLAUDE_PLUGIN_DATA", str(d), str(self.tmp),
                     str(self.tmp / "plugins" / "data"), str(inside_repo)):
            with self.subTest(data=data):
                r = self.prof(d, "show", data=data)
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("etk profile:", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
        link = self.tmp / "link"
        link.symlink_to(d)
        self.assertEqual(self.prof(d, "show", data=str(link)).returncode, 2)

    def test_data_before_or_after_subcommand(self):
        d = self.repo()
        a = subprocess.run([sys.executable, str(PROFILE), "--data", str(self.data), "path"], cwd=d, env=self.env,
                           capture_output=True, text=True)
        b = subprocess.run([sys.executable, str(PROFILE), "path", f"--data={self.data}"], cwd=d, env=self.env,
                           capture_output=True, text=True)
        self.assertEqual((a.returncode, b.returncode), (0, 0))
        self.assertEqual(a.stdout, b.stdout)
        self.assertTrue(a.stdout.strip().startswith(str(self.data / "projects")))
        self.assertTrue(a.stdout.strip().endswith("/profile.json"))

    def test_round_trip_keeps_unknown_keys_and_modes(self):
        d = self.repo(remote="git@github.com:o/r.git")
        path = Path(self.ok(d, "path").strip())
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema": 1, "custom": {"x": [1, 2]}, "release": {"push": "auto", "extra": True}}))
        self.ok(d, "set", "release.integrate", '"pr"')
        self.ok(d, "set", "team.notes", '{"a": 1}')
        prof = json.loads(path.read_text())
        self.assertEqual(prof["custom"], {"x": [1, 2]})
        # a file with no binding (hand-written, or from before bindings) loses its `auto` values on the first edit
        self.assertEqual(prof["release"], {"extra": True, "integrate": "pr"})
        self.assertEqual(prof["team"], {"notes": {"a": 1}})
        self.assertEqual(prof["project"]["key"], self.detect(d)["key"])
        self.assertIn("updated_at", prof)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual([p.name for p in path.parent.iterdir()], ["profile.json"])  # no temp files left
        self.ok(d, "unset", "release.extra")
        self.assertNotIn("extra", json.loads(path.read_text())["release"])
        self.assertEqual(json.loads(self.ok(d, "show")), json.loads(path.read_text()))

    def test_set_validation(self):
        d = self.repo()
        bad = [("release.integrate", '"yolo"'), ("release.push", "maybe"), ("release.wait_ci", '"yes"'),
               ("branches.protected", '"main"'), ("branches.model", "1"), ("deploy.targets", '{"name": "x"}'),
               ("deploy.targets", '[{"name": "x", "kind": "magic"}]'), ("deploy.targets", '[{"kind": "manual"}]'),
               ("deploy.targets", '[{"name": "x", "kind": "command"}]'),
               ("deploy.targets", '[{"name": "x", "kind": "manual", "production": "yes"}]'),
               ("release", '"pr"'), ("release.merge.method", '"ff"'), ("commit.language", '"English!"'),
               ("project.key", '"x"'), ("project", "{}"), ("schema", "2"), ("confirmed_at", '"now"'),
               ("release..push", '"auto"'), ("release.push", "{not json"), ("vcs.type", "null")]
        for path, value in bad:
            with self.subTest(path=path, value=value):
                r = self.prof(d, "set", path, value)
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.prof(d, "unset", "project.key").returncode, 2)
        self.assertEqual(self.prof(d, "frobnicate").returncode, 2)
        self.assertEqual(self.prof(d, "set", "release.push").returncode, 2)
        self.assertFalse(Path(self.ok(d, "path").strip()).exists())
        self.ok(d, "set", "deploy.targets", '[{"name": "staging", "kind": "command", "command": "make deploy", '
                                           '"production": false, "verify": null}]')
        self.ok(d, "set", "commit.language", "vi")
        self.ok(d, "set", "host.cli", "null")

    def test_missing(self):
        d = self.repo(remote="git@github.com:o/r.git")
        self.assertEqual(self.ok(d, "missing").split(),
                         ["vcs.type", "branches.model", "release.commit", "release.push", "release.integrate",
                          "commit.style", "deploy"])
        for path, value in (("vcs.type", "git"), ("branches.model", "feature"), ("release.commit", "auto"),
                            ("release.push", "confirm"),
                            ("commit.style", "conventional"), ("release.integrate", "pr")):
            self.ok(d, "set", path, value)
        self.assertEqual(self.ok(d, "missing").split(), ["deploy"])
        self.ok(d, "set", "deploy.none", "true")
        self.assertEqual(self.ok(d, "missing"), "")
        local = self.repo("local")
        self.ok(local, "set", "vcs.type", "git")
        self.assertNotIn("release.integrate", self.ok(local, "missing").split())  # no remote, nothing to integrate

    def test_corrupt_file_moves_to_bak(self):
        d = self.repo()
        path = Path(self.ok(d, "path").strip())
        path.parent.mkdir(parents=True)
        for content in ("{not json", "[1, 2]"):
            path.write_text(content)
            r = self.prof(d, "show")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("no workflow profile yet", r.stdout)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1)
            self.assertIn("warning", r.stderr)
            self.assertEqual(path.with_name("profile.json.bak").read_text(), content)
            self.assertFalse(path.exists())
        self.ok(d, "set", "commit.style", "project")
        self.assertEqual(json.loads(path.read_text())["commit"], {"style": "project"})

    def test_remember_caps_and_single_line(self):
        d = self.repo()
        for i in range(55):
            self.ok(d, "remember", f"fact {i}")
        self.ok(d, "remember", "multi\nline " + "x" * 400, "--source", "detected")
        mem = json.loads(self.ok(d, "show"))["memory"]
        self.assertEqual(len(mem), 50)
        self.assertEqual(mem[0]["fact"], "fact 6")
        self.assertNotIn("\n", mem[-1]["fact"])
        self.assertLessEqual(len(mem[-1]["fact"]), 300)
        self.assertEqual(mem[-1]["source"], "detected")
        self.assertRegex(mem[-1]["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(self.prof(d, "remember", "x", "--source", "repo").returncode, 2)
        self.assertEqual(self.prof(d, "remember", "  ").returncode, 2)

    def test_show_brief_and_confirm(self):
        d = self.repo(remote="git@github.com:o/r.git")
        self.assertEqual(self.ok(d, "show", "--brief").strip(), "no workflow profile yet")
        for path, value in (("vcs.type", "git"), ("host", '{"type": "github", "cli": "gh", "cli_authed": true}'),
                            ("branches", '{"model": "feature", "default": "main"}'),
                            ("commit", '{"style": "conventional", "language": "en"}'),
                            ("release", '{"commit": "auto", "push": "auto", "integrate": "pr", '
                                        '"merge": {"method": "squash"}, "wait_ci": true}'),
                            ("deploy.targets", '[{"name": "staging", "kind": "command", "command": "make deploy"}, '
                                               '{"name": "production", "kind": "ci-on-tag", "production": true}]')):
            self.ok(d, "set", path, value)
        self.ok(d, "remember", "a")
        self.ok(d, "remember", "b")
        self.ok(d, "confirm")
        lines = self.ok(d, "show", "--brief").strip().splitlines()
        self.assertLessEqual(len(lines), 5)
        self.assertEqual(lines[0], "git · github (gh, signed in) · feature branches from main · conventional, en")
        self.assertEqual(lines[1], "release: commit auto · push auto · PR (squash) · wait for CI")
        self.assertEqual(lines[2], "deploy: staging (command), production (ci-on-tag, production)")
        self.assertEqual(lines[3], "memory: 2 notes")
        self.assertTrue(lines[4].startswith("file: ") and lines[4].endswith("profile.json"))
        self.assertIn("confirmed_at", json.loads(self.ok(d, "show", "--json")))
        self.ok(d, "unset", "deploy.targets")
        self.ok(d, "set", "deploy.none", "true")
        self.assertIn("deploy: none", self.ok(d, "show", "--brief"))

    def test_mixed_history_is_reported_as_project_style_not_a_finding(self):
        """`init` asks the style on `project` instead of saving it: detect guesses, it doesn't know."""
        d = self.repo(subjects=("feat: a", "Update readme", "wip", "fix stuff", "Merge branch x"))
        facts = self.detect(d)
        self.assertEqual(facts["commit_style"], "project")
        self.assertEqual(facts["commit_tools"], [])
        self.assertIn("commit.style", self.ok(d, "missing").split())

    def test_remember_ignores_an_exact_duplicate(self):
        d = self.repo()
        self.ok(d, "remember", "run one subagent at a time")
        out = self.ok(d, "remember", "  run one subagent at a time  ")
        self.assertIn("already remembered (1 note(s))", out)
        self.ok(d, "remember", "run one subagent at a time", "--source", "detected")
        self.ok(d, "remember", "another note")
        self.assertEqual([m["fact"] for m in json.loads(self.ok(d, "show", "--json"))["memory"]],
                         ["run one subagent at a time", "another note"])

    def test_brief_says_unconfirmed_after_a_change(self):
        d = self.repo(remote="git@github.com:o/r.git")
        self.ok(d, "set", "vcs.type", "git")
        self.ok(d, "set", "release.commit", "confirm")
        self.assertTrue(self.ok(d, "show", "--brief").strip().endswith("(unconfirmed)"))
        self.ok(d, "confirm")
        self.assertFalse(self.ok(d, "show", "--brief").strip().endswith("(unconfirmed)"))
        self.ok(d, "remember", "a note changes nothing")
        self.assertFalse(self.ok(d, "show", "--brief").strip().endswith("(unconfirmed)"))
        self.ok(d, "set", "release.push", "auto")
        self.assertTrue(self.ok(d, "show", "--brief").strip().endswith("(unconfirmed)"))

    def test_init_flow_keep_and_reset(self):
        """The command sequence `/engineering-team:init` runs: set, remember, confirm, then keep or reset."""
        d = self.repo(remote="git@github.com:o/r.git", subjects=("feat: a", "fix: b"))
        answers = (("vcs.type", "git"), ("branches.model", "feature"), ("release.commit", "auto"),
                   ("release.push", "confirm"), ("release.integrate", "pr"), ("commit.style", "conventional"),
                   ("deploy.none", "true"))
        for path, value in answers:
            self.ok(d, "set", path, value)
        self.ok(d, "remember", "run one subagent at a time")
        self.ok(d, "confirm")
        before = json.loads(self.ok(d, "show", "--json"))
        # keep: nothing is missing, and running the saves again leaves the file as it was
        self.assertEqual(self.ok(d, "missing"), "")
        self.ok(d, "remember", "run one subagent at a time")
        self.assertEqual(json.loads(self.ok(d, "show", "--json")), before)
        self.assertFalse(self.ok(d, "show", "--brief").strip().endswith("(unconfirmed)"))
        # reset: the fields init re-asks come back, the note stays, and the file says unconfirmed
        for top in ("vcs", "host", "branches", "commit", "release", "deploy"):
            self.assertEqual(self.prof(d, "unset", top).returncode, 0)
        self.assertEqual(self.ok(d, "missing").split(),
                         ["vcs.type", "branches.model", "release.commit", "release.push", "release.integrate",
                          "commit.style", "deploy"])
        self.assertEqual([m["fact"] for m in json.loads(self.ok(d, "show", "--json"))["memory"]],
                         ["run one subagent at a time"])
        self.assertTrue(self.ok(d, "show", "--brief").strip().endswith("(unconfirmed)"))
        self.assertEqual(self.git(d, "status", "--porcelain"), "")

    def test_profile_is_bound_to_checkout_and_push_url(self):
        d = self.repo(remote="https://github.com/victim/prod.git")
        for path, value in (("vcs.type", "git"), ("branches.model", "trunk"), ("release.push", "auto"),
                            ("release.commit", "auto"), ("release.integrate", "none"), ("commit.style", "project"),
                            ("deploy.none", "true")):
            self.ok(d, "set", path, value)
        self.ok(d, "confirm")
        stored = json.loads(self.ok(d, "show", "--json"))["project"]
        self.assertEqual((stored["root"], stored["push_hash"]),
                         (str(d), etk_profile.url_hash("https://github.com/victim/prod.git")))
        self.assertEqual(self.ok(d, "missing"), "")
        self.assertNotIn("re-confirm", self.ok(d, "show", "--brief"))
        # repository code redirects the push: the stored `auto` values stop counting
        self.git(d, "config", "remote.origin.pushurl", "https://user:pw@evil.example/x.git?token=SECRET")
        lines = self.ok(d, "show", "--brief").splitlines()
        self.assertEqual(lines[0], etk_profile.RECONFIRM)
        self.assertLessEqual(len(lines), 5)
        self.assertNotIn("push auto", "\n".join(lines))
        self.assertEqual(self.ok(d, "missing").splitlines(),
                         [etk_profile.RECONFIRM, "release.commit", "release.push"])
        out = DiscoverProfileTests.discover(self, d, "--data", str(self.data))
        self.assertIn("profile from a different checkout/remote; re-confirm", out)
        self.ok(d, "set", "commit.style", "conventional")  # an edit binds here and drops the old `auto`s
        self.assertEqual(self.ok(d, "missing").split(), ["release.commit", "release.push"])
        self.assertNotIn("auto", json.dumps(json.loads(self.ok(d, "show", "--json")).get("release", {})))
        self.ok(d, "confirm")  # the developer looked at it again here: nothing hidden comes back
        self.assertEqual(self.ok(d, "missing").split(), ["release.commit", "release.push"])
        self.ok(d, "set", "release.commit", "auto")
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "confirm")
        self.assertEqual(self.ok(d, "missing"), "")
        stored = json.loads(self.ok(d, "show", "--json"))["project"]
        self.assertEqual(stored["push_hash"], etk_profile.url_hash("https://user:pw@evil.example/x.git?token=SECRET"))
        # another checkout that claims the same origin finds the same file but not its `auto`s
        other = self.repo("other", "git@github.com:victim/prod.git")
        self.assertEqual(self.ok(other, "path"), self.ok(d, "path"))
        self.assertEqual(self.ok(other, "show", "--brief").splitlines()[0], etk_profile.RECONFIRM)
        self.assertIn("release.push", self.ok(other, "missing").splitlines())

    ATTACKS = (
        "https://github.com/o/r.git", "https://evil.example?@github.com/o/r.git", "https://evil.example#@github.com/o/r.git",
        "https://github.com\\@evil.example/victim/prod.git", "https://evil.example;@github.com/o/r.git",
        "ssh://github.com%2F@evil.example/o/r.git", "git://github.com%2F@evil.example/o/r.git",
        "ssh+git://github.com%2F@evil.example/o/r.git", "https://user@evil@github.com/o/r.git",
        "https://github.com:443@evil.example/o/r.git", "https:////github.com/o/r", "git@github.com:o/r.git",
        "https://github.com /o/r", "https://" + "a" * 600 + ".com/o/r", "https://alice:pa\\ss@github.com/o/r.git",
        "https://alice:pa#ss@github.com/o/r.git", "https://github.com/o/r\x00.git",
    )

    def test_mismatch_is_decided_on_the_raw_push_url(self):
        for n, bound in enumerate(self.ATTACKS):
            with self.subTest(bound=bound[:60]):
                d = self.repo(f"p{n}", "https://github.com/o/r.git")
                if "\x00" in bound:  # git can't hold a NUL; the hash helper must still not raise on it
                    self.assertIsNotNone(etk_profile.url_hash(bound))
                    continue
                self.git(d, "config", "remote.origin.pushurl", bound)
                self.ok(d, "set", "release.push", "auto")
                self.ok(d, "confirm")
                run = self.open_run(d)
                self.assertEqual(self.authorize(d, run, "push").returncode, 0)
                self.assertNotIn("re-confirm", self.ok(d, "show", "--brief"))
                near = tuple(self.ATTACKS[(n + k) % len(self.ATTACKS)] for k in (1, 2, 3))
                for other in near + ("https://github.com/o/r.git ", "HTTPS://github.com/o/r.git"):
                    if other.strip() == bound.strip() or "\x00" in other:
                        continue
                    self.git(d, "config", "remote.origin.pushurl", other)
                    self.assertEqual(self.ok(d, "show", "--brief").splitlines()[0], etk_profile.RECONFIRM, other[:60])
                    self.assertEqual(self.authorize(d, run, "push").returncode, 2, other[:60])
                self.git(d, "config", "remote.origin.pushurl", bound)  # the identical raw string is the same push
                self.assertNotIn("re-confirm", self.ok(d, "show", "--brief"))
                self.assertEqual(self.authorize(d, run, "push").returncode, 0)

    SECRETS = {
        "https://alice:paXq\\ssZ@github.com/o/r.git": ("paXq", "ssZ"),
        "https://oauth2:glpat-ABxy\\CDzw@gitlab.com/o/r.git": ("glpat-ABxy", "CDzw"),
        "https://alice:paXq#ssZ@github.com/o/r.git": ("paXq", "ssZ"), "https://alice:paXq?ssZ@github.com/o/r.git": ("paXq", "ssZ"),
        "https://alice:paXq/ssZ@github.com/o/r.git": ("paXq", "ssZ"), "https://alice:s3cr3t@github.com/o/r.git": ("s3cr3t",),
        "https://alice:paXq;ssZ@github.com/o/r.git": ("paXq", "ssZ"), "https://alice:paXq%40ssZ@github.com/o/r.git": ("paXq", "ssZ"),
        "ssh://git:hunter2@github.com%2F@evil.example/o/r.git": ("hunter2", "evil.example"),
        "https://github.com/o/r.git?access_token=TOK3N#frag": ("TOK3N",), "git@evil@github.com:o/r.git": ("evil@",),
    }

    def test_no_url_text_or_secret_reaches_any_output_or_the_saved_file(self):
        for n, (url, secrets) in enumerate(self.SECRETS.items()):
            with self.subTest(url=url):
                d = self.repo(f"s{n}", url)
                self.git(d, "config", "remote.origin.pushurl", url)
                outputs = [self.ok(d, "detect"), self.ok(d, "show", "--brief")]
                outputs += [self.ok(d, "set", "commit.style", "project"), self.ok(d, "set", "release.push", "auto"),
                            self.ok(d, "show"), self.ok(d, "show", "--json"), self.ok(d, "missing"),
                            self.ok(d, "confirm"), self.ok(d, "unset", "release.push")]
                self.git(d, "config", "remote.origin.pushurl", url + "x")  # now stale: brief, set, confirm again
                outputs += [self.ok(d, "show", "--brief"), self.ok(d, "missing"), self.ok(d, "set", "release.push", "auto"),
                            self.ok(d, "confirm")]
                out = DiscoverProfileTests.discover(self, d, "--data", str(self.data))
                saved = Path(self.ok(d, "path").strip()).read_text()
                for text in outputs + [out, saved]:
                    for secret in secrets:
                        self.assertNotIn(secret, text)
                self.assertNotIn("alice", saved)
                self.assertNotIn("://", saved)
                for text in outputs[1:] + [out]:  # everything but `detect` (which shows a plain host) has no URL
                    self.assertNotIn("://", text)

    def test_stale_brief_gives_a_reason_without_repository_text(self):
        d = self.repo(remote="https://github.com/o/r.git")
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "confirm")
        self.git(d, "config", "remote.origin.pushurl", "https://user:pw@evil.example/x.git?token=SECRET")
        lines = self.ok(d, "show", "--brief").splitlines()
        self.assertEqual(lines[0], etk_profile.RECONFIRM)
        self.assertEqual(lines[1], "push URLs changed since you confirmed (see `git remote get-url --push --all origin`)")
        self.assertLessEqual(len(lines), 5)
        self.assertNotIn("evil", "\n".join(lines))
        other = self.repo("other", "https://github.com/o/r.git")
        self.assertIn("checkout moved (profile was confirmed at another path)", self.ok(other, "show", "--brief"))
        self.assertNotIn(str(d), self.ok(other, "show", "--brief"))

    def test_different_origins_never_share_a_profile_path(self):
        origins = [u for u in self.ATTACKS if "\x00" not in u and not u.startswith("git@")] + [
            "https://github.com/o/other.git", "ssh://github.com%2F@evil.example/o/r.git",
            "ssh://github.com%2F@evil.example/o/r2.git", "https://evil.example?@github.com/o/r.git?x"]
        paths = {}
        for n, url in enumerate(dict.fromkeys(origins)):
            d = self.repo(f"o{n}", url)
            path = self.ok(d, "path").strip()
            self.assertNotIn(path, paths, f"{url[:50]} shares a profile with {paths.get(path, '')[:50]}")
            paths[path] = url
        # the same repository spelled two plain ways still finds one profile
        a = self.repo("pa", "git@github.com:o/same.git")
        b = self.repo("pb", "https://user:pw@GitHub.com/o/same.git/")
        self.assertEqual(self.ok(a, "path"), self.ok(b, "path"))

    def test_garbage_in_the_stored_profile_never_raises(self):
        d = self.repo(remote="https://github.com/o/r.git")
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "confirm")
        path = Path(self.ok(d, "path").strip())
        good = json.loads(path.read_text())
        for bad in (7, [1], {"x": 1}, True, None, "x", 1.5):
            for field in ("root", "origin_hash", "push_hash", "key", "remote", "push"):
                prof = json.loads(json.dumps(good))
                prof["project"][field] = bad
                path.write_text(json.dumps(prof))
                for args in (("show", "--brief"), ("missing",), ("show",), ("show", "--json"),
                             ("set", "release.integrate", '"pr"'), ("unset", "release.integrate"),
                             ("remember", f"n{field}{bad}"), ("confirm",)):
                    with self.subTest(field=field, bad=bad, cmd=args[0]):
                        r = self.prof(d, *args)
                        self.assertNotIn("Traceback", r.stderr)
                        self.assertIn(r.returncode, (0, 2), r.stderr)
                path.write_text(json.dumps(good))
            for key in ("project", "release", "memory", "deploy", "confirmed_hash"):
                prof = json.loads(json.dumps(good))
                prof[key] = bad
                path.write_text(json.dumps(prof))
                for args in (("show", "--brief"), ("missing",), ("confirm",), ("set", "commit.style", "project")):
                    with self.subTest(key=key, bad=bad, cmd=args[0]):
                        r = self.prof(d, *args)
                        self.assertNotIn("Traceback", r.stderr)
                        self.assertIn(r.returncode, (0, 2), r.stderr)
                        path.write_text(json.dumps(prof))
                out = DiscoverProfileTests.discover(self, d, "--data", str(self.data))
                self.assertNotIn("Traceback", out)
                path.write_text(json.dumps(good))

    def test_old_plaintext_binding_is_stale_and_drops_its_auto_values(self):
        d = self.repo(remote="https://github.com/o/r.git")
        path = Path(self.ok(d, "path").strip())
        path.parent.mkdir(parents=True)
        old = {"schema": 1, "project": {"remote": "https://github.com/o/r.git", "push": "https://github.com/o/r.git",
                                        "root": str(d), "key": "x"}, "release": {"push": "auto"}}
        path.write_text(json.dumps(old))
        self.assertEqual(self.ok(d, "show", "--brief").splitlines()[0], etk_profile.RECONFIRM)
        self.assertIn("older format", self.ok(d, "show", "--brief"))
        self.assertIn("dropped release.push=auto", self.ok(d, "set", "release.commit", "auto"))
        stored = json.loads(path.read_text())
        self.assertEqual(sorted(stored["project"]), ["key", "origin_hash", "push_hash", "root"])

    def test_same_checkout_keeps_auto_values_and_confirmed_state(self):
        d = self.repo(remote="https://github.com/o/r.git")
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "confirm")
        before = json.loads(self.ok(d, "show", "--json"))
        self.assertEqual(self.ok(d, "set", "release.integrate", '"pr"').strip(), "set release.integrate")
        self.assertEqual(json.loads(self.ok(d, "show", "--json"))["release"]["push"], "auto")
        self.assertEqual(json.loads(self.ok(d, "show", "--json"))["project"], before["project"])
        self.ok(d, "confirm")
        self.assertNotIn("(unconfirmed)", self.ok(d, "show", "--brief"))
        self.assertEqual(self.authorize(d, self.open_run(d), "push").returncode, 0)

    def test_confirm_in_another_checkout_does_not_approve_hidden_auto_values(self):
        remote = "https://github.com/victim/prod.git"
        a = self.repo("a", remote)
        for path, value in (("vcs.type", "git"), ("release.push", "auto"), ("release.commit", "auto")):
            self.ok(a, "set", path, value)
        self.ok(a, "confirm")
        b = self.repo("b", remote)
        self.assertEqual(self.ok(b, "path"), self.ok(a, "path"))
        self.assertEqual(self.ok(b, "show", "--brief").splitlines()[0], etk_profile.RECONFIRM)
        self.ok(b, "set", "branches.model", "feature")
        self.ok(b, "confirm")
        stored = json.loads(self.ok(b, "show", "--json"))
        self.assertNotIn("push", stored.get("release", {}))
        self.assertNotIn("commit", stored.get("release", {}))
        self.assertEqual(stored["project"]["root"], str(b))
        self.assertEqual(self.ok(b, "missing").split(), ["release.commit", "release.push", "release.integrate",
                                                         "commit.style", "deploy"])
        self.assertNotIn("(unconfirmed)", self.ok(b, "show", "--brief"))
        etk = ROOT / "scripts" / "etk_run.py"
        r = subprocess.run([sys.executable, str(etk), "init", "ship it", "--kind", "ship"], cwd=b, env=self.env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        run = r.stdout.strip()
        for action in ("push", "commit"):
            r = subprocess.run([sys.executable, str(etk), "authorize", "--action", action, "--source", "profile",
                                "--data", str(self.data), run], cwd=b, env=self.env, capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 2, r.stdout)
            self.assertIn("doesn't pre-authorize", r.stderr)
        # the developer answers the fields again here, and only then does the profile authorize
        self.ok(b, "set", "release.push", "auto")
        self.ok(b, "confirm")
        r = subprocess.run([sys.executable, str(etk), "authorize", "--action", "push", "--source", "profile",
                            "--data", str(self.data), run], cwd=b, env=self.env, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def authorize(self, cwd, run, action):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "etk_run.py"), "authorize", "--action", action,
                               "--source", "profile", "--data", str(self.data), run], cwd=cwd, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def open_run(self, cwd):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "etk_run.py"), "init", "ship it", "--kind", "ship"],
                           cwd=cwd, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_reanswering_in_another_checkout_needs_one_confirm(self):
        """The order the init skill uses: missing, set the dropped fields, one confirm."""
        remote = "https://github.com/victim/prod.git"
        a = self.repo("a", remote)
        for path, value in (("vcs.type", "git"), ("branches.model", "trunk"), ("release.commit", "auto"),
                            ("release.push", "auto"), ("release.integrate", "none"), ("commit.style", "project"),
                            ("deploy.none", "true")):
            self.ok(a, "set", path, value)
        self.ok(a, "confirm")
        b = self.repo("b", remote)
        run = self.open_run(b)
        self.assertEqual(self.authorize(b, run, "push").returncode, 2)
        self.assertEqual(self.ok(b, "missing").splitlines(), [etk_profile.RECONFIRM, "release.commit", "release.push"])
        self.ok(b, "set", "release.commit", "auto")
        self.ok(b, "set", "release.push", "auto")
        refused = self.authorize(b, run, "push")  # set without confirm never authorizes
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("confirm", refused.stderr)
        self.ok(b, "confirm")
        self.assertEqual(self.ok(b, "missing"), "")
        self.assertEqual(self.authorize(b, run, "push").returncode, 0)
        self.assertEqual(self.authorize(b, run, "commit").returncode, 0)

    def test_a_rewritten_push_url_stays_refused_until_answered_and_confirmed_again(self):
        d = self.repo(remote="https://github.com/victim/prod.git")
        for path, value in (("vcs.type", "git"), ("release.commit", "auto"), ("release.push", "auto")):
            self.ok(d, "set", path, value)
        self.ok(d, "confirm")
        run = self.open_run(d)
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        self.git(d, "config", "remote.origin.pushurl", "https://evil.example/x.git")
        self.assertEqual(self.authorize(d, run, "commit").returncode, 2)
        self.ok(d, "confirm")  # looking at it is not answering it
        self.assertEqual(self.authorize(d, run, "commit").returncode, 2)
        self.ok(d, "set", "release.commit", "auto")
        self.assertEqual(self.authorize(d, run, "commit").returncode, 2)  # not confirmed yet
        self.ok(d, "confirm")
        self.assertEqual(self.authorize(d, run, "commit").returncode, 0)
        self.assertEqual(self.authorize(d, run, "push").returncode, 2)  # never re-answered

    def test_set_unset_and_remember_say_what_they_drop_and_never_bind_hidden_autos(self):
        remote = "https://github.com/victim/prod.git"
        a = self.repo("a", remote)
        for path, value in (("release.push", "auto"), ("release.commit", "auto")):
            self.ok(a, "set", path, value)
        self.ok(a, "confirm")
        b = self.repo("b", remote)
        out = self.ok(b, "set", "branches.model", "feature")
        self.assertIn("dropped release.push=auto, release.commit=auto", out)
        self.assertIn("answer them again here", out)
        self.assertNotIn("dropped", self.ok(b, "set", "release.integrate", "pr"))  # nothing left to drop
        c = self.repo("c", remote)
        self.ok(a, "set", "release.push", "auto")
        self.ok(a, "confirm")
        self.assertIn("dropped release.push=auto", self.ok(c, "unset", "branches.model"))
        # an unbound hand-written file: `remember` must not bind it with its `auto` values in place
        d = self.repo("d", "https://github.com/other/thing.git")
        path = Path(self.ok(d, "path").strip())
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema": 1, "release": {"push": "auto"}}))
        self.ok(d, "remember", "a note")
        stored = json.loads(path.read_text())
        self.assertNotIn("push", stored.get("release", {}))
        self.assertEqual([m["fact"] for m in stored["memory"]], ["a note"])

    def test_confirm_and_unset_report_what_a_stale_profile_drops(self):
        remote = "https://github.com/victim/prod.git"
        a = self.repo("a", remote)
        self.ok(a, "set", "release.push", "auto")
        self.ok(a, "confirm")
        b = self.repo("b", remote)
        self.assertNotIn("dropped", self.ok(b, "remember", "n"))
        out = self.ok(b, "confirm")
        self.assertIn("dropped release.push=auto", out)
        self.assertNotIn("push", json.loads(self.ok(b, "show", "--json")).get("release", {}))
        c = self.repo("c", remote)
        self.ok(b, "set", "release.push", "auto")
        self.ok(b, "confirm")
        r = self.prof(c, "unset", "release.push")  # the file still holds the value: it is not "not set"
        self.assertEqual(r.returncode, 0)
        self.assertIn("unset release.push", r.stdout)
        self.assertNotIn("was not set", r.stderr)
        self.assertNotIn("dropped", r.stdout)
        self.assertNotIn("push", json.loads(self.ok(c, "show", "--json")).get("release", {}))
        self.assertIn("was not set", self.prof(c, "unset", "release.push").stderr)

    def test_commit_tooling_without_history_settles_the_style(self):
        """The init skill saves `project` when tooling exists but there is no history to read a style from."""
        d = self.repo(subjects=())
        (d / "commitlint.config.js").write_text("module.exports = {}")
        facts = self.detect(d)
        self.assertIsNone(facts["commit_style"])
        self.assertTrue(facts["commit_tools"])
        self.assertIn("commit.style", self.ok(d, "missing").split())
        style = facts["commit_style"] or ("project" if facts["commit_tools"] else None)
        self.ok(d, "set", "commit.style", style)
        self.assertNotIn("commit.style", self.ok(d, "missing").split())

    def test_push_auto_needs_a_plain_push_to_the_bound_remote(self):
        d = self.repo(remote="https://github.com/victim/prod.git")
        self.ok(d, "set", "release.push", '"auto"')
        self.ok(d, "confirm")
        run = self.open_run(d)
        self.assertNotIn("re-confirm", self.ok(d, "show", "--brief"))
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        self.git(d, "remote", "add", "decoy", "https://github.com/victim/prod.git")  # same URL, another remote
        branch = self.git(d, "symbolic-ref", "--short", "HEAD").strip()
        for key, value in ((f"branch.{branch}.pushRemote", "decoy"), ("remote.pushDefault", "decoy")):
            self.git(d, "config", key, value)
            brief = self.ok(d, "show", "--brief")
            self.assertIn(etk_profile.PUSH_NA, brief.splitlines())
            self.assertIn("push confirm", brief)
            self.assertLessEqual(len(brief.splitlines()), 5)
            self.assertEqual(self.authorize(d, run, "push").returncode, 2)
            self.assertNotIn("release.push", self.ok(d, "missing"))  # nothing to ask: the stored answer is kept
            self.git(d, "config", "--unset", key)
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)  # unchanged config keeps auto

    def test_changing_the_set_of_push_or_fetch_urls_makes_the_profile_stale(self):
        remote = "https://github.com/victim/prod.git"
        evil = "https://evil.example/x.git"

        def fresh(name):
            d = self.repo(name, remote)
            self.ok(d, "set", "release.push", "auto")
            self.ok(d, "confirm")
            run = self.open_run(d)
            self.assertEqual(self.authorize(d, run, "push").returncode, 0, name)
            self.assertNotIn("re-confirm", self.ok(d, "show", "--brief"), name)
            return d, run

        def stale(d, run, reason, what):
            lines = self.ok(d, "show", "--brief").splitlines()
            self.assertEqual(lines[0], etk_profile.RECONFIRM, what)
            self.assertIn(reason, lines[1], what)
            self.assertEqual(self.authorize(d, run, "push").returncode, 2, what)

        push = "push URLs changed since you confirmed"
        d, run = fresh("a")  # (a) the original again, then an evil second push URL
        self.git(d, "config", "--add", "remote.origin.pushurl", remote)  # pushes to the same single URL: no change
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        self.git(d, "config", "--add", "remote.origin.pushurl", evil)
        stale(d, run, push, "second pushurl evil")
        d, run = fresh("b")  # (b) decoy remote, pushDefault decoy, origin.pushurl evil
        self.git(d, "remote", "add", "decoy", remote)
        self.git(d, "config", "remote.pushDefault", "decoy")
        self.git(d, "config", "remote.origin.pushurl", evil)
        stale(d, run, push, "decoy + evil pushurl")
        d, run = fresh("d")  # (d) the same URLs in another order
        self.git(d, "config", "--add", "remote.origin.pushurl", remote)
        self.git(d, "config", "--add", "remote.origin.pushurl", evil)
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "confirm")
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        self.git(d, "config", "--unset-all", "remote.origin.pushurl")
        self.git(d, "config", "--add", "remote.origin.pushurl", evil)
        self.git(d, "config", "--add", "remote.origin.pushurl", remote)
        stale(d, run, push, "reordered")
        d, run = fresh("e")  # (e) another fetch URL
        self.git(d, "config", "--add", "remote.origin.url", evil)
        stale(d, run, "origin URLs changed since you confirmed", "second fetch url")
        d = self.repo("f", remote)  # only the origin (fetch) URL changes, to another spelling of the same repo
        self.git(d, "config", "remote.origin.pushurl", remote)
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "confirm")
        run = self.open_run(d)
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        self.git(d, "config", "remote.origin.url", "git@github.com:victim/prod.git")
        lines = self.ok(d, "show", "--brief").splitlines()
        self.assertEqual(lines[0], etk_profile.RECONFIRM)
        self.assertEqual(lines[1], "origin URLs changed since you confirmed (see `git remote get-url --all origin`)")
        self.assertEqual(self.authorize(d, run, "push").returncode, 2)

    def test_no_origin_never_satisfies_push_auto_and_a_later_redirect_cannot_either(self):
        d = self.repo("noremote")
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "set", "release.commit", "auto")
        self.ok(d, "confirm")
        run = self.open_run(d)
        self.assertEqual(self.authorize(d, run, "push").returncode, 2)
        r = self.authorize(d, run, "commit")  # a local commit needs no remote
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(etk_profile.PUSH_NA, self.ok(d, "show", "--brief"))
        # (c) a redirect created after the profile was confirmed without an origin
        self.git(d, "config", "url.https://evil.example/.insteadOf", "origin:")
        self.git(d, "remote", "add", "origin", "origin:x.git")
        # an origin changes the profile key (it came from the checkout path before), so the old file isn't found
        self.assertEqual(self.ok(d, "show", "--brief").strip(), "no workflow profile yet")
        self.assertEqual(self.authorize(d, run, "push").returncode, 2)
        self.ok(d, "set", "release.push", "auto")  # the user answers again, here
        self.ok(d, "confirm")
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        self.git(d, "config", "--unset", "url.https://evil.example/.insteadOf")  # the redirect disappears
        self.assertEqual(self.authorize(d, run, "push").returncode, 2)

    def etk_run(self, cwd, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "etk_run.py"), *args], cwd=cwd, env=self.env,
                              capture_output=True, text=True, timeout=60)

    def ship_ready(self, d, remote="https://github.com/victim/prod.git"):
        """A confirmed profile with push auto, a ship run whose gates pass, and a profile push authorization."""
        self.ok(d, "set", "release.push", "auto")
        self.ok(d, "set", "release.commit", "auto")
        self.ok(d, "confirm")
        run = self.open_run(d)
        led = json.loads((Path(run) / "gates.json").read_text())
        led["acceptance_criteria"] = [{"id": "AC-1", "text": "it works", "status": "met"}]
        for g in led["gates"]:
            led["gates"][g] = {"status": "PASS", "evidence": "checked carefully with evidence", "commands": []}
        for g in ("G3", "G4"):
            led["gates"][g]["commands"] = [{"cmd": "t", "exit_code": 0, "type": "test", "recorded_by": "exec"}]
        led["gates"]["G4"]["commands"].append({"cmd": "r", "exit_code": 0, "type": "runtime", "recorded_by": "exec"})
        led["gates"]["G7"] = {"status": "NOT_RUN", "evidence": "", "commands": []}
        (Path(run) / "gates.json").write_text(json.dumps(led))
        self.assertEqual(self.authorize(d, run, "push").returncode, 0)
        return run

    def act(self, d, run, *extra, data=True):
        return self.etk_run(d, "act", "--action", "push", "--ref", "x", "--exit", "0",
                            *(["--data", str(self.data)] if data else []), *extra, run)

    def test_act_push_rechecks_the_binding_the_profile_authorized(self):
        d = self.repo("act", "https://github.com/victim/prod.git")
        run = self.ship_ready(d)
        self.git(d, "config", "--add", "remote.origin.pushurl", "https://evil.example/x.git")
        r = self.act(d, run)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("changed since the profile authorized it", r.stderr)
        self.assertNotIn("evil", r.stderr + r.stdout)
        self.git(d, "config", "--unset-all", "remote.origin.pushurl")
        self.assertEqual(self.act(d, run).returncode, 0)
        self.assertIs(json.loads((Path(run) / "gates.json").read_text())["actions"][0]["binding_ok"], True)

    def test_act_needs_data_to_recheck_a_profile_authorized_push(self):
        d = self.repo("nodata", "https://github.com/victim/prod.git")
        run = self.ship_ready(d)
        r = self.act(d, run, data=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--data", r.stderr)

    def test_force_record_of_a_moved_binding_fails_check(self):
        d = self.repo("force", "https://github.com/victim/prod.git")
        run = self.ship_ready(d)
        self.assertEqual(self.etk_run(d, "check", run).returncode, 0)
        self.git(d, "config", "--add", "remote.origin.pushurl", "https://evil.example/x.git")
        self.assertEqual(self.act(d, run).returncode, 2)
        r = self.act(d, run, "--force-record")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("binding had moved", r.stdout)
        self.assertIs(json.loads((Path(run) / "gates.json").read_text())["actions"][0]["binding_ok"], False)
        r = self.etk_run(d, "check", run)
        self.assertEqual(r.returncode, 1)
        self.assertIn("binding had moved", r.stdout + r.stderr)
        self.assertNotIn("evil", r.stdout + r.stderr)

    def test_force_record_without_a_moved_binding_is_clean(self):
        d = self.repo("forceok", "https://github.com/victim/prod.git")
        run = self.ship_ready(d)
        self.assertEqual(self.act(d, run, "--force-record").returncode, 0)
        self.assertIs(json.loads((Path(run) / "gates.json").read_text())["actions"][0]["binding_ok"], True)
        self.assertEqual(self.etk_run(d, "check", run).returncode, 0)

    def test_local_path_origins_and_parsed_remotes_have_different_keys(self):
        local = self.repo("loc", "github.com/o/r")
        plain = self.repo("web", "https://github.com/o/r")
        self.assertNotEqual(self.ok(local, "path"), self.ok(plain, "path"))

    def test_symlinks_in_the_store_are_refused(self):
        d = self.repo()
        path = Path(self.ok(d, "path").strip())
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        for link in (path.parent.parent, path.parent, path):
            for p in (path, path.parent, path.parent.parent):  # reset
                if p.is_symlink() or p.is_file():
                    p.unlink()
                elif p.is_dir():
                    p.rmdir()
            link.parent.mkdir(parents=True, exist_ok=True)
            target = elsewhere / "profile.json" if link == path else elsewhere
            if link == path:
                target.write_text(json.dumps({"release": {"push": "auto"}}))
            link.symlink_to(target)
            for args in (("set", "commit.style", "project"), ("show",), ("missing",)):
                with self.subTest(link=link.name, args=args):
                    r = self.prof(d, *args)
                    self.assertEqual(r.returncode, 2, r.stdout)
                    self.assertIn("symlink", r.stderr)
                    self.assertNotIn("Traceback", r.stderr)
            self.assertFalse((elsewhere / ".profile.tmp").exists())
            self.assertEqual(sorted(x.name for x in elsewhere.iterdir()),
                             ["profile.json"] if link == path else [])
            if link == path:
                target.unlink()

    def test_through_etk_sh(self):
        d = self.repo()
        r = subprocess.run(["sh", str(ROOT / "scripts" / "etk.sh"), "profile", "set", "release.push", '"confirm"',
                            "--data", str(self.data)], cwd=d, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(["sh", str(ROOT / "scripts" / "etk.sh"), "profile", "show", "--brief",
                            "--data", str(self.data)], cwd=d, env=self.env, capture_output=True, text=True)
        self.assertIn("release: push confirm", r.stdout)
        r = subprocess.run(["sh", str(ROOT / "scripts" / "etk.sh"), "profile", "show"], cwd=d, env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


class DiscoverProfileTests(Base):
    def discover(self, cwd: Path, *args: str) -> str:
        r = subprocess.run([sys.executable, str(DISCOVER), *args], cwd=cwd, env=self.env, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("discover.py failed", r.stdout)
        return r.stdout

    def test_profile_block(self):
        d = self.repo(remote="git@github.com:o/r.git")
        base = self.discover(d)
        for args in ((), ("--data", "${CLAUDE_PLUGIN_DATA}"), ("--data", str(self.tmp))):
            out = self.discover(d, *args)
            self.assertIn("- profile: unknown here; run `etk.sh profile show --data <plugin data dir>`", out)
            self.assertNotIn("### Workflow profile", out)
        out = self.discover(d, "--data", str(self.data))
        self.assertIn("### Workflow profile", out)
        self.assertIn("- missing: vcs.type, branches.model, release.commit, release.push, release.integrate, "
                      "commit.style, deploy "
                      "→ onboard (workflows/profile.md)", out)
        for path, value in (("vcs.type", "git"), ("branches.model", "trunk"), ("release.commit", "auto"),
                            ("release.push", "auto"), ("release.integrate", "none"), ("commit.style", "project"),
                            ("deploy.none", "true")):
            self.ok(d, "set", path, value)
        self.ok(d, "remember", "x")
        out = self.discover(d, "--data", str(self.data))
        block = out.split("### Workflow profile\n", 1)[1].split("\n\n", 1)[0].splitlines()
        self.assertLessEqual(len(block), 4)
        self.assertEqual(block[0], "- git · trunk-based · project")
        self.assertIn("memory: 1 note", block[-1])
        self.assertLessEqual(len(out.splitlines()) - len(base.splitlines()), 6)

    def test_profile_block_keeps_unconfirmed_visible(self):
        d = self.repo()
        for path, value in (("vcs.type", "git"), ("branches.model", "trunk"), ("release.push", "confirm"),
                            ("commit.style", "project"), ("deploy.none", "true")):
            self.ok(d, "set", path, value)
        block = self.discover(d, "--data", str(self.data)).split("### Workflow profile\n", 1)[1].split("\n\n")[0]
        self.assertIn("(unconfirmed)", block)
        self.ok(d, "confirm")
        block = self.discover(d, "--data", str(self.data)).split("### Workflow profile\n", 1)[1].split("\n\n")[0]
        self.assertNotIn("unconfirmed", block)

    def test_status_does_not_run_repository_filters(self):
        import discover  # noqa: E402  (scripts/ is on sys.path)
        d = self.repo()
        (d / "a.txt").write_text("hello\n")
        self.git(d, "add", "a.txt")
        self.git(d, "commit", "-q", "-m", "a")
        marker = self.tmp / "filter-ran"
        (d / ".gitattributes").write_text("* filter=x\n")
        self.git(d, "config", "filter.x.clean", f": > '{marker}'")
        st = (d / "a.txt").stat()
        os.utime(d / "a.txt", (st.st_atime, st.st_mtime + 5))  # same content, new stat: status must hash it
        out = self.discover(d)
        self.assertFalse(marker.exists(), "discover ran the repository's clean filter")
        if discover.git_version(d) < (2, 40):
            self.assertIn("uncommitted changes UNKNOWN", out)
        else:
            self.assertNotIn("UNKNOWN", out)
        self.git(d, "status", "--porcelain")  # the setup really would have run it
        self.assertTrue(marker.exists())

    def test_conventions_line_only_when_present(self):
        d = self.repo()
        out = self.discover(d)
        has = (ROOT / "conventions" / "README.md").is_file()
        self.assertEqual(f"Conventions: {ROOT / 'conventions' / 'README.md'}" in out, has)

    def test_conventions_opt_out_and_extra(self):
        if not (ROOT / "conventions" / "README.md").is_file():
            self.skipTest("conventions pack not present")
        d = self.repo()
        (d / "docs").mkdir()
        (d / "docs" / "api-guide.md").write_text("x")
        outside = self.tmp / "outside.md"
        outside.write_text("x")
        cfg = d / ".claude" / "engineering-team.json"
        cfg.parent.mkdir(exist_ok=True)
        cfg.write_text(json.dumps({"conventions": {"disable": ["ui", "api", "bogus"],
                                                   "extra": ["docs/api-guide.md", str(outside), "../outside.md",
                                                             "missing.md"]}}))
        line = [x for x in self.discover(d).splitlines() if x.startswith("- Conventions:")]
        self.assertEqual(len(line), 1)
        self.assertIn("(skip: api, ui)", line[0])
        self.assertIn("; project: docs/api-guide.md", line[0])
        self.assertNotIn("outside", line[0])
        self.assertNotIn("missing", line[0])
        cfg.write_text(json.dumps({"conventions": {"disable": ["all"]}}))
        self.assertNotIn("- Conventions:", self.discover(d))
        cfg.write_text(json.dumps({"conventions": "nonsense"}))
        self.assertIn("- Conventions:", self.discover(d))

    def test_previous_run_skips_untrustworthy_entries(self):
        d = self.repo()
        good = d / ".etk" / "runs" / "20240101-120000-real"
        good.mkdir(parents=True)
        (good / "gates.json").write_text("{}")
        future = d / ".etk" / "runs" / "99999999-000000-x"
        future.mkdir()
        (future / "gates.json").write_text("{}")
        later = d / ".etk" / "runs" / "20990101-000000-planted"
        later.mkdir()
        (later / "gates.json").write_text("{}")
        tracked = d / ".etk" / "runs" / "20250101-000000-tracked"
        tracked.mkdir()
        (tracked / "gates.json").write_text("{}")
        self.git(d, "add", "-f", ".etk/runs/20250101-000000-tracked/gates.json")
        self.git(d, "commit", "-q", "-m", "plant")
        elsewhere = self.tmp / "elsewhere" / "20250601-000000-link"
        elsewhere.mkdir(parents=True)
        (elsewhere / "gates.json").write_text("{}")
        (d / ".etk" / "runs" / "20250601-000000-link").symlink_to(elsewhere)
        out = self.discover(d)
        self.assertIn("- previous ETK run: `.etk/runs/20240101-120000-real`", out)
        e = self.repo("e")
        (e / ".etk").mkdir()
        (e / ".etk" / "runs").symlink_to(d / ".etk" / "runs")
        self.assertNotIn("previous ETK run", self.discover(e))

    def test_repo_strings_are_sanitized(self):
        d = self.repo()
        (d / "package.json").write_text(json.dumps({"scripts": {"test`; rm -rf /`\u0007\u202e\u2066" + "x" * 200:
                                                                "jest`x`\u200b"}}))
        (d / ".claude").mkdir()
        (d / ".claude" / "engineering-team.json").write_text(json.dumps(
            {"rules": [{"paths": ["a/**"], "rule": "r", "check": "npm run lint`\n## injected" + "y" * 200}]}))
        out = self.discover(d)
        line = next(l for l in out.splitlines() if "npm run test" in l)
        self.assertEqual(line.count("`"), 2)
        for ch in ("\u0007", "\u202e", "\u2066", "\u200b"):
            self.assertNotIn(ch, out)
        self.assertLess(len(line), 200)
        self.assertNotIn("\n## injected", out)
        rule = next(l for l in out.splitlines() if "(check:" in l)
        self.assertEqual(rule.count("`"), 4)


class GuardProfileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(os.path.realpath(tmp.name)) / "plugins" / "data" / "etk"
        self.data.mkdir(parents=True)
        self.env = dict(os.environ, CLAUDE_PLUGIN_DATA=str(self.data))

    def call(self, tool, inp, agent="engineering-team:developer", cwd="/work/proj"):
        payload = {"tool_name": tool, "tool_input": inp, "cwd": cwd, "hook_event_name": "PreToolUse",
                   "agent_type": agent}
        return subprocess.run([sys.executable, str(GUARD)], cwd="/", input=json.dumps(payload), env=self.env,
                              capture_output=True, text=True, timeout=30)

    def blocked(self, cmd, agent="engineering-team:developer") -> bool:
        return self.call("Bash", {"command": cmd}, agent).returncode == 2

    def test_write_tools_into_plugin_data(self):
        target = str(self.data / "projects" / "k" / "profile.json")
        for tool in ("Write", "Edit", "MultiEdit"):
            r = self.call(tool, {"file_path": target})
            self.assertEqual(r.returncode, 2, tool)
            self.assertIn("plugin data dir", r.stderr)
        self.assertEqual(self.call("NotebookEdit", {"notebook_path": str(self.data / "n.ipynb")}).returncode, 2)
        self.assertEqual(self.call("Read", {"file_path": target}).returncode, 0)
        self.assertEqual(self.call("Write", {"file_path": "/work/proj/src/a.py"}).returncode, 0)

    def test_shell_writes_into_plugin_data(self):
        p = self.data / "projects" / "k" / "profile.json"
        for cmd in (f"echo '{{}}' > {p}", f"tee {p} < x", f"rm {p}", f"cp /tmp/x {p}", f"mv {p} /tmp/y",
                    f"cd {self.data} && touch projects/x", f"sed -i s/a/b/ {p}",
                    'echo x > "$CLAUDE_PLUGIN_DATA/projects/k/profile.json"',
                    "echo x > ~/.claude/plugins/data/engineering-team/projects/k/profile.json"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd))
        for cmd in (f"cat {p}", f"cp {p} /tmp/copy.json", f"ls {self.data}"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.blocked(cmd))

    def test_run_records_are_lead_only(self):
        gates = "/work/proj/.etk/runs/20260101-000000-x/gates.json"
        for tool in ("Write", "Edit"):
            self.assertEqual(self.call(tool, {"file_path": gates}).returncode, 2, tool)
        for cmd in (f"echo {{}} > {gates}", "sed -i s/a/b/ .etk/runs/r/gates.json", "rm -rf .etk",
                    "cd .etk/runs && touch x", "echo x > .ETK/runs/r/gates.json", "rm -rf .e*",
                    "echo x > .et?/runs/r/gates.json"):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.blocked(cmd))
        self.assertFalse(self.blocked("cat .etk/runs/r/gates.json"))
        self.assertFalse(self.blocked("rm -rf build/*"))
        self.assertEqual(self.call("Read", {"file_path": gates}).returncode, 0)

    def test_profile_and_ledger_mutations(self):
        etk = "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh"
        for cmd in (f'sh "{etk}" profile set release.push \'"auto"\' --data /x/plugins/data/e',
                    f'sh "{etk}" profile --data /x/plugins/data/e unset release.push',
                    f'sh "{etk}" profile confirm --data /d', f'sh "{etk}" profile remember "x" --data /d',
                    "python3 scripts/etk_profile.py set a b --data /d", "cd scripts && python3 -m etk_profile set a b",
                    f'sh "{etk}" run authorize push', f'sh "{etk}" run phase ship', f'sh "{etk}" run act deploy',
                    f'sh "{etk}" run decide x', "python3 scripts/etk_run.py authorize push",
                    f"bash -c 'sh {etk} profile set a b'",
                    f'sh "{etk}" exec G3 --type test -- python3 scripts/etk_run.py decide x'):
            with self.subTest(cmd=cmd):
                r = self.call("Bash", {"command": cmd})
                self.assertEqual(r.returncode, 2)
                self.assertIn("only the Lead records workflow profile / release decisions", r.stderr)
        for cmd in (f'sh "{etk}" profile show --brief --data /x/plugins/data/e',
                    f'sh "{etk}" profile path --data /d', f'sh "{etk}" profile detect --data /d',
                    f'sh "{etk}" profile missing --data /d', f'sh "{etk}" run latest', f'sh "{etk}" run check',
                    'grep -rn "profile set" docs/', 'git commit -m "docs: etk.sh profile set and run authorize"'):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.blocked(cmd), cmd)

    def test_main_session_untouched(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "sh etk.sh profile set a b"}, "cwd": "/work/proj"}
        r = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
