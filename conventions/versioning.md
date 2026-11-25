# Versioning

How to version releases, write changelogs and version APIs and schemas.

## SemVer 2.0.0

- `MAJOR.MINOR.PATCH`: MAJOR for incompatible changes, MINOR for compatible
  features, PATCH for compatible fixes.
- Pre-release: `1.4.0-rc.1`, `2.0.0-beta.2`; it sorts before the release.
- `0.y.z` is unstable: anything may change.
- Never change a published version; release a new one.

## Picking the bump

- Use the highest bump among commits since the last tag.
- `BREAKING CHANGE` footer or `!` -> major. In 0.x, breaking -> minor.
- `feat` -> minor. `fix`, `perf` -> patch.
- `docs`, `style`, `refactor`, `test`, `build`, `ci`, `chore` alone -> no release,
  unless the project releases them.
- If the project uses calendar versioning (e.g. `2026.11.0`), keep it; do not
  introduce CalVer otherwise.

## Changelog (Keep a Changelog 1.1.0)

- File `CHANGELOG.md`, newest first. Keep `## [Unreleased]` at the top.
- Release heading: `## [x.y.z] - YYYY-MM-DD`.
- Sections, only those with entries: Added, Changed, Deprecated, Removed, Fixed,
  Security.
- Write for users: what changed for them and what they must do. Not a commit dump,
  no hashes as entries, no internal refactors unless they affect users.
- Mark breaking changes clearly and say how to migrate.
- Follow the project's existing changelog format if it differs.

## Bumping

- Bump the version everywhere the project declares it, in one commit, using its bump tool
  if it has one (`npm version`, `poetry version`, `cargo set-version`, etc.); let tools
  regenerate lockfiles.
- Tag that commit `vX.Y.Z` (annotated; see `git.md`).
- Do not publish, push tags or release without the user's approval.

## API versions

- Version in the URL (`/v1/...`) or a header; follow what the project does.
- Additive changes stay in the same version. Breaking changes need a new version.
- Deprecate before removing: announce in docs and changelog, send `Deprecation` and
  `Sunset` headers if the project uses them, keep the old version until the date.

## Schema versions

- Version database schemas through migrations, never manual edits. See `database.md`.

Sources: SemVer 2.0.0 https://semver.org/spec/v2.0.0.html ;
Keep a Changelog 1.1.0 https://keepachangelog.com/en/1.1.0/ ;
CalVer https://calver.org/ ; Sunset header RFC 8594 https://www.rfc-editor.org/rfc/rfc8594 ;
Deprecation header RFC 9745 https://www.rfc-editor.org/rfc/rfc9745
