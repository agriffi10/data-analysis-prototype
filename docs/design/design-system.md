# Design System — Data Quarry

**Aesthetic:** Clean / minimal SaaS. Generous whitespace, neutral grays, a single accent (indigo), light hairline borders, table-forward layouts. Reads as trustworthy enterprise tooling.

This doc is the source of truth for the look. The tokens it describes are defined in the `@theme` block of `apps/portal/src/index.css`, with the dark theme in `:root[data-theme='dark']` below it, and the tables in §1–§3 restate those values. The one mockup still in the repo is `Responsive Breakpoints.dc.html`, the file browser's selection-toolbar handoff that `README.md` beside it describes. The per-surface mockups this doc used to name (`file-management.html`, `query-workspace.html` and `shared-connections.html`) were deleted in #203.

**Sizes** are given as the Tailwind class plus the px it renders. The app's root is 14px (`html { font-size: 14px }` in index.css), so a rem-based class renders at 7/8 of its usual size: `h-12` is 42px, not 48px. Arbitrary values such as `w-[248px]` are literal px, and so are the `@theme` font sizes and radii.

**Stack mapping:** The app is on Tailwind v4, which has no `tailwind.config` file. Each variable in `@theme` mints the utilities of the same name (§4), so components use `bg-surface`, `text-text-2` and `rounded-lg`, and the variables themselves are there for raw CSS.

---

## 1. Color

Single accent system — one indigo accent does all the "primary action / active / focus" work. Everything else is neutral gray. Status colors are reserved for state (success / warning / danger), never decoration, though the SQL editor's syntax theme borrows two of them for strings and numbers (§6).

Every colour token has a light value in `@theme` and a dark one in `:root[data-theme='dark']`, and both columns below are the code's. `public/theme-init.js` stamps `data-theme` on `<html>` before the first paint, and the top bar's Theme menu (§5) chooses Light, Dark or System, which follows `prefers-color-scheme`. The dark values were derived under the contrast harness rather than picked (§8, and the [dark-palette entry](../decisions/browser.md#the-dark-palette-is-derived-under-the-harness-not-chosen-and-the-theme-boundary-put-four-fences-there-spec-210)).

### Neutrals

| Token | Light | Dark | Use |
|---|---|---|---|
| `bg` | `#f7f8fa` | `#0d1014` | App canvas behind panels |
| `surface` | `#ffffff` | `#14181e` | Cards, panels, table, rows |
| `surface-2` | `#fafbfc` | `#191e25` | Table header, hover fills, inset fields |
| `border` | `#e6e8eb` | `#2b323c` | Default hairline borders |
| `border-2` | `#f0f1f3` | `#1f242c` | Lighter row dividers |

### Text

| Token | Light | Dark | Use |
|---|---|---|---|
| `text` | `#15191e` | `#e9edf3` | Primary text, file names, headings |
| `text-2` | `#5b6573` | `#a5aeba` | Secondary — metadata, labels |
| `text-3` | `#646b78` | `#98a1ad` | Muted — placeholders, captions, disabled |

### Accent (indigo)

| Token | Light | Dark | Use |
|---|---|---|---|
| `accent` | `#4f46e5` | `#615ae9` | Primary buttons, active nav, folder icon, progress, the focus ring |
| `accent-hover` | `#4338ca` | `#4f46e5` | Hover state of primary; it deepens in both themes |
| `accent-soft` | `#eef2ff` | `#191b36` | Active nav background, selected row, soft hover |
| `accent-text` | `#4338ca` | `#a5b4fc` | Accent-coloured text and links |
| `accent-border` | `#dfe3fb` | `#383c6b` | The visible edge of an `accent-soft` fill (open help card, active chip, unread notification, hero badge); decorative, never the only signal |

### Status

| Token | Light | Dark | Use |
|---|---|---|---|
| `success` | `#047857` | `#34d399` | Upload complete, validation passed |
| `success-soft` | `#e7f7f0` | `#0a231b` | Success fill |
| `warning` | `#b45309` | `#f0b429` | Overwrite confirm, non-atomic op warning |
| `warning-soft` | `#fdf4e3` | `#271e0a` | Warning fill |
| `danger` | `#b91c1c` | `#f87171` | Delete actions, errors, and the fill of the filled danger button (§5) |
| `danger-soft` | `#fdeceb` | `#2f1517` | Danger fill, and the hover of a danger-ghost button |
| `danger-border` | `#f6caca` | `#4a2427` | The visible edge of a `danger-soft` fill; decorative, never the only signal |
| `on-danger` | `#ffffff` | `#1a0c0c` | Text on the filled danger button. It is near-black in the dark theme, where the danger fill is light |

Each strong status shade doubles as text on white and on its own `-soft` fill, which is why the three are darker than the earlier `#0f9d6e`, `#c2820a` and `#dc2626`: each of those missed 4.5:1 in one role or both (index.css records the old and new ratios).

### Editor

| Token | Light | Dark | Use |
|---|---|---|---|
| `syntax-fn` | `#7c3aed` | `#c4b5fd` | Function names in the SQL editor's syntax theme (§6) |

One surface has fixed colour variables of its own. The landing page's call-to-action strip is painted from `--landing-cta-*` in `:root`, which no theme block reaches, so its white buttons keep their labels readable in the dark theme.

> Focus ring: by default a solid 2px `accent` outline, offset 2px (`:focus-visible` in index.css; §8 covers the controls that draw their own). It is solid rather than a 40%-alpha tint so that the ring itself clears WCAG 1.4.11's 3:1. Never rely on color alone for state — pair with icon or text (accessibility).

---

## 2. Typography

Inter, loaded from Google Fonts at weights 400, 500, 600 and 700 (the `@import` on the first line of index.css), with the system UI font behind it. One typeface, weight + size carry hierarchy. Base size is **14px**, which is also the root font size — appropriate for a dense, data-oriented tool while staying readable.

```
font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
```

| Token | Size / line-height | Weight | Use |
|---|---|---|---|
| `text-xs` | 12px / 16px | 500/600 | Pills, captions, uppercase labels |
| `text-sm` | 13px / 18px | 400/500 | Secondary metadata, queue subtext |
| `text-base` | 14px / 20px | 400/500 | Body, table rows, buttons (default) |
| `text-md` | 16px / 24px | 600 | Panel/section titles, brand |
| `text-lg` | 18px / 26px | 600 | Page titles |
| `text-xl` | 22px / 30px | 600/700 | Empty-state headlines |

- Uppercase micro-labels (sidebar section headers, table column headers) share one class string, `SECTION_CAPTION` in `components/fieldStyles.ts`: `text-xs`, weight 600, `tracking-wide` (0.025em), `text-3`.
- Line-height: each size carries its own, paired with it in `@theme` (the table above). Multi-line explanatory text adds `leading-relaxed` (1.625).

---

## 3. Spacing, radius, shadow

**Spacing** — Tailwind's default scale, which the app does not override. One step is `--spacing: 0.25rem` and the root font is 14px (`html { font-size: 14px }` in `apps/portal/src/index.css`), so **a step is 3.5px, not 4**, and every spacing-scale class — padding, margin, gap and the `h-*` / `w-*` / `min-h-*` sizes — measures 7/8 of what the same class would under the browser's default 16px root. For padding, margin and gap, stay on Tailwind's scale rather than arbitrary px — the table lists the common steps, and half steps such as `gap-1.5` are in use too; a value that encodes a threshold or a fixed width is written in px instead (§8).

| Step | `sp-1` | `sp-2` | `sp-3` | `sp-4` | `sp-5` | `sp-6` | `sp-8` | `sp-10` |
|---|---|---|---|---|---|---|---|---|
| px | 3.5 | 7 | 10.5 | 14 | 17.5 | 21 | 28 | 35 |

`sp-N` is this doc's name for Tailwind step N (`p-N`, `gap-N`, `h-N`, …). Elsewhere in this doc a size is given as its class and the px it renders, e.g. `h-12` (42px). What is written in px renders as written: the type sizes, radii, shadows and breakpoints the theme declares, border and ring widths, and arbitrary values such as `w-[248px]`. A Tailwind default the theme does not redeclare is in rem and shrinks the same way — `max-w-lg` on a dialog is 448px, and `rounded-t-xl` on the drawer's bottom sheet is 10.5px.

**Radius** — literal px from `@theme`, so the root does not scale them.

| Token | Class | Value | Use |
|---|---|---|---|
| `r-sm` | `rounded-sm` | 6px | Menu items, segmented-control segments, small close buttons |
| `r-md` | `rounded-md` | 8px | Buttons, icon buttons, inputs, menus, nav items, query tab chips |
| `r-lg` | `rounded-lg` | 10px | Cards, table container, dialogs, banners, toasts |
| `r-full` | `rounded-full` | 999px | Pills, badges, avatars, progress bars |

Drawer panels are square from `tablet` (`tablet:rounded-none` in `components/Drawer.tsx`), where they are full-height slide-overs against the viewport edge. Below `tablet` the bottom-sheet variant rounds only its top corners, with `rounded-t-xl` (Tailwind's 0.75rem, 10.5px).

**Shadow** — kept minimal; elevation is mostly borders + surface, shadows only for floating layers. Each shadow reads its colour from a `--shadow-tint-*` variable, and the dark theme overrides the tint (§4 says why).

| Token | Light | Dark | Use |
|---|---|---|---|
| `shadow-sm` | `0 1px 2px rgba(16,24,40,.05)` | `0 1px 2px rgba(0,0,0,.5)` | The active tab of a tab strip, the selected segment of a segmented control, the landing page's cards |
| `shadow-md` | `0 4px 12px rgba(16,24,40,.08)` | `0 4px 12px rgba(0,0,0,.6)` | Menus (`components/Menu.tsx`), and two landing-page panels |
| `shadow-lg` | `0 12px 32px rgba(16,24,40,.14)` | `0 12px 32px rgba(0,0,0,.72)` | Drawers (the mobile nav drawer included), modal dialogs, toasts, and other floating panels, such as the username typeahead's list, the in-flight file-operations panel, the Data Explorer's value panel |

**Key layout dimensions:** top bar `h-14` (49px, §5), Query editor toolbar at least 52px (`min-h-[52px]`), file-table row `h-12` (42px), sidebar `w-[248px]` (the Query rail is `w-[220px]` until `desktop`).

---

## 4. Tailwind theme (`@theme`)

The app configures Tailwind v4 in CSS and has no `tailwind.config.ts`. The tokens are declared in the `@theme` block at the top of `apps/portal/src/index.css`, and each namespace there mints its utilities: `--color-*` (`bg-surface`, `text-text-2`), `--font-*` (`font-sans`), `--text-*` with its paired `--text-*--line-height` (`text-base`), `--radius-*` (`rounded-lg`), `--shadow-*` (`shadow-md`) and `--breakpoint-*`, where Tailwind's five defaults are reset so only `tablet:` (900px) and `desktop:` (1300px) exist. This section says how the tokens reach Tailwind rather than repeat their values. The dark theme overrides the `--color-*` values under `:root[data-theme='dark']` in the same file, and a shadow is themed through its `--shadow-tint-*` rather than `--shadow-*`, because Tailwind inlines a shadow's value into the utility (the comment above `--shadow-sm` says why).

The block declares no `--spacing`, so the spacing scale is Tailwind's default `0.25rem`, which is 3.5px against the 14px root (§3).

A new colour token needs three things, and `lib/contrast.test.ts` fails until it has them. It needs a value in both theme blocks, the same two values in `PALETTE` in `lib/palette.ts` (the test pins both palettes against the stylesheet, token for token), and a pairing in `CONTRAST_PAIRS` that measures it, since the list of decorative tokens with no floor is frozen at `border`, `border-2`, `accent-border` and `danger-border`. A colour written in a `.ts` or `.tsx` file instead of a token fails `lib/colourLiterals.test.ts` in the four forms it sweeps: a hex, a stock Tailwind scale such as `text-gray-900`, a faded foreground such as `text-danger/80`, and `white` or `black` outside the files it exempts by name. It does not read `rgb()`/`hsl()`, CSS named colours or an arbitrary value such as `bg-[red]`, so those rest on review.

---

## 5. Component patterns

These map to the feature-folder + shared-component conventions in `CLAUDE.md` (components in `src/components/`, feature UIs in `src/features/<name>/`).

### Buttons
`components/Button.tsx` has four variants and three sizes. Every size is `rounded-md` with `gap-2` (7px) to the icon: `sm` is `h-8` (28px) with `px-3` (10.5px) and `text-sm`, `md`, the default, is `h-9` (31.5px) with `px-4` (14px) and `text-base`, and `lg` is `h-[46px]` with `px-6` (21px) and `text-md`.
- **Primary** — `bg-accent text-white`, hover `bg-accent-hover`. One per context (the main action, e.g. Upload).
- **Default** — `bg-surface border border-border text-text`, hover `bg-surface-2`. Secondary actions (New folder, Rename, Manage).
- **Ghost** — transparent, `text-2`, hover `bg-surface-2` and `text`. Cancel and Back, and toolbar actions (Copy and Move on the selection bar; Copy, Download, Save, Saved queries and Create view on the editor toolbar).
- **Danger** — filled: `bg-danger text-on-danger`, hover `bg-danger/90`. The confirming action of a destructive prompt: `ConfirmDialog` with `confirmVariant="danger"` (Delete, Drop table, Clear, Close tab, Leave, Delete shared space and others), and Overwrite in the collision prompts.
- **Danger-ghost** is not a variant. It is a ghost button given `text-danger` and a `danger-soft` hover by its caller: Delete on the selection bar, Stop on the editor toolbar, Leave and Delete on a connection card, and Remove on a member row.
- Disabled: `opacity-45`, `cursor-not-allowed`. A button given `disabledReason` is refused with `aria-disabled` rather than `disabled`, so it keeps its place in the tab order and its reason as its description. Icons are `h-4 w-4` (14px), `h-[15px]` on the selection bar, mostly stroke-width 2.

### Top bar
One bar on every route but the landing page (`/`): `h-14` (49px against the app's 14px root) on `surface`, with a bottom `border` hairline. Left to right: the hamburger, the brand mark (a `rounded-md` `accent` square holding a white database icon, then the **Data Quarry** wordmark in `text-md` weight 600), the primary tabs, a spacer, **Help**, **Notifications** and **Theme**, then the account trigger. What a signed-in user sees depends on the width:

| Width | Left of the spacer | Right of it |
|---|---|---|
| Below `tablet` (under 900px) | the hamburger, which opens `AppNavDrawer`; the brand square | Help, Notifications and Theme as icons alone; the avatar and the kebab |
| `tablet` (900–1299px) | the brand square; the tabs, as text only | the three controls, each with its word; the avatar and the kebab |
| `desktop` (1300px and up) | the square and the wordmark; the tabs, each with its icon | the three labelled controls; the avatar, the username and the kebab |

- **Tabs** — Files, Query, Data Explorer, Shared spaces and Data quality, each *removed* (not disabled) when its feature flag is off, and all of them absent while the flags load. Underline tabs the full height of the bar: `text-base` weight 500, `text-2` at rest and `text` on hover; the **active** tab is `accent-text` over a 2px `accent` bottom border, which keeps it distinct from the sidebar's filled `accent-soft` item so the two levels of navigation read differently. The route drives the active tab, so a deep link or back/forward sets it. A label never wraps. Below `tablet` the same destinations, under the same flags, are rows in the drawer, followed by Notifications and Help.
- **Help, Notifications, Theme** — one control style (`components/headerControl.ts`): an icon, its word beside it from `tablet`, `text-3` at rest, and `accent-text` on `surface-2` for the route you are on or the panel or menu it has open. Help opens the page's guide panel where one covers the route, and links to `/help` everywhere else; Notifications links to `/notifications`, with an `accent` unread count on the bell capped at `9+`; Theme opens a Light / Dark / System menu.
- **Account trigger** — the avatar (a gradient circle carrying the username's first two characters, uppercased), the username in `text-2` from `desktop`, capped with an ellipsis, and a kebab that says a menu is there to open. The menu holds **Give feedback**, a separator, then **Sign out** in `danger`.
- **Signed out** there is no hamburger, no tabs and no account trigger: the wordmark shows at every width, followed on the right by Theme and a primary **Sign in**.

Why the words stay at `tablet` while the wordmark, the tab icons and the username wait for `desktop`, and what that costs between 900 and 1299px, is the register entry [At `tablet` the words stay and the decoration waits](../decisions/browser.md#at-tablet-the-words-stay-and-the-decoration-waits--the-top-bar-and-the-selection-toolbar-2026-09-10), which rests on *What paid for the room is the WORDMARK* in the [dark-palette entry](../decisions/browser.md#the-dark-palette-is-derived-under-the-harness-not-chosen-and-the-theme-boundary-put-four-fences-there-spec-210).

### Sidebar (248px) — the Files-tab Spaces list
A `CollapsibleRail` (`w-[248px]`): surface panel, right hairline border. On the **Files** tab the sidebar is a single **Spaces** list (SPEC-057, `features/connections/SpacesList.tsx`): the user's **personal** space first (its item labelled with the Cognito `username`, with a trailing `text-3` "user space"), then every shared connection A–Z — so "My Files" reads as `alice`, `marketing_data`, `sales_2026`, … all in one list. Nav items: 34px tall (`py-2` with `text-base`), weight 500, `rounded-md`, an 18px folder icon + label; **active** (the space being browsed) = `bg-accent-soft text-accent-text`; hover = `bg-surface-2`. A shared space that is not `active` carries a trailing `text-xs` `text-3` status label ("Provisioning…" and the like), never a colour alone, and is **disabled** (you can't browse a not-ready space); an active one carries no label. Selecting a space roots the file browser at that space's bucket/prefix (personal → `{username}/` in the user-space bucket; shared → `{name}/` in the shared-space bucket). **Managing** spaces (create/delete, members) is **not** here — it lives in the **Shared spaces** top-level tab (§7).

### Breadcrumbs
In the toolbar. Each earlier segment is a button in `text-2` that turns `text` and underlines on hover; `/` separators in `text-3`; final (current) segment is `text` weight 600, non-interactive. Maps directly to the S3 key path under the space's root: `{username}/` for the personal space, `{name}/` for a shared one.

### File table
`features/file-browser/FileListTable.tsx`, from `tablet` up; below it the same rows render as two-line cards (`FileListRowMobile.tsx`, `h-14`, 49px). Container: `surface`, `border`, `rounded-lg`, clipped. Header row `h-10` (35px) on `surface-2`, uppercase `text-xs` column labels. The columns are a flex row, not a grid: `[checkbox w-10 (35px), only when rows are selectable] [name flex-1] [size w-24 (84px)] [modified w-40 (140px)] [type w-28 (98px), from desktop] [actions w-44 (154px)]`.
- Rows `h-12` (42px), divider `border-2`, hover `surface-2`, **selected** `accent-soft`.
- Name cell: `h-5 w-5` (17.5px) icon (folder = `accent` fill, file = `text-3` stroke) + filename (weight 500, ellipsis-truncated).
- Size / modified in `text-2 text-sm` (a folder's size is a `text-3` "—"); type as a neutral **pill** (`surface-2` bg, `border`, `rounded-full`, `text-xs`).
- Checkbox `accent-color: accent`. The actions column holds an always-visible **Details** button, plus **Download** in read-only browse, where there is no selection bar; nothing is revealed on hover.
- Pagination: the shared **Pager** (Prev — *Page N* — Next) below the table, one `ListObjectsV2` page per browser page (25 entries; the page count appears only once the last server page has loaded). Shown only for a folder that does not fit on one page. The destination picker keeps the centered ghost **Load more** (`ListObjectsV2` is capped at 1000 keys — see architecture.md → *Constraints that shape the system*; both pair with TanStack `useInfiniteQuery`).

### Selection bar
A second bar below the toolbar, which it does not replace, shown whenever the folder has contents and the session can write to it (read-only browse has none). Master checkbox, the count, a spacer, then the batch actions. With nothing selected it is a plain `surface` bar reading "Select all" in `text-3`; once a row is selected it turns `accent-soft` with an `accent` border and the count reads "N selected" (`accent-text`, weight 600). The actions, in order: **Check data quality** (only where the data-quality feature is on), **Send to…**, **Archive** (except inside `archive/`), then **Copy**, **Move** and **Delete** (danger-ghost). Download and Rename are not here; they live in the details panel. The actions are icons alone below `tablet`, words alone at `tablet` and both at `desktop`, and from `tablet` up the count truncates rather than push an action out; the top bar's [register entry](../decisions/browser.md#at-tablet-the-words-stay-and-the-decoration-waits--the-top-bar-and-the-selection-toolbar-2026-09-10) covers this bar too.

### Upload drawer (right slide-over)
The shared `Drawer` (`components/Drawer.tsx`): from `tablet` a full-height right panel, `tablet:max-w-[440px]` (440px), `shadow-lg`, over a `bg-black/30 backdrop-blur-sm` scrim, and below `tablet` a full-width bottom sheet (`max-h-[85dvh]`). It appears without animation. The header reads **Upload**, with "to {folder}" beside it naming the destination folder. Body:
- **Dropzone** — a dashed 2px border in the `border` colour (`border-2 border-dashed border-border`) on `surface-2`; a file dragged over it turns the border `accent` and the fill `accent-soft`. Headline ("Drag files here") + a "choose files" link + a hint line, "Up to 5.0 GB per file · multipart handled automatically" (`features/file-browser/UploadDropzone.tsx`). The hint reads the limit it names from `maxUploadBytes()`, the same function that enforces it: `maxUploadBytes()` in `uploadLimits.ts` — `maxUploadBytes` from `/config.json` (`VITE_MAX_UPLOAD_BYTES` in a dev build), defaulting to and clamped at 5 GiB, S3's ceiling for one `PUT` — so a lower configured limit is enforced without changing the hint. The browser has no AWS SDK. Whether an upload is one `PUT` or multipart, and how it is cut, is the server's plan from `objects.upload`; the browser runs the parts (`multipartUpload.ts`) and every `PUT` over `XMLHttpRequest` (`xhrUpload.ts`), because `fetch` reports no upload progress.
- **Queue** (`UploadList.tsx`) — an uppercase **Uploads** micro-label with "N in progress" or "Complete" beside it in `text-sm text-2` and a **Clear finished** button at the right, then one row per file in a single bordered list, `border-2` dividers between them: an `h-7 w-7` (24.5px) file-type chip, name + subtext ("{loaded} of {total}" while uploading; otherwise "Waiting…", the error, "Cancelled" or the size), an `h-1.5` (5.25px) `accent` **progress bar** while the file is uploading, and a right-aligned status chip with a dot and a word: **Queued** and **Cancelled** (neutral), **Uploading** (warning, pulsing), **Uploaded** (success), **Failed** (danger). No percentage is shown. Per-file cancel (SPEC-020) is revealed when the row is hovered or the button has focus, and is always shown where the primary input cannot hover, as on a phone, since there the hover reveal never applies and a tap focuses the button only as it fires it, if at all. It becomes Dismiss once the upload has ended, whether it was uploaded, failed or was cancelled (`TERMINAL_STATUSES` in `upload.types.ts`).

### Overwrite prompts (warn-and-confirm)
Versioning is off, so nothing is overwritten without a confirmation (architecture.md: *The product presents filesystem UX over a store that has neither move nor rename*). The file browser makes no HEAD check: a write goes out refusing to overwrite, and the conflict it meets comes back to be confirmed. Which surface confirms it follows where the write ran — in the browser, or on the file-operations plane — and `features/file-browser/fileOpRouting.ts` is the one statement of that rule, so this section does not restate it.
- **`CollisionPrompt.tsx`** — an inline `alertdialog` card, not a modal: `rounded-lg`, `border-warning-soft`, `bg-warning-soft`, no scrim and no shadow. A filled `warning` triangle and one line, "A {file|folder} named “{name}” already exists.", then **Rename** (default), **Cancel** (ghost) and **Overwrite** (danger); Rename swaps in a name field with **Save as new name** (primary) and **Back** (ghost). It confirms an upload, on the file's row in the queue, and a new folder or a rename the browser performs, above the listing.
- **`BatchOverwritePrompt.tsx`** — the same `warning-soft` card with no icon, "N item(s) already exist at the destination.", **Overwrite all** (danger) and **Cancel**. It confirms a copy or move the browser performs.
- **`FileOpConflictsDialog.tsx`** — for a copy, move or rename the plane performed. Its **Review conflicts** control opens a neutral `ConfirmDialog`, "Some items could not be placed", which lists them with **Close** and **Overwrite…**; **Overwrite…** then opens a danger confirm, "Overwrite this item?" or "Overwrite these N items?". For a rename the first dialog offers **Use a different name…** instead, with an inline "overwrite what is there" link, and that opens a `FormDialog` with a **New name** field and **Request again**.
- **The Query workspace** confirms in a modal danger `ConfirmDialog`: "Overwrite “{file}”?" before saved results replace a file, and "Replace “{name}”?" before a saved query does (§6). A Parquet, JSON or Excel save asks the API whether the file exists (`objects.exists`) before it is queued, and a refusal to say counts as occupied.

### Empty / error states
Emptiness is never an error — per architecture.md → *Constraints that shape the system*. An empty space root renders an empty state: a `text-3` folder icon (`h-10`, 35px), "This folder is empty" in `text-xl` weight 600, and, where the user can write, "Upload a file or create a folder to get started." in `text-sm text-2`. It has no button; SPEC-024 FR-008, which specified it, names none. An empty sub-folder renders the table with only its `..` row, so the way back up stays in place. A missing `{username}/user_settings/shared-connections.json` reads as no connections, and the Shared spaces page shows one dashed `surface-2` line (§7).

---

## 6. Data analysis surface (Query workspace)

The portal's second surface — the Glue/Athena **Query workspace** (SPEC-034→036) — reuses every token and most components from the file browser, and adds **one token of its own**: `syntax-fn`, the editor's function colour (§1). Where a component already exists (table, pill, button, drawer), reuse it rather than building a parallel one.

### Primary tab navigation
The primary tabs are the top bar's (§5 *Top bar* carries their look and how they change with the width); Query is one of them. **Shared spaces** (SPEC-052) is the place to *manage* shared spaces (create/delete, member management). Files and Query *use* spaces: **Files** lists the user's spaces (personal + shared) as browsable roots (§5, SPEC-057) and **Query** lists their databases (personal + shared) in the schema rail (below, SPEC-047). So a shared space is managed under Shared spaces, browsed under Files and queried under Query, fed by one `useConnections` source.

### Schema browser (left rail)
The rail is **browse-only**. There is **no active database**: nothing in it chooses what a query runs against, so every base table a query reads is written `database.table` — the register entry [Query workspace has NO active database](../decisions/analytics.md#query-workspace-has-no-active-database-spec-077) records why.

**Chrome** (`components/CollapsibleRail.tsx`, shared with the Files sidebar). A `surface` panel with a right hairline, `w-[248px]` at `desktop` and `w-[220px]` in the `tablet` band. Its header carries the uppercase `Databases` caption and a **Collapse sidebar** control; inside, the personal database sits under a **My database** heading and the shared spaces under **Shared spaces** (no heading when there are none) — sentence-case `text-xs` `text-3` labels, not a level of the tree, so every database node keeps the same indent; collapsing eases the panel to zero width and leaves a slim **Show sidebar** handle to reopen it. The panel stays mounted, so whatever is expanded inside it survives a collapse. Collapsed or open is one choice, shared by both rails and remembered per browser, so collapsing either collapses the other. Below `tablet` the rail is not rendered; the same tree sits in `AppNavDrawer`'s contextual slot under the same caption.

**The tree** (`features/query/SchemaBrowser.tsx`, `DatabaseNode.tsx`). One node per database the user can reach, in `useConnections` order: the personal database first, labelled with the username, then each shared connection A–Z. With the shared-workspaces flag off, the rail lists the personal database alone. A usable database is a disclosure button — rotating chevron, database icon, then the label in `text-base` weight 600, `text-2` turning `text` on hover — whose accessible name reads "Expand {name}" or "Collapse {name}". On first reveal the personal database is expanded and every other node collapsed. The user's toggles hold only while the tree stays mounted: leaving `/query` resets them, and in the drawer every open is a first reveal. A node reads its schema only while expanded, and an expanded node gains a **Refresh tables in {name}** icon button that re-reads that one database, spinning and disabled while it does, without opening or closing anything. A shared connection that is `provisioning`, `failed`, `leaving` or `deleting` is a **static row** instead: a blank where the chevron would be, the icon and label in `text-3`, and its status as trailing `text-xs` text ("Provisioning…", "Failed", "Leaving…", "Deleting…"). It cannot be expanded. With no databases at all the rail reads "No databases available."

**An expanded node.** While its schema loads it reads "Loading schema…". The personal database, when Glue reports it as not existing, reads as setup rather than failure — "Setting up your database… This is automatic right after sign-up. If it persists, contact the Administrator." A shared space's database exists before anyone joins, so a missing one is a failure like any other, and any other failure is an alert in `danger`: "Couldn't load this schema. Try Refresh, or contact the Administrator." A loaded schema splits into two collapsible groups, **Tables** and **Views**, each headed by an uppercase `text-xs` caption with its count (`Tables (3)`); a Glue `VIRTUAL_VIEW` is a view and everything else a table, so the group conveys the type and no row carries a badge. Tables starts open, Views starts open only when there is at least one view, and a click on either pins it. An empty group keeps its heading, `(0)`, and says "No tables." or "No views." when open, so an empty Views group shows only its heading until clicked. Each object row is a 32px disclosure button — `py-2` (7px a side) around `text-sm`'s 18px line; a table glyph, the name in weight 500, a trailing chevron — that reveals its columns indented `pl-8` (28px) beneath it, each `name` beside a right-aligned monospace `text-xs` `text-3` type, or "No columns".

**No click-to-insert.** Nothing in the rail writes into the editor: rows open and close, and columns are there to read. Names reach the editor through autocomplete instead, which offers every accessible database's tables and views fully qualified (`database.table`) and their columns by bare name (`features/query/sqlCompletions.ts`).

> **Superseded by SPEC-244:** when the statement at the cursor names tables, only those tables'
> columns are offered, and in a Trino statement a name is inserted **quoted** where SQL would
> misread it bare. Full entry: `docs/decisions/analytics.md` → *Suggestions follow the statement,
> and a Trino insert is quoted where the name needs it*.

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
The editor pane sits below the toolbar and shares the column with the results through a draggable divider (SPEC-209, `features/query/useEditorSplit.ts`): a `separator` that moves by drag or by arrow keys in 5% steps, and resets on a double-click. It starts at half the column (`DEFAULT_EDITOR_FRACTION`), never lets the editor fall below 96px (`MIN_EDITOR_HEIGHT`) or the results below 120px (`MIN_RESULTS_HEIGHT`), all three in `features/query/query.constants.ts`, and remembers each user's split for the tab's session (`sessionStorage`). The Monaco theme (`features/query/SqlEditor.tsx`) sets three colours: the code area on `surface`, a left **gutter** on `surface-2`, and `text-3` line numbers; there is no divider line between gutter and code. The code is monospace at 13px (`text-sm`'s size) with no line-height of its own, so Monaco's default applies (20px on macOS, 18px elsewhere). Syntax theme maps onto tokens: **keywords** `accent-text` in bold (Monaco's theme rules offer bold and nothing lighter, so 700), **operators** `text-2`, **strings** `success`, **numbers** `warning`, **comments** `text-3` italic, **functions** `syntax-fn`, a violet that sits beside the indigo accent without becoming a second brand color. The real editor is Monaco (SPEC-035), lazy-loaded for the Query route only.

### Query tab strip (SPEC-041, SPEC-043)
An `h-10` strip (35px) on `surface-2` with a bottom hairline, sitting **above the editor toolbar**. It holds the open query tabs — each an independent query window — so it must read as a *third*, narrower level of navigation, visually distinct from both the top bar's underline tabs (§5) and the sidebar's filled `accent-soft` item. These are **"card" tabs**: an `h-7` (24.5px) `r-md` chip, `text-sm` weight 500, `text-2` at rest → `text` + `surface` background on hover; the **active** tab is `surface` with a `border` hairline, `shadow-sm` and a weight-600 label (so active state is never color-only), and carries no leading dot, which would read as the dirty marker below. **Labels:** blank `+` tabs are the monotonic `Query N` (never reused this session); tabs opened from a **saved query** (SPEC-043) or a **table action** (SPEC-044) carry a feature-supplied label (`Monthly revenue`, `sales_2026`, `DDL: sales_2026`). A linked saved-query tab with unsaved edits shows a leading **`accent` dirty dot/•** before its name (re-save clears it). Each tab carries a trailing close (`×`) hit target that tints `danger`/`danger-soft` on hover; closing a tab with non-empty SQL warns-and-confirms first (reuse the SPEC-026 dialog). The **last remaining tab hides its close control** (there is always ≥1 tab). A `+` ghost button at the start of the strip (`aria-label="New query tab"`) adds a tab and is **never disabled** — at the `QUERY_TABS_MAX = 10` cap, clicking it (or any other tab-opening action) raises the **tab-limit dialog** (a SPEC-026 `alertdialog`: "You have the maximum of 10 query tabs open. Close a tab before opening another." — single dismiss; the attempted action is not completed). The tab list scrolls horizontally if tabs overflow, leaving the `+` and the global buttons in place. A **global button** lives right-aligned on this same strip (right of the tab list, which takes the spare width), because it acts across all tabs: **History** (a compact ghost button). **Saved queries** sat beside it until 2026-09-28 (SPEC-043 FR-010) and moved to the editor toolbar, beside **Save**: at the far end of the strip, outside reviewers asked for a saved-queries feature without finding it. The active tab drives the editor content and all per-tab toolbar actions (Run / Clear / Save / Stop) below it.

### Editor toolbar
A `surface` row with a bottom hairline, at least 52px tall (`min-h-[52px]`), that wraps rather than overflows. There is **no database chip**, and the left of the row is empty. Everything sits in a right cluster of per-tab editor actions, acting on the active tab (SPEC-041): **Clear** (red outline, trash — SPEC-040; warn-and-confirm, disabled while running/empty), **Copy** (ghost; the whole buffer to the clipboard, disabled when empty), **Download** (ghost; the whole buffer as a `.sql` file named after the tab, built in the browser, disabled when empty), **Save** (ghost, save icon — SPEC-043; name-prompt, pre-filled when linked, disabled when empty), **Saved queries** (ghost, document icon; opens the drawer — it acts on no tab, and sits here because this is where people look for it), **Create view** (ghost, SPEC-048; opens a name-prompt and runs `CREATE OR REPLACE VIEW` in the background, disabled when empty), then **Run** — the one primary control, a split button: **Run Statement** (play icon; the selection or the statement under the cursor, ⌘/Ctrl+Enter) with a **More run options** menu holding **Run Query Tab** (⌘/Ctrl+Shift+Enter) and **Run Multiple Queries** (⌘/Ctrl+Alt+Enter). Run is disabled when the editor is empty; while a query is in flight **Stop** (danger-ghost, square) takes its place. The words show at `desktop`; in the `tablet` band the buttons are icons alone, each keeping its `aria-label`, and below `tablet` the workspace is browse-first and has no editor toolbar. **History is not here** — it's on the global tab-strip row above (SPEC-043 FR-010).

### Status bar
A slim bar below the editor showing execution state — `tablet:h-11` (38.5px) from `tablet`, and `min-h-11` below it, where it wraps — **never color-only** — always icon/spinner + text: **Running** = `accent-text` with a spinner + an indeterminate `accent` progress sliver + elapsed time and bytes scanned; **Succeeded** = `success` dot + "N rows · X scanned · Ys"; **Failed** = `danger` dot + "Failed", the reason itself carried by the workspace's `danger` **Banner** (SPEC-028) as **authored wording** mapped through `lib/errorMessages.ts` — the raw Athena `stateChangeReason` is **never** the banner's sentence, and appears only beneath it in a closed **Details** disclosure when the error is in the user's own SQL; **Cancelled** = `text-3` dot + "Cancelled". A right-aligned **Save results…** ghost button (SPEC-049 — replaces the old "Download CSV") sits beside **whichever terminal state is showing** (a state is required, not merely the absence of a spinner), whenever the displayed result is row-returning and its statement not a SHOW or DESCRIBE — for those it stays, refused with its reason, because Athena writes their output as plain text rather than a result set: a batch that failed at statement 3 can still save statement 1's rows, which are complete and already billed. Beside **Failed** or **Cancelled** it is preceded by a `text-2` note naming what it would write — "N rows from an earlier statement" — because `script-single` scope has no result-tab strip to identify the grid; the failed statement's own scanned/duration figures stay off the bar, so the two executions never read as one. The bar is an accessible live region.

**Save-results modal (SPEC-049).** "Save results…" opens a SPEC-026 centered modal (`features/catalog/SaveResultsDialog.tsx`) holding, in order: a **file name** `Input` defaulted to `query-results-{YYYYMMDD-HHmm}` (or `{saved name}-{YYYYMMDD-HHmm}` for a tab linked to a saved query), a **Format** `<select>` (CSV / Parquet / JSON / Excel, defaulting to CSV, and **absent** — not disabled — behind the `resultsConversion` flag), a **Save to** space select (the user's own space plus any shared spaces they belong to, SPEC-055, and absent when the user has only their own), a **destination folder** picker (the file-browser `DestinationPicker`, excluding each space's `athenaresults/`), and Save/Cancel. The extension follows the chosen format and replaces another one the user had typed. **Every ROW travels either way**, not the loaded page, and either way a name that already exists opens a modal danger confirm, "Overwrite “{file}”?", before anything is replaced (§5 *Overwrite prompts*). **Which COLUMNS travel is the caller's** since SPEC-239: the Query workspace sends every one, and the Data Explorer sends the result columns its grid is showing, in the order it shows them. Whenever that is not the result's own columns in its own order — which is the only time a copy cannot produce the file — the modal gains one line above the folder picker, "The file holds N result columns, in the order shown." **CSV** is a server-side copy of Athena's own result object **whenever the file wanted is that object**: immediate, the primary button reads **Save here**, and the success **Toast** carries a **View in Files** action that opens the destination folder in the space it was saved to, personal or shared — the link names that space (`/files?space={id}&prefix={folder}`), because without it Files resolves the personal one. **Parquet, JSON and Excel** are built by the results-conversion plane, **and so is a CSV that keeps only some of the columns**, which no copy can produce: the button reads **Convert and save**, the modal closes on submit, and the toast promises a notification rather than a file — nothing is written yet, so no listing changes until that notification arrives (SPEC-223, SPEC-239).

### Results table (reuses the file table)
`features/query/QueryResultsTable.tsx`. Same container as the file table: `surface`, `border`, `rounded-lg`; an `h-10` (35px) `surface-2` header in which each header stacks the column **name**, shown as Athena returned it rather than uppercased, over its **type** in a `text-[10px]` monospace `text-3` caption. Only the leading `#` header takes the uppercase micro-label style. Rows are monospace `text-sm`, `h-12` (42px), `border-2` dividers, `surface-2` hover, with a leading muted row-number column. Columns resize from a handle in the header, and cells truncate with the full text on hover. The body scrolls both ways inside the panel, with the header and the row-number column sticky, so a wide result never breaks the shell. Pagination is the shared **Pager** (`components/Pager.tsx`) below the scroll region: bordered **Prev** and **Next** buttons (`text-2`, `surface-2` hover, `h-[38px]` below `tablet` and `h-9` (31.5px) from it) either side of an `aria-live` range reading "Rows X–Y", which gains "of N" once the exact total is known, and Next reads "Loading…" while it fetches. It is a *replace* pager (SPEC-038, which retired the results "Load more"): one page is in the DOM, the page size is the workspace-wide **Rows per page** control above the grid, and `useQueryResults` keeps the fetched pages in a `useInfiniteQuery` keyed by execution and page size, each page threading Athena's `NextToken`, so Prev is served from cache. An empty result is not an error, and it is a single muted line rather than the §5 empty state: "No rows returned." in a bordered `surface` box for a zero-row result, and "The run finished without returning rows." in the results area when the run produced no result set to show. A read that failed before any page loaded is not an empty result either: it shows the error in the same place instead, while a failed re-read of a result already shown keeps what it showed.

### Query history drawer (right slide-over, reuses the upload-drawer pattern)
The shared `Drawer` again — 440px from `tablet`, `shadow-lg`, the same `bg-black/30` blurred scrim, no animation, a bottom sheet below `tablet` — identical mechanics to the upload drawer (`features/query/QueryHistoryPanel.tsx`). The drawer header carries a **Refresh** icon-button (SPEC-046) in its `headerAccessory` slot (a ghost `IconButton`, `aria-label="Refresh history"`) that re-reads `query-history.json` through the API on demand — disabled with a spinner while in flight, back on the newest page once the re-read settles, and a read error surfaces as a `danger` `Banner` ("Couldn’t load history.") without dropping the current list. Each entry is a bordered `r-md` card (`QueryHistoryRow.tsx`): a status **pill** (Succeeded, Failed, Cancelled or Unknown, on `success`/`danger`/neutral soft fills with a leading dot — never color-only), a right-aligned relative timestamp (absolute on hover), a "Saved: {name}" `accent-soft` chip when the run came from a saved query, a single-line monospace SQL preview (ellipsis-truncated), and a footer with the run stats (`scanned · duration`, since an entry stores no row count), the database, and right-aligned **Open** / **Re-run** text actions (`accent-text`), each opening the entry in a NEW tab so the tab it was opened from keeps its SQL. History is the per-user `{username}/user_settings/query-history.json` store only, capped at 100 entries — it never shows other users' or workgroup-wide queries. **Pagination (SPEC-042):** the drawer shows the **7 most recent** entries (newest-first) with the shared **Pager** in its footer — **Prev**, a `text-2` range label in the form `1–7 of N`, then **Next** (Prev disabled on page 1, Next disabled on the last page). It is a *replace* pager (one page of ≤7 in the DOM), like the results pager (SPEC-038), not append; it resets to the newest page when the drawer is reopened or a new entry arrives.

### Saved queries drawer (SPEC-043)
A second right slide-over with the **same mechanics as the history drawer** (440px, `shadow-lg`, scrim, Escape/scrim/close-button dismiss). Opening one closes the other. Each entry is a bordered `r-md` card (`features/query/SavedQueriesPanel.tsx`): the saved query's **name** (weight 600), a right-aligned relative **updated** time, the file's **size** in `text-sm text-3` (not a SQL preview — a `.sql` object carries no metadata, so a preview would cost a read per row), and right-aligned **Open** and **Open and run** (`accent-text`) + **Delete** (`danger`) text actions. **Open** routes through `openTab` (named, linked tab; honors the tab-limit dialog); **Open and run** does the same and then runs the tab's whole SQL as **Run Query Tab** does, recording the saved query in history. **Delete** raises an "are you sure" `alertdialog`, `Delete “{name}”?`. The drawer pages ten at a time with the shared **Pager** (label `X–Y of Z`, or `Z+` while more pages remain) and carries a space selector (register entry [A display page is not a listing page, and the space selector is gated](../decisions/browser.md#a-display-page-is-not-a-listing-page-and-the-space-selector-is-gated-spec-174)). Empty state: "No saved queries in {space}", then "Save a query from the editor and it’ll appear here so you can open and run it again."

### Confirm dialogs & name prompt (SPEC-026 reuse)
All modals reuse the SPEC-026 centered-modal pattern (`components/Modal.tsx`: scrim `bg-black/40` with a blur, darker than the drawer's; `surface` panel, `r-lg`, `shadow-lg`, header title + body, a `surface-2` footer with right-aligned Cancel + action; Escape/scrim dismiss), mostly through `ConfirmDialog` and `FormDialog`. Used by, among others: the **Save name-prompt** (a space select, a labelled `Input`, a note that it saves a `.sql` file under that space's `saved_queries`, and Save/Cancel), the **Create-view name-prompt** (SPEC-048 — labelled `Input`, catalog-safe-name validation + inline error, Create/Cancel), the **Save-results modal** (SPEC-049 — see Status bar), the **Clear query** and **Close tab** confirms, the **Drop table / Drop view** confirm (`alertdialog`, danger action), the **Delete saved query** confirm (`alertdialog`, danger), the **Share table** and **Refresh table** dialogs, and the **tab-limit** dialog (`alertdialog`, single dismiss with **Got it**).

### Toast (SPEC-044)
A lightweight transient notice (`components/Toast.tsx`), first built for **Drop table** feedback and now used across the app. Bottom-right, `r-lg`, `shadow-lg`, `max-w-sm`, and the whole card takes its variant's tone: **success** is `success` text and border on `success-soft`, **danger** is `danger` on `danger-soft`, and **info** is `text-2` on `surface` with a `border` hairline. Success and danger dismiss themselves after 4 seconds (`AUTO_DISMISS_MS`), unless they carry an action link, which keeps them until the user acts or dismisses; an info toast (a "working…" notice) stays until its caller clears it. Every toast has a dismiss button and is a live region (`alert` for danger, `status` otherwise). One shows at a time, a new one replacing it, and it never blocks interaction.

### Charts (future)
A results chart should use the `accent` as series 1 and extend with analogous hues (e.g. `syntax-fn`'s violet, the green of `success`) rather than introducing a second brand color. Out of scope for v1; no new tokens anticipated.

---

## 7. Shared spaces (Bucket 2)

The third surface — collaborative **shared spaces** (SPEC-050→056) — reuses every token and component above; **no new tokens**. Connections are created/managed through an **asynchronous pipeline** (see `lambdas/info/planes/shared-spaces.md`), so the UI's defining trait is **status**: a connection can be *provisioning*, *active*, *failed*, *leaving* or *deleting*, and a member *pending* or *active*. A membership change reaches the user's access at the next credential vend, which Refresh shared spaces forces (architecture.md, *Propagation is not instant*). The design must make that state legible and never present a pending resource as ready.

### Status treatment (the shared-surface primitive)
On the Shared spaces list a connection's state renders as a `StatusPill` — a dot and a word, never color-only (`connectionStatus.ts`): **Provisioning…**, **Leaving…** and **Deleting…** are `warning` pills whose dot pulses; **Active** is a `success` pill; **Failed** is a `danger` pill + a short reason ("Provisioning failed.", "Deleting this shared space failed."), with a size-`sm` **Retry** button (default variant) and, only when the failure was a create, **Dismiss** (ghost). A row stuck in `deleting` gets the same Retry. The other surfaces say less: the Files Spaces list and the Query rail show a not-ready connection's status as a plain `text-3` word and nothing for an active one (§5, and *Inline appearance* below), the space selects show no status, and the member list uses the same pill for each member's join status (**Active** or **Pending**).

### Shared spaces tab (management list)
The **Shared spaces** tab in the top bar (§5; the route is still `/connections`) is the management surface (SPEC-052, `features/shared-spaces/ConnectionsPage.tsx`). A page header titled **Shared spaces**, with a **Refresh shared spaces** icon-button and then a **New shared space** primary button, whose label shortens to **New** below `desktop`. Below, a list of bordered `r-lg` cards — one per connection: the **name** (weight 600, monospace, since it's also the prefix/DB), a **role** indicator (a neutral `Owner`/`Member` pill), a **status** pill (above), and right-aligned role-gated actions — **Manage** (owner only, default variant → opens the members **drawer**, below), **View members** (member, ghost), **Leave** (member, `danger`-ghost), **Delete** (owner, `danger`-ghost). Empty state (no connections): one dashed `surface-2` box reading "No shared spaces yet — create one or ask an owner to add you." in `text-sm text-2`, with no icon, headline or button; **New shared space** is already in the header. A failed card, or one stuck in `deleting`, shows Retry (and Dismiss after a failed create) in place of its role actions. Otherwise an owner's card that is not active keeps Manage disabled and has no Delete, and a member's has no actions until it is active.

### Create shared space dialog (SPEC-051)
A SPEC-026 centered modal: a labelled **name** `Input` validated to the catalog-safe rule (`^[a-z][a-z0-9_]{2,62}$`) with inline error, a note that the name is **permanent and globally unique** (it becomes the S3 prefix and the Glue database, and can't be reused later even if the space is deleted), and Create/Cancel. On Create the connection appears immediately in a **provisioning** state (a Toast `Creating “{name}”…`). It flips to active (or failed) by itself: after any create, add, leave or delete the page polls the connections cache every 4 seconds for 30 seconds (`useConnections.ts`).

### Manage-members drawer (owner, SPEC-053)
Opened via **Manage** on an owned connection — a **right slide-over drawer** (the shared `Drawer`: 440px from `tablet` and full height below it, scrim, Escape/scrim/close-button dismiss), *not* a separate page. The drawer header names the connection, with a Refresh shared spaces icon-button and an **Add members** primary button. The body is a member list (`MembersList.tsx`; rows: avatar, username, an `Owner` pill on the owner, an **Active** or **Pending** pill — Pending means added but not yet opened in Files — and on each other member a **Remove** `danger`-ghost and a transfer-ownership action; the owner row has neither). **Add members** opens a dialog with a username **chips field** with typeahead (`UsernameChipsField`), which takes one name or a pasted list split on commas and spaces, + Add/Cancel. On submit a toast reads "Adding 3 members to “{space}”…" ("member" for one). Usernames are checked against the User Pool, and none is silently dropped: each one refused comes back to the owner as a notification, "…no such user." or "…they've reached their shared-space limit.".

### Leave / Delete confirms (SPEC-054)
**Leave** (member) is a danger-toned `ConfirmDialog` titled "Leave shared space", with a danger confirm: "Leave {name}? You'll lose access to its files and tables. They are not deleted — everyone else keeps access." **Delete** (owner) is a `danger` **`alertdialog`** saying that every member loses access, the owner included, that the files and tables are kept by administrators rather than destroyed, and that the name can never be reused (register entry [A delete removes people, not things](../decisions/control-planes.md#a-delete-removes-people-not-things--and-retention-keys-on-a-durable-fact-never-live-status-spec-205)). It requires **typing the space name** to enable the destructive button — the one typed confirmation in the app, where file delete and Drop table confirm with a button alone. Both show the connection in a transient `leaving`/`deleting` state until the cache drops it.

### Inline appearance — Query rail & Files list (shared)
Shared spaces appear inline where they're *used*, fed by the same `useConnections` source. In the **Query** schema rail (§6 *Schema browser*), every shared connection lists below the personal database, A–Z. An **active** one is a database node like the personal one: expand it to browse its tables and views, whose row menus act on that database. Nothing in the rail makes it a query's target, because there is no active database ([register](../decisions/analytics.md#query-workspace-has-no-active-database-spec-077)): a query reads a shared table by naming it in full, `{connection}.{table}`. Results land in the personal prefix; a shared space is a destination the user picks when saving them (§6 *Save-results modal*). A `provisioning`, `failed`, `leaving` or `deleting` one is a static row that cannot be expanded, its status as plain `text-3` text rather than the pill above, with no reason shown for a failure. With the shared-workspaces flag off, the rail lists the personal database alone. In the **Files** sidebar Spaces list (§5, SPEC-057), **active** shared connections appear as browsable roots, and one in any other state is **disabled** with its status so the user sees progress but can't browse a not-ready space.

### Refresh shared spaces (SPEC-052)
A ghost icon-button (the SPEC-046 refresh pattern) on the connections screen and in both drawers it opens — the owner's Manage-members drawer and a member's read-only roster. It **re-mints the Cognito ID token**, so a newly-granted membership's claims reach the API, which stamps the tag at its next credential vend (the browser holds no AWS credentials), and then re-reads the per-user connections cache through the API — the on-demand way to pick up a just-granted space without an app reload. Spinner + disabled while the re-read is in flight; error → `Banner` ("Couldn’t load your shared spaces. Try Refresh, or contact the Administrator."), prior list intact.

---

## 8. Accessibility notes
- Contrast in the light theme, by the WCAG formula `lib/contrast.ts` implements: on white (`surface`) `text` is ≈ 17.7:1, `text-2` ≈ 5.9:1 and `text-3` ≈ 5.4:1, and the slightly darker `bg` brings them to ≈ 16.6, 5.6 and 5.1:1, so all three clear AA (4.5:1) for body text on each of the three text surfaces (`bg`, `surface`, `surface-2`), which are the pairings `CONTRAST_PAIRS` measures for them. `accent` on white and white on `accent` are both ≈ 6.3:1. `success`, `warning` and `danger` clear 4.5:1 on white (≈ 5.5, 5.0 and 6.5:1) and on their own `-soft` fills (≈ 5.0, 4.6 and 5.7:1), and `syntax-fn` is ≈ 5.7:1 on the editor background. Avoid `text-3` for essential body copy.
- Both themes are measured rather than eyeballed. `lib/contrast.test.ts` resolves every pairing in `CONTRAST_PAIRS` (`lib/palette.ts`) against each palette and fails on any that misses its floor. In the dark theme the ratios run 3.25–16.2, and the five tightest are all the focus ring, against `warning-soft`, `success-soft`, `surface-2`, `accent-soft` and `danger-soft` (floor 3:1, WCAG 1.4.11).
- Every interactive element gets a visible focus ring: by default a 2px solid `accent` outline, offset 2px (§1). A control that draws its own ring suppresses that outline and draws the ring in its place — `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`, 2px with no offset — and adds `focus-visible:ring-inset` inside an `overflow-*` container or on an edge-to-edge row, where an outside ring is clipped. The ring alone, without `outline-none`, draws two indicators. An input in error and the saved-query **Delete** ring in `danger` instead (`focus-visible:ring-danger`).
- State is never color-only: selected rows also show a checked box; status pills carry text/icon.
- Pointer targets must be at least 24×24px (WCAG 2.5.8), and that is the floor, not a larger one. Write it in px — `h-[24px]`, not `h-6`, which is 21px against the 14px root. *Target size in this app* in `apps/portal/info/best-practices/accessibility/accessibility.md` carries the rule, and `lib/targetSize.test.ts` backs it with a sweep of the size classes that fails the test suite on a new control below the floor; the controls already under it are listed there, each with a note, in `ACCEPTED_UNDERSIZED`. The common controls: `IconButton` `h-8` (28px) and `h-7` (24.5px), `Button` `h-9` (31.5px) and `h-8` (28px), file-table rows `h-12` (42px).
