# Feature map

How to reach and prove each user-facing feature. QA and UX reviewers drive features
from this file, and the team fixes it in the same change when it drifts. Facts only,
checked against the code.

| Feature | How a user reaches it | What proves it works | What usually lies |
|---|---|---|---|
| <name> | <route / command / screen + steps> | <test names, driver script, command + expected output, selectors> | <traps: cached state, feature flag, seed data, mocked API that hides a bug> |

## Drivers

Reusable scripts that put the app in a known state or run a journey, so nobody has to
re-derive the steps every time:

- `<path/to/script>`: what it does, how to run it, what it prints on success
