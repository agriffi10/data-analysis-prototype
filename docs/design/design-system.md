# Design System — S3 File Portal

**Aesthetic:** Clean / minimal SaaS. Generous whitespace, neutral grays, a single accent (indigo), light hairline borders, table-forward layouts. Reads as trustworthy enterprise tooling.

This doc is the source of truth for the look. The companion file `file-management.html` is a live, interactive realization of these tokens (file browser + upload flow). The CSS variables in the mockup match the token tables below 1:1, so changes can be made in either place and kept in sync.

**Stack mapping:** Tokens below are written as CSS custom properties and as a `tailwind.config` extension. The app uses TailwindCSS, so prefer the Tailwind tokens in components; the CSS variables exist for the mockup and for any raw CSS.

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

> Focus ring: 2px `accent` at 40% alpha, offset 2px. Never rely on color alone for state — pair with icon or text (accessibility).

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

**Spacing** — 4px base scale. Use these steps only; avoid arbitrary px.

`4 · 8 · 12 · 16 · 20 · 24 · 32 · 40`  (`sp-1` … `sp-10`)

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
| `shadow-md` | `0 4px 12px rgba(16,24,40,.08)` | Popovers, dropdowns, toasts |
| `shadow-lg` | `0 12px 32px rgba(16,24,40,.14)` | Drawer, modal dialog |

**Key layout dimensions:** topbar `56px`, toolbar `52px`, table row `48px`, sidebar `248px`.

---

## 4. Tailwind config extension

Drop into `apps/portal/tailwind.config.ts` under `theme.extend`. Component classes can then use `bg-surface`, `text-text-2`, `rounded-lg`, `text-base`, etc.

```ts
// tailwind.config.ts — theme.extend
export default {
  theme: {
    extend: {
      colors: {
        bg: '#f7f8fa',
        surface: { DEFAULT: '#ffffff', 2: '#fafbfc' },
        border: { DEFAULT: '#e6e8eb', 2: '#f0f1f3' },
        text: { DEFAULT: '#15191e', 2: '#5b6573', 3: '#8a93a2' },
        accent: {
          DEFAULT: '#4f46e5',
          hover: '#4338ca',
          soft: '#eef2ff',
          text: '#4338ca',
        },
        success: { DEFAULT: '#0f9d6e', soft: '#e7f7f0' },
        warning: { DEFAULT: '#c2820a', soft: '#fdf4e3' },
        danger:  { DEFAULT: '#dc2626', soft: '#fdeceb' },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      fontSize: {
        xs:   ['12px', '16px'],
        sm:   ['13px', '18px'],
        base: ['14px', '20px'],
        md:   ['16px', '24px'],
        lg:   ['18px', '26px'],
        xl:   ['22px', '30px'],
      },
      borderRadius: { sm: '6px', md: '8px', lg: '10px', full: '999px' },
      boxShadow: {
        sm: '0 1px 2px rgba(16,24,40,.05)',
        md: '0 4px 12px rgba(16,24,40,.08)',
        lg: '0 12px 32px rgba(16,24,40,.14)',
      },
    },
  },
};
```

> Tailwind's default spacing scale (`p-1`=4px … `p-10`=40px) already matches the 4px base — no override needed.

---

## 5. Component patterns

These map to the feature-folder + shared-component conventions in `CLAUDE.md` (components in `src/components/`, feature UIs in `src/features/<name>/`).

### Buttons
- **Primary** — `bg-accent text-white`, hover `bg-accent-hover`, height 36px, `rounded-md`, `px-4`, gap 8px to icon. One per context (the main action, e.g. Upload).
- **Default** — `bg-surface border border-border text-text`, hover `bg-surface-2`. Secondary actions (New folder, Cancel).
- **Ghost** — transparent, hover `bg-surface-2`. Toolbar/row actions (Download, Rename, Move).
- **Danger-ghost** — transparent, `text-danger`, hover `bg-danger-soft`. Delete.
- Disabled: `opacity-45`, `cursor-not-allowed`. Icons 16px, stroke-width 2.

### Top bar
Fixed 56px. Brand mark (rounded accent square + wordmark) → search field (inset `surface-2`, `rounded-md`, leading search icon) → spacer → help icon-button → user avatar (gradient circle, initials).

### Sidebar (248px) — the Files-tab Spaces list
Surface panel, right hairline border. On the **Files** tab the sidebar is a single **Spaces** list (SPEC-057): the user's **personal** space first (its item labelled with the Cognito `username`), then each **active** shared connection (alphabetical) — so "My Files" reads as `alice`, `marketing_data`, `sales_2026`, … all in one list. Nav items: 36px tall, `rounded-md`, icon + label; **active** (the space being browsed) = `bg-accent-soft text-accent-text`; hover = `bg-surface-2`. A shared space carries a small trailing **status dot** (§7); `provisioning`/`failed` spaces appear **disabled** with their status (you can't browse a not-ready space). Selecting a space roots the file browser at that space's bucket/prefix (personal → `{username}/`; shared → `dat-prod-shared-space/{name}/`). **Managing** spaces (create/delete, members) is **not** here — it lives in the **Connections** top-level tab (§7); an optional "Add connection" affordance in this list just links there. (The Connections surface is detailed in §7; its companion mockup is `shared-connections.html`.)

### Breadcrumbs
In the toolbar. Each segment is a hover-highlightable link; `/` separators in `text-3`; final (current) segment is `text` weight 600, non-interactive. Maps directly to the S3 key path under `{username}/`.

### File table
Container: `surface`, `border`, `rounded-lg`, clipped. Header row 40px on `surface-2`, uppercase `text-xs` column labels. Grid columns: `[checkbox 40px] [name 1fr] [size 120px] [modified 180px] [type 120px]`.
- Rows 48px, divider `border-2`, hover `surface-2`, **selected** `accent-soft`.
- Name cell: 20px icon (folder = `accent` fill, file = `text-3` stroke) + filename (weight 500, ellipsis-truncated).
- Size / modified in `text-2 text-sm`; type as a neutral **pill** (`surface-2` bg, `border`, `rounded-full`, `text-xs`).
- Checkbox `accent-color: accent`. Row-hover reveals inline actions (opacity 0 → 1).
- Pagination: a centered ghost **Load more** button below the table (`ListObjectsV2` is capped at 1000 keys — see architecture Known Constraints; pairs with TanStack `useInfiniteQuery`).

### Selection bar
When ≥1 row is selected, the default toolbar is replaced by an `accent-soft` bar: master checkbox + "N selected" (`accent-text`, weight 600) + spacer + batch actions (Download, Rename, Move, **Delete** as danger-ghost). This is where SPEC-018/019 multi-select operations live.

### Upload drawer (right slide-over)
420px panel, `shadow-lg`, slides in over a 32%-black scrim. Header shows the destination prefix. Body:
- **Dropzone** — dashed `border`, `surface-2`, hover → `accent` border + `accent-soft` fill. Headline + "browse" link + hint line ("Up to 5 GB per file · multipart handled automatically" — reflects `VITE_MAX_UPLOAD_BYTES` and `@aws-sdk/lib-storage` auto-multipart from SPEC-016).
- **Queue** — uppercase count label, then one card per file: 28px file-type chip, name + subtext (size · bytes-transferred), 6px `accent` **progress bar**, and a right-aligned status: `✓ Done` (success), `62%` (accent), `Queued` (muted). Per-file cancel (SPEC-020) lives as a hover action on each card.

### Overwrite confirm dialog (warn-and-confirm)
Centered modal, `rounded-lg`, `shadow-lg`. Warning-circle icon (`warning` on `warning-soft`) + title + explanation naming the conflicting key in `<code>`. Footer on `surface-2` with three actions: **Keep both (rename)**, **Cancel**, **Overwrite** (primary). This is the HEAD-check → Overwrite-or-Rename flow required because versioning is off (architecture: "No overwrite protection from S3").

### Empty / error states
Missing `connections.json` or an empty folder renders as a friendly empty state (icon + `text-xl` headline + `text-2` guidance + primary CTA), **not** an error — per architecture Known Constraints.

---

## 6. Data analysis surface (Query workspace)

The portal's second surface — the Glue/Athena **Query workspace** (SPEC-034→036) — reuses every token and most components from the file browser; **no new tokens are introduced**. The companion file `query-workspace.html` is the live realization of this section, exactly as `file-management.html` is for the file browser. Where a component already exists (table, pill, button, drawer), reuse it rather than building a parallel one.

### Primary tab navigation (Files | Query | Connections)
The authenticated shell gains a primary tab strip in the **topbar**, right of the brand mark. Tabs are 56px-tall (full topbar height), `text-base` weight 500, icon + label, `text-2` at rest → `text` on hover. The **active** tab is `accent-text` with a 2px `accent` bottom border (an underline tab, distinct from the sidebar's filled `accent-soft` nav item so the two navigation levels read differently). Driven by the route (`/files`, `/query`, `/connections`); keyboard-focusable with the standard focus ring. **Connections** (SPEC-052) is the third tab — the place to *manage* shared spaces (create/delete, member management). The other two surfaces *use* spaces: **Files** lists the user's spaces (personal + shared) as browsable roots (§5, SPEC-057) and **Query** lists their databases (personal + shared) in the schema rail (below, SPEC-047). So a shared connection appears in all three tabs — managed under Connections, browsed under Files, queried under Query — fed by one `useConnections` source.

### Schema browser (left, reuses the 248px sidebar)
Same surface panel + right hairline border as the file-browser sidebar. The single uppercase micro-label `Database` heads a **tree** (SPEC-063): every database the user can access — the personal database first, then any **active** shared connections A–Z — is its own **collapsible node** (rotating chevron + database icon + label) under a `radiogroup`. **Expanding to browse is decoupled from choosing the active query target** (SPEC-063): the chevron/label disclosure only expands or collapses that node; a separate **radio dot** on each node sets the **workspace-global** active database (`accent` fill + `accent-soft` row when active, `aria-checked`/`aria-current` + sr-only "(current database)" — never color-only), so a user can browse any accessible database's objects without changing what their queries run against. The radios form one keyboard-navigable `radiogroup` (arrow keys rove focus, Enter/Space selects). `provisioning`/`failed`/`leaving` shared connections appear as a static, **non-expandable / non-selectable** row with their status label (§7). With only the personal database, it's a single node (expanded by default). The editor toolbar's `db-chip` is a **read-only** reflection of the active database — not a separate switcher. An expanded node loads **its own** schema (per-node `useSchema`, with the same loading / empty / "setting up" / error states rendered inline) and splits the objects into **two collapsible sub-groups — `Tables` and `Views`** — each with its own chevron + object count (e.g. `Tables (3)`), so a database's tables and views always read grouped beneath it. Default reveal opens `Tables`; `Views` opens only when the database has ≥1 view. Inside each group, rows are 32px expandable (`text-sm`, weight 500) with a rotating chevron; expanding reveals columns indented under `sp-8`, each showing `name` + a right-aligned monospace `text-xs text-3` type. Tables/views and columns are click-to-insert into the editor. **Views (SPEC-048)** live in the `Views` group — membership conveys the type, so the old inline **`view` badge is dropped** — but keep their view-aware row actions (§ Table options menu). Empty group states stay legible rather than vanishing: the `Tables` group shows the `text-3` `CREATE EXTERNAL TABLE …` `<code>` hint when there are no tables (normal, not an error); the `Views` group shows a muted "No views.".

### Table options menu (SPEC-044)
Each table row gets a **kebab (⋮)** button that appears on row hover/focus (`text-3`, `surface-2` hover) and opens a small **popover menu** — the app's first menu primitive, so build it reusable and accessible (`aria-haspopup`/`aria-expanded`, focus into the menu, Escape + outside-click close, arrow-key nav; opening it must not toggle the row's expand). The menu is a `surface` panel with `border` + `shadow-md`, `r-md`, `sp-1` padding; items are full-width `text-sm` rows (`surface-2` hover) with a leading `text-3` icon. Four actions: **View source files**, **View DDL**, **View data**, a `menu-sep` hairline, then **Drop table** in `danger` tone (`danger-soft` hover). View-data/DDL open a new query tab; Drop opens a confirm `alertdialog` (below) and reports via a toast. **For a view row (SPEC-048)** the same menu is **view-aware**: View DDL runs `SHOW CREATE VIEW` (not `… TABLE`), the danger action reads **Drop view** (`DROP VIEW`), and **View source files** is **disabled** (a view has no S3 location) — View data still previews rows.

### SQL editor (Monaco)
A fixed-height editor pane (~230px, resizable in implementation) below the toolbar. Left **gutter** on `surface-2` with a `border-2` right divider and monospace `text-3` line numbers; code area is monospace `text-sm`, line-height 1.7. Syntax theme maps onto tokens: **keywords** `accent-text` weight 600, **strings** `success`, **numbers** `warning`, **comments** `text-3` italic, **functions** a violet (`#7c3aed`) that sits beside the indigo accent without becoming a second brand color. The real editor is Monaco (SPEC-035), lazy-loaded for the Query route only.

### Query tab strip (SPEC-041, SPEC-043)
A 40px strip on `surface-2` with a bottom hairline, sitting **above the editor toolbar**. It holds the open query tabs — each an independent query window — so it must read as a *third*, narrower level of navigation, visually distinct from both the topbar's underline tabs (Files | Query) and the sidebar's filled `accent-soft` item. These are **"card" tabs**: a 28px `r-md` chip, `text-sm` weight 500, `text-2` at rest → `text` + `surface` background on hover; the **active** tab is `surface` with a `border` hairline, `shadow-sm`, and a small leading `accent` dot (so active state is never color-only). **Labels:** blank `+` tabs are the monotonic `Query N` (never reused this session); tabs opened from a **saved query** (SPEC-043) or a **table action** (SPEC-044) carry a feature-supplied label (`Monthly revenue`, `sales_2026`, `DDL: sales_2026`). A linked saved-query tab with unsaved edits shows a leading **`accent` dirty dot/•** before its name (re-save clears it). Each tab carries a trailing close (`×`) hit target that tints `danger`/`danger-soft` on hover; closing a tab with non-empty SQL warns-and-confirms first (reuse the SPEC-026 dialog). The **last remaining tab hides its close control** (there is always ≥1 tab). A trailing `+` ghost button (`aria-label="New query tab"`) adds a tab and is **never disabled** — at the `QUERY_TABS_MAX = 10` cap, clicking it (or any other tab-opening action) raises the **tab-limit dialog** (a SPEC-026 `alertdialog`: "You have the maximum of 10 query tabs open. Close a tab before opening another." — single dismiss; the attempted action is not completed). The strip scrolls horizontally if tabs overflow. **Global buttons** live right-aligned on this same strip (right of a flex spacer), because they act across all tabs: **Saved queries** and **History** (compact ghost `bar-btn`s), hoisted here out of the per-tab toolbar (SPEC-043 FR-010). The active tab drives the editor content and all per-tab toolbar actions (Run / Clear / Save / Stop) below it.

### Editor toolbar
52px toolbar (same height as the file-browser toolbar). Left: the `db-chip` — a **read-only** `surface-2` rounded-full pill (an `accent` dot + the monospace name of the **active database**, e.g. "My workspace" or a shared name). It is **not** a switcher: changing the database happens in the **schema-rail `Database` list** (SPEC-047, above); the chip just reflects the workspace's current target. Right cluster (per-tab editor actions, acting on the active tab — SPEC-041): **Format** (ghost, ⌘⏎ hint), **Clear** (ghost, trash — SPEC-040; warn-and-confirm, disabled while running/empty), **Save** (ghost, save icon — SPEC-043; name-prompt, pre-filled when linked, disabled when empty), **Create view** (ghost, SPEC-048; opens a name-prompt and runs `CREATE OR REPLACE VIEW` against the **active (workspace-global) database** in the background, disabled when empty), **Stop** (danger-ghost, square, visible only while running), and **Run** (the one primary button — accent, play icon; runs the active tab's SQL against the workspace database). Run is disabled when the editor is empty or a query is in flight; ⌘/Ctrl+Enter triggers Run. **History and Saved-queries are not here** — they're on the global tab-strip row above (SPEC-043 FR-010).

### Status bar
A slim bar (~44px) below the editor showing execution state, **never color-only** — always icon/spinner + text: **Running** = `accent-text` with a spinner + an indeterminate `accent` progress sliver + elapsed time and bytes scanned; **Succeeded** = `success` dot + "N rows · X scanned · Ys" and a right-aligned **Save results to my files** ghost button (SPEC-049 — replaces the old "Download CSV"; shown only for a row-returning success); **Failed** = the `danger` **Banner** (SPEC-028) carrying the Athena `stateChangeReason` (with the offending token in `<code>`); **Cancelled** = neutral note. The bar is an accessible live region.

**Save-results modal (SPEC-049).** "Save results to my files" opens a SPEC-026 centered modal: a **destination folder** picker (reuses the file-browser `DestinationPicker`, the user's own space — plus any shared spaces they belong to, SPEC-055 — excluding each `athenaresults/`) + a **file name** `Input` defaulted to `query-results-{YYYYMMDD-HHmm}` with the `.csv` extension normalized, and Save/Cancel. Save writes the **complete** result set (a server-side copy of Athena's full result object — all rows, not just the loaded page) into the chosen folder, runs the standard overwrite warn-and-confirm on a collision, and on success shows a **Toast** with a "view in Files" deep-link.

### Results table (reuses the file table)
Same container as the file table: `surface`, `border`, `rounded-lg`, clipped; 40px `surface-2` header with uppercase `text-xs` column labels — here each header stacks the column **name** over its **type** in a small monospace caption (the type also available as the neutral **pill**). Rows are monospace `text-sm`, 48px, `border-2` dividers, `surface-2` hover, with a leading muted row-number column. Wide result sets scroll horizontally inside the panel without breaking the shell. Pagination reuses the centered ghost **Load more** (`GetQueryResults` `NextToken`, mirrors listing pagination). Empty result sets (successful DDL, zero-row SELECT) render the friendly empty state, not an error.

### Query history drawer (right slide-over, reuses the upload-drawer pattern)
440px panel, `shadow-lg`, slides in over the 32%-black scrim — identical mechanics to the upload drawer. The drawer header carries a **Refresh** icon-button (SPEC-046) in its `headerAccessory` slot (a ghost `IconButton`, `aria-label="Refresh history"`) that re-reads `query-history.json` from S3 on demand — disabled with a spinner while in flight, resets to the newest page on success, and surfaces a read error as a `Banner` without dropping the current list. Each entry is a bordered `r-md` card: a status **badge** (`success`/`danger`/neutral soft fills with a leading dot — never color-only), a right-aligned relative timestamp (absolute on hover), a single-line monospace SQL preview (ellipsis-truncated), a footer with run stats (`rows · scanned · duration`) and right-aligned **Open** / **Re-run** text actions (`accent-text`). History is the per-user `{username}/user_settings/query-history.json` store only — it never shows other users' or workgroup-wide queries. **Pagination (SPEC-042):** the drawer shows the **7 most recent** entries (newest-first) with a footer **pager** — a `text-2` range label in the form `1–7 of N` on the left and ghost **Prev** / **Next** buttons on the right (Prev disabled on page 1, Next disabled on the last page). It is a *replace* pager (one page of ≤7 in the DOM), mirroring the results pager (SPEC-038), not append; it resets to the newest page when the drawer is reopened or a new query is run.

### Saved queries drawer (SPEC-043)
A second right slide-over with the **same mechanics as the history drawer** (440px, `shadow-lg`, scrim, Escape/scrim/close-button dismiss). Opening one closes the other. Each entry is a bordered `r-md` card: the saved query's **name** (weight 600), a right-aligned relative **updated** time, a single-line monospace **SQL preview**, and right-aligned **Open** (`accent-text`) + **Delete** (`danger`) text actions. **Open** routes through `openTab` (named, linked tab; honors the tab-limit dialog). **Delete** raises an "are you sure" `alertdialog`. Empty state: "No saved queries yet — Save a query to see it here." v1 shows the full list (no pager).

### Confirm dialogs & name prompt (SPEC-026 reuse)
All modals reuse the SPEC-026 centered-modal pattern (scrim `bg-black/40`, `surface` panel, `r-lg`, `shadow-lg`, header title + body, a `surface-2` footer with right-aligned Cancel + action; Escape/scrim dismiss). Used by: the **Save name-prompt** (a labelled `Input` + Save/Cancel), the **Create-view name-prompt** (SPEC-048 — labelled `Input`, catalog-safe-name validation + inline error, a note that the name is permanent, Create/Cancel), the **Save-results modal** (SPEC-049 — see Status bar), the **Drop table / Drop view** confirm (`alertdialog`, danger action), the **Delete saved query** confirm (`alertdialog`, danger), and the **tab-limit** dialog (`alertdialog`, single dismiss).

### Toast (SPEC-044)
A lightweight transient notice for **Drop table** feedback (the app's first toast). Bottom-right, `surface` card with `border` + a 3px left accent in `success` (or `danger` on failure), `shadow-md`, `r-md`; auto-dismiss after a few seconds, manually dismissible, an accessible live region. Never blocks interaction. (Alternative under consideration: reuse the `Banner` shown transiently — see SPEC-044 Open Questions.)

### Charts (future)
A results chart should use the `accent` as series 1 and extend with analogous hues (e.g. the violet above, teal `success`) rather than introducing a second brand color. Out of scope for v1; no new tokens anticipated.

---

## 7. Shared connections (Bucket 2)

The third surface — collaborative **shared connections** (SPEC-050→056) — reuses every token and component above; **no new tokens**. The companion file `shared-connections.html` is its live realization. Connections are created/managed through an **asynchronous pipeline** (see `docs/architecture.md` → *Control Planes → Shared Spaces*), so the UI's defining trait is **status**: a connection or member can be *provisioning*, *active*, or *failed*, and changes apply on the next credential refresh. The design must make that state legible and never present a pending resource as ready.

### Status treatment (the shared-surface primitive)
A connection's state renders as a **status pill/dot** that is never color-only: **provisioning** = a `warning`/neutral pill with a small spinner + "Provisioning…"; **active** = a `success` dot (or no pill — the default ready state); **failed** = a `danger` pill + a short reason, with **Dismiss** and (where applicable) **Retry** text actions. The same vocabulary is used in the sidebar dot, the connections list, the selector, and the member list.

### Connections tab (management list)
The **Connections** top-level tab (Files | Query | Connections, §6) is the management surface (SPEC-052). A page header with title + a **New shared connection** primary button (left of a **Refresh connections** ghost icon-button). Below, a list of bordered `r-md` cards (or rows reusing the file-table container) — one per connection: the **name** (weight 600, monospace, since it's also the prefix/DB), a **role** indicator (a neutral `Owner`/`Member` pill), a **status** pill (above), and right-aligned role-gated actions — **Manage** (owner only → opens the members **drawer**, below), **Leave** (member, `danger`-ghost), **Delete** (owner, `danger`-ghost). Empty state (no connections): the standard friendly empty state — "No shared connections yet — create one or ask an owner to add you" + the New-connection CTA. Provisioning/failed cards show their status and disable actions that don't apply yet.

### Create shared connection dialog (SPEC-051)
A SPEC-026 centered modal: a labelled **name** `Input` validated to the catalog-safe rule (`^[a-z][a-z0-9_]{2,62}$`) with inline error, a one-line note that the name is **permanent and globally unique** (it becomes the S3 prefix and the Glue database), and Create/Cancel. On Create the connection appears immediately in a **provisioning** state (a Toast "Creating {name}…"); it flips to active (or failed) on the next Refresh-connections.

### Manage-members drawer (owner, SPEC-053)
Opened via **Manage** on an owned connection — a **right slide-over drawer** (the SPEC-036 `Drawer`: 440px, scrim, Escape/scrim/close-button dismiss), *not* a separate page. The drawer header names the connection + an **Add members** primary button. The body is a member list (rows: username + an `Owner` pill on the owner, a per-member **Remove** `danger`-ghost; the owner row has no Remove). **Add members** opens a dialog with a single `textarea`/`Input` accepting **one username or a bulk list** (comma/space/newline-separated) + Add/Cancel; on submit the request is enqueued and a **summary** is surfaced on resolution — "added N · ignored M (unknown) · skipped K (at limit)" — because unknown usernames are silently dropped (validated against the User Pool). New members show as **provisioning** until the pipeline finishes.

### Leave / Delete confirms (SPEC-054)
**Leave** (member) is a plain SPEC-026 confirm: "Leave {name}? You'll lose access to its files and tables. They are not deleted." **Delete** (owner) is a `danger` **`alertdialog`** that spells out the cascade (all files, all tables, the database, every member's access) and requires **typing the space name** to enable the destructive button (stronger than a plain confirm, matching the file-delete/drop-table precedent). Both show the connection in a transient `leaving`/`deleting` state, then it disappears on Refresh; a tab that targeted it falls back to the personal connection.

### Inline appearance — Query rail & Files list (shared)
Shared connections appear inline where they're *used*, fed by the same `useConnections` source. In the **Query** schema-rail `Database` list (§6, SPEC-047), **active** shared connections list below the personal one (A–Z); selecting one sets the **workspace-global** active database (the tables/views + Run target follow), and its results route to the shared space (SPEC-055). In the **Files** sidebar Spaces list (§5, SPEC-057), **active** shared connections appear as browsable roots. In both, `provisioning`/`failed` shared connections are **disabled** with their status so the user sees progress but can't target/browse a not-ready space.

### Refresh connections (SPEC-052)
A ghost icon-button (the SPEC-046 refresh pattern) on the connections screen and near the selector. It **forces a credential/token refresh** (so a newly-granted membership tag is stamped) and then re-reads the per-user connections cache — the on-demand way to pick up a just-granted space without an app reload. In-flight spinner + disabled; error → `Banner`, prior list intact.

---

## 8. Accessibility notes
- Contrast: `text` on `surface` ≈ 16:1; `text-2` on `surface` ≈ 6:1 (AA for body). Avoid `text-3` for essential body copy.
- Every interactive element gets a visible focus ring (`accent` @ 40%, 2px, offset 2px).
- State is never color-only: selected rows also show a checked box; status pills carry text/icon.
- Hit targets ≥ 32px; table rows 48px.
