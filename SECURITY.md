# Security policy

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately through
GitHub: **Security → Report a vulnerability** on this repository. Include the
version, the steps to reproduce, and what an attacker gains.

You'll get an answer within a week. Fixes ship in a patch release, and the reporter is
credited in the changelog unless they prefer not to be.

## Scope

In scope: the guard hook (`hooks/`), the scripts (`scripts/`), how skills handle
repository content, the workflow profile, and the release ledger.

The guard is a best-effort tripwire, not a sandbox. The gaps already known are listed
in [docs/limitations.md](docs/limitations.md). A new bypass of a rule the guard claims
to enforce is still worth reporting.

## Supported versions

Only the latest release gets security fixes.
