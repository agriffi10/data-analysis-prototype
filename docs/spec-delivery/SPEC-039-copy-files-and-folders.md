# Completed Spec — SPEC-039: Copy Files and Folders (recursive)

## What was completed?

- **Copy** is now a first-class file-browser action (row hover-actions + multi-select bar), for files
  and folders, leaving the original in place. Folder copy is recursive.
- `copyFolder` service (`fileBrowser.service.ts`) — the copy-only counterpart of `moveFolder`:
  recursive, paginated, best-effort (partial failure leaves a partial duplicate, no rollback),
  into-itself guard, pre-flight collision count. **Never issues a delete.** Reuses the existing
  SPEC-019 `copyObject` per key. New `CopyResult` type.
- `useCopy` hook — copy orchestration (single + multi-select) with **destination-only** invalidation
  (the source is unchanged, unlike move), collision warn-and-confirm (Overwrite-all / Cancel), folder
  progress, and the **same-folder auto-number** flow: when the destination is the item's current
  parent, it proposes an editable, HEAD-checked `{name} (N)` name (before the extension for files, on
  the leaf for folders). Aggregates a `CopySummary`.
- `DestinationPicker` — shared folder picker extracted from `MoveDialog` (FR-006): excludes operated
  subtrees and the protected `athenaresults/` folder; `allowCurrentParent` distinguishes Move
  (current parent forbidden) from Copy (current parent → same-folder auto-number).
- `CopyDialog` — thin shell over `DestinationPicker` that swaps in the editable name field for the
  same-folder case.
- **Deviation (as specified):** same-folder suffix uses the numbered form `report (1).pdf` / `docs (1)/`
  per FR-003 and the resolved Open Question — the stale Phase-1 checkpoint "`{name} copy`" wording was
  not used. Same-folder copy is single-item by design (the auto-number prompt is per-item); copying
  many items in place is not a v1 flow.

## What changed from earlier specs?

- **SPEC-019 `MoveDialog`** was refactored to consume the new `DestinationPicker` — no behavior change
  to move (its "into itself" wording is preserved via the picker's `selfMessage` prop); existing move
  tests pass unchanged.
- No service signatures changed; `copyObject`/`moveFolder` were reused as-is.

## Verification

`npm run lint`, `npm run test` (386 pass — +39 new across `copyFolder` no-delete/recursive/collision/
marker, `useCopy` dest-only-invalidation/auto-number/collision/multi-select, `DestinationPicker`,
`CopyDialog`, and `FileBrowser` copy wiring), and `npm run build` all pass locally. The Phase-2 live
browser checkpoint (copy in place → `… (1)`, recursive folder copy, into-itself blocked, `athenaresults/`
not offered, partial-failure reporting) is deferred to deploy with a real user. No IAM change, no new
dependency — copy uses the existing `s3:GetObject` + `s3:PutObject`.
