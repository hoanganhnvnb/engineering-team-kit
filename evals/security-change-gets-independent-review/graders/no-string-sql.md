---
type: regex
target: {source: file, path: app/repo.py}
pattern: '\bf"[^"\n]*\b(SELECT|WHERE|LIKE)\b[^"\n]*\{|\bf''[^''\n]*\b(SELECT|WHERE|LIKE)\b[^''\n]*\{|"[^"\n]*\b(SELECT|WHERE|LIKE)\b[^"\n]*"\s*(\+|%\s*[(\w]|\.format\()|''[^''\n]*\b(SELECT|WHERE|LIKE)\b[^''\n]*''\s*(\+|%\s*[(\w]|\.format\()'
flags: i
match: not_contains
---
No user input is formatted into the SQL text (f-string, concatenation, `%` or `.format`).
Building the bound parameter (e.g. `"%" + term + "%"`) is fine.
