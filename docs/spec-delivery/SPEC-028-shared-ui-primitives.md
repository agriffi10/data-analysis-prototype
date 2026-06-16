# Completed Spec - SPEC-028 Shared UI Primitives

## What was completed from this spec?

A dependency-free primitive set was extracted into `src/components/` (+ `src/lib/cx.ts`) and
the SPEC-022–027 consumers were refactored onto it:

**New primitives** (all `forwardRef` where interactive):
- `cx` (`lib/cx.ts`) + `cx.test.ts` — class-name join helper, no external dep.
- `Button` (`variant` primary/default/ghost/danger, `size` sm/md) + `Button.test.tsx`.
- `IconButton` (ghost icon-only, `label` → aria-label).
- `Input` (`label` + `error` state, aria-invalid/described-by wiring) + `Input.test.tsx`.
- `Badge` (neutral type pill).
- `Banner` (`variant` success/warning/danger/info, optional `title`/`onDismiss`) + `Banner.test.tsx`.
- `BrandMark` (`size` sm/md, `showWordmark`) — the accent-square upload-arrow + wordmark.

**Consumer updates:**
- `LandingPage` → `BrandMark` + `Button` (primary/default).
- `Header` → `BrandMark` + `Button` (primary sign-in, ghost sign-out).
- `FileBrowser` → `Button` (New folder, selection-bar Move/Delete, move-collision actions),
  `Badge` (type pills), `Banner` (write/download/delete/move error + delete/move result banners).
- `CreateFolderDialog`, `RenameDialog` → `Button` + `Input`.
- `CollisionPrompt` → `Button` (all actions) + `Input` (rename field).
- `DeleteConfirmDialog` → `Button` (ghost Cancel w/ ref, danger Delete).
- `MoveDialog` → `Button` (ghost Cancel, primary Move).
- `MetadataPanel` → `IconButton` (close).

New tests bring the suite to **240 passing** (was 225). `lint` and `build` are clean.

## What has changed?

This is a refactor of code delivered in SPEC-022–027 — no new visual design. Notes / scoped
deviations:

1. **`cx` over class merging.** Primitives concatenate `base + variant + size + className` via
   `cx`. Tailwind resolves genuine utility conflicts by stylesheet order, not class-list order,
   so where a consumer must override a variant's color reliably (the selection-bar **Delete**
   button needs danger-ghost, which isn't one of the four variants) the override uses Tailwind's
   `!` important modifier (`!text-danger hover:!bg-danger-soft`). This is the documented,
   reliable path given the 4-variant API.
2. **Row-action buttons in `FileBrowser` stay inline.** The per-row Rename / Details / Download
   affordances use `h-7` sizing and an accent-ghost Download treatment that the Button `size`
   (sm = h-8) and 4-variant API don't express. FR-007's enumerated list names "toolbar and
   selection-bar buttons" for `Button`; the row-action overlay buttons are intentionally left as
   purpose-built styled buttons. Likewise the `Load more` pagination button.
3. **Banner Dismiss accessible name.** The per-banner `aria-label`s (e.g. "Dismiss upload
   error") collapse to the generic "Dismiss" provided by `Banner`. No test depended on the
   specific labels; the visible "Dismiss" text is the accessible name.
4. **LandingPage brand mark is now horizontal.** It previously stacked icon-above-wordmark;
   using the shared `BrandMark` (`flex items-center gap-2`) makes it horizontal and identical to
   the Header — the intent of a single shared definition (FR-006/007).

All existing roles, aria-labels, refs (`cancelRef`, rename `inputRef`), keyboard handling, and
button text (incl. busy "Deleting…"/"Renaming…"/"Moving…") are preserved, so the SPEC-022–027
test suites pass unchanged alongside the new primitive tests.
