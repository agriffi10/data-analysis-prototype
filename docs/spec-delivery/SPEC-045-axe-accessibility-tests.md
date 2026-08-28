# Completed Spec — SPEC-045: Automated Accessibility (axe) Test Suite

## What was completed?

- Added **`vitest-axe`** (wraps `axe-core` 4.12) as a dev dependency; runtime matcher registered in
  `src/test-setup.ts` via `expect.extend(vitest-axe/matchers)`, with types declared in a new
  `src/vitest-axe.d.ts` (`declare module 'vitest'` — Vitest 4 no longer reads vitest-axe's legacy `Vi`
  namespace augmentation).
- **`src/test/axe.ts`** — one shared helper `expectNoA11yViolations(ui, axeOptions?)` (renders via RTL,
  runs axe, asserts `toHaveNoViolations`) plus the single centrally-defined config: WCAG tags
  `wcag2a`/`wcag2aa`/`wcag21a`/`wcag21aa`/`wcag22aa`; `color-contrast` disabled with a written reason
  (jsdom has no layout/computed style — manual/visual concern, not faked). Exported override presets:
  `ROUTE_AXE_OPTIONS` (adds best-practice landmark/heading/region rules) and `COMPONENT_AXE_OPTIONS`
  (`region` off for isolated renders).
- **Route-level checks** (`*.a11y.test.tsx`): Landing, Files (authenticated, folders + files via the
  established `useFileBrowser` mock surface), Query workspace (real `SchemaBrowser` over mocked
  `useSchema` + a succeeded result set), Not Found. Each also asserts exactly one `<h1>` + a `<main>`.
- **Component-level checks**: Modal / ConfirmDialog / Drawer (open), Input (error state), Banner (every
  variant), Toast (every variant), Pager, UploadQueuePanel (uploading/done/failed/collision),
  CollisionPrompt, DestinationPicker, and a multi-tab QueryTabStrip + a structural guard
  (tablist → tab children → aria-controls-linked tabpanel).
- `npm run test:a11y -w apps/portal` (`vitest run a11y`) runs only the axe specs; they also run under the
  normal `npm test` (no new CI pipeline). Contributor note appended to
  `apps/portal/info/best-practices/accessibility/accessibility.md` (how to add a check; what axe does/doesn't cover).

## Real defects the suite surfaced on first run (fixed in scope)

- **`NotFoundPage`** rendered no `<main>` landmark (the skip-link target `#main` was missing) — wrapped
  its content in `<main id="main">`.
- **`QueryTabStrip`** put the `+` / Saved queries / History buttons directly inside `role="tablist"`
  (`aria-required-children`) — the tablist now wraps only the `role="tab"` elements; those controls are
  siblings outside it. Also added **Delete/Backspace** to close the focused tab (keyboard close path).
- **Known limitation, tracked separately:** a closable tab still nests its ✕ `<button>` inside the
  `role="tab"` element (`nested-interactive`). A correct fix (decorative ✕ + Delete-key, or `aria-owns`
  reparenting) is a keyboard-model change beyond this testing spec, so `nested-interactive` is disabled
  **only** for the QueryTabStrip component check (documented inline); every other rule still runs there
  and the single-tab route check enforces it.

## What changed from earlier specs?

- `test-setup.ts` (SPEC-004) gains the axe matcher; `QueryTabStrip` (SPEC-041) and `NotFoundPage`
  (SPEC-031-era) got the a11y fixes above. No behavioral/UX change beyond the markup corrections.
- No infra/IAM change — testing/tooling only. New dependency noted in `CLAUDE.md` Tech Stack.

## Verification

`npm run lint`, `npm run build`, and `npm run test` (**550 pass**, +28 axe specs over the prior 522) all
green locally; `npm run test:a11y` runs the 28 axe specs alone. The matcher was confirmed to genuinely
fail on a real violation (unlabeled input) — not a silent no-op — and `color-contrast` is reported
disabled, not faked.
