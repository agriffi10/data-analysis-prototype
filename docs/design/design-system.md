# Design System — S3 File Portal

**Aesthetic:** Clean / minimal SaaS. Generous whitespace, neutral grays, a single accent (indigo), light hairline borders, table-forward layouts. Reads as trustworthy enterprise tooling.

This doc is the source of truth for the look. The companion file `mockup.html` is a live, interactive realization of these tokens (file browser + upload flow). The CSS variables in the mockup match the token tables below 1:1, so changes can be made in either place and kept in sync.

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

### Sidebar (248px)
Surface panel, right hairline border. Uppercase section labels (`My Files`, `Shared Connections`). Nav items: 36px tall, `rounded-md`, icon + label; **active** = `bg-accent-soft text-accent-text`; hover = `bg-surface-2`. "Add connection" is a dashed-border ghost button at the bottom of the connections group. The active user-space item carries the Cognito `username` as its label.

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

## 6. Forward-looking: data analysis surface

The portal will grow a Glue/Athena query + results surface. To keep it visually consistent when it lands, reuse: the table component (query results), the pill (column types), the accent (run-query primary + active tab), `surface-2` (SQL editor gutter / inset), and the drawer pattern (query history / saved queries). A results chart should use the accent as series 1 and extend with analogous hues rather than introducing a second brand color. No new tokens should be needed for v1 of that surface.

---

## 7. Accessibility notes
- Contrast: `text` on `surface` ≈ 16:1; `text-2` on `surface` ≈ 6:1 (AA for body). Avoid `text-3` for essential body copy.
- Every interactive element gets a visible focus ring (`accent` @ 40%, 2px, offset 2px).
- State is never color-only: selected rows also show a checked box; status pills carry text/icon.
- Hit targets ≥ 32px; table rows 48px.
