# Spec: The Draggable Editor/Results Divider

**ID:** SPEC-209
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-079 (the layout presets this replaces), SPEC-035 (the query workspace), SPEC-100 (Query workspace responsive), SPEC-045 (axe assertions), SPEC-064 (resizable result columns — the precedent for a pointer-driven resize in this workspace)

## Overview

The query workspace splits vertically between the SQL editor and the results, and today that split
snaps to one of three fixed proportions chosen from a segmented control in the toolbar: Editor, Even,
Results. Three sizes is not enough — the right split depends on how long the query is and how wide
the result is — and the control costs permanent toolbar space to offer a choice the user would rather
make by dragging.

This spec replaces the control with the thing people expect: a divider between the two panes that
can be dragged to any position between the existing minimum-height floors. The segmented control is
removed outright, and its three named presets stop existing as a concept.

Mobile is unchanged. The mobile query surface switches between editor and results rather than
splitting them, so there is no divider to drag and nothing there to replace.

## Scope

### In Scope

- A draggable divider between the editor pane and the results region at `tablet` and above.
- Keyboard operation of the divider, since a mouse-only control is an accessibility defect and this
  repo asserts against axe.
- Per-user, per-session persistence of the dragged position.
- Double-click to reset to an even split.
- Removal of `EditorLayoutControl`, `EditorLayoutPreset`, `DEFAULT_LAYOUT_PRESET` and
  `LAYOUT_PRESET_EDITOR_FRACTION`.

### Out of Scope

- **Horizontal splitting**, or a side-by-side editor and results arrangement.
- **Resizing the schema rail**, which is a separate boundary with its own collapse control.
- **Cross-session persistence.** The position is per session, exactly as the preset was. Making it
  durable means a per-user document, which is a different spec's worth of machinery for a pane size.
- **Mobile.** The mobile surface keeps its existing editor/results switching, and renders no divider.
- **A reset control in the toolbar.** Double-clicking the divider is the reset; adding a button back
  to the toolbar would reintroduce what this spec removes.

---

## Functional Requirements

### FR-001: The divider resizes the split by pointer

#### Description:

A divider element sits between the editor pane and the results region. Pressing on it and moving the
pointer changes the editor pane's height continuously; releasing commits the position.

#### Acceptance Criteria:

- [ ] A pointer-down on the divider followed by a move of *n* pixels changes the editor pane's height
      by *n* pixels, subject to the clamps in FR-003.
- [ ] The results region's height is the container height minus the editor height minus the divider —
      the two panes always exactly fill the column, at every drag position.
- [ ] Releasing the pointer ends the drag; a subsequent pointer move with no button held changes
      nothing.
- [ ] A drag that ends outside the window (pointer released off-element) still ends the drag — a test
      dispatches the release on the document and asserts no further movement is tracked.
- [ ] Text selection does not occur while dragging.
- [ ] The Monaco editor is re-laid-out after the drag so its own scroll geometry matches the new
      height; a test asserts the layout call happened.

### FR-002: The divider is operable from the keyboard

#### Description:

The divider is a focusable `separator` with a value, and arrow keys move it.

#### Acceptance Criteria:

- [ ] The divider has `role="separator"`, `aria-orientation="horizontal"`, a `tabIndex` that puts it
      in the tab order, and an accessible name of `Resize the editor and results`.
- [ ] It carries `aria-valuenow`, `aria-valuemin` and `aria-valuemax` expressed as the editor's
      percentage of the column, and `aria-valuenow` changes as the divider moves — by drag as well
      as by key.
- [ ] `ArrowUp` / `ArrowDown` move the divider by a fixed step; `Home` moves it to the minimum editor
      height and `End` to the maximum.
- [ ] A focus ring is visible on the divider when it is focused by keyboard.
- [ ] `expectNoA11yViolations` runs against the driven container with the workspace rendered at
      `tablet` width.

### FR-003: The clamps hold, on drag and on container resize

#### Description:

`MIN_EDITOR_HEIGHT` and `MIN_RESULTS_HEIGHT` survive as the drag clamps, and they are re-applied
whenever the measured container height changes.

#### Acceptance Criteria:

- [ ] Dragging past the top clamp leaves the editor at `MIN_EDITOR_HEIGHT` and does not overshoot.
- [ ] Dragging past the bottom clamp leaves the results region at `MIN_RESULTS_HEIGHT`.
- [ ] On a container too short to honour both floors, the editor floor wins and the result height is
      non-negative — the same resolution `clampEditorHeight` already takes, and a test pins it.
- [ ] Shrinking the container after a drag re-clamps the stored fraction rather than leaving a pane
      overflowing; a test drives a container height change and asserts the recomputed heights.
- [ ] The stored value is a **fraction**, not a pixel height, so a position set on a tall window is
      proportional on a short one.

### FR-004: The position persists for the session, per user

#### Description:

The dragged fraction is written to `sessionStorage` under a per-username key, and read back on mount.

#### Acceptance Criteria:

- [ ] A drag, then a remount of the workspace, restores the dragged fraction.
- [ ] The key is `s3portal.query.editorSplit.<username>` — a **new** key. The old preset key holds
      the string `'even'`, and reading it as a number yields `NaN`; a new key makes that unreachable
      rather than defended against. A test asserts the old key is never read.
- [ ] A stored value that is not a finite number in `(0, 1)` is ignored and the default is used.
- [ ] With `sessionStorage` throwing (disabled or over quota), the workspace renders and the divider
      drags; only persistence is lost. Both the read and the write are wrapped.
- [ ] With no username, nothing is read or written and the default is used.
- [ ] The default with no stored value is an even split.

### FR-005: Double-click resets to even

#### Acceptance Criteria:

- [ ] Double-clicking the divider sets the split to even and persists it.
- [ ] A double-click does not leave a drag in progress.

### FR-006: The preset control is gone

#### Description:

This is a removal, and the risk of a removal is what stops being checked. The assertion is
enumerated, not sampled.

#### Acceptance Criteria:

- [ ] `EditorLayoutControl.tsx` no longer exists.
- [ ] `EditorLayoutPreset`, `DEFAULT_LAYOUT_PRESET`, `LAYOUT_PRESET_EDITOR_FRACTION` and
      `QUERY_EDITOR_LAYOUT_STORAGE_PREFIX` no longer exist in `query.constants.ts`, and `index.ts`
      exports none of them. The storage prefix belongs in this list: its only consumers are
      `useEditorLayout.ts` and `queryPure.test.ts`, both of which this spec deletes, so leaving it
      behind would strand the one constant that still names the old key.
- [ ] A test renders the query workspace and asserts no control named `Editor`, `Even` or `Results`
      is present in the toolbar.
- [ ] `npm run build` passes — every call site of the removed exports is gone, which `tsc -b` is the
      only gate that proves.
- [ ] The tests that covered the presets are **replaced, not deleted**: each behaviour they asserted
      (the proportion mapping, the results-floor cap, the default, the per-user persistence) has a
      corresponding assertion against the divider. A checklist in the PR maps each old test name to
      its replacement, so a dropped guard is visible rather than absorbed into a coverage number.

### FR-007: Mobile is untouched

#### Acceptance Criteria:

- [ ] Below `tablet` the divider does not render.
- [ ] `useMobileQuerySurface`'s behaviour is unchanged, and its tests are unmodified.
- [ ] A test at mobile width asserts no element with `role="separator"` and the divider's accessible
      name is present.

---

## Data Model

```ts
// apps/portal/src/features/query/query.constants.ts — after this spec

/** Editor share of the editor+results column when nothing is stored. */
export const DEFAULT_EDITOR_FRACTION = 0.5;

/** Keyboard step, as a fraction of the column, per arrow press. */
export const EDITOR_SPLIT_KEY_STEP = 0.05;

/** sessionStorage key prefix for the per-user split (full key: prefix + username). */
export const QUERY_EDITOR_SPLIT_STORAGE_PREFIX = 's3portal.query.editorSplit.';

// MIN_EDITOR_HEIGHT and MIN_RESULTS_HEIGHT are unchanged and become the drag clamps.
```

## API / Interface Contract

```ts
// apps/portal/src/features/query/useEditorSplit.ts  (replaces useEditorLayout.ts)

export type UseEditorSplitResult = {
  /** Editor share of the column, clamped, in (0, 1). */
  fraction: number;
  /** The editor pane's derived pixel height, clamped to both floors. */
  editorHeight: number;
  /** Handlers for the divider element. */
  dividerProps: React.HTMLAttributes<HTMLDivElement>;
  /** Sets the fraction directly (keyboard, double-click reset). */
  setFraction: (next: number) => void;
};

export function useEditorSplit(username: string | null, containerHeight: number): UseEditorSplitResult;

/** Pure: fraction + container height → clamped editor pixel height. Unit-tested alone. */
export function clampEditorHeight(fraction: number, containerHeight: number): number;
```

## File & Folder Structure

```
apps/portal/src/features/query/
├── EditorSplitDivider.tsx
├── useEditorSplit.ts
├── EditorLayoutControl.tsx      ← DELETED
├── useEditorLayout.ts           ← DELETED
├── query.constants.ts           # presets out, split constants in
├── QueryToolbar.tsx             # the preset control removed from the toolbar
├── QueryWorkspace.tsx           # renders the divider between the panes
└── queryPure.test.ts            # preset tests replaced by split tests
```

## Implementation Phases

### Phase 1: The split hook and its pure core

- `clampEditorHeight(fraction, height)` and its tests, including both floors and the too-short case.
- `useEditorSplit` with the new storage key, the degrade-safe wrapping and the invalid-value paths.
- The old-test-to-new-test mapping written down before anything is deleted.

### Phase 2: The divider

- `EditorSplitDivider` with pointer, keyboard and double-click behaviour.
- Wire it into `QueryWorkspace`; Monaco relayout after a drag.
- Container-resize re-clamping.

### Phase 3: The removal

- Delete `EditorLayoutControl` and `useEditorLayout`, strip the presets from `query.constants.ts`
  and `index.ts`, remove the toolbar slot.
- The absence assertions, the mobile assertions, axe, and `npm run build`.
