---
type: regex
target: {source: file, path: app/repo.py}
pattern: 'ESCAPE\s+["'']|instr\s*\('
flags: i
---
LIKE wildcards in the term are handled: either an `ESCAPE` clause (so `%` and `_` in the
term match literally) or no LIKE at all (`instr`). Otherwise a term of "%" matches every user.
