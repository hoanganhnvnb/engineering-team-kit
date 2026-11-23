---
name: improve-ui
description: Improve a screen or flow with the small AI team. Capture the current state as evidence, agree on concrete UX changes, implement them within the project's design system, and re-verify visually at desktop and mobile widths, including accessibility.
argument-hint: <screen, route, or component> [what feels wrong]
disable-model-invocation: true
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discover.py"), Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/etk_run.py":*)
---

# /engineering-team:improve-ui

You are the **Lead**. UI work is judged by what the user sees, so it gets visual
evidence before and after.

**Target:** $ARGUMENTS

## Project snapshot

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/discover.py"`

## Steps

1. **Understand.** Read the project instructions and find the design system in use
   (Polaris for Shopify admin apps, the theme's own conventions for Liquid themes,
   Tailwind/shadcn, MUI, a custom kit…). Find how to run the app (project config
   `ui.start` / `ui.url`, package scripts, README). If the project has its own UI or design
   skills, use them. Otherwise installed design skills are fine for guidance, but
   the project's existing look wins over generic taste.
2. **Check tools.** Is a browser tool available (Claude in Chrome, Playwright MCP, built-in
   browser)? If not, say up front that G5 will be at most "static review only" and
   visual verification will be `BLOCKED`.
3. **Baseline.** Ledger: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/etk_run.py" init "ui: <target>" --kind improve-ui --mode medium`.
   Spawn `engineering-team:ux-reviewer` on the current state: the journey, desktop + mobile,
   states, accessibility. Its findings (`U0-n`) are the problem list.
4. **Decide.** Turn the user's complaint + baseline findings into ACs ("AC-1: on 375px the
   form fits without horizontal scroll"). Pick the changes that matter most. Don't redesign
   what the user didn't ask about. If a change alters product behavior or branding, ask
   first.
5. **Implement.** Small → yourself. Otherwise `engineering-team:developer` with the ACs, the
   design-system constraints, and the baseline findings. Reuse existing components and
   tokens. No one-off colors or spacing values.
6. **Verify.** Fresh `engineering-team:ux-reviewer` re-walks the same journey at the same
   widths and checks the ACs and baseline findings. Plus `engineering-team:code-reviewer`
   if the change has logic beyond markup/styles. Loop per
   `${CLAUDE_PLUGIN_ROOT}/workflows/review-loop.md` (max 3 cycles).
7. **Tests.** Run the project's tests/lint/typecheck (G3/G4). Visual changes still
   break snapshot and component tests.
8. **Gates + report.** G5 `PASS` needs browser evidence from this session. Static review
   alone is `BLOCKED` with the reason. `etk_run.py check`, then report before → after per
   AC, with what was seen at which width.

Never describe how something looks unless a browser tool showed it in this session.
