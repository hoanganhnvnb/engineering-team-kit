"""Workflow profile (scripts/etk_profile.py), its discover block, and the guard rules around it."""
from __future__ import annotations

import json
import os
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
        self.assertEqual(etk_profile.redact_remote("https://h.com/o/r\u202e.git"), "https://h.com/o/r .git")

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
        self.assertEqual(stored["project"]["remote"], "https://github.com/o/r.git")
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
        self.assertEqual(prof["release"], {"push": "auto", "extra": True, "integrate": "pr"})
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
                         ["vcs.type", "branches.model", "release.push", "release.integrate", "commit.style", "deploy"])
        for path, value in (("vcs.type", "git"), ("branches.model", "feature"), ("release.push", "confirm"),
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

    def test_profile_is_bound_to_checkout_and_push_url(self):
        d = self.repo(remote="https://github.com/victim/prod.git")
        for path, value in (("vcs.type", "git"), ("branches.model", "trunk"), ("release.push", "auto"),
                            ("release.commit", "auto"), ("release.integrate", "none"), ("commit.style", "project"),
                            ("deploy.none", "true")):
            self.ok(d, "set", path, value)
        self.ok(d, "confirm")
        stored = json.loads(self.ok(d, "show", "--json"))["project"]
        self.assertEqual((stored["root"], stored["push"]), (str(d), "https://github.com/victim/prod.git"))
        self.assertEqual(self.ok(d, "missing"), "")
        self.assertNotIn("re-confirm", self.ok(d, "show", "--brief"))
        # repository code redirects the push: the stored `auto` values stop counting
        self.git(d, "config", "remote.origin.pushurl", "https://user:pw@evil.example/x.git?token=SECRET")
        lines = self.ok(d, "show", "--brief").splitlines()
        self.assertEqual(lines[0], etk_profile.RECONFIRM)
        self.assertLessEqual(len(lines), 5)
        self.assertNotIn("push auto", "\n".join(lines))
        self.assertEqual(self.ok(d, "missing").splitlines(), [etk_profile.RECONFIRM, "release.push"])
        out = DiscoverProfileTests.discover(self, d, "--data", str(self.data))
        self.assertIn("profile from a different checkout/remote; re-confirm", out)
        self.ok(d, "set", "commit.style", "conventional")  # an edit doesn't re-approve the binding
        self.assertIn(etk_profile.RECONFIRM, self.ok(d, "missing"))
        self.ok(d, "confirm")  # the developer looked at it again here
        self.assertEqual(self.ok(d, "missing"), "")
        stored = json.loads(self.ok(d, "show", "--json"))["project"]
        self.assertEqual(stored["push"], "https://evil.example/x.git")
        # another checkout that claims the same origin finds the same file but not its `auto`s
        other = self.repo("other", "git@github.com:victim/prod.git")
        self.assertEqual(self.ok(other, "path"), self.ok(d, "path"))
        self.assertEqual(self.ok(other, "show", "--brief").splitlines()[0], etk_profile.RECONFIRM)
        self.assertIn("release.push", self.ok(other, "missing").splitlines())

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
        self.assertIn("- missing: vcs.type, branches.model, release.push, release.integrate, commit.style, deploy "
                      "→ onboard (workflows/profile.md)", out)
        for path, value in (("vcs.type", "git"), ("branches.model", "trunk"), ("release.push", "auto"),
                            ("release.integrate", "none"), ("commit.style", "project"), ("deploy.none", "true")):
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
