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
        self.assertEqual(SKILLS, {"build", "fix", "review", "test", "improve-ui"})

    def test_required_agents_exist(self):
        self.assertEqual(AGENTS, {"developer", "code-reviewer", "qa-engineer", "ux-reviewer"})

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
                self.assertNotIn("hooks", fm, "hooks are ignored for plugin agents; use hooks/hooks.json")
                self.assertNotIn("permissionMode", fm, "ignored for plugin agents")

    def test_reviewers_are_read_only(self):
        for name in ("code-reviewer", "ux-reviewer"):
            tools = frontmatter(ROOT / "agents" / f"{name}.md").get("disallowedTools", "")
            for t in ("Edit", "Write"):
                self.assertIn(t, tools, f"{name} must not be able to {t}")

    def test_skills_are_user_commands(self):
        for name in SKILLS:
            fm = frontmatter(ROOT / "skills" / name / "SKILL.md")
            with self.subTest(skill=name):
                self.assertEqual(fm.get("name"), name)
                self.assertTrue(fm.get("description"))
                self.assertTrue(fm.get("argument-hint"))
                self.assertEqual(fm.get("disable-model-invocation"), "true",
                                 "team workflows are heavy; only the user should start them")

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
