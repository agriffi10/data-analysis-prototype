# Completed Spec — SPEC-209: The Draggable Editor/Results Divider

## What was completed?

The query workspace's editor/results split is now dragged, not chosen. The three-preset segmented
control is gone from the toolbar, and a focusable divider sits between the two panes at `tablet` and
above.

- **`useEditorSplit` (new, `features/query/`):** owns the split — the fraction (per-user
  `sessionStorage` under `QUERY_EDITOR_SPLIT_STORAGE_PREFIX + username`, degrade-safe, default even,
  written once on pointer **release**), the editor pane's derived pixel height, and `dividerProps`:
  the separator's role, its ARIA value and its pointer / arrow / `Home` / `End` / double-click
  handlers. Exports `clampEditorHeight`, `clampFraction` and `splitBounds`.
- **`EditorSplitDivider` (new, `features/query/`):** a 24px band holding three children — a step
  button, the separator that spreads `dividerProps`, and the other step button. The band's height is an
  inline style because the same constant is inside the results cap; the buttons are sized in **px**
  because the root font-size is 14px, so `h-6` draws 21px and misses the 24px minimum target
  silently — found by measuring in a browser, since jsdom reports axe's `target-size` as a pass. The buttons are siblings rather than children because a focusable widget may not contain
  focusable content, and that arrangement is also what keeps a click off them from starting a drag.
- **`SqlEditor`:** `SqlEditorHandle` gains `layout()`. Monaco's own `automaticLayout` (set by
  `@monaco-editor/react`) reacts a frame late, which a continuous drag makes visible; the workspace
  calls it as the pane height lands.
- **`QueryWorkspace`:** the measured column is now exactly three flex children — editor pane, divider,
  results region. The preset easing (`animateSplit` + its `onTransitionEnd`) is deleted: a height
  transition on a continuous drag is the lag the flag was written to avoid.
- **Removed:** `EditorLayoutControl.tsx`, `useEditorLayout.ts`, `EditorLayoutPreset`,
  `DEFAULT_LAYOUT_PRESET`, `LAYOUT_PRESET_EDITOR_FRACTION`, `QUERY_EDITOR_LAYOUT_STORAGE_PREFIX` and
  the toolbar slot that held them. A guard test enumerates the directory listing and both modules'
  runtime export sets rather than sampling them.

### Deliberate deviations

- **Three constants the spec's Data Model did not list** — `EDITOR_SPLIT_DIVIDER_HEIGHT`,
  `MIN_EDITOR_FRACTION`, `MAX_EDITOR_FRACTION`. The spec was amended in the same PR rather than the
  divergence being left in a plan file. Reasoning: [`decisions/browser/` → *One split, two clamp
  domains*](../decisions/browser/one-split-two-clamp-domains-and-the-pair-has-to-agree.md).
- **FR-006 AC3's literal names were wrong and were corrected in the spec.** It asked for the absence
  of a control named `Editor` / `Even` / `Results`; the shipped control's accessible names were
  `Default layout: …` / `Query Editor layout: …` / `Results layout: …`, so the criterion matched
  nothing *before* the removal either and would have passed vacuously. The test enumerates the four
  names that actually existed.
- **Scope added on a user decision: the divider carries a pair of step buttons.** The retired preset
  control was three `onClick` buttons — a single-pointer, non-dragging path to a chosen split — so
  the query workspace met WCAG 2.5.7 before this spec, and a drag-only divider would have *caused* a
  regression rather than inherited one. Escalated mid-build and answered "add the steppers"; the
  spec gained FR-002 AC6. `ColumnResizeHandle` has never had such a path and is untouched — a
  standing gap, not this one. Full entry: [`decisions/browser/` → *The divider needs a click path*](../decisions/browser/the-divider-needs-a-click-path-because-a-drag-is-not-an-alternative-to.md).
- **FR-001 AC2 is settled arithmetically and structurally, not by measurement.** jsdom lays nothing
  out, so a swept test pins `editor + divider + results ≤ column` with the results side never under
  its floor, and the DOM test pins the three flex children and which one takes the remainder. It does
  **not** prove the browser's laid-out heights; the live check in `testing/e2e.md` §4.3 does.

## What changed from earlier specs?

SPEC-079's presets are retired outright — its delivery doc describes a control that no longer exists.
The clamp order it established survives with the divider's height folded into the results cap, and
its `MIN_EDITOR_HEIGHT` / `MIN_RESULTS_HEIGHT` are unchanged. SPEC-035's `SqlEditorHandle` gains a
member. The Help & guides sentence describing the preset control is rewritten. The step buttons were nested inside the separator first; axe's `nested-interactive` failed
the route check, which is how the sibling arrangement was arrived at rather than guessed. The
`e.target !== e.currentTarget` filtering that arrangement replaced was then measured to be worse than
dead: the visible grip is a child of the separator, so the guard ignored a grab on the one place a
user aims at, and a test now drives the drag from the grip. The step test's "does not start a drag" assertion was
vacuous in the same way — `user.click` ends with a `pointerup` that unbinds the drag before the move
could see it — and now holds the button down.

## Verification

Prettier, ESLint, `tsc -b` and Vitest green locally — **2191 passed**, 138 files, exit 0; plus
`scripts/validate_docs.py`. Eleven guards were mutation-tested and all eleven reddened: the Monaco
relayout, the drag's `preventDefault`, the delta-from-origin arithmetic, `tabIndex`, the move
handler's clamp, `storageKey`'s null guard, `pointercancel`, the unmount cleanup, the column's
re-measure across the tablet breakpoint, the step direction, and the grip grab.

**Two guards were vacuous when first written and were replaced.** The old-storage-key guard used
`vi.spyOn(Storage.prototype, 'getItem')`; that spy records **zero** calls in this suite (measured —
jsdom's storage does not dispatch through the prototype here), so `[].every(...)` passed whatever the
hook read, and a planted read of the old key went undetected. It now records through a stubbed
global that self-checks. The drag test also grabbed at a `clientY` equal to the pane height, where a
delta handler and an absolute-position handler agree; the fixture now grabs where they differ. The
`clampEditorHeight` ↔ `splitBounds` agreement sweep caught two real divergences while it was being
written.

Deferred to a signed-in session: the drag itself, the keyboard path, the reload persistence and the
window-resize re-clamp — jsdom has no layout engine, and local dev now points at a real API. The
steps are in [`testing/e2e.md`](../testing/e2e.md) §4.3.
