"""Structural checks on the plugin itself. Cheap, run on every change.

Prose drifts; these catch the drift: a skill pointing at a file that was renamed,
an agent name that doesn't exist, manifests disagreeing on the version.
"""
from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
MARKET = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
NAME = PLUGIN["name"]
AGENTS = {p.stem for p in (ROOT / "agents").glob("*.md")}
SKILLS = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
PROSE = [p for d in ("skills", "agents", "workflows", "quality") for p in (ROOT / d).rglob("*.md")]


def frontmatter(path: Path) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path} has no frontmatter"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


class PluginStructure(unittest.TestCase):
    def test_required_commands_exist(self):
        self.assertEqual(SKILLS, {"build", "fix", "review", "test", "improve-ui", "retro", "team"})

    def test_required_agents_exist(self):
        self.assertEqual(AGENTS, {"developer", "code-reviewer", "qa-engineer", "ux-reviewer", "scout", "tech-writer"})

    def test_model_tiering(self):
        """Cheap models for mechanical work, the strongest for judgement and writing."""
        want = {"scout": "haiku", "qa-engineer": "sonnet", "code-reviewer": "opus", "tech-writer": "opus",
                "developer": "inherit", "ux-reviewer": "inherit"}
        for name, model in want.items():
            self.assertEqual(frontmatter(ROOT / "agents" / f"{name}.md").get("model"), model, name)

    def test_plugin_root_references_resolve(self):
        for doc in PROSE:
            for ref in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+)", doc.read_text()):
                with self.subTest(doc=doc.name, ref=ref):
                    self.assertTrue((ROOT / ref).exists(), f"{doc.relative_to(ROOT)} → missing {ref}")

    def test_namespaced_names_exist(self):
        for doc in PROSE + [ROOT / "README.md"]:
            if not doc.exists():
                continue
            for ref in re.findall(rf"\b{NAME}:([a-z][\w-]*)", doc.read_text()):
                with self.subTest(doc=doc.name, ref=ref):
                    self.assertIn(ref, AGENTS | SKILLS, f"{doc.relative_to(ROOT)} mentions unknown {NAME}:{ref}")

    def test_agents_are_contained(self):
        for name in AGENTS:
            fm = frontmatter(ROOT / "agents" / f"{name}.md")
            with self.subTest(agent=name):
                self.assertEqual(fm.get("name"), name)
                self.assertTrue(fm.get("description"))
                self.assertIn("Agent", fm.get("disallowedTools", ""), "subagents must not spawn subagents")
                self.assertIn("AskUserQuestion", fm.get("disallowedTools", ""),
                              "only the Lead talks to the user (workflows/decisions.md)")
                self.assertNotIn("hooks", fm, "hooks are ignored for plugin agents; use hooks/hooks.json")
                self.assertNotIn("permissionMode", fm, "ignored for plugin agents")

    def test_reviewers_are_read_only(self):
        for name in ("code-reviewer", "ux-reviewer", "scout"):
            tools = frontmatter(ROOT / "agents" / f"{name}.md").get("disallowedTools", "")
            for t in ("Edit", "Write"):
                self.assertIn(t, tools, f"{name} must not be able to {t}")

    def test_skills_are_user_commands(self):
        """Step commands start only when the user types them; `team` is the one entry the model may pick."""
        team = frontmatter(ROOT / "skills" / "team" / "SKILL.md")
        self.assertNotIn("disable-model-invocation", team)
        self.assertIn("Not for questions", team.get("description", ""))
        for name in SKILLS - {"team"}:
            fm = frontmatter(ROOT / "skills" / name / "SKILL.md")
            with self.subTest(skill=name):
                self.assertEqual(fm.get("name"), name)
                self.assertTrue(fm.get("description"))
                self.assertTrue(fm.get("argument-hint"))
                self.assertEqual(fm.get("disable-model-invocation"), "true",
                                 "team workflows are heavy; only the user should start them")

    def test_parallel_reviewers_get_distinct_id_prefixes(self):
        reviewer = (ROOT / "agents" / "code-reviewer.md").read_text()
        briefs = (ROOT / "workflows" / "briefs.md").read_text()
        findings = (ROOT / "quality" / "findings.md").read_text()
        self.assertIn("ID prefix", briefs)
        self.assertIn("S<cycle>-<n>", reviewer)
        self.assertIn("`S` security pass", " ".join(findings.split()))

    def test_small_diff_self_review_has_a_security_exception(self):
        review = " ".join((ROOT / "skills" / "review" / "SKILL.md").read_text().split())
        self.assertIn("not security-sensitive", review)
        self.assertIn("always get an independent reviewer", review)

    def test_improve_ui_sizing_and_g2_follow_routing_and_gates(self):
        text = " ".join((ROOT / "skills" / "improve-ui" / "SKILL.md").read_text().split())
        self.assertIn("workflows/routing.md", text)
        self.assertIn("quality/gates.md", text)
        self.assertIn("it fills G5", text)

    def test_gates_doc_matches_checker_on_open_mediums(self):
        gates = " ".join((ROOT / "quality" / "gates.md").read_text().split())
        self.assertIn("report-only `review` run, which may finish with open mediums", gates)

    def test_progress_log_counts_match_the_repo(self):
        words = {4: "four", 5: "five", 6: "six", 7: "seven"}
        progress = (ROOT / "docs" / "PROGRESS.md").read_text()
        self.assertIn(f"{len(AGENTS)} subagents", progress)
        self.assertIn(f"all {words[len(SKILLS) - 1]} step skills", progress)
        self.assertNotIn("couldn't execute", progress)
        self.assertIn(f"the {words[len(SKILLS)]} commands", (ROOT / "docs" / "install.md").read_text())

    def test_exec_is_not_pre_approved_by_any_skill(self):
        """`etk.sh exec` runs arbitrary commands; a pre-approval would skip the permission prompt."""
        for name in SKILLS:
            allowed = frontmatter(ROOT / "skills" / name / "SKILL.md").get("allowed-tools", "")
            with self.subTest(skill=name):
                self.assertNotIn("exec", allowed)
                self.assertNotIn("etk_run.py", allowed)

    def test_ci_matches_the_supported_platforms_and_tools(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn('python-version: "3.12"', ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("macos-latest", ci)
        for wrapper in ("scripts/etk.sh", "hooks/run-guard.sh", "evals/run.sh"):
            self.assertIn(f"sh -n {wrapper}", ci)
        built_on = re.search(r"built and tested on (\d+\.\d+\.\d+)", (ROOT / "README.md").read_text())
        self.assertTrue(built_on, "README must say which Claude Code version it was built on")
        self.assertIn(f"@anthropic-ai/claude-code@{built_on.group(1)}", ci)

    def test_docs_state_the_python_minimum_and_the_selftest_command(self):
        for name in ("README.md", "docs/install.md", "docs/limitations.md"):
            text = (ROOT / name).read_text()
            with self.subTest(doc=name):
                self.assertNotIn("3.8", text)
                self.assertRegex(text, r"3\.12\+|≥ 3\.12")
        readme = (ROOT / "README.md").read_text()
        self.assertIn("bash scripts/selftest.sh", readme)
        self.assertNotIn("./scripts/selftest.sh", readme)

    def test_limitations_mention_exec_guard_caveat(self):
        text = " ".join((ROOT / "docs" / "limitations.md").read_text().split())
        self.assertIn("`etk.sh exec` is only as guarded as the guard's wrapper handling", text)

    def test_versions_agree(self):
        entry = next(p for p in MARKET["plugins"] if p["name"] == NAME)
        self.assertEqual(entry.get("version"), PLUGIN["version"])
        self.assertEqual(entry["source"], "./")
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn(f"## {PLUGIN['version']}", changelog, "CHANGELOG needs an entry for the current version")

    def test_hooks_use_plugin_root(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        for groups in hooks["hooks"].values():
            for g in groups:
                for h in g["hooks"]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", h["command"])
                    self.assertNotRegex(h["command"], r"/home/|/Users/", "no absolute paths")

    def test_no_absolute_user_paths_anywhere(self):
        listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                                capture_output=True, text=True).stdout.split()
        for p in (ROOT / f for f in listed):
            if p.is_file() and p.suffix in {".md", ".json", ".py", ".sh"}:
                if p.name == "test_plugin.py":
                    continue
                with self.subTest(file=str(p.relative_to(ROOT))):
                    self.assertNotRegex(p.read_text(errors="ignore"), r"/home/[a-z]+/|/Users/[A-Za-z]+/")


if __name__ == "__main__":
    unittest.main()
