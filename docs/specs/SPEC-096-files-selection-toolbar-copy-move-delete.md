# Spec: Files — Selection Toolbar Narrowed to Copy / Move / Delete

**ID:** SPEC-096
**Status:** Completed
**Last Updated:** 2026-07-08
**Depends On:** None

## Overview

Today the file-browser multi-select toolbar (`SelectionToolbar`) carries five actions — Download, Copy,
Move, Rename, Delete — mixing **single-item** actions (Download, Rename) with **whole-selection** batch
actions. The Claude Design mockups redraw the toolbar as a focused **selection (bulk-action) bar** that
operates on the whole selection and holds only **Copy / Move / Delete**. Download and Rename move to the
per-object details panel (SPEC-097), where they belong as single-item actions. This spec makes the
toolbar change only; SPEC-097 lands the panel side.

## Scope

### In Scope

- Remove **Download** and **Rename** from `SelectionToolbar`; keep **Copy**, **Move**, **Delete**.
- Keep the toolbar's existing "N selected" label + master/select-all checkbox + Clear affordance and
  its `accent-soft` bar styling (design tokens per `design-system.md` §5 "Selection bar").
- Keep the toolbar shown whenever `useSelection().count >= 1` and hidden at `count === 0`.
- Update `FileBrowser`'s wiring so it no longer passes `onRequestDownload` / `onRequestRename` into the
  toolbar; those handlers move to the details panel in SPEC-097.
- Update `SelectionToolbar` tests to assert the new three-button set.

### Out of Scope

- Adding Download/Rename to the details panel — that is SPEC-097 (this spec may temporarily leave those
  actions reachable only from existing per-row/detail affordances until 097 lands; sequence 096 → 097).
- The `..` parent-folder row (SPEC-098) and any responsive reflow of the bar (SPEC-099, which makes it
  icon-only on mobile).
- Any change to `useCopy` / `useMove` / `useDelete` behavior, dialogs, or S3 operations.
- Read-only browse mode's per-row Download control (dev-unauth), which is unaffected.

---

## Functional Requirements

### FR-001: Toolbar holds only Copy / Move / Delete

#### Description:

`SelectionToolbar` renders exactly three action buttons — Copy, Move, Delete — right-aligned after the
selected-count label and spacer. Download and Rename are removed from it.

#### Acceptance Criteria:

- [ ] With ≥1 item selected, the toolbar shows Copy, Move, and Delete buttons and does **not** show
      Download or Rename.
- [ ] Copy opens `CopyDialog` → `useCopy`; Move opens `MoveDialog` → `useMove`; Delete opens the
      delete confirm → `useDelete` — all unchanged from today.
- [ ] Delete renders in the danger tone (`text-danger`, `danger-soft` hover); Copy/Move render as
      default/ghost buttons per `design-system.md`.
- [ ] The buttons are disabled while a batch operation is in flight (existing `isBusy` gating).

### FR-002: Selected-count label, select-all, and Clear preserved

#### Description:

The bar keeps its master checkbox (select-all/clear), the live "N selected" label (`accent-text`,
weight 600, `aria-live="polite"`), and its `accent-soft` styling.

#### Acceptance Criteria:

- [ ] The master checkbox toggles select-all / clear over the current listing (excluding the `..` row
      once SPEC-098 lands).
- [ ] The "{n} selected" label updates as selection changes and is announced to assistive tech.
- [ ] `Clear` (or the master checkbox) invokes `useSelection().clear()`.
- [ ] The bar appears only when `count >= 1`.

### FR-003: `FileBrowser` wiring updated

#### Description:

`FileBrowser` stops passing single-item handlers into the toolbar. Its download/rename handlers are
retained for SPEC-097 (details panel) but are no longer toolbar props.

#### Acceptance Criteria:

- [ ] `SelectionToolbar`'s props no longer include `onRequestDownload` / `onRequestRename`.
- [ ] Removing those props causes no TypeScript, lint, or unused-variable errors.
- [ ] Existing Copy/Move/Delete flows from the toolbar are unchanged end-to-end.

---

## API / Interface Contract

> **Note:** `SelectionToolbar` is an inline function component inside `FileBrowser.tsx` (not a
> standalone module) and has no dedicated test file today; its props are an internal shape. Edit it in
> place. (If a future refactor extracts it to `SelectionToolbar.tsx`, that's optional and out of this
> spec's scope.)

```ts
// SelectionToolbar (inline in FileBrowser.tsx) — revised internal props
type SelectionToolbarProps = {
  allItems: SelectableItem[];
  onRequestCopy: () => void;
  onRequestMove: () => void;
  onRequestDelete: () => void;
  // removed: onRequestDownload, onRequestRename
};
```

## File & Folder Structure

```
src/features/file-browser/
├── FileBrowser.tsx        # edit the inline SelectionToolbar: remove Download + Rename buttons/props;
│                          # drop the two handler props from the toolbar render (retain handlers for SPEC-097)
└── FileBrowser.test.tsx   # update assertions to the 3-button toolbar set
```

## Implementation Phases

### Phase 1: Toolbar + wiring

- Remove Download/Rename buttons and their internal props from the inline `SelectionToolbar` in
  `FileBrowser.tsx`.
- Update `FileBrowser` to stop passing those props (retain the handlers for SPEC-097).
- Update any `FileBrowser.test.tsx` assertions that reference the
  removed toolbar buttons.
- Run format/lint/test green.
