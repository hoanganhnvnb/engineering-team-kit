# Database

How to name schema objects, write migrations and queries. Match what the project already does first.

## Naming

- `snake_case` everywhere.
- Tables plural (`orders`).
- Columns singular. Primary key `id`; ID type (integer, UUID, ULID) as the project
  does.
- Foreign key column `<singular>_id` (`customer_id`).
- Index `idx_<table>_<cols>`, unique `uq_<table>_<cols>`, FK constraint
  `fk_<table>_<ref_table>`.
- Booleans `is_` / `has_` (`is_active`, `has_invoice`).
- Timestamps `created_at`, `updated_at`, stored in UTC.

## Migrations

- Every schema change is a migration in the project's tool. No manual DDL.
- Forward-only in shared environments; write a down/rollback when practical.
- Never edit a migration that has been applied anywhere shared; add a new one.
- One concern per migration. Keep schema and large data changes separate.

## Zero-downtime changes (expand, migrate, contract)

1. Expand: add the new nullable column or table; old code keeps working.
2. Migrate: write to both, backfill, then switch reads to the new shape.
3. Contract: drop the old column in a later release, after nothing reads it.

- Backfill large tables in batches with a limit and pause; never one giant UPDATE.
- Add NOT NULL, defaults and constraints in ways that avoid long table locks.

## Queries

- Parameterized queries or the ORM only. Never build SQL by string concatenation.
- Wrap multi-step writes in a transaction; keep transactions short.
- Add an index for each new query pattern; check the plan (`EXPLAIN`) on real-sized data.
- Avoid N+1 queries; select only needed columns on hot paths.

## Data safety

- Soft delete (`deleted_at`) only if the project already uses it.
- No destructive data operations (DROP, TRUNCATE, mass DELETE/UPDATE) without explicit
  user permission in this conversation.
- Agents never run migrations against shared, staging or production databases. Locally
  or in a disposable test database only when the brief allows it (see `testing-errors.md`);
  a human applies them elsewhere.

Sources: Parallel Change (expand/contract) https://martinfowler.com/bliki/ParallelChange.html ;
OWASP SQL Injection Prevention
https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
