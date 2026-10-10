# Accessibility

Target: WCAG 2.1 AA.

## Automated audit

`frontend/e2e/accessibility.spec.ts` runs axe-core (WCAG 2.1 A/AA rules) in Chrome on 14 pages
— home, library, search results, chat, collections, notes, compare, reviews, projects,
knowledge graph, evaluation, usage, settings, help — in **light and dark** themes, plus a
paper page, with the sample papers loaded so pages show content. It runs with the other
browser tests (`npm run e2e`) and in CI, so a regression fails the build.

First run (Phase 16) found three problems, all fixed:

| Finding | Where | Fix |
|---|---|---|
| Secondary text 4.0:1 on white, 3.8:1 on the page background (needs 4.5:1) | every page, light theme: the `--text-subtle` token | `#807f79` → `#6f6e68` (≥ 4.6:1 on every light surface; still lighter than `--text-muted`, so the hierarchy holds) |
| White text on the dark theme's error red, 2.75:1 | the Delete account button | new `--on-error` token: dark text on the dark-theme red |
| Links inside running text distinguished by colour only | knowledge graph empty state | underlined |

Automated rules catch only part of the problems, so these are also built in and checked by
hand:

## Keyboard and screen readers

- A **Skip to content** link is the first focusable element; every page has one `h1` and a
  `main` landmark.
- Everything is reachable by keyboard with a visible focus ring (`:focus-visible`); dialogs,
  sheets, menus and popovers (Radix) trap and restore focus and close with Escape. Shortcuts
  are listed on the Help page.
- Icon-only buttons have labels (e.g. "Delete: <question>", "Source 2: <paper>, p. 1"); live
  progress uses `role="status"` / `role="progressbar"` with values; streamed answers don't
  announce every token (`aria-live="off"` on the transcript), the finished answer and its
  support status are reachable as normal content.
- Form fields have visible labels; errors are announced with the field.

## Visual

- Colour is never the only signal: support status, run results and evaluation findings carry
  text labels and icons; chart series have a legend and the values are always in a table
  next to the chart (a hover tooltip is never the only way to read a number).
- The chart palette was validated for colour-vision deficiencies in light and dark themes
  (Phase 13); themes are designed separately, not inverted.
- Text size can be set to compact / default / large (Settings → Appearance); layouts reflow
  on phones without horizontal page scrolling (checked at 390 px for every page added since
  Phase 9; wide tables scroll inside their own box).
- `prefers-reduced-motion` turns animations off.

## Known gaps

- The knowledge-graph canvas (force layout) is not usable with a screen reader; the same
  information is available as lists — entity pages, the timeline, and the topic list.
- The PDF reader shows page images with the extracted text alongside; scanned papers depend
  on OCR quality.
- No formal audit with assistive-technology users yet.
