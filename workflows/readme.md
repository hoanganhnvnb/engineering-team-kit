# README redesign

Read by `/engineering-team:readme`. The README is the entry point, not the whole
documentation. The repository is the source of truth: never invent features, commands,
compatibility or claims.

## Audit: what to look for

Visual hierarchy, accuracy against the code, readability, onboarding path, relevance,
navigation, duplication, completeness, maintainability, GitHub rendering. Mark each
problem as outdated, duplicated, misleading, too long or missing. Keep important
information; if detail moves, link to where it went.

## Structure

Adapt to the repository type (app, CLI, library or SDK, agent framework, plugin,
monorepo, service). Pick only sections that carry information:

hero · overview · key capabilities · quick start · usage examples · configuration ·
architecture · repository layout · development · testing · documentation · contributing ·
security · license.

Most important content first. A visitor should find in 30 seconds: what it is, what
problem it solves, who it is for, how to start, where the docs are.

## Design rules

- **Hero.** Existing logo if there is one, project name, one concrete sentence, 3–5
  navigation links. Centre it only if that helps; the rest stays left-aligned.
- **Headings.** Exactly one H1. Logical H2/H3. Consistent capitalisation. No emojis in
  headings or navigation, no decorative icons.
- **Badges.** 3–5, each backed by something real (a workflow, a release, a manifest, a
  license file). No technology badges, counters or fake status.
- **Assets.** Reuse what exists. Use a screenshot, GIF or diagram only when it explains
  something. Descriptive alt text, no external trackers. Check both GitHub themes.
- **Diagrams.** Mermaid only where it shows architecture, flow or lifecycle better than
  text, kept small.
- **Markdown.** GitHub Flavored Markdown. HTML only for hero alignment, image sizing or
  theme-aware images. No custom CSS, scripts, fonts or complex layouts. Avoid wide tables.
- **Words.** Plain, specific, technically accurate. In the repository's documentation
  language. No buzzwords, filler or unverifiable claims about speed or security.
- **Structure of docs.** Move long explanations into the existing docs tree, with a link.
  Don't duplicate between README and docs. No empty or placeholder files.

## Validation

Check, and say what you could not check:

1. Every command exists and runs as written (safe, read-only forms only), or is marked
   `unverified`.
2. Every link and local asset resolves. Anchors match their headings.
3. Badges point to a real workflow, release or license.
4. Mermaid syntax parses; headings nest; there is one H1.
5. Readable on a phone width and in light and dark mode: no horizontal overflow, images
   that work on both backgrounds.
6. No duplicated content, secrets or internal-only details.

## Done when

The README matches the repository, the first screen answers what and why, onboarding is
quick to find, every claim is backed or marked, and the limits of what was verified are
written down.
