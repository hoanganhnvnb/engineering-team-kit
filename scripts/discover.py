#!/usr/bin/env python3
"""Print a compact snapshot of the current project for the Lead agent.

Read-only. Standard library only. Meant to be injected into a skill with
!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover` so the Lead starts from
facts instead of guesses. Output is markdown, kept short on purpose: it lists
*where* things are, the agent reads what it actually needs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_LIST = 15
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", ".tox", "target", ".turbo", ".cache",
    "coverage", ".etk", ".claude/worktrees",
}


def run(cmd: list[str], cwd: Path, timeout: int = 10) -> str:
    out = run_checked(cmd, cwd, timeout)
    return out or ""


def run_checked(cmd: list[str], cwd: Path, timeout: int = 10) -> str | None:
    """stdout on success, None if the command failed or timed out (unknown != empty)."""
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def find_root(start: Path) -> Path:
    top = run(["git", "rev-parse", "--show-toplevel"], start)
    return Path(top) if top else start


def walk(root: Path, max_depth: int):
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath).relative_to(root)
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and (here / d).as_posix() not in SKIP_DIRS
        ]
        if len(Path(dirpath).parts) - root_depth >= max_depth:
            dirnames[:] = []
        yield Path(dirpath), filenames


def rel(p: Path, root: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return str(p)


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def frontmatter(p: Path) -> dict[str, str]:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def short(s: str, n: int = 110) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def section(title: str, lines: list[str]) -> None:
    if not lines:
        return
    print(f"\n### {title}")
    for line in lines[:MAX_LIST]:
        print(f"- {line}")
    if len(lines) > MAX_LIST:
        print(f"- … {len(lines) - MAX_LIST} more")


def hard_checks(root: Path, names: set[str], pkg, ci: list[str]) -> list[str]:
    """Which automatic constraints exist, with the file that proves each. Root + one level only."""
    top = sorted(n for n in names if n.count("/") <= 1)

    def find(pattern: str) -> list[str]:
        return [n for n in top if re.search(pattern, n.rsplit("/", 1)[-1])]

    def text(n: str) -> str:
        try:
            return (root / n).read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            return ""

    def has(n: str, marker: str) -> list[str]:
        return [n] if n in names and marker in text(n) else []

    pkg = pkg if isinstance(pkg, dict) else {}
    pyproj = "pyproject.toml"
    eslint = find(r"^(eslint\.config\.|\.eslintrc)") + (["package.json (eslintConfig)"] if "eslintConfig" in pkg else [])
    ruff = find(r"^\.?ruff\.toml$") + has(pyproj, "[tool.ruff")
    golangci = find(r"^\.golangci\.")
    lint = (eslint + find(r"^biome\.jsonc?$") + ruff + find(r"^\.flake8$") + has("setup.cfg", "[flake8]")
            + has("tox.ini", "[flake8]") + golangci + find(r"^phpstan(\.dist)?\.neon") + find(r"^psalm\.xml$")
            + find(r"^\.rubocop\.yml$") + find(r"^\.theme-check\.yml$")
            + find(r"^(\.stylelintrc|stylelint\.config\.)") + (["package.json (stylelint)"] if "stylelint" in pkg else []))
    compiled = [f"{n} (compiler)" for n in ("go.mod", "Cargo.toml") if n in names]
    types = (find(r"^tsconfig.*\.json$") + find(r"^mypy\.ini$") + has(pyproj, "[tool.mypy") + has("setup.cfg", "[mypy]")
             + find(r"^pyrightconfig\.json$") + has(pyproj, "[tool.pyright") + compiled)
    fmt = (find(r"^(\.prettierrc|prettier\.config\.)") + (["package.json (prettier)"] if "prettier" in pkg else [])
           + has(pyproj, "[tool.black") + [f"{r} (ruff format)" for r in ruff[:1]]
           + [f"{n} (gofmt)" for n in ("go.mod",) if n in names] + [f"{n} (rustfmt)" for n in ("Cargo.toml",) if n in names])
    # tests: a test dir/file anywhere in the walked list, or a declared test script
    tests = [n for n in sorted(names) if re.search(r"(^|/)(tests?|__tests__|spec)/", n)
             or re.search(r"(_test\.go|\.(test|spec)\.[a-z]+|(^|/)test_[^/]*\.py)$", n)][:1]
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    script = str(scripts.get("test", ""))
    if script and "no test specified" not in script:
        tests.append("package.json (scripts.test)")
    comp = read_json(root / "composer.json")
    if isinstance(comp, dict) and isinstance(comp.get("scripts"), dict) and comp["scripts"].get("test"):
        tests.append("composer.json (scripts.test)")
    if "Makefile" in names and re.search(r"^test[a-zA-Z0-9_-]*:", text("Makefile"), re.M):
        tests.append("Makefile (test target)")
    hooks = (find(r"^\.pre-commit-config\.yaml$") + [n for n in top if n.startswith(".husky/")][:1]
             + find(r"^lefthook\.ya?ml$") + find(r"^\.lintstagedrc") + (["package.json (lint-staged)"] if "lint-staged" in pkg else []))
    bounds = find(r"^\.dependency-cruiser\.") + find(r"^\.importlinter$") + has("setup.cfg", "[importlinter]") + has(pyproj, "[tool.importlinter")
    for n in top:
        if re.search(r"^(eslint\.config\.|\.eslintrc)", n.rsplit("/", 1)[-1]) and re.search(
                r"no-restricted-imports|import/no-restricted-paths|boundaries/", text(n)):
            bounds.append(f"{n} (import rules)")
    bounds += [f"{n} (depguard)" for n in golangci if "depguard" in text(n)]

    cats = [("lint", lint), ("types", types), ("format", fmt), ("tests", tests), ("ci", ci),
            ("pre-commit", hooks), ("boundaries", bounds)]
    lines = []
    for label, proof in cats:
        proof = list(dict.fromkeys(proof))
        lines.append(f"{label}: ✓ " + ", ".join(f"`{x}`" for x in proof[:3]) if proof else f"{label}: ✗")
    have = {label: bool(proof) for label, proof in cats}
    if (not have["lint"] and not have["types"]) or not have["tests"] or not have["ci"]:
        missing = [l for l in ("lint", "types", "tests", "ci") if not have[l]]
        lines.append("⚠ weak hard constraints: agents copy whatever patterns exist; recommend adding "
                     f"{', '.join(missing)} before large features")
    else:
        lines.append("constraints: ok")
    return lines


def main() -> int:
    root = find_root(Path.cwd())
    print(f"## Project snapshot\n\n- root: `{root}`")

    # Git state -- the Lead must know about uncommitted work before touching anything.
    branch = run(["git", "branch", "--show-current"], root)
    if branch or run(["git", "rev-parse", "--git-dir"], root):
        raw = run_checked(["git", "status", "--porcelain"], root, timeout=30)
        if raw is None:
            print(f"- git: branch `{branch or '(detached)'}`, uncommitted changes UNKNOWN (git status failed or "
                  "timed out). Run `git status` yourself before touching files")
            status = []
        else:
            status = raw.splitlines()
            print(f"- git: branch `{branch or '(detached)'}`, {len(status)} uncommitted path(s)")
        last = run(["git", "log", "-1", "--format=%h %s"], root)
        if last:
            print(f"- last commit: {short(last, 90)}")
        if status:
            section("Uncommitted changes (do not overwrite)", [f"`{s}`" for s in status])
    else:
        print("- git: not a repository (no branch/worktree isolation available)")

    files: list[Path] = []
    for d, names in walk(root, 4):
        files.extend(d / n for n in names)
    names = {rel(f, root) for f in files}

    # Instructions the project already gives to agents. These win over ETK defaults.
    instr = sorted(
        rel(f, root) for f in files
        if f.name in {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "GEMINI.md", ".cursorrules",
                      "copilot-instructions.md"}
        or "/.cursor/rules/" in f"/{rel(f, root)}"
        or rel(f, root).startswith(".claude/rules/")
    )
    section("Project instructions (read before planning)", [f"`{p}`" for p in instr])

    skills, agents = [], []
    for f in files:
        r = rel(f, root)
        if f.name == "SKILL.md" and "/skills/" in f"/{r}":
            fm = frontmatter(f)
            skills.append(f"`{fm.get('name') or f.parent.name}` — {short(fm.get('description', ''))} (`{r}`)")
        elif r.startswith(".claude/agents/") and f.suffix == ".md":
            fm = frontmatter(f)
            agents.append(f"`{fm.get('name') or f.stem}` — {short(fm.get('description', ''))}")
    section("Project skills", sorted(skills))
    section("Project agents", sorted(agents))

    docs = sorted(
        r for r in names
        if re.search(r"(^|/)(ARCHITECTURE|CONTRIBUTING|DESIGN|CONVENTIONS|STYLEGUIDE)\.md$", r, re.I)
        or r.startswith("docs/agent/")
        or re.search(r"(^|/)(adr|adrs|decisions)/", r, re.I)
    )
    section("Architecture / decision docs", [f"`{d}`" for d in docs])

    # Stack + commands. We only report what is declared; nothing is executed.
    stack, cmds = [], []
    pkg = read_json(root / "package.json")
    if isinstance(pkg, dict):
        pm = "npm"
        for lock, name in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
            if (root / lock).exists():
                pm = name
        deps = {k: v for key in ("dependencies", "devDependencies")
                if isinstance(pkg.get(key), dict) for k, v in pkg[key].items()}
        known = [d for d in ("next", "react", "vue", "nuxt", "svelte", "@remix-run/react", "@shopify/polaris",
                             "@shopify/shopify-app-remix", "@shopify/hydrogen", "express", "vitest", "jest",
                             "@playwright/test", "cypress", "typescript", "eslint") if d in deps]
        stack.append(f"node ({pm})" + (f": {', '.join(known)}" if known else ""))
        for k, v in (pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}).items():
            if re.search(r"test|lint|type|check|build|e2e|format", k):
                cmds.append(f"`{pm} run {k}` → {short(str(v), 70)}")
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
        py = (root / "pyproject.toml").read_text(errors="replace") if (root / "pyproject.toml").exists() else ""
        stack.append("python" + (" (django)" if "django" in py.lower() or (root / "manage.py").exists() else ""))
        if "pytest" in py or (root / "pytest.ini").exists() or (root / "conftest.py").exists():
            cmds.append("`pytest`")
        if (root / "manage.py").exists():
            cmds.append("`python manage.py test`")
    for marker, label, cmd in (
        ("go.mod", "go", "`go test ./...`"),
        ("Cargo.toml", "rust", "`cargo test`"),
        ("composer.json", "php (composer)", None),
        ("Gemfile", "ruby", None),
        ("pom.xml", "java (maven)", "`mvn test`"),
        ("build.gradle", "java/kotlin (gradle)", "`./gradlew test`"),
    ):
        if (root / marker).exists():
            stack.append(label)
            if cmd:
                cmds.append(cmd)
    comp = read_json(root / "composer.json")
    if isinstance(comp, dict):
        for k in (comp.get("scripts") if isinstance(comp.get("scripts"), dict) else {}):
            if re.search(r"test|lint|stan|check", k):
                cmds.append(f"`composer {k}`")
    if (root / "Makefile").exists():
        targets = re.findall(r"^([a-zA-Z0-9_-]+):", (root / "Makefile").read_text(errors="replace"), re.M)
        useful = [t for t in targets if re.search(r"test|lint|check|build|e2e", t)]
        cmds.extend(f"`make {t}`" for t in useful[:6])

    # Shopify detection: only flag it when there is real evidence.
    shopify = []
    if any(n in names for n in ("shopify.app.toml", "shopify.web.toml")) or any(n.startswith("shopify.app.") and n.endswith(".toml") for n in names):
        shopify.append("Shopify app (shopify.app.toml)")
    if "layout/theme.liquid" in names or ("config/settings_schema.json" in names and any(n.startswith("sections/") for n in names)):
        shopify.append("Shopify theme (Liquid)")
    if any(n.startswith("extensions/") and n.endswith("shopify.extension.toml") for n in names):
        shopify.append("Shopify extensions")
    if isinstance(pkg, dict) and any(str(k).startswith("@shopify/") for key in ("dependencies", "devDependencies")
                                       if isinstance(pkg.get(key), dict) for k in pkg[key]):
        shopify.append("@shopify/* packages")

    ui = any(re.search(r"\.(tsx|jsx|vue|svelte|liquid|html|css|scss)$", n) for n in names)
    section("Stack", stack + ([f"UI files present: yes"] if ui else []))
    section("Declared test/build commands (verify before trusting)", cmds)
    if shopify:
        section("Shopify signals", shopify + ["→ use the installed Shopify skills/plugins for API, Liquid, Polaris details"])

    ci = sorted(r for r in names if r.startswith(".github/workflows/") or r in {".gitlab-ci.yml", "bitbucket-pipelines.yml", ".circleci/config.yml"})
    section("CI config (shows the real gate commands)", [f"`{c}`" for c in ci])

    try:
        checks = hard_checks(root, names, pkg, ci)
    except Exception as exc:  # one odd config file shouldn't cost the rest of the snapshot
        checks = [f"(couldn't read: {exc})"]
    section("Hard checks (what the project enforces automatically)", checks)

    cfg_path = root / ".claude" / "engineering-team.json"
    cfg = read_json(cfg_path)
    if cfg is not None:
        print("\n### ETK project config (`.claude/engineering-team.json`)")
        print("```json\n" + json.dumps(cfg, indent=2)[:1500] + "\n```")
        rules = cfg.get("rules") if isinstance(cfg, dict) else None
        rl = []
        for r in rules if isinstance(rules, list) else []:
            if isinstance(r, dict) and r.get("rule"):
                paths = r.get("paths")
                paths = ", ".join(map(str, paths)) if isinstance(paths, list) else str(paths or "*")
                rl.append(f"`{paths}` → {short(str(r['rule']), 160)}" + (f" (check: `{r['check']}`)" if r.get("check") else ""))
        section("Path-scoped rules", rl)

    runs = sorted((root / ".etk" / "runs").glob("*/gates.json")) if (root / ".etk" / "runs").exists() else []
    if runs:
        print(f"\n- previous ETK run: `{rel(runs[-1].parent, root)}`")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the skill that injects us
        print(f"(discover.py failed: {exc}; do discovery manually)")
        sys.exit(0)
