# Completed Spec — SPEC-097: Object Details Panel Gains Download & Rename

## What was completed?

The per-object **details panel** (opened by the always-visible per-row **Details** button) now carries the single-item actions removed from the toolbar in SPEC-096.

- **`MetadataPanel`** (file) — a **Download** (primary) + **Rename** (secondary) action pair at the top. Download resolves a presigned URL (`getDownloadUrl` → shared `triggerBrowserDownload`) with its own busy state and an **in-drawer** error alert; Rename calls `onRequestRename(file)` (opens the shared `RenameDialog`). Desktop = side-by-side 50/50, mobile sheet = stacked full-width (`flex-col tablet:flex-row`, `!h-11 tablet:!h-[38px]`).
- **`FolderDetailsPanel`** — a full-width **Rename** action (folders aren't downloadable).
- Both gate Rename on a new `canModify` prop (hidden in read-only dev-unauth); Download always shows on the file panel.
- `FileBrowser` passes `canModify` + per-object rename handlers (`openRenameFile` / `openRenameFolder`, which open `RenameDialog` and close the panel).
- New shared util `fileBrowser.download.ts` (`triggerBrowserDownload`), extracted from `FileBrowser` and reused by the panel.

**Deviation from the spec contract:** the spec suggested Download be handled "internally" with no prop; implemented exactly that (internal to `MetadataPanel`), and error surfacing is **in-drawer** (the FileBrowser download banner sits behind the open drawer, so an inline alert is the correct place).

The Details trigger is unchanged and not selection-gated (per the 2026-07-08 user decision recorded in the spec — the mockup's `count===1` inline-column model was not adopted).

## What changed from earlier specs?

- `MetadataPanel` / `FolderDetailsPanel` (SPEC-017) gained required `canModify` + `onRequestRename` props. `FileBrowser` updated accordingly.
- `triggerBrowserDownload` moved from `FileBrowser.tsx` to `fileBrowser.download.ts` (behavior identical).

## Verification

`format` + `lint` + `tsc` clean; full suite green (1061). New/updated unit tests: panel actions render, Download calls `getDownloadUrl` → `triggerBrowserDownload`, download failure shows an inline alert, Rename invokes `onRequestRename`, read-only hides Rename (file panel keeps Download; folder panel shows nothing); `FileBrowser.test` exercises rename-from-panel end-to-end. Authenticated visual layout (50/50 vs stacked) deferred to manual — preview can't hold a Cognito session; the responsive utilities are the ones covered by SPEC-095's Drawer tests.
