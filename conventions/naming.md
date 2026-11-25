# Naming

How to name files, symbols, routes, keys and variables in code you write or change.

Match the surrounding code first. The table is the default when the project is silent.

| Language / thing | Defaults |
|---|---|
| Python | `snake_case` functions, variables, modules; `PascalCase` classes; `UPPER_SNAKE` constants; `_leading` for private |
| JavaScript / TypeScript | `camelCase` variables, functions; `PascalCase` classes, types, interfaces, components; `UPPER_SNAKE` constants |
| JS/TS files | `kebab-case.ts`, or what the framework requires; React components `PascalCase.tsx` |
| PHP | `PascalCase` classes, `camelCase` methods, `UPPER_SNAKE` constants (PSR-1). Variables as the project does: Laravel/Magento often `camelCase`, WordPress `snake_case` |
| Java / Kotlin | `PascalCase` classes; `camelCase` methods, fields; `UPPER_SNAKE` constants; lowercase packages |
| C# | `PascalCase` types, methods, properties, public members; `camelCase` locals, parameters; `_camelCase` private fields; `I` prefix on interfaces |
| Go | `MixedCaps` identifiers, no underscores (files may use `_test.go`, `_linux.go`); capitalized = exported; initialisms all one case (`userID`, `HTTPClient`); short lowercase package names, no `util`/`common` |
| Rust | `snake_case` functions, variables, modules; `PascalCase` types, traits; `SCREAMING_SNAKE` consts, statics |
| Ruby | `snake_case` methods, variables, files; `PascalCase` classes, modules; `UPPER_SNAKE` constants; `?` predicates, `!` dangerous methods |
| SQL | See `database.md` |
| CSS | `kebab-case` classes; BEM (`block__element--modifier`) only if the project uses it |
| Env vars | `UPPER_SNAKE`, prefixed by app or service when shared |
| URLs | `kebab-case` plural nouns (`/order-items/{id}`); see `api.md` |
| JSON keys | Follow the API's existing case. New API with no precedent: the server framework's default (`snake_case` for Django/Rails, `camelCase` for Node/Java/.NET). Never mix in one payload |

## Rules

- Names say intent: `retryDelayMs`, not `d` or `tmp2`.
- Booleans read as questions: `is_active`, `hasAccess`, `canEdit`, `shouldRetry`.
- Functions and methods are verbs: `fetch_orders`, `calculateTotal`. Classes are nouns.
- No abbreviations except well-known ones (`id`, `url`, `http`, `db`, `config`).
- No type prefixes or Hungarian notation (`strName`, `arrItems`). C# `I` interfaces excepted.
- Use the project's domain vocabulary. If the code says `customer`, do not add `client`.
- One concept, one name across layers: the same thing is not `user` here and `account` there.
- Units in names when not typed: `timeout_seconds`, `sizeBytes`.
- Test names describe behaviour: `test_rejects_expired_token`, `returns 404 when order is missing`.
- Do not rename existing symbols unless the task asks for it.

Sources: PEP 8 https://peps.python.org/pep-0008/ · PSR-1 https://www.php-fig.org/psr/psr-1/ · Google TypeScript Style https://google.github.io/styleguide/tsguide.html · Google Java Style https://google.github.io/styleguide/javaguide.html · Kotlin https://kotlinlang.org/docs/coding-conventions.html · .NET naming https://learn.microsoft.com/en-us/dotnet/standard/design-guidelines/naming-guidelines · Effective Go https://go.dev/doc/effective_go · Rust API Guidelines https://rust-lang.github.io/api-guidelines/naming.html · Ruby Style Guide https://rubystyle.guide/ · BEM https://getbem.com/naming
