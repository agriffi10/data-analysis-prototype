# Completed Spec — SPEC-079: Editor / Results Layout Presets

> **Retired by SPEC-209 (2026-09-01).** The three-preset control described below no longer exists —
> the split is dragged at a divider. The clamp order and the two height floors survive; everything
> else here is history. See `docs/spec-delivery/SPEC-209-draggable-editor-results-divider.md`.

## What was completed?

The query workspace's frozen `h-[200px]` editor / `flex-1` results split is now user-controlled via a
three-option segmented control (**Editor** ~90% / **Even** 50/50 default / **Results** ~90%) in the tab
toolbar. Presentation-only; no data/IAM/infra.

- **`useEditorLayout` (new, `features/query/`):** owns the preset (per-user `sessionStorage` at
  `QUERY_EDITOR_LAYOUT_STORAGE_PREFIX + username`, degrade-safe, default `even`) and derives the editor
  pane's clamped px height from the measured editor+results column. Clamp order: cap at
  `container − MIN_RESULTS_HEIGHT` (120px), then floor at `MIN_EDITOR_HEIGHT` (96px) — on a viewport too
  short for both floors the editor floor wins. `clampEditorHeight` exported for tests.
- **`EditorLayoutControl` (new, `features/query/`):** labeled `role="group"` of three `aria-pressed`
  toggle buttons (same pattern as the notifications filter); keyboard-operable native buttons.
- **`QueryWorkspace`:** wraps editor+status+results in a measured column (`ResizeObserver`, guarded for
  environments without one) and applies the derived height to the editor pane; Monaco re-lays-out via its
  default `automaticLayout`. Constants/type (`EditorLayoutPreset`, fractions, floors) in
  `query.constants.ts`; hook + constants re-exported from the feature barrel.

Deviation: the control uses the repo's established `role="group"` + `aria-pressed` segmented pattern
rather than radio semantics (FR-003 allows either).

## What changed from earlier specs?

The SPEC-035 fixed `h-[200px]` editor pane is replaced by the derived preset height (status bar + results
flex into the remainder; internal results scrolling from the 2026-06-30 scroll model is unchanged).

## Verification

Prettier, ESLint, `tsc`, Vitest **944 passed** (13 new hook tests: preset→height, clamps/floors, default,
persistence, corrupt/foreign/throwing storage; control tests incl. axe). Live-verified in the dev browser
(dev-unauth): all three presets apply with correct clamped heights (687px column → 344/567-capped/96-floored),
Monaco follows, no page scroll, ResizeObserver re-derives on viewport resize. Session persistence
exercised by unit tests (dev-unauth has no username, so storage is a designed no-op there).
