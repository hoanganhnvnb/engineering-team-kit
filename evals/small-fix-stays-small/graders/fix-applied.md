---
type: regex
target: {source: file, path: src/cart.js}
pattern: 'qty\s*\+=|qty\s*=\s*existing\.qty\s*\+|existing\.qty\s*\+\s*qty'
---
The quantity is added, not replaced. Also makes sure the run did real work: a run that
stops at turn 0 passes the "no delegation" grader but fails this one.
