# Handoff: File Dashboard — Selection Toolbar, Single-Selection Metadata Panel & Parent-Folder Row

## Overview
Three related changes to the **file browser** (Files tab) of the S3 Upload Portal, worked out as responsive HTML mockups across desktop / tablet / mobile breakpoints:

1. **Move Copy / Move / Delete into a multi-select "selection toolbar"** that sits above the file table and operates on the whole selection (one or many items).
2. **Gate the metadata (Details) panel to a single selection.** Download + Rename live *there* (never in the bulk toolbar), split 50/50 on desktop and stacked full-width on mobile. When two or more items are selected the panel is suppressed entirely.
3. **Add a `..` parent-folder row** at the top of every file listing (all breakpoints) for navigating up one level — hidden only at the space root.

A fourth clarification is baked into the mobile mockup: the three action surfaces stay strictly separated (see **Mobile: three-menu split** below).

## About the Design Files
The file in this bundle — `Responsive Breakpoints.dc.html` — is a **design reference created in HTML**. It is a prototype showing the intended look, layout, and responsive behavior; it is **not production code to copy**. Each screen is rendered at a fixed frame size (desktop 1300px, tablet 820px, mobile 390px) purely to illustrate the breakpoints — there is no live media-query behavior to lift.

The task is to **recreate these designs in the existing codebase** (`apps/portal`, a React/TypeScript app) using its established components, hooks, and styling conventions — not to ship the HTML. The good news: the codebase already has the right structure for all three changes (see **Mapping to the codebase**), so most of this is wiring and small UI moves rather than new architecture.

## Fidelity
**High-fidelity.** Colors, spacing, type, and control sizes are final — see **Design Tokens**. Recreate pixel-accurately using the app's existing component library and Tailwind/utility conventions. Where the mockup and an existing codebase pattern disagree on a class name or token, prefer the codebase's token that matches the hex/px value listed here.

---

## Mapping to the codebase
These already exist (from `apps/portal/info/component-inventory/INDEX.md`) and are the intended integration points:

- **`FileBrowser` (`features/files/FileBrowser.tsx`)** — top-level browser: breadcrumbs, listing, upload/create-folder. Per the inventory, rows already carry an always-visible **Details** button and *"bulk/single actions (download/copy/move/rename/delete) live in the selection toolbar."* This design **narrows the selection toolbar to Copy / Move / Delete only** and moves Download + Rename to the metadata panel. Adjust the toolbar's button set accordingly.
- **`MetadataPanel` (`MetadataPanel.tsx`)** — read-only metadata drawer (close button + Escape). Add the **Download + Rename** action pair to its header region and gate its visibility to `selection.count === 1`.
- **`useSelection()` (`selectionContext.ts`)** — `toggle` / `selectAll` / `clear` / `count` / `isSelected`. Drive both the toolbar (`count >= 1`) and panel (`count === 1`) off this.
- **`useCopy` / `useMove` / `useDelete`** — action orchestration. Note `useMove` covers **both** rename (single) and move (multi-select); rename is a move within the same parent. So the panel's **Rename** button and the toolbar's **Move** button are both `useMove`, just different entry paths (`RenameDialog` vs `MoveDialog`).
- **`getDownloadUrl(...)` / `useObjectMetadata(...)`** — panel's Download action and the read-only property rows.
- **`RenameDialog` / `MoveDialog` / `CopyDialog`** — the dialogs the buttons open.
- **`SelectionProvider`** — already clears selection on prefix change (so navigating via `..` resets selection, which is correct).

No new hooks or services are required. This is: (a) re-partition the toolbar's buttons, (b) add two buttons + a visibility gate to `MetadataPanel`, (c) add a `..` row to the listing renderer.

---

## Screens / Views

### 1. File list + selection toolbar (Desktop, `lg` ≥ ~1280px)
- **Purpose:** Browse a folder, select one or many items, act on the selection.
- **Layout:** App shell is a two-column grid `[248px rail | 1fr main]`. Main = 56px top bar, 52px breadcrumb bar, then the listing area with `16px 20px` padding.
- **Selection toolbar** (new position — above the table, shown whenever `count >= 1`):
  - Full-width bar, `background #eef2ff`, `border 1px solid #dfe3fb`, `border-radius 10px`, `padding 8px 8px 8px 14px`, `margin-bottom 12px`, `display:flex; align-items:center; gap:10px`.
  - Left: **"{n} selected"** label — 13px / 600 / `#4338ca`.
  - Next to it: a **Clear** ghost button — 28px tall, `padding 0 8px`, `border 1px solid #cdd4f6`, transparent bg, `#4338ca`, 12px/500, ✕ icon 13px.
  - Spacer (`flex:1`), then three action buttons, right-aligned:
    - **Copy** and **Move**: 32px tall, `padding 0 12px`, `border-radius 8px`, `border 1px solid #d5dbf5`, `background #fff`, text `#15191e`, 13px/500, `gap 6px`, icon 15px.
    - **Delete**: same metrics but `border 1px solid #f6cfcb`, text `#dc2626`.
  - Icons: Copy = duplicate/overlapping-rects; Move = box-with-arrow-in (`M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4 / M10 8l4 4-4 4 / M14 12H3`); Delete = trash.
- **Table** (`background #fff`, `border 1px solid #e6e8eb`, `border-radius 10px`):
  - Header row 40px, `background #fafbfc`, columns `40px 1fr 120px 180px 120px` = [checkbox, Name, Size, Last modified, Type]. Header labels 12px/600 uppercase `#8a93a2`.
  - Data rows 48px, divider `1px solid #f0f1f3`, 14px text. Checkbox `accent-color #4f46e5`.
  - **Selected row:** `background #eef2ff` and the checkbox `checked`.
  - Name cell: 20px file/folder icon + label. Folders use a **filled** indigo folder (`fill #4f46e5`); files use an outline doc icon (`stroke #8a93a2`). Type column shows a pill: 12px, `padding 2px 8px`, `border-radius 999px`, `background #fafbfc`, `border 1px solid #e6e8eb`, `#5b6573`.
- **`..` parent row** (new — first data row, see **Parent-folder row** below).
- **Behavior shown:** two rows selected (`annual-summary.pdf`, `revenue-model.xlsx`) → toolbar reads "2 selected"; no metadata panel visible in this frame (because count ≥ 2).

### 2. File list + metadata panel (Desktop — single selection)
- **Purpose:** Inspect one file's metadata and Download / Rename it.
- **Layout:** Main area splits `[1fr | 340px]` (`lg:grid-cols-[1fr_340px]`). Left = the listing (with its selection toolbar still visible, reading **"1 selected"** — Copy/Move/Delete remain reachable for the single item). Right = the metadata panel.
- **Metadata panel** (`MetadataPanel`):
  - `background #fff`, left edge `border 1px solid #e6e8eb` (it's the right column).
  - Header strip: `padding 16px 18px`, `border-bottom 1px solid #e6e8eb`. "DETAILS" 13px/600 uppercase `#8a93a2`, spacer, 16px close ✕ (`#8a93a2`).
  - Body `padding 18px`, `gap 18px` column:
    - **Title block:** 26px file icon (outline, `stroke #dc2626` for PDF) + filename 16px/600 (word-break) + subtitle `2.4 MB · PDF document` 12px `#8a93a2`.
    - **Actions row** — the key change. `display:flex; gap:8px`, two buttons **each `flex:1` (50%)**, both 38px tall, `border-radius 8px`:
      - **Download** — primary: `background #4f46e5`, `border 1px solid #4f46e5`, `#fff`, 14px/600, download-arrow icon 16px.
      - **Rename** — secondary: `background #fff`, `border 1px solid #e6e8eb`, `#15191e`, 14px/600, pencil icon 16px.
    - **Properties list:** rows separated by `1px solid #f0f1f3`, `padding 9px 0`, 13px. Label `#8a93a2` left, value `#15191e`/500 right (Type, Size w/ bytes, Last modified, Storage class). Last row (**S3 key**) stacks label over a `JetBrains Mono` 12px value, word-break.
- **Visibility rule:** render this panel **only when `useSelection().count === 1`.** At `count === 0` no panel (nothing selected); at `count >= 2` **disable/hide it entirely** and keep only the selection toolbar. Copy / Move / Delete never appear in this panel.

### 3. File list (Tablet, `md` 768–1279px)
- **Layout:** Same `[248px rail | 1fr]` shell; table sheds the **Type** column → columns `40px 1fr 110px 150px` = [checkbox, Name, Size, Modified]. Listing padding `16px`.
- **Selection toolbar:** same bar, slightly tighter (`gap 8px`, `padding 8px 8px 8px 12px`), no Clear button shown, Copy/Move/Delete labelled buttons right-aligned. Two rows selected in the mock.
- **`..` row:** present (4-column variant).
- Metadata panel becomes a bottom sheet at this width (see mobile).

### 4. File list (Mobile, `< 768px`)
- **Layout:** 56px top bar (hamburger + title + bell + avatar), compact breadcrumb bar with a folder-crumb chip and a header **⋯** button, then a compact list of **56px two-line rows** (no table chrome): icon + (name / meta) + trailing size or chevron. Persistent bottom bar carries **New folder** + full-width **Upload** (44px targets).
- **Selection toolbar (mobile):** appears directly under the breadcrumb as a `flex:none` bar — `background #eef2ff`, `border-bottom 1px solid #dfe3fb`, `padding 9px 14px`. "{n} selected" label left, spacer, then **icon-only** 36px buttons (Copy, Move, Delete) — `border-radius 9px`, `border 1px solid #d5dbf5` (Delete `#f6cfcb`/`#dc2626`), white bg, icon 17px. Selected rows get `background #eef2ff` + `box-shadow: inset 3px 0 0 #4f46e5` + a 22px indigo check-circle replacing the file icon.
- **`..` row:** first row, folder icon + `..` with `Up one level` subtitle.
- **Metadata = bottom sheet:** full-width slide-over (shares the `Drawer` shell with "View members"), header title + close ✕, Escape + backdrop tap to close. **Actions stack full-width** (not 50/50): Download (primary, 44px, `border-radius 10px`) then Rename (secondary, 44px) in a `flex-direction:column; gap:10px` container. Then the read-only properties.

#### Mobile: three-menu split (definition)
Keep these three surfaces strictly separate — do not let them overlap in responsibility:
- **Header `⋯` (overflow):** folder / page-level actions only — **New folder, Upload, Sort, Select** (enter selection mode).
- **Single-row tap → details sheet:** the single-item surface — **Download + Rename** (+ read-only metadata).
- **Multi-select toolbar:** selection actions only — **Copy / Move / Delete**.

---

## Interactions & Behavior
- **Selection drives everything.** `count === 0`: no toolbar, no panel. `count === 1`: toolbar ("1 selected", Copy/Move/Delete) **and** metadata panel (Download/Rename/metadata). `count >= 2`: toolbar only ("{n} selected"); metadata panel hidden/disabled.
- **Clear** button (desktop toolbar) → `useSelection().clear()`.
- **Copy** → `CopyDialog` → `useCopy` (multi-select copy; same-folder auto-number `{name} (N)`).
- **Move** → `MoveDialog` → `useMove` (multi-select move).
- **Rename** (panel, single only) → `RenameDialog` → `useMove` (rename = move within same parent).
- **Download** (panel, single only) → `getDownloadUrl({ bucket, key, fileName })`, presigned `GetObject`, attachment disposition.
- **Delete** → `useDelete` (mixed file/folder selection; files batched, folders recursive). Surface results via `OperationSummaryBanner`.
- **`..` row click** → navigate to the parent prefix (drop the last path segment of the current prefix). `SelectionProvider` clears selection on prefix change — expected.
- **Responsive:** table→two-line-list swap at `md` (`hidden md:grid` / `md:hidden`); Type column drops below `lg`; metadata panel → bottom sheet below `lg`; panel actions go 50/50 → stacked at the sheet breakpoint.

## Parent-folder row (`..`) — all breakpoints
- **When:** render as the **first listing row** whenever the current prefix is **not** the space root. Omit at root.
- **Not selectable:** no checkbox (leave the checkbox grid cell empty); it is navigation, not an item. Exclude it from `selectAll` and from `count`.
- **Desktop/tablet (grid rows):** height 48px, `cursor:pointer`. Name cell = 20px **filled indigo** folder icon (`fill #4f46e5`) + `..` label (14px/500, `#5b6573`). Size cell = `—` (`#8a93a2`). Remaining cells empty.
- **Mobile (flex row):** height 56px. Folder icon + two lines: `..` (15px/500 `#5b6573`) over `Up one level` (12px `#8a93a2`). No trailing chevron.

## State Management
- `useSelection()` set (`toggle`/`selectAll`/`clear`/`count`/`isSelected`) — single source for toolbar + panel visibility. Ensure the `..` row is never added to the selection set and `selectAll` skips it.
- Active space / prefix from `useFileSpace(...)`; `..` computes the parent prefix from the current prefix; root check = prefix equals the space `rootPrefix`.
- Per-object metadata via `useObjectMetadata(bucket, key)` (disabled when key is null / count ≠ 1).
- Dialog open/close state for Copy/Move/Rename; delete confirmation.

## Design Tokens
**Colors**
- Indigo primary `#4f46e5`; indigo text/active `#4338ca`; indigo tint bg `#eef2ff`; tint border `#dfe3fb`; tint-button border `#d5dbf5`; ghost-button border on tint `#cdd4f6`.
- Text: primary `#15191e`, secondary `#5b6573`, muted `#8a93a2`.
- Borders/dividers: card/border `#e6e8eb`, row divider `#f0f1f3`, device frame `#d5d9df`.
- Surfaces: white `#fff`, subtle fill / pill `#fafbfc`, page bg `#f7f8fa`.
- Danger: `#dc2626`; danger border (light) `#f6cfcb`, (lighter) `#fdeceb`.

**Radii:** buttons 8px (desktop) / 9–10px (mobile); bars & cards 10px; pills 999px; frames 16–22px.

**Spacing:** listing padding `16px 20px` (desktop) / `16px` (tablet); bar padding `8px 8px 8px 14px`; bar `margin-bottom 12px`; panel body `padding 18px`, `gap 18px`; property rows `padding 9px 0`.

**Control heights:** grid rows 48px; mobile list rows 56px; top bar 56px; breadcrumb bar 52px; desktop toolbar buttons 32px (Clear 28px); mobile toolbar icon buttons 36px; panel action buttons 38px (desktop) / 44px (mobile); mobile hit targets ≥ 44px.

**Typography:** system UI stack for content; **JetBrains Mono** for S3 keys / code chips (12px). Sizes — row text 14px, secondary/property 13px, meta 12px, panel filename 16px, section labels 12–13px/600 uppercase.

**Icons:** inline stroke SVGs, `stroke-width 2`, sizes 13–20px per context. Copy = overlapping rects; Move = box-with-in-arrow; Delete = trash; Download = down-arrow-to-line; Rename = pencil; Folder = filled indigo folder; check = ✓ in a 22px indigo circle.

## Assets
No image assets — all icons are inline SVG paths (reproduce with the codebase's existing icon set / lucide-equivalents). No fonts to ship beyond the app's existing system stack + JetBrains Mono (already used for keys).

## Files
- `Responsive Breakpoints.dc.html` — the full responsive mockup. Relevant frames: **FILES · DESKTOP** (selection toolbar + `..` row, 2 selected), **FILES · TABLET**, **FILES · MOBILE — FINAL** (mobile toolbar + `..` + three-menu split), **FILES · METADATA PANE (DESKTOP)** (single-selection panel + "1 selected" toolbar + `..` row), **FILES · METADATA SHEET (MOBILE)** (stacked Download/Rename). Each frame has a caption card beneath it restating the intent.
- Codebase targets: `features/files/FileBrowser.tsx`, `MetadataPanel.tsx`, `SelectionProvider.tsx` / `selectionContext.ts`, `useCopy.ts`, `useMove.ts`, `useDelete.ts`, `RenameDialog`/`MoveDialog`/`CopyDialog`.
