Overlays are copied on top of a fixture *after* its baseline commit, so they show up
as uncommitted work (e.g. a change to review). Used with `tests/e2e/run.py --overlay`.

- `sqli-search/`: adds `search_by_name` to the python fixture with string-formatted SQL.
- `stale-readme/`: a README for the node fixture with wrong function names, scripts and claims, to test `/engineering-team:readme`.
