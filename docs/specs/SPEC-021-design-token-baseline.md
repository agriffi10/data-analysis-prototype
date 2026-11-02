---
type: Spec
id: SPEC-021
title: "Design Token Baseline"
description: "Gives developers the design system's semantic tokens for color, type, spacing, radius, and shadow in a Tailwind v4 theme block in the CSS entry point, replacing the Vite boilerplate styles."
spec_status: Completed
depends_on: []
---

## Overview

The app was built with default Tailwind CSS utility classes (`gray-*`, `blue-*`, `red-*`). The design system defined in `docs/design/design-system.md` specifies a complete set of semantic tokens — colors, typography, spacing, radius, and shadow — using a neutral-gray + single-indigo-accent palette. This spec wires those tokens into the codebase so that every subsequent visual-polish spec can reference them directly (e.g. `bg-surface`, `text-text-2`, `rounded-lg`, `shadow-md`) instead of hard-coded color values.

The app uses **Tailwind CSS v4** (via `@tailwindcss/vite`). In v4, custom tokens are declared in the CSS entry point using an `@theme` block — there is no `tailwind.config.ts`. This spec replaces the legacy Vite boilerplate in `apps/portal/src/index.css` and installs the full design token set.

## Scope

### In Scope

- Replace `apps/portal/src/index.css` with a clean reset: `@import "tailwindcss"`, the `@theme` token block, and minimal base styles matching the design system (font, body bg, antialiasing).
- Define all color tokens from `docs/design/design-system.md §1`: neutrals, text, accent, status (success / warning / danger), each with their soft-bg variants.
- Define typography tokens (§2): Inter font stack, `text-xs` through `text-xl` at the specified sizes and line heights.
- Define radius tokens (§3): `--radius-sm` (6px), `--radius-md` (8px), `--radius-lg` (10px), `--radius-full` (999px).
- Define shadow tokens (§3): `--shadow-sm`, `--shadow-md`, `--shadow-lg`.
- Add an `@layer base` rule that sets `font-family: var(--font-sans)` and `font-size: 14px` on `html`, `background-color: var(--color-bg)` and `color: var(--color-text)` on `body`, and the standard focus-ring rule (`outline: 2px solid color-mix(in srgb, var(--color-accent) 40%, transparent); outline-offset: 2px`) on `:focus-visible`.
- Add Inter from Google Fonts via `@import url(...)` at the top of the CSS file.
- Remove all Vite scaffold styles (the purple accent variables, `#root` max-width constraint, `h1`/`h2` resets, `code`/`counter` blocks, `color-scheme: light dark` dark-mode override). **The portal is light-mode only.**

### Out of Scope

- Updating any component files — this spec only touches `index.css`.
- Dark mode support.
- Adding or changing any Tailwind plugin.

---

## Functional Requirements

### FR-001: Design token `@theme` block

#### Description

`index.css` must declare a single `@theme` block containing all design system tokens as Tailwind CSS v4 CSS custom properties. Tokens must use Tailwind v4 naming conventions so they generate utility classes automatically.

#### Acceptance Criteria

- [ ] `@theme` block exists in `index.css` after the `@import "tailwindcss"` line.
- [ ] Color tokens generate utility classes: `bg-bg`, `bg-surface`, `bg-surface-2`, `border-border`, `border-border-2`, `text-text`, `text-text-2`, `text-text-3`, `bg-accent`, `bg-accent-hover`, `bg-accent-soft`, `text-accent`, `text-accent-hover`, `text-accent-soft`, `text-accent-text`, `bg-success`, `bg-success-soft`, `text-success`, `bg-warning`, `bg-warning-soft`, `text-warning`, `bg-danger`, `bg-danger-soft`, `text-danger`.
- [ ] Font family token `--font-sans` generates `font-sans` utility.
- [ ] Font size tokens (`--font-size-xs` through `--font-size-xl`) override Tailwind defaults so `text-xs` = 12px, `text-sm` = 13px, `text-base` = 14px, `text-md` = 16px, `text-lg` = 18px, `text-xl` = 22px — each paired with the line-height from the design system.
- [ ] Radius tokens (`--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-full`) generate `rounded-sm` = 6px, `rounded-md` = 8px, `rounded-lg` = 10px, `rounded-full` = 999px.
- [ ] Shadow tokens (`--shadow-sm`, `--shadow-md`, `--shadow-lg`) generate `shadow-sm`, `shadow-md`, `shadow-lg` utilities.

### FR-002: Inter font loaded

#### Description

The Inter typeface must be loaded from Google Fonts so it renders in the browser.

#### Acceptance Criteria

- [ ] `index.css` begins with `@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');` before `@import "tailwindcss"`.
- [ ] `font-family` on `html` resolves to Inter when available, falling back to the system stack.

### FR-003: Base layer resets

#### Description

The `@layer base` block must establish the design system's default type treatment, background, and focus ring.

#### Acceptance Criteria

- [ ] `html` has `font-family: var(--font-sans)` and `font-size: 14px` (the design base).
- [ ] `body` has `background-color: var(--color-bg)` (`#f7f8fa`) and `color: var(--color-text)` (`#15191e`).
- [ ] `-webkit-font-smoothing: antialiased` and `moz-osx-font-smoothing: grayscale` are set on `body`.
- [ ] `* { box-sizing: border-box; }` is set.
- [ ] `:focus-visible` gets a 2px `accent`-colored outline at 40% alpha (using `color-mix`) with `outline-offset: 2px`.
- [ ] No dark-mode `@media (prefers-color-scheme: dark)` block exists.
- [ ] The Vite scaffold's `#root` width/margin/border constraints are removed.

### FR-004: No regressions

#### Description

Removing the Vite scaffold styles must not break any existing component that relies on CSS currently in `index.css`.

#### Acceptance Criteria

- [ ] The app builds without errors (`npm run build -w apps/portal`).
- [ ] Tests pass (`npm run test -w apps/portal`).
- [ ] The existing component classes (e.g. `rounded-lg`, `border`, `bg-white`) continue to work — they are not affected because they reference Tailwind utilities, not the removed root CSS variables.

---

## Data Model

_No new TypeScript types._

---

## API / Interface Contract

Token reference — Tailwind utility class → hex value (use in components, not raw hex):

```
bg-bg                → #f7f8fa
bg-surface           → #ffffff
bg-surface-2         → #fafbfc
border-border        → #e6e8eb
border-border-2      → #f0f1f3
text-text            → #15191e
text-text-2          → #5b6573
text-text-3          → #8a93a2
bg-accent            → #4f46e5
bg-accent-hover      → #4338ca
bg-accent-soft       → #eef2ff
text-accent-text     → #4338ca
bg-success           → #0f9d6e   bg-success-soft → #e7f7f0
bg-warning           → #c2820a   bg-warning-soft → #fdf4e3
bg-danger            → #dc2626   bg-danger-soft  → #fdeceb

rounded-sm  → 6px   rounded-md → 8px
rounded-lg  → 10px  rounded-full → 999px

shadow-sm   → 0 1px 2px rgba(16,24,40,.05)
shadow-md   → 0 4px 12px rgba(16,24,40,.08)
shadow-lg   → 0 12px 32px rgba(16,24,40,.14)
```

---

## File & Folder Structure

```
apps/portal/src/
└── index.css    ← sole file changed
```

---

## Implementation Phases

### Phase 1: Replace index.css

Structure of the new file (in order):

1. `@import url('https://fonts.googleapis.com/...')` — Inter 400/500/600/700
2. `@import "tailwindcss";`
3. `@theme { ... }` — all tokens (see FR-001 acceptance criteria for the full list)
4. `@layer base { ... }` — html/body resets, focus ring, box-sizing (FR-003)

The `@theme` block follows Tailwind v4 naming: color values use `--color-*`, font family uses `--font-*`, font sizes use `--font-size-*` (paired with `--line-height-*` or inline as a space-separated pair), radii use `--radius-*`, shadows use `--shadow-*`.

**Exact token values:**

```css
@theme {
  /* Colors — neutrals */
  --color-bg:         #f7f8fa;
  --color-surface:    #ffffff;
  --color-surface-2:  #fafbfc;
  --color-border:     #e6e8eb;
  --color-border-2:   #f0f1f3;

  /* Colors — text */
  --color-text:   #15191e;
  --color-text-2: #5b6573;
  --color-text-3: #8a93a2;

  /* Colors — accent (indigo) */
  --color-accent:      #4f46e5;
  --color-accent-hover: #4338ca;
  --color-accent-soft:  #eef2ff;
  --color-accent-text:  #4338ca;

  /* Colors — status */
  --color-success:      #0f9d6e;
  --color-success-soft: #e7f7f0;
  --color-warning:      #c2820a;
  --color-warning-soft: #fdf4e3;
  --color-danger:       #dc2626;
  --color-danger-soft:  #fdeceb;

  /* Typography */
  --font-sans: 'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;

  --font-size-xs:   12px;
  --font-size-sm:   13px;
  --font-size-base: 14px;
  --font-size-md:   16px;
  --font-size-lg:   18px;
  --font-size-xl:   22px;

  --line-height-xs:   16px;
  --line-height-sm:   18px;
  --line-height-base: 20px;
  --line-height-md:   24px;
  --line-height-lg:   26px;
  --line-height-xl:   30px;

  /* Radius */
  --radius-sm:   6px;
  --radius-md:   8px;
  --radius-lg:   10px;
  --radius-full: 999px;

  /* Shadow */
  --shadow-sm: 0 1px 2px rgba(16,24,40,.05);
  --shadow-md: 0 4px 12px rgba(16,24,40,.08);
  --shadow-lg: 0 12px 32px rgba(16,24,40,.14);
}
```

**Note on `text-md`:** Tailwind v4 does not have `text-md` by default. Defining `--font-size-md` generates the `text-md` utility. Confirm this works in a dev build; if not, name it `--font-size-[16px]` and reference it with the arbitrary value `text-[16px]`.

#### Checkpoint

- `npm run build -w apps/portal` succeeds.
- `npm run test -w apps/portal` passes.
- In the Vite dev server, open the app. The body background should visually change from white to `#f7f8fa` (a very light gray). Inter should be loaded (check Network tab for `fonts.googleapis.com`).
- In DevTools, verify `--color-accent` resolves to `#4f46e5` on `:root`.

---

## Open Questions

- [ ] Tailwind v4 `--font-size-md` generating `text-md` — confirm in a dev build that the non-standard step name works. If not, the simplest workaround is to add a CSS alias `.text-md { font-size: 16px; line-height: 24px; }` in `@layer components`.
