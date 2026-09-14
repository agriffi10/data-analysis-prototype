# Design System — Data Quarry

**Aesthetic:** Clean / minimal SaaS. Generous whitespace, neutral grays, a single accent (indigo), light hairline borders, table-forward layouts. Reads as trustworthy enterprise tooling.

This doc is the source of truth for the look. The companion file `file-management.html` is a live, interactive realization of these tokens (file browser + upload flow). The CSS variables in the mockup match the token tables below 1:1, so changes can be made in either place and kept in sync.

**Stack mapping:** Tokens below are written as CSS custom properties, and the app declares them to Tailwind v4 in the `@theme` block of `apps/portal/src/index.css` (§4). Prefer the Tailwind tokens in components; the CSS variables exist for the mockup and for any raw CSS.

---

## 1. Color

Single accent system — one indigo accent does all the "primary action / active / focus" work. Everything else is neutral gray. Status colors are reserved for state (success / warning / danger), never decoration.

### Neutrals

| Token | Hex | Use |
|---|---|---|
| `bg` | `#f7f8fa` | App canvas behind panels |
| `surface` | `#ffffff` | Cards, panels, table, rows |
| `surface-2` | `#fafbfc` | Table header, hover fills, inset fields |
| `border` | `#e6e8eb` | Default hairline borders |
| `border-2` | `#f0f1f3` | Lighter row dividers |

### Text

| Token | Hex | Use |
|---|---|---|
| `text` | `#15191e` | Primary text, file names, headings |
| `text-2` | `#5b6573` | Secondary — metadata, labels |
| `text-3` | `#8a93a2` | Muted — placeholders, captions, disabled |

### Accent (indigo)

| Token | Hex | Use |
|---|---|---|
| `accent` | `#4f46e5` | Primary buttons, active nav, folder icon, progress |
| `accent-hover` | `#4338ca` | Hover state of primary |
| `accent-soft` | `#eef2ff` | Active nav background, selected row, soft hover |
| `accent-text` | `#4338ca` | Accent-colored text/links on light bg |

### Status

| Token | Hex | Soft bg | Use |
|---|---|---|---|
| `success` | `#0f9d6e` | `#e7f7f0` | Upload complete, validation passed |
| `warning` | `#c2820a` | `#fdf4e3` | Overwrite confirm, non-atomic op warning |
| `danger` | `#dc2626` | `#fdeceb` | Delete actions, errors |

> Focus ring: 2px solid `accent`, offset 2px — solid rather than a 40% tint, so the ring itself clears 3:1 (WCAG 1.4.11; the `:focus-visible` rule in `index.css`). Never rely on color alone for state — pair with icon or text (accessibility).

---

## 2. Typography

System-safe Inter stack. One typeface, weight + size carry hierarchy. Base size is **14px** — appropriate for a dense, data-oriented tool while staying readable.

```
font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
```

| Token | Size | Weight | Use |
|---|---|---|---|
| `text-xs` | 12px | 500/600 | Pills, captions, uppercase labels |
| `text-sm` | 13px | 400/500 | Secondary metadata, queue subtext |
| `text-base` | 14px | 400/500 | Body, table rows, buttons (default) |
| `text-md` | 16px | 600 | Panel/section titles, brand |
| `text-lg` | 18px | 600 | Page titles |
| `text-xl` | 22px | 600/700 | Empty-state headlines |

- Uppercase micro-labels (sidebar section headers, table column headers): `text-xs`, weight 600, `letter-spacing: .03–.04em`, color `text-3`.
- Line-height: 1.5 for prose; 1 for single-line table/UI rows.

---

## 3. Spacing, radius, shadow

**Spacing** — Tailwind's default scale, which the app does not override. One step is `--spacing: 0.25rem` and the root font is 14px (`html { font-size: 14px }` in `apps/portal/src/index.css`), so **a step is 3.5px, not 4**, and every spacing-scale class — padding, margin, gap and the `h-*` / `w-*` / `min-h-*` sizes — measures 7/8 of what the same class would under the browser's default 16px root. For padding, margin and gap, use these steps only and avoid arbitrary px; a value that encodes a threshold or a fixed width is written in px instead (§8).

| Step | `sp-1` | `sp-2` | `sp-3` | `sp-4` | `sp-5` | `sp-6` | `sp-8` | `sp-10` |
|---|---|---|---|---|---|---|---|---|
| px | 3.5 | 7 | 10.5 | 14 | 17.5 | 21 | 28 | 35 |

`sp-N` is this doc's name for Tailwind step N (`p-N`, `gap-N`, `h-N`, …). Elsewhere in this doc a size is given as its class and the px it renders, e.g. `h-12` (42px). What is written in px renders as written: the type sizes, radii, shadows and breakpoints the theme declares, border and ring widths, and arbitrary values such as `w-[248px]`. A Tailwind default the theme does not redeclare is in rem and shrinks the same way — `max-w-lg` on a dialog is 448px, and `rounded-t-xl` on the drawer's bottom sheet is 10.5px.

**Radius**

| Token | Value | Use |
|---|---|---|
| `r-sm` | 6px | Inputs, small chips, icon buttons |
| `r-md` | 8px | Buttons, nav items, queue items |
| `r-lg` | 10px | Cards, table container, dialogs, drawer panels |
| `r-full` | 999px | Pills, avatars, progress bars |

**Shadow** — kept minimal; elevation is mostly borders + surface, shadows only for floating layers.

| Token | Value | Use |
|---|---|---|
| `shadow-sm` | `0 1px 2px rgba(16,24,40,.05)` | Resting cards (optional) |
| `shadow-md` | `0 4px 12px rgba(16,24,40,.08)` | Popovers, dropdowns |
| `shadow-lg` | `0 12px 32px rgba(16,24,40,.14)` | Drawer, modal dialog, toasts |

**Key layout dimensions:** top bar `h-14` (49px, §5), Query editor toolbar at least 52px (`min-h-[52px]`), file-table row `h-12` (42px), sidebar `w-[248px]` (the Query rail is `w-[220px]` until `desktop`).

---

## 4. Tailwind theme (`@theme`)

The app configures Tailwind v4 in CSS and has no `tailwind.config.ts`. The tokens are declared in the `@theme` block at the top of `apps/portal/src/index.css`, and each namespace there mints its utilities: `--color-*` (`bg-surface`, `text-text-2`), `--font-*` (`font-sans`), `--text-*` with its paired `--text-*--line-height` (`text-base`), `--radius-*` (`rounded-lg`), `--shadow-*` (`shadow-md`) and `--breakpoint-*`, where Tailwind's five defaults are reset so only `tablet:` (900px) and `desktop:` (1300px) exist. This section says how the tokens reach Tailwind rather than repeat their values. The dark theme overrides the `--color-*` values under `:root[data-theme='dark']` in the same file, and a shadow is themed through its `--shadow-tint-*` rather than `--shadow-*`, because Tailwind inlines a shadow's value into the utility (the comment above `--shadow-sm` says why).

The block declares no `--spacing`, so the spacing scale is Tailwind's default `0.25rem`, which is 3.5px against the 14px root (§3).

---

## 5. Component patterns

These map to the feature-folder + shared-component conventions in `CLAUDE.md` (components in `src/components/`, feature UIs in `src/features/<name>/`).

### Buttons
- **Primary** — `bg-accent text-white`, hover `bg-accent-hover`, `h-9` (31.5px) at `Button`'s default `md` size, `rounded-md`, `px-4` (14px), `gap-2` (7px) to icon. One per context (the main action, e.g. Upload).
- **Default** — `bg-surface border border-border text-text`, hover `bg-surface-2`. Secondary actions (New folder, Cancel).
- **Ghost** — transparent, hover `bg-surface-2`. Toolbar actions (Copy and Move on the selection bar; Clear, Save and Create view on the editor toolbar).
- **Danger-ghost** — transparent, `text-danger`, hover `bg-danger-soft`. Delete.
- Disabled: `opacity-45`, `cursor-not-allowed`. Icons `h-4 w-4` (14px), stroke-width 2.

### Top bar
One bar on every route but the landing page (`/`): `h-14` (49px against the app's 14px root) on `surface`, with a bottom `border` hairline. Left to right: the hamburger, the brand mark (a `rounded-md` `accent` square holding a white database icon, then the **Data Quarry** wordmark in `text-md` weight 600), the primary tabs, a spacer, **Help**, **Notifications** and **Theme**, then the account trigger. What a signed-in user sees depends on the width:

| Width | Left of the spacer | Right of it |
|---|---|---|
| Below `tablet` (under 900px) | the hamburger, which opens `AppNavDrawer`; the brand square | Help, Notifications and Theme as icons alone; the avatar and the kebab |
| `tablet` (900–1299px) | the brand square; the tabs, as text only | the three controls, each with its word; the avatar and the kebab |
| `desktop` (1300px and up) | the square and the wordmark; the tabs, each with its icon | the three labelled controls; the avatar, the username and the kebab |

- **Tabs** — Files, Query, Data Explorer, Connections and Data quality, each *removed* (not disabled) when its feature flag is off, and all of them absent while the flags load. Underline tabs the full height of the bar: `text-base` weight 500, `text-2` at rest and `text` on hover; the **active** tab is `accent-text` over a 2px `accent` bottom border, which keeps it distinct from the sidebar's filled `accent-soft` item so the two levels of navigation read differently. The route drives the active tab, so a deep link or back/forward sets it. A label never wraps. Below `tablet` the same destinations, under the same flags, are rows in the drawer, followed by Notifications and Help.
- **Help, Notifications, Theme** — one control style (`components/headerControl.ts`): an icon, its word beside it from `tablet`, `text-3` at rest, and `accent-text` on `surface-2` for the route you are on or the panel or menu it has open. Help opens the page's guide panel where one covers the route, and links to `/help` everywhere else; Notifications links to `/notifications`, with an `accent` unread count on the bell capped at `9+`; Theme opens a Light / Dark / System menu.
- **Account trigger** — the avatar (a gradient circle carrying the username's first two characters, uppercased), the username in `text-2` from `desktop`, capped with an ellipsis, and a kebab that says a menu is there to open. The menu holds **Give feedback**, a separator, then **Sign out** in `danger`.
- **Signed out** there is no hamburger, no tabs and no account trigger: the wordmark shows at every width, followed on the right by Theme and a primary **Sign in**.

Why the words stay at `tablet` while the wordmark, the tab icons and the username wait for `desktop`, and what that costs between 900 and 1299px, is the register entry [At `tablet` the words stay and the decoration waits](../decisions/browser.md#at-tablet-the-words-stay-and-the-decoration-waits--the-top-bar-and-the-selection-toolbar-2026-09-10), which rests on *What paid for the room is the WORDMARK* in the [dark-palette entry](../decisions/browser.md#the-dark-palette-is-derived-under-the-harness-not-chosen-and-the-theme-boundary-put-four-fences-there-spec-210).

### Sidebar (248px) — the Files-tab Spaces list
Surface panel, right hairline border. On the **Files** tab the sidebar is a single **Spaces** list (SPEC-057): the user's **personal** space first (its item labelled with the Cognito `username`), then each **active** shared connection (alphabetical) — so "My Files" reads as `alice`, `marketing_data`, `sales_2026`, … all in one list. Nav items: 34px tall — `py-2` (7px a side) around `text-base`'s 20px line — `rounded-md`, icon + label; **active** (the space being browsed) = `bg-accent-soft text-accent-text`; hover = `bg-surface-2`. A shared space that is not active shows its status as trailing `text-3` text (§7) and is **disabled** (you can't browse a not-ready space). Selecting a space roots the file browser at that space's bucket/prefix (personal → `{username}/`; shared → `dat-prod-shared-space/{name}/`). **Managing** spaces (create/delete, members) is **not** here — it lives in the **Connections** top-level tab (§7); an optional "Add connection" affordance in this list just links there. (The Connections surface is detailed in §7; its companion mockup is `shared-connections.html`.)

### Breadcrumbs
In the toolbar. Each earlier segment is a button in `text-2` that turns `text` and underlines on hover; `/` separators in `text-3`; final (current) segment is `text` weight 600, non-interactive. Maps directly to the S3 key path under `{username}/`.

### File table
Container: `surface`, `border`, `rounded-lg`, clipped. Header row `h-10` (35px) on `surface-2`, uppercase `text-xs` column labels. Flex columns share width constants so the header and rows line up: checkbox `w-10` (35px, only where rows are selectable), name `flex-1`, size `w-24` (84px), modified `w-40` (140px), type `w-28` (98px, from `desktop` only), then an actions column `w-44` (154px).
- Rows `h-12` (42px), divider `border-2`, hover `surface-2`, **selected** `accent-soft`.
- Name cell: `h-5 w-5` (17.5px) icon (folder = `accent` fill, file = `text-3` stroke) + filename (weight 500, ellipsis-truncated).
- Size / modified in `text-2 text-sm`; type as a neutral **pill** (`surface-2` bg, `border`, `rounded-full`, `text-xs`).
- Checkbox `accent-color: accent`. The actions column's **Details** button is always visible; nothing is revealed on hover.
- Pagination: the shared **Pager** (Prev — *Page N* — Next) below the table, one `ListObjectsV2` page per browser page (25 entries; the page count appears only once the last server page has loaded). Shown only for a folder that does not fit on one page. The destination picker keeps the centered ghost **Load more** (`ListObjectsV2` is capped at 1000 keys — see architecture.md → *Constraints that shape the system*; both pair with TanStack `useInfiniteQuery`).

### Selection bar
A second bar below the toolbar, which it does not replace, shown whenever the folder has contents. Master checkbox, the count, a spacer, then the batch actions. With nothing selected it is a plain `surface` bar reading "Select all" in `text-3`; once a row is selected it turns `accent-soft` with an `accent` border and the count reads "N selected" (`accent-text`, weight 600). The actions, in order: **Check data quality** (only where the data-quality feature is on), **Send to…**, **Archive** (except inside `archive/`), then **Copy**, **Move** and **Delete** (danger-ghost). Download and Rename are not here; they live in the details panel. The actions are icons alone below `tablet`, words alone at `tablet` and both at `desktop`, and from `tablet` up the count truncates rather than push an action out; the top bar's [register entry](../decisions/browser.md#at-tablet-the-words-stay-and-the-decoration-waits--the-top-bar-and-the-selection-toolbar-2026-09-10) covers this bar too.

### Upload drawer (right slide-over)
The shared `Drawer`: a `max-w-[440px]` panel from `tablet` and a full-width bottom sheet below it (`max-h-[85dvh]`), `shadow-lg`, over a 30%-black, blurred scrim (`bg-black/30 backdrop-blur-sm`). Header shows the destination prefix. Body:
- **Dropzone** — dashed `border`, `surface-2`, hover → `accent` border + `accent-soft` fill. Headline + "browse" link + hint line ("Up to 5 GB per file · multipart handled automatically" — reflects `VITE_MAX_UPLOAD_BYTES` and `@aws-sdk/lib-storage` auto-multipart from SPEC-016).
- **Queue** — uppercase count label, then one card per file: `h-7 w-7` (24.5px) file-type chip, name + subtext (size · bytes-transferred), `h-1.5` (5.25px) `accent` **progress bar**, and a right-aligned status: `✓ Done` (success), `62%` (accent), `Queued` (muted). Per-file cancel (SPEC-020), which becomes a dismiss once the upload is done, failed or cancelled, is revealed when the card is hovered or the button has focus, and is always shown where the primary input cannot hover, as on a phone, since there the hover reveal never applies and a tap focuses the button only as it fires it, if at all.

### Overwrite confirm dialog (warn-and-confirm)
Centered modal, `rounded-lg`, `shadow-lg`. Warning-circle icon (`warning` on `warning-soft`) + title + explanation naming the conflicting key in `<code>`. Footer on `surface-2` with three actions: **Keep both (rename)**, **Cancel**, **Overwrite** (primary). This is the HEAD-check → Overwrite-or-Rename flow required because versioning is off (architecture: "No overwrite protection from S3").

### Empty / error states
Missing `connections.json` or an empty folder renders as a friendly empty state (icon + `text-xl` headline + `text-2` guidance + primary CTA), **not** an error — per architecture.md → *Constraints that shape the system*.

---

## 6. Data analysis surface (Query workspace)

The portal's second surface — the Glue/Athena **Query workspace** (SPEC-034→036) — reuses every token and most components from the file browser; **no new tokens are introduced**. The companion file `query-workspace.html` is the live realization of this section, exactly as `file-management.html` is for the file browser. Where a component already exists (table, pill, button, drawer), reuse it rather than building a parallel one.

### Primary tab navigation
The primary tabs are the top bar's (§5 *Top bar* carries their look and how they change with the width); Query is one of them. **Connections** (SPEC-052) is the place to *manage* shared spaces (create/delete, member management). Files and Query *use* spaces: **Files** lists the user's spaces (personal + shared) as browsable roots (§5, SPEC-057) and **Query** lists their databases (personal + shared) in the schema rail (below, SPEC-047). So a shared connection is managed under Connections, browsed under Files and queried under Query, fed by one `useConnections` source.

### Schema browser (left rail)
The rail is **browse-only**. There is **no active database**: nothing in it chooses what a query runs against, so every base table a query reads is written `database.table` — the register entry [Query workspace has NO active database](../decisions/analytics.md#query-workspace-has-no-active-database-spec-077) records why.

**Chrome** (`components/CollapsibleRail.tsx`, shared with the Files sidebar). A `surface` panel with a right hairline, `w-[248px]` at `desktop` and `w-[220px]` in the `tablet` band. Its header carries the uppercase `Databases` caption and a **Collapse sidebar** control; collapsing eases the panel to zero width and leaves a slim **Show sidebar** handle to reopen it. The panel stays mounted, so whatever is expanded inside it survives a collapse. Collapsed or open is one choice, shared by both rails and remembered per browser, so collapsing either collapses the other. Below `tablet` the rail is not rendered; the same tree sits in `AppNavDrawer`'s contextual slot under the same caption.

**The tree** (`features/query/SchemaBrowser.tsx`, `DatabaseNode.tsx`). One node per database the user can reach, in `useConnections` order: the personal database first, labelled with the username, then each shared connection A–Z. With the shared-workspaces flag off, the rail lists the personal database alone. A usable database is a disclosure button — rotating chevron, database icon, then the label in `text-base` weight 600, `text-2` turning `text` on hover — whose accessible name reads "Expand {name}" or "Collapse {name}". On first reveal the personal database is expanded and every other node collapsed. The user's toggles hold only while the tree stays mounted: leaving `/query` resets them, and in the drawer every open is a first reveal. A node reads its schema only while expanded, and an expanded node gains a **Refresh tables in {name}** icon button that re-reads that one database, spinning and disabled while it does, without opening or closing anything. A shared connection that is `provisioning`, `failed`, `leaving` or `deleting` is a **static row** instead: a blank where the chevron would be, the icon and label in `text-3`, and its status as trailing `text-xs` text ("Provisioning…", "Failed", "Leaving…", "Deleting…"). It cannot be expanded. With no databases at all the rail reads "No databases available."

**An expanded node.** While its schema loads it reads "Loading schema…". A database Glue reports as not existing reads as setup rather than failure — "Setting up your database… This is automatic right after sign-up. If it persists, contact an administrator." — and any other failure is an alert in `danger`: "Couldn't load this schema. Try Refresh, or contact the Administrator." A loaded schema splits into two collapsible groups, **Tables** and **Views**, each headed by an uppercase `text-xs` caption with its count (`Tables (3)`); a Glue `VIRTUAL_VIEW` is a view and everything else a table, so the group conveys the type and no row carries a badge. Tables starts open, Views starts open only when there is at least one view, and a click on either pins it. An empty group keeps its heading, `(0)`, and says "No tables." or "No views." when open, so an empty Views group shows only its heading until clicked. Each object row is a 32px disclosure button — `py-2` (7px a side) around `text-sm`'s 18px line; a table glyph, the name in weight 500, a trailing chevron — that reveals its columns indented `pl-8` (28px) beneath it, each `name` beside a right-aligned monospace `text-xs` `text-3` type, or "No columns".

**No click-to-insert.** Nothing in the rail writes into the editor: rows open and close, and columns are there to read. Names reach the editor through autocomplete instead, which offers every accessible database's tables and views fully qualified (`database.table`) and their columns by bare name (`features/query/sqlCompletions.ts`).

### Table options menu (SPEC-044)
Every table and view row ends in a **kebab (⋮)** trigger (`features/query/TableActionsMenu.tsx`): `h-[24px]` (24px), `text-3`, named "Options for {table}", and hidden until the row is hovered or holds focus, except where the primary input cannot hover, as on a phone, where it is always shown. The hover reveal applies only where the primary input can hover, and Safari does not focus a tapped button, so on an iPhone nothing would reveal it at rest. It opens the shared `Menu` primitive (`components/Menu.tsx`): a `surface` panel with `border`, `rounded-md` and `shadow-md`; focus moves to the first item that can act, Arrow Up/Down move between items, Escape closes and returns focus to the trigger, and an outside click closes. Opening it never toggles the row. Items are `text-sm` rows with no icon, a disabled one at 45% opacity. Each action takes its database from the node the row sits in (`features/query/useTableActions.tsx`), in this order:

- **View source files** opens Files at the table's data folder, in that node's space. It is disabled unless the table's `LOCATION` lies inside that space, bucket and prefix both, so a view (which has no location) and a table pointed elsewhere both show it disabled.
- **View DDL** runs `SHOW CREATE TABLE`, or `SHOW CREATE VIEW` for a view, and opens the result unrun in a new `DDL: {table}` tab. An info toast says it is loading; a failure is a `danger` toast.
- **View data** opens a `{table}` tab holding `SELECT * FROM {database}.{table}` and runs it.
- **Explore data** opens the Data Explorer on the table, a view included. It is shown only while the Data Explorer flag is on.
- **Refresh table** (base tables only) opens the Refresh dialog, and is disabled when the table has no location.
- **Share table** (base tables only) opens the Share dialog.
- A hairline, then **Drop table**, or **Drop view** for a view, in `danger` (`danger-soft` hover). It asks first, in a danger `alertdialog` that reads "Dropping…" while the statement runs; the outcome is a toast, and the run is recorded in the query history like any other statement.

A tab-opening action at the ten-tab cap raises the tab-limit dialog instead. Below `tablet`, where there is no editor, View DDL shows the statement in the read-only view and View data runs into the mobile results view.

### SQL editor (Monaco)
A resizable editor pane below the toolbar, split from the results by a draggable divider. It opens at half the editor-and-results column (`DEFAULT_EDITOR_FRACTION`), remembers the split per user for the tab's session (`sessionStorage`), and keeps the editor at least 96px (`MIN_EDITOR_HEIGHT`) and the results at least 120px (`MIN_RESULTS_HEIGHT`), both in `features/query/query.constants.ts`. Left **gutter** on `surface-2` with a `border-2` right divider and monospace `text-3` line numbers; code area is monospace `text-sm`, line-height 1.7. Syntax theme maps onto tokens: **keywords** `accent-text` weight 600, **strings** `success`, **numbers** `warning`, **comments** `text-3` italic, **functions** a violet (`#7c3aed`) that sits beside the indigo accent without becoming a second brand color. The real editor is Monaco (SPEC-035), lazy-loaded for the Query route only.

### Query tab strip (SPEC-041, SPEC-043)
An `h-10` strip (35px) on `surface-2` with a bottom hairline, sitting **above the editor toolbar**. It holds the open query tabs — each an independent query window — so it must read as a *third*, narrower level of navigation, visually distinct from both the top bar's underline tabs (§5) and the sidebar's filled `accent-soft` item. These are **"card" tabs**: an `h-7` (24.5px) `r-md` chip, `text-sm` weight 500, `text-2` at rest → `text` + `surface` background on hover; the **active** tab is `surface` with a `border` hairline, `shadow-sm` and a weight-600 label (so active state is never color-only), and carries no leading dot, which would read as the dirty marker below. **Labels:** blank `+` tabs are the monotonic `Query N` (never reused this session); tabs opened from a **saved query** (SPEC-043) or a **table action** (SPEC-044) carry a feature-supplied label (`Monthly revenue`, `sales_2026`, `DDL: sales_2026`). A linked saved-query tab with unsaved edits shows a leading **`accent` dirty dot/•** before its name (re-save clears it). Each tab carries a trailing close (`×`) hit target that tints `danger`/`danger-soft` on hover; closing a tab with non-empty SQL warns-and-confirms first (reuse the SPEC-026 dialog). The **last remaining tab hides its close control** (there is always ≥1 tab). A `+` ghost button at the start of the strip (`aria-label="New query tab"`) adds a tab and is **never disabled** — at the `QUERY_TABS_MAX = 10` cap, clicking it (or any other tab-opening action) raises the **tab-limit dialog** (a SPEC-026 `alertdialog`: "You have the maximum of 10 query tabs open. Close a tab before opening another." — single dismiss; the attempted action is not completed). The tab list scrolls horizontally if tabs overflow, leaving the `+` and the global buttons in place. **Global buttons** live right-aligned on this same strip (right of the tab list, which takes the spare width), because they act across all tabs: **Saved queries** and **History** (compact ghost `bar-btn`s), hoisted here out of the per-tab toolbar (SPEC-043 FR-010). The active tab drives the editor content and all per-tab toolbar actions (Run / Clear / Save / Stop) below it.

### Editor toolbar
A `surface` row with a bottom hairline, at least 52px tall (`min-h-[52px]`), that wraps rather than overflows. There is **no database chip**, and the left of the row is empty. Everything sits in a right cluster of per-tab editor actions, acting on the active tab (SPEC-041): **Clear** (ghost, trash — SPEC-040; warn-and-confirm, disabled while running/empty), **Save** (ghost, save icon — SPEC-043; name-prompt, pre-filled when linked, disabled when empty), **Create view** (ghost, SPEC-048; opens a name-prompt and runs `CREATE OR REPLACE VIEW` in the background, disabled when empty), then **Run** — the one primary control, a split button: **Run Statement** (play icon; the selection or the statement under the cursor, ⌘/Ctrl+Enter) with a **More run options** menu holding **Run Query Tab** (⌘/Ctrl+Shift+Enter) and **Run Multiple Queries** (⌘/Ctrl+Alt+Enter). Run is disabled when the editor is empty; while a query is in flight **Stop** (danger-ghost, square) takes its place. The words show at `desktop`; in the `tablet` band the buttons are icons alone, each keeping its `aria-label`, and below `tablet` the workspace is browse-first and has no editor toolbar. **History and Saved-queries are not here** — they're on the global tab-strip row above (SPEC-043 FR-010).

### Status bar
A slim bar below the editor, `tablet:h-11` (38.5px) from `tablet` and `min-h-11` below it, where it wraps, showing execution state, **never color-only** — always icon/spinner + text: **Running** = `accent-text` with a spinner + an indeterminate `accent` progress sliver + elapsed time and bytes scanned; **Succeeded** = `success` dot + "N rows · X scanned · Ys"; **Failed** = `danger` dot + "Failed", the reason itself carried by the workspace's `danger` **Banner** (SPEC-028) as **authored wording** mapped through `lib/errorMessages.ts` — the raw Athena `stateChangeReason` is **never** rendered; **Cancelled** = `text-3` dot + "Cancelled". A right-aligned **Save results to my files** ghost button (SPEC-049 — replaces the old "Download CSV") sits beside **whichever terminal state is showing** (a state is required, not merely the absence of a spinner), whenever the displayed result is row-returning: a batch that failed at statement 3 can still save statement 1's rows, which are complete and already billed. Beside **Failed** or **Cancelled** it is preceded by a `text-2` note naming what it would write — "N rows from an earlier statement" — because `script-single` scope has no result-tab strip to identify the grid; the failed statement's own scanned/duration figures stay off the bar, so the two executions never read as one. The bar is an accessible live region.

**Save-results modal (SPEC-049).** "Save results to my files" opens a SPEC-026 centered modal: a **destination folder** picker (reuses the file-browser `DestinationPicker`, the user's own space — plus any shared spaces they belong to, SPEC-055 — excluding each `athenaresults/`) + a **file name** `Input` defaulted to `query-results-{YYYYMMDD-HHmm}`, a **Format** `<select>` (CSV / Parquet / JSON / Excel, defaulting to CSV, and **absent** — not disabled — behind the `resultsConversion` flag), and Save/Cancel. The extension follows the chosen format and replaces another one the user had typed. **Either way the whole result set travels**, not the loaded page, and either way a collision runs the standard overwrite warn-and-confirm. **CSV** is a server-side copy of Athena's own result object: immediate, the primary button reads **Save here**, and the success **Toast** carries a "view in Files" deep-link. **Parquet, JSON and Excel** are built by the results-conversion plane: the button reads **Convert and save**, the modal closes on submit, and the toast promises a notification rather than a file — nothing is written yet, so no listing changes until that notification arrives (SPEC-223).

### Results table (reuses the file table)
Same container as the file table: `surface`, `border`, `rounded-lg`, clipped; `h-10` (35px) `surface-2` header with uppercase `text-xs` column labels — here each header stacks the column **name** over its **type** in a small monospace caption (the type also available as the neutral **pill**). Rows are monospace `text-sm`, `h-12` (42px), `border-2` dividers, `surface-2` hover, with a leading muted row-number column. Wide result sets scroll horizontally inside the panel without breaking the shell. Pagination reuses the centered ghost **Load more** (`GetQueryResults` `NextToken`, mirrors listing pagination). Empty result sets (successful DDL, zero-row SELECT) render the friendly empty state, not an error.

### Query history drawer (right slide-over, reuses the upload-drawer pattern)
The shared `Drawer` again — `max-w-[440px]` from `tablet`, `shadow-lg`, over the same 30%-black scrim — identical mechanics to the upload drawer. The drawer header carries a **Refresh** icon-button (SPEC-046) in its `headerAccessory` slot (a ghost `IconButton`, `aria-label="Refresh history"`) that re-reads `query-history.json` from S3 on demand — disabled with a spinner while in flight, resets to the newest page on success, and surfaces a read error as a `Banner` without dropping the current list. Each entry is a bordered `r-md` card: a status **badge** (`success`/`danger`/neutral soft fills with a leading dot — never color-only), a right-aligned relative timestamp (absolute on hover), a single-line monospace SQL preview (ellipsis-truncated), a footer with run stats (`rows · scanned · duration`) and right-aligned **Open** / **Re-run** text actions (`accent-text`). History is the per-user `{username}/user_settings/query-history.json` store only — it never shows other users' or workgroup-wide queries. **Pagination (SPEC-042):** the drawer shows the **7 most recent** entries (newest-first) with a footer **pager** — a `text-2` range label in the form `1–7 of N` on the left and ghost **Prev** / **Next** buttons on the right (Prev disabled on page 1, Next disabled on the last page). It is a *replace* pager (one page of ≤7 in the DOM), mirroring the results pager (SPEC-038), not append; it resets to the newest page when the drawer is reopened or a new query is run.

### Saved queries drawer (SPEC-043)
A second right slide-over with the **same mechanics as the history drawer** (`max-w-[440px]`, `shadow-lg`, scrim, Escape/scrim/close-button dismiss). Opening one closes the other. Each entry is a bordered `r-md` card: the saved query's **name** (weight 600), a right-aligned relative **updated** time, a single-line monospace **SQL preview**, and right-aligned **Open** (`accent-text`) + **Delete** (`danger`) text actions. **Open** routes through `openTab` (named, linked tab; honors the tab-limit dialog). **Delete** raises an "are you sure" `alertdialog`. Empty state: "No saved queries yet — Save a query to see it here." v1 shows the full list (no pager).

### Confirm dialogs & name prompt (SPEC-026 reuse)
All modals reuse the SPEC-026 centered-modal pattern (scrim `bg-black/40`, `surface` panel, `r-lg`, `shadow-lg`, header title + body, a `surface-2` footer with right-aligned Cancel + action; Escape/scrim dismiss). Used by: the **Save name-prompt** (a labelled `Input` + Save/Cancel), the **Create-view name-prompt** (SPEC-048 — labelled `Input`, catalog-safe-name validation + inline error, a note that the name is permanent, Create/Cancel), the **Save-results modal** (SPEC-049 — see Status bar), the **Drop table / Drop view** confirm (`alertdialog`, danger action), the **Delete saved query** confirm (`alertdialog`, danger), and the **tab-limit** dialog (`alertdialog`, single dismiss).

### Toast (SPEC-044)
A lightweight transient notice, first built for **Drop table** feedback and now the app's one toast (`components/Toast.tsx`). Bottom-right, a `rounded-lg` card with `shadow-lg`, tinted and bordered in its tone: `success` text and a 1px `success` border on `success-soft`, the same in `danger` on `danger-soft`, or, for `info`, `text-2` with a `border` hairline on `surface`. A `success` or `danger` toast dismisses itself after 4s (`AUTO_DISMISS_MS`); an `info` toast, or one carrying an action, stays until the caller clears it or the user dismisses it. Always manually dismissible, an accessible live region. Never blocks interaction.

### Charts (future)
A results chart should use the `accent` as series 1 and extend with analogous hues (e.g. the violet above, teal `success`) rather than introducing a second brand color. Out of scope for v1; no new tokens anticipated.

---

## 7. Shared connections (Bucket 2)

The third surface — collaborative **shared connections** (SPEC-050→056) — reuses every token and component above; **no new tokens**. The companion file `shared-connections.html` is its live realization. Connections are created/managed through an **asynchronous pipeline** (see `lambdas/info/planes/shared-spaces.md`), so the UI's defining trait is **status**: a connection or member can be *provisioning*, *active*, or *failed*, and changes apply on the next credential refresh. The design must make that state legible and never present a pending resource as ready.

### Status treatment (the shared-surface primitive)
A connection's state renders as a **status pill/dot** that is never color-only: **provisioning** = a `warning`/neutral pill with a small spinner + "Provisioning…"; **active** = a `success` dot (or no pill — the default ready state); **failed** = a `danger` pill + a short reason, with **Dismiss** and (where applicable) **Retry** text actions. The connections list carries a connection's state as this pill, and the member list uses the same pill for each member's join status (Active or Pending). The Files Spaces list and the Query rail show a not-ready connection's status as plain `text-3` text instead (§5, and *Inline appearance* below).

### Connections tab (management list)
The **Connections** tab in the top bar (§5) is the management surface (SPEC-052). A page header with title + a **New shared connection** primary button (left of a **Refresh connections** ghost icon-button). Below, a list of bordered `r-md` cards (or rows reusing the file-table container) — one per connection: the **name** (weight 600, monospace, since it's also the prefix/DB), a **role** indicator (a neutral `Owner`/`Member` pill), a **status** pill (above), and right-aligned role-gated actions — **Manage** (owner only → opens the members **drawer**, below), **Leave** (member, `danger`-ghost), **Delete** (owner, `danger`-ghost). Empty state (no connections): the standard friendly empty state — "No shared connections yet — create one or ask an owner to add you" + the New-connection CTA. Provisioning/failed cards show their status and disable actions that don't apply yet.

### Create shared connection dialog (SPEC-051)
A SPEC-026 centered modal: a labelled **name** `Input` validated to the catalog-safe rule (`^[a-z][a-z0-9_]{2,62}$`) with inline error, a one-line note that the name is **permanent and globally unique** (it becomes the S3 prefix and the Glue database), and Create/Cancel. On Create the connection appears immediately in a **provisioning** state (a Toast "Creating {name}…"); it flips to active (or failed) on the next Refresh-connections.

### Manage-members drawer (owner, SPEC-053)
Opened via **Manage** on an owned connection — a **right slide-over drawer** (the SPEC-036 `Drawer`: `max-w-[440px]`, scrim, Escape/scrim/close-button dismiss), *not* a separate page. The drawer header names the connection + an **Add members** primary button. The body is a member list (rows: username + an `Owner` pill on the owner, a per-member **Remove** `danger`-ghost; the owner row has no Remove). **Add members** opens a dialog with a single `textarea`/`Input` accepting **one username or a bulk list** (comma/space/newline-separated) + Add/Cancel; on submit the request is enqueued and a **summary** is surfaced on resolution — "added N · ignored M (unknown) · skipped K (at limit)" — because unknown usernames are silently dropped (validated against the User Pool). New members show as **provisioning** until the pipeline finishes.

### Leave / Delete confirms (SPEC-054)
**Leave** (member) is a plain SPEC-026 confirm: "Leave {name}? You'll lose access to its files and tables. They are not deleted." **Delete** (owner) is a `danger` **`alertdialog`** that spells out the cascade (all files, all tables, the database, every member's access) and requires **typing the space name** to enable the destructive button (stronger than a plain confirm, matching the file-delete/drop-table precedent). Both show the connection in a transient `leaving`/`deleting` state, then it disappears on Refresh.

### Inline appearance — Query rail & Files list (shared)
Shared connections appear inline where they're *used*, fed by the same `useConnections` source. In the **Query** schema rail (§6 *Schema browser*), every shared connection lists below the personal database, A–Z. An **active** one is a database node like the personal one: expand it to browse its tables and views, whose row menus act on that database. Nothing in the rail makes it a query's target, because there is no active database ([register](../decisions/analytics.md#query-workspace-has-no-active-database-spec-077)): a query reads a shared table by naming it in full, `{connection}.{table}`. A `provisioning`, `failed`, `leaving` or `deleting` one is a static row that cannot be expanded, its status as plain `text-3` text rather than the pill above, with no reason shown for a failure. With the shared-workspaces flag off, the rail lists the personal database alone. In the **Files** sidebar Spaces list (§5, SPEC-057), **active** shared connections appear as browsable roots, and one in any other state is **disabled** with its status so the user sees progress but can't browse a not-ready space.

### Refresh connections (SPEC-052)
A ghost icon-button (the SPEC-046 refresh pattern) on the connections screen and in both drawers it opens — the owner's Manage-members drawer and a member's read-only roster. It **forces a credential/token refresh** (so a newly-granted membership tag is stamped) and then re-reads the per-user connections cache — the on-demand way to pick up a just-granted space without an app reload. In-flight spinner + disabled; error → `Banner`, prior list intact.

---

## 8. Accessibility notes
- Contrast: `text` on `surface` ≈ 16:1; `text-2` on `surface` ≈ 6:1 (AA for body). Avoid `text-3` for essential body copy.
- Every interactive element gets a visible focus ring: by default a 2px solid `accent` outline, offset 2px (§1). A control that draws its own ring suppresses that outline and draws the ring in its place — `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`, 2px with no offset — and adds `focus-visible:ring-inset` inside an `overflow-*` container or on an edge-to-edge row, where an outside ring is clipped. The ring alone, without `outline-none`, draws two indicators.
- State is never color-only: selected rows also show a checked box; status pills carry text/icon.
- Pointer targets must be at least 24×24px (WCAG 2.5.8). Write that floor in px — `h-[24px]`, not `h-6`, which is 21px against the 14px root. *Target size in this app* in `apps/portal/info/best-practices/accessibility/accessibility.md` carries the rule, and `lib/targetSize.test.ts` backs it with a sweep of the size classes; the controls already under the floor are listed there, each with a note, in `ACCEPTED_UNDERSIZED`. The common controls: `IconButton` `h-8` (28px) and `h-7` (24.5px), `Button` `h-9` (31.5px) and `h-8` (28px), file-table rows `h-12` (42px).
