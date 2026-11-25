#!/usr/bin/env python3
"""Print a compact snapshot of the current project for the Lead agent.

Read-only. Standard library only. Meant to be injected into a skill with
!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/etk.sh" discover` so the Lead starts from
facts instead of guesses. Output is markdown, kept short on purpose: it lists
*where* things are, the agent reads what it actually needs.
"""
from __future__ import annotations

import functools
import json
import os
import re
import datetime as dt
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import etk_profile  # noqa: E402  (same directory; imported, not spawned)

MAX_LIST = 15
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", ".tox", "target", ".turbo", ".cache",
    "coverage", ".etk", ".claude/worktrees",
}
# Read-only git: never start an fsmonitor daemon, run a hook or take an optional lock.
GIT = ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "--no-optional-locks"]
# Hashing a work-tree file for `status` runs the clean filter that .gitattributes names. With git
# 2.40+ the attributes can come from the empty tree instead, so no repository filter applies.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
# The newest run date accepted; must match etk_run.latest_run (a planted future-dated run is skipped).
FUTURE_SLACK = dt.timedelta(days=1)
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


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


def git_version(cwd: Path) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)", run(["git", "--version"], cwd))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


@functools.lru_cache(maxsize=None)
def safe_git(root: Path) -> list[str] | None:
    """The git prefix for commands that may hash work-tree files (status, ls-files), or None when
    git is too old to ignore repository attributes and the repository configures a filter or
    textconv program: then those commands could run repository code and are skipped."""
    if git_version(root) >= (2, 40):
        return [*GIT, f"--attr-source={EMPTY_TREE}"]
    if run(GIT + ["config", "--get-regexp", r"^filter\.|textconv"], root):
        return None
    return list(GIT)


def find_root(start: Path) -> Path:
    top = run(GIT + ["rev-parse", "--show-toplevel"], start)
    return Path(top) if top else start


def git_files(root: Path) -> list[str] | None:
    """Tracked + untracked-not-ignored paths, or None when this isn't a git work tree."""
    try:
        out = subprocess.run((safe_git(root) or GIT) + ["ls-files", "-co", "--exclude-standard", "-z"], cwd=root,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return [n for n in out.stdout.split("\0") if n]


def walk(root: Path, max_depth: int):
    """Yield (dir, filenames) down to max_depth.

    Inside git the file list comes from git, so ignore rules decide what is skipped and a
    tracked `skills/build/` is never mistaken for build output. Without git, SKIP_DIRS names
    are skipped at any depth, except directly under a `skills/` directory.
    """
    listed = git_files(root)
    if listed is not None:
        by_dir: dict[str, list[str]] = {}
        for n in listed:
            if n.startswith((".etk/", ".claude/worktrees/")) or not (root / n).is_file():
                continue
            d, _, f = n.rpartition("/")
            if d and d.count("/") + 1 > max_depth:
                continue
            by_dir.setdefault(d, []).append(f)
        for d in sorted(by_dir):
            yield root / d, by_dir[d]
        return
    root_depth = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath).relative_to(root)
        dirnames[:] = [
            d for d in dirnames
            if (here / d).as_posix() not in SKIP_DIRS and (d not in SKIP_DIRS or here.name == "skills")
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


def clean(s, n: int = 80) -> str:
    """Repository text shown inside the snapshot: no control, zero-width or bidi characters and no
    backticks, bounded length."""
    return short(re.sub("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069`]", " ", str(s)), n)


def data_arg(argv: list[str]) -> str | None:
    for i, a in enumerate(argv):
        if a == "--data" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--data="):
            return a.split("=", 1)[1]
    return None


def profile_block(root: Path, raw_data: str | None) -> None:
    """The developer's workflow profile (kept in the plugin data dir, never in the repo)."""
    try:
        lines, missing, _ = etk_profile.snapshot(raw_data, root)
    except etk_profile.UsageError:
        print("- profile: unknown here; run `etk.sh profile show --data <plugin data dir>`")
        return
    unconfirmed = any(l.startswith("file: ") and l.endswith("(unconfirmed)") for l in lines)
    if missing:
        lines = [f"missing: {', '.join(missing)} → onboard (workflows/profile.md)"]
    else:
        mem = [l for l in lines if l.startswith("memory: ")]
        lines = [l for l in lines if not l.startswith(("file: ", "memory: "))][:3]
        if mem and lines:
            lines[-1] += f" · {mem[0]}"
    if unconfirmed and lines:  # the developer never reviewed it: say so even in the short form
        lines[-1] += " · (unconfirmed)"
    print("\n### Workflow profile")
    for line in lines:
        print(f"- {line}")


def previous_run(root: Path) -> str | None:
    """Newest real run dir. A repo can commit `.etk/runs/<future-date>-x/` or symlink it elsewhere: skipped."""
    etk, runs = root / ".etk", root / ".etk" / "runs"
    if etk.is_symlink() or runs.is_symlink() or not runs.is_dir():
        return None
    out = run((safe_git(root) or GIT) + ["ls-files", "-z", "--", ".etk"], root)
    tracked = {n.split("/")[2] for n in out.split("\0") if n.count("/") >= 2}
    limit = dt.datetime.now() + FUTURE_SLACK
    best = None
    for d in sorted(runs.iterdir()):
        m = re.match(r"^(\d{8}-\d{6})", d.name)
        if not m or d.is_symlink() or d.name in tracked:
            continue
        try:
            when = dt.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        gates = d / "gates.json"
        if when <= limit and gates.is_file() and not gates.is_symlink():
            best = d
    return rel(best, root) if best else None


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
    tests = [n for n in sorted(names)
             if re.search(r"(^|/)(tests?|spec)/.*\.(py|rb|php|js|jsx|ts|tsx|go|rs|java|kt|cs|sh)$", n)
             or re.search(r"(^|/)__tests__/[^/]+\.[a-z]+$", n)
             or re.search(r"(_test\.[a-z]+|\.(test|spec)\.[a-z]+|(^|/)test_[^/]*\.py)$", n)][:1]
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


CONVENTION_TOPICS = {"git", "naming", "style", "api", "database", "versioning", "testing-errors", "security",
                     "docs-review", "ui"}


def conventions_line(root: Path) -> str | None:
    """One line pointing at the conventions index, minus what the project switched off.

    `conventions.extra` may only name files inside the project, so a repo can add its own
    guide but can't point agents at files elsewhere on the machine.
    """
    index = PLUGIN_ROOT / "conventions" / "README.md"
    if not index.is_file():
        return None
    cfg = read_json(root / ".claude" / "engineering-team.json")
    conv = cfg.get("conventions") if isinstance(cfg, dict) else None
    conv = conv if isinstance(conv, dict) else {}
    disable = {str(x) for x in conv.get("disable") or [] if isinstance(x, str)} \
        if isinstance(conv.get("disable"), list) else set()
    if "all" in disable:
        return None
    line = f"- Conventions: {index}"
    off = sorted(disable & CONVENTION_TOPICS)
    if off:
        line += f" (skip: {', '.join(off)})"
    extra = []
    real_root = root.resolve()
    for x in conv.get("extra") or [] if isinstance(conv.get("extra"), list) else []:
        if not isinstance(x, str) or not x or Path(x).is_absolute():
            continue
        target = (root / x).resolve()
        if target.is_relative_to(real_root) and target.is_file():
            extra.append(clean(x))
        if len(extra) == 5:
            break
    if extra:
        line += f"; project: {', '.join(extra)}"
    return line


def main() -> int:
    root = find_root(Path.cwd())
    print(f"## Project snapshot\n\n- root: `{root}`")
    line = conventions_line(root)
    if line:
        print(line)

    # Git state -- the Lead must know about uncommitted work before touching anything.
    branch = run(GIT + ["branch", "--show-current"], root)
    if branch or run(GIT + ["rev-parse", "--git-dir"], root):
        sgit = safe_git(root)
        raw = run_checked(sgit + ["status", "--porcelain"], root, timeout=30) if sgit else None
        if raw is None:
            why = "git status failed or timed out" if sgit else \
                "skipped: the repository configures a filter/textconv program and this git can't ignore it"
            print(f"- git: branch `{branch or '(detached)'}`, uncommitted changes UNKNOWN ({why}). "
                  "Run `git status` yourself before touching files")
            status = []
        else:
            status = raw.splitlines()
            print(f"- git: branch `{branch or '(detached)'}`, {len(status)} uncommitted path(s)")
        last = run(GIT + ["-c", "log.showSignature=false", "log", "-1", "--format=%h %s"], root)
        if last:
            print(f"- last commit: {short(last, 90)}")
        if status:
            section("Uncommitted changes (do not overwrite)", [f"`{s}`" for s in status])
    else:
        print("- git: not a repository (no branch/worktree isolation available)")
    profile_block(root, data_arg(sys.argv[1:]))

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
                cmds.append(f"`{pm} run {clean(k)}` → {clean(v, 70)}")
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
                cmds.append(f"`composer {clean(k)}`")
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
                rl.append(f"`{paths}` → {short(str(r['rule']), 160)}" + (f" (check: `{clean(r['check'])}`)" if r.get("check") else ""))
        section("Path-scoped rules", rl)

    prev = previous_run(root)
    if prev:
        print(f"\n- previous ETK run: `{prev}`")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break the skill that injects us
        print(f"(discover.py failed: {exc}; do discovery manually)")
        sys.exit(0)
