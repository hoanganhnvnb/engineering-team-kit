# Style

How to format and shape code you write or change, in any language.

Match the surrounding code first. Never reformat untouched code.

## Formatter and linter

- Use the project's formatter and linter config. Run them on changed files only.
- Respect `.editorconfig` (indent, line endings, final newline, charset).
- If the formatter would rewrite lines you did not change, format only your hunks or skip it.
- With no config, use the language default:

| Language | Default |
|---|---|
| Python | PEP 8 (79 cols); if the project uses Black or `ruff format`, their 88 |
| JavaScript / TypeScript | Prettier defaults, ESLint recommended |
| PHP | PSR-12 |
| Go | `gofmt` (always; not optional) |
| Rust | `rustfmt` |
| Java | Google Java Style |
| C# | .NET coding conventions |
| Kotlin | Kotlin official coding conventions |

## Shape

- Small functions with one job. Split when a function needs a section comment.
- Early returns and guard clauses over deep nesting.
- No dead code, unused imports, or commented-out code. Version control keeps history.
- No magic numbers or strings: use named constants. `0`, `1`, `""` in obvious use are fine.
- Comments explain why, not what. Update or delete comments your change makes wrong.
- Imports ordered and grouped as the formatter or linter does.
- Types on public APIs when the project uses them (Python hints, explicit types on exported
  TS functions, PHP signature types). Do not add types to untouched code or introduce them
  to an untyped codebase.
- Prefer the standard library and existing project helpers over new code.
- No new dependency without need. If one is needed, say why in the PR; see `security.md`.

## Diffs

- Keep diffs minimal: only lines the task needs.
- No drive-by reformatting, renaming, or reordering. Propose it as a separate change.
- Keep the file's existing quote style, indent, and brace placement.
- Do not mix formatting-only and behaviour changes in one commit.

Sources: PEP 8 https://peps.python.org/pep-0008/ · Black https://black.readthedocs.io/en/stable/the_black_code_style/current_style.html · Prettier https://prettier.io/docs/en/options.html · ESLint https://eslint.org/docs/latest/rules/ · PSR-12 https://www.php-fig.org/psr/psr-12/ · gofmt https://pkg.go.dev/cmd/gofmt · rustfmt https://github.com/rust-lang/rustfmt · Google Java Style https://google.github.io/styleguide/javaguide.html · C# conventions https://learn.microsoft.com/en-us/dotnet/csharp/fundamentals/coding-style/coding-conventions · Kotlin https://kotlinlang.org/docs/coding-conventions.html · EditorConfig https://editorconfig.org/
