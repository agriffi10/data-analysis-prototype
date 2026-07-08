# Completed Spec — SPEC-099: Files Responsive Layout

## What was completed?

The Files surface now reflows across mobile / tablet / desktop. Presentation/markup only — no data/service/IAM/infra/routing/auth change.

- **Rail (FR-001).** The on-page 248px Spaces rail is already `hidden tablet:flex` (SPEC-095). Below `tablet` its list is fed into the mobile `AppNavDrawer`: extracted **`SpacesList`** (from `Sidebar`), and `FilesPage` registers a memoized rail via `useProvideNavRail`.
- **Table columns (FR-002).** The `≥ tablet` table keeps its flex layout; the **Type** column (header + each row's Badge cell) is `hidden desktop:block` so it shows on desktop and sheds at tablet.
- **Mobile card list (FR-003).** New **`FileListRowMobile`** (56px two-line: icon + name/meta, trailing size for files / chevron for folders, per-object Details control, selection checkbox + `accent-soft`/inset-`accent`-bar selected treatment). `ParentFolderRow` gained a `variant="mobile"` two-line (`..` / "Up one level") presentation.
- **Bottom bar (FR-005).** `MobileActionBar` carries **New folder + Upload** (≥44px); the top-toolbar New folder/Upload/Create-table group renders at ≥ tablet. Content gets `pb-24 tablet:pb-0` so the fixed bar never occludes the last row. **No header ⋯ overflow menu, no selection mode** (per the product decision).
- **Bulk toolbar (FR-006).** Copy/Move/Delete are labelled at ≥ tablet, **icon-only on mobile** (Delete danger-toned); checkboxes stay always-visible at every width.
- Shared `formatDate` extracted to `fileBrowser.format.ts` (used by table + mobile row).

**Deliberate implementation deviation (reversible/technical):** the spec's AC name a CSS `hidden tablet:grid` / `tablet:hidden` swap. In jsdom Tailwind CSS isn't applied, so both markups would live in the DOM — duplicating every row/button (breaking ~30 tests) and double-mounting. Instead the table-vs-card list and the top-toolbar-vs-`MobileActionBar` are **mount-gated by `useIsMobile()`** (SPEC-095's FR-008 exception-1: matchMedia reads correctly on first paint, so no flash and exactly one tree mounts). User-visible behavior is identical; the responsive intent of every FR is met.

## What changed from earlier specs?

- `Sidebar` (SPEC-057) now composes the extracted `SpacesList` (same DOM). `ParentFolderRow` (SPEC-098) gained a `variant` prop. `FileBrowser` inline `FileRow`/`FolderRow`/`SelectionToolbar` reflowed; `formatDate` moved into `fileBrowser.format.ts`.

## Verification

`format` + `lint` (incl. React Compiler) + `tsc -b` + `build` clean; full suite green (1084, +12). New tests: `FileListRowMobile` (file/folder variants, trailing size/chevron, selected treatment, checkbox, activate/open/details, axe) and a `FileBrowser` mobile block (card-list-not-table, `MobileActionBar` present + read-only omission, icon bulk actions, `..` mobile variant, no overflow menu). `/files` is auth-gated, so the authenticated mobile view wasn't browser-verified (preview can't hold a Cognito session); the breakpoint tokens themselves are browser-verified via SPEC-095.
