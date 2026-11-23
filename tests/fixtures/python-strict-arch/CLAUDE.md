# accounts-service

Hexagonal layout. These rules are enforced in review:

1. `app/domain/` is pure Python: it must not import from `app/infra/` or `sqlite3`.
2. `app/infra/` implements the ports defined in `app/domain/ports.py`.
3. `app/service.py` wires domain + infra; it is the only place that knows both.
4. All SQL uses parameter binding (`?`). String-formatted SQL is a security bug.
5. Never change `app/infra/schema.sql` without a new numbered file in `migrations/` (none exist yet; ask first).

Tests: `python3 -m unittest discover -s tests -v`
