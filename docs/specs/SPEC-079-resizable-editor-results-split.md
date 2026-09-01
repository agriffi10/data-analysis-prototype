# Spec: Editor / Results Layout Presets

**ID:** SPEC-079
**Status:** Completed
**Last Updated:** 2026-07-03
**Depends On:** SPEC-035 (query workspace layout)

> **The presets this spec shipped were retired by SPEC-209 (2026-09-01).** The split is dragged at a
> divider now; `EditorLayoutControl`, `useEditorLayout`, the three-preset type and its storage key are
> all deleted. The status stays Completed because this spec *was* delivered — what follows is the
> record of that, not a description of the product. `MIN_EDITOR_HEIGHT` / `MIN_RESULTS_HEIGHT` and the
> clamp order survive. Full entry: `docs/decisions/browser.md` → *One split, two clamp domains*.

## Overview

The query workspace stacks a **fixed-height** editor (`h-[200px]`) above a
`flex-1` results pane. Users writing longer queries can't grow the editor, and users
scanning wide/tall result sets can't grow the results area — the split is frozen.
This spec adds a small set of **layout preset controls** that let the user snap the
vertical split between the editor and the results region to one of three fixed
proportions: **editor 90%**, an **even 50/50** split, or **results 90%**. This is a
discrete, click-to-choose interaction (not a continuous drag). The chosen preset
persists for the session so it survives tab switches and reloads.

## Scope

### In Scope

- A three-option layout control (a segmented control) in the query workspace that
  sets the editor/results vertical split to one of three presets:
  - **Editor** — editor takes ~90% of the available vertical space.
  - **Even** — editor and results split the space ~50/50 (the default).
  - **Results** — results region takes ~90% of the available vertical space.
- Applying the chosen preset as the editor pane's height (a percentage of the
  available editor+results column height), with the results region taking the
  remainder; the Monaco editor re-lays-out to the new height.
- Minimum-height floors so that even at the extreme presets neither pane collapses
  to an unusable size (the 90% presets are floored/capped by these).
- Keyboard operability of the control (the segmented control is a proper
  focusable/selectable control group with accessible names).
- Persist the chosen preset for the session (per-user `sessionStorage`, same pattern
  as tabs/draft state) so it survives tab switches and reloads within the session.
- Correct behavior within the existing viewport-bounded flex column (the workspace
  is capped to `100dvh - header`; the results region scrolls internally).

### Out of Scope

- A **draggable / continuously-resizable** splitter between the editor and results —
  explicitly replaced by discrete presets (this reworks the original SPEC-079
  drag-resize design).
- Resizing the **schema rail** width (left column) — separate concern, not requested.
- Resizing result **columns** — already shipped (SPEC-064).
- A collapse/expand (fully hide-a-pane) toggle — the extreme presets are ~90%, not
  100%; neither pane fully disappears.
- Persisting the preset **across** sessions (a durable per-user server-side setting)
  — session persistence only, matching existing workspace state.
- Horizontal (side-by-side) editor/results layout — vertical stack only.
- Arbitrary/custom proportions — only the three fixed presets.

---

## Functional Requirements

### FR-001: Three layout presets

#### Description:

A layout control offers three options — **Editor** (~90% editor), **Even** (~50/50),
and **Results** (~90% results). Selecting an option sets the editor pane's height to
the corresponding proportion of the available editor+results column height; the
results region takes the remainder. The results region continues to scroll
internally rather than growing the page.

#### Acceptance Criteria:

- [ ] Selecting **Editor** grows the editor to ~90% of the available height and
      shrinks the results region to the remainder.
- [ ] Selecting **Results** shrinks the editor to ~10% (floored, see FR-002) and
      grows the results region to the remainder.
- [ ] Selecting **Even** splits the available height ~50/50 between editor and
      results.
- [ ] The currently-selected preset is visually indicated in the control.
- [ ] The workspace stays bounded to the viewport; the results region scrolls
      internally (no page-level scroll introduced).
- [ ] The Monaco editor re-lays-out to the new height after a preset change (no
      clipped/frozen editor viewport).

### FR-002: Minimum-height floors

#### Description:

Both panes have a minimum height. At the extreme presets the applied proportion is
clamped so neither the editor nor the results region drops below its floor
(important on short viewports where 10% would be unusably small).

#### Acceptance Criteria:

- [ ] At the **Results** preset the editor never renders below `MIN_EDITOR_HEIGHT`.
- [ ] At the **Editor** preset the results region never renders below
      `MIN_RESULTS_HEIGHT`.
- [ ] On a short viewport where the proportions would violate a floor, the applied
      split clamps to respect both floors (no negative/overlapping panes).

### FR-003: Keyboard + accessibility

#### Description:

The layout control is fully keyboard-operable and exposes accessible names so a
selection can be made without a pointer.

#### Acceptance Criteria:

- [ ] The three options form a single focusable control group (radio/segmented
      semantics) with an accessible group label and per-option accessible names.
- [ ] The options are selectable via keyboard (focus + Enter/Space or arrow-key
      selection consistent with the control's role).
- [ ] The selected option is programmatically indicated (e.g. `aria-pressed` /
      `aria-checked` / `aria-current`) for assistive tech.

### FR-004: Session persistence of the preset

#### Description:

The chosen preset persists per-user in `sessionStorage`, so switching query tabs or
reloading within the session keeps the user's chosen layout. A disabled/failed
storage degrades to non-persistent (never crashes the workspace).

#### Acceptance Criteria:

- [ ] After choosing a preset and switching tabs, the preset is unchanged.
- [ ] After choosing a preset and reloading the page, the preset is restored.
- [ ] With `sessionStorage` unavailable, preset selection still works for the session
      (just not persisted) and no error surfaces.
- [ ] With no stored value, the workspace opens at the **Even** default.

---

## Data Model

```ts
// apps/portal/src/features/query/query.constants.ts
export type EditorLayoutPreset = 'editor' | 'even' | 'results';

export const DEFAULT_LAYOUT_PRESET: EditorLayoutPreset = 'even';

// Editor-pane share of the editor+results column height, per preset.
export const LAYOUT_PRESET_EDITOR_FRACTION: Record<EditorLayoutPreset, number> = {
  editor: 0.9,
  even: 0.5,
  results: 0.1,
};

export const MIN_EDITOR_HEIGHT = 96;   // px — editor floor (Results preset clamp)
export const MIN_RESULTS_HEIGHT = 120; // px — results-region floor (Editor preset clamp)
export const QUERY_EDITOR_LAYOUT_STORAGE_PREFIX = 's3portal.query.editorLayout.';

// Hook state: the selected preset; the pixel height is derived from the preset,
// the container height, and the min-height clamps.
```

## API / Interface Contract

```ts
// apps/portal/src/features/query/useEditorLayout.ts
export type UseEditorLayoutResult = {
  preset: EditorLayoutPreset;              // current selection (persisted)
  setPreset: (p: EditorLayoutPreset) => void; // select + persist
  editorHeight: number;                    // derived px height, clamped to floors
};
export function useEditorLayout(
  username: string | null,
  containerHeight: number,
): UseEditorLayoutResult;

// A small presentational <EditorLayoutControl> renders the three-option segmented
// control (accessible group + selection state), calling setPreset. QueryWorkspace
// owns the height and applies editorHeight to the editor pane (replacing the fixed
// h-[200px]); the results region takes the remainder and scrolls internally.
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── useEditorLayout.ts           # preset → clamped height + session persistence (+ .test.ts)
├── EditorLayoutControl.tsx      # three-option segmented control (+ .test.tsx, a11y)
├── QueryWorkspace.tsx           # apply derived height to the editor pane; render the control
└── query.constants.ts           # presets, fractions, floors, storage prefix
```

## Implementation Phases

### Phase 1: Preset state + persistence

- `useEditorLayout` deriving the clamped editor height from the selected preset +
  container height + min-height floors, with `sessionStorage` persistence
  (degrade-safe, default **even**); unit tests for preset→height, clamping, persist,
  and default.

### Phase 2: Layout control + wiring

- `EditorLayoutControl` (accessible three-option segmented control with selection
  state); replace the editor's fixed `h-[200px]` with the derived height; ensure
  Monaco re-layouts and the results region keeps scrolling internally. Component +
  a11y tests.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`useEditorLayout`,
  `EditorLayoutControl`).
