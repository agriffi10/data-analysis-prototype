# Spec: Resizable Editor / Results Split

**ID:** SPEC-079
**Status:** Draft
**Last Updated:** 2026-07-01
**Depends On:** SPEC-035 (query workspace layout), SPEC-064 (drag-resize precedent)

## Overview

The query workspace stacks a **fixed-height** editor (`h-[200px]`) above a
`flex-1` results pane. Users writing longer queries can't grow the editor, and users
scanning wide/tall result sets can't grow the results area — the split is frozen.
This spec adds a **draggable horizontal splitter** between the editor and the results
region so the user can rebalance the two panes, mirroring the drag-to-resize
interaction already shipped for result columns (SPEC-064). The chosen split persists
for the session so it survives tab switches and paging.

## Scope

### In Scope

- A draggable divider between the SQL editor pane and the results region (the
  status bar + error banner + results table below it) that changes the editor's
  height and lets the results region take the remainder.
- Minimum heights for both panes (the editor can't collapse to nothing; the results
  region keeps a usable floor), enforced as drag clamps.
- Keyboard operability + a double-click-to-reset on the divider (reuse the SPEC-064
  pattern): the divider is focusable, Arrow Up/Down nudges the split, double-click
  restores the default height.
- Persist the editor height for the session (per-user `sessionStorage`, same pattern
  as tabs/draft state) so it survives tab switches and reloads within the session.
- Correct behavior within the existing viewport-bounded flex column (the workspace
  is capped to `100dvh - header`; the results region scrolls internally).

### Out of Scope

- Resizing the **schema rail** width (left column) — separate concern, not
  requested.
- Resizing result **columns** — already shipped (SPEC-064).
- A collapse/expand (hide-a-pane) toggle — only continuous resize is in scope.
- Persisting the split **across** sessions (a durable per-user server-side setting)
  — session persistence only, matching existing workspace state.
- Horizontal (side-by-side) editor/results layout — vertical stack only.

---

## Functional Requirements

### FR-001: Draggable editor/results divider

#### Description:

A horizontal divider sits between the editor pane and the results region. Dragging it
down grows the editor and shrinks the results region; dragging up does the reverse.
The results region continues to scroll internally rather than growing the page.

#### Acceptance Criteria:

- [ ] Dragging the divider down increases the editor's height and decreases the
      results region's height by the same amount.
- [ ] Dragging up decreases the editor's height and increases the results region.
- [ ] The workspace stays bounded to the viewport; the results region scrolls
      internally (no page-level scroll introduced).
- [ ] The Monaco editor re-lays-out to the new height (no clipped/!frozen editor
      viewport after a resize).

### FR-002: Minimum-height clamps

#### Description:

Both panes have a minimum height enforced during drag, so neither the editor nor the
results region can be dragged away to an unusable size.

#### Acceptance Criteria:

- [ ] The editor cannot be dragged below `MIN_EDITOR_HEIGHT`.
- [ ] The results region cannot be dragged below its minimum (the editor cannot grow
      past `containerHeight - MIN_RESULTS_HEIGHT`).
- [ ] Clamping is smooth (the divider stops at the bound; no overshoot/jump).

### FR-003: Keyboard + double-click reset

#### Description:

The divider is keyboard-operable and resets to the default split on double-click,
matching the SPEC-064 column-resize affordances.

#### Acceptance Criteria:

- [ ] The divider is focusable and exposes an accessible role/name (a
      `separator`-style control with an aria-label).
- [ ] Arrow Up / Arrow Down move the split by a fixed step (clamped by FR-002).
- [ ] Double-clicking the divider restores `DEFAULT_EDITOR_HEIGHT`.

### FR-004: Session persistence of the split

#### Description:

The editor height persists per-user in `sessionStorage`, so switching query tabs or
reloading within the session keeps the user's chosen split. A disabled/failed
storage degrades to non-persistent (never crashes the workspace).

#### Acceptance Criteria:

- [ ] After resizing and switching tabs, the split is unchanged.
- [ ] After resizing and reloading the page, the split is restored.
- [ ] With `sessionStorage` unavailable, resize still works for the session (just
      not persisted) and no error surfaces.

---

## Data Model

```ts
// apps/portal/src/features/query/query.constants.ts
export const DEFAULT_EDITOR_HEIGHT = 200; // px — today's fixed h-[200px]
export const MIN_EDITOR_HEIGHT = 96;      // px — editor drag floor
export const MIN_RESULTS_HEIGHT = 120;    // px — results-region drag floor
export const EDITOR_RESIZE_STEP_PX = 16;  // px per Arrow key press
export const QUERY_EDITOR_HEIGHT_STORAGE_PREFIX = 's3portal.query.editorHeight.';

// Hook state: a single number (editor height in px), clamped and persisted.
```

## API / Interface Contract

```ts
// apps/portal/src/features/query/useEditorHeight.ts
export type UseEditorHeightResult = {
  height: number;                 // current editor height (px), clamped
  setHeight: (px: number) => void;// clamp to [MIN_EDITOR_HEIGHT, max] + persist
  reset: () => void;              // back to DEFAULT_EDITOR_HEIGHT
};
export function useEditorHeight(username: string | null, containerHeight: number): UseEditorHeightResult;

// A small presentational <ResizableDivider> handles pointer drag + Arrow keys +
// double-click, calling setHeight/reset; QueryWorkspace owns the height and applies
// it to the editor pane (replacing the fixed h-[200px]).
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── useEditorHeight.ts          # clamp + session persistence (+ .test.ts)
├── ResizableDivider.tsx        # pointer/keyboard/dbl-click handle (+ .test.tsx, a11y)
├── QueryWorkspace.tsx          # apply height to the editor pane; render the divider
└── query.constants.ts          # heights + step + storage prefix
```

## Implementation Phases

### Phase 1: Height state + persistence

- `useEditorHeight` with clamp to the container and `sessionStorage` persistence
  (degrade-safe); unit tests for clamp/persist/reset.

### Phase 2: Divider component + wiring

- `ResizableDivider` (pointer drag, Arrow keys, double-click reset); replace the
  editor's fixed `h-[200px]` with the hook height; ensure Monaco re-layouts and the
  results region keeps scrolling internally. Component + a11y tests.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`useEditorHeight`,
  `ResizableDivider`).
