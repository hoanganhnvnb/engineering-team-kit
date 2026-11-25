# UI

How to build accessible, consistent user interfaces. Match the project's design system first.

## Accessibility (WCAG 2.2 AA essentials)

- Semantic HTML first (`button`, `a`, `nav`, `label`, headings in order); ARIA only
  to fill gaps.
- Every input has a visible label tied to it. Every meaningful image has `alt`;
  decorative ones get `alt=""`.
- Everything works by keyboard, in a logical order, with a visible focus indicator.
- Contrast: 4.5:1 for text; 3:1 for large text (≥24px, or ≥18.66px bold), and for icons
  and the parts of UI components needed to identify them and their state.
- Pointer targets at least 24 by 24 CSS px.
- Never convey information by colour alone; add text or an icon.
- Pause, stop or hide auto-playing motion longer than 5s (2.2.2). Also respect
  `prefers-reduced-motion` (beyond AA).

## States

- Every view handles loading, empty, error and success states.
- Errors say what happened and offer a next step (retry, go back, contact).

## Layout

- Responsive. Check at 320 CSS px (WCAG 1.4.10 Reflow) and desktop width; no horizontal
  scroll on the page body at 320px.

## Design system

- Reuse the project's components, tokens and patterns before writing new ones.
- No one-off colours, spacing, font sizes or shadows; use the tokens.

## Forms

- Show validation messages inline, next to the field, and link them to it.
- Never clear the user's input on error.
- Disable or guard the submit button while a request is in flight (no double submit).

## Copy

- Plain language, consistent terms across screens, sentence case as the project does.
- Error messages are actionable: what went wrong and how to fix it.
- If the project has i18n, no hard-coded user-facing strings; add keys.

## Performance

- Lazy-load heavy images, routes and widgets below the fold.
- Reserve space for images and async content (width/height, skeletons) to avoid layout shift.

Reviewers: for G5 (UX gate), hand UI changes to `ux-reviewer`.

Sources: WCAG 2.2 https://www.w3.org/TR/WCAG22/ ;
Cumulative Layout Shift https://web.dev/articles/cls
