# Completed Spec - SPEC-021 Design Token Baseline

## What was completed from this spec?

`apps/portal/src/index.css` was replaced with a clean Tailwind v4 baseline:

- Inter loaded via Google Fonts `@import` (before `@import "tailwindcss"`).
- A single `@theme` block declaring the full design-system token set: neutral / text /
  accent / status colors (each with soft variants), the Inter `--font-sans` stack, the
  six-step type scale with paired line-heights, the four radii, and the three shadows.
- An `@layer base` block: `box-sizing: border-box`, `html { font-family; font-size:14px }`,
  `body { bg-bg; text; antialiased; margin:0 }`, and the `:focus-visible` accent ring
  (2px @ 40% via `color-mix`).
- All Vite scaffold styles removed (purple accent vars, `#root` width clamp, `h1/h2`
  resets, `code`/`counter` blocks, and the `prefers-color-scheme: dark` override — the
  portal is light-mode only).

Color, radius, and shadow utilities (`bg-accent`, `text-text-2`, `rounded-lg`, `shadow-md`,
etc.) now generate, and the type scale overrides Tailwind's defaults.

## What has changed?

**Deviation from the spec's literal token names (important for downstream specs).**
The spec body specified the type scale using `--font-size-*` and `--line-height-*` custom
properties. In **Tailwind CSS v4 the font-size theme namespace is `--text-*`**, not
`--font-size-*` (paired line-height is `--text-<step>--line-height`). Declaring
`--font-size-md` does **not** generate a `text-md` utility and does **not** override
`text-base`/`text-sm` — those names are treated as plain, unused custom properties.

This was the spec's flagged Open Question. Resolution: the typography tokens are declared
under the correct `--text-*` namespace. This satisfies the actual acceptance-criteria
intent — `text-xs`=12px, `text-sm`=13px, `text-base`=14px, `text-md`=16px (now generates),
`text-lg`=18px, `text-xl`=22px, each with its design line-height. Verified by inspecting
the built CSS (`--text-base:14px`, `.text-md{font-size:var(--text-md);...}`).

The `@layer components` `.text-md` fallback floated in the Open Question is **not needed** —
the native `--text-md` token generates the utility.

No component files were touched (per spec scope). `npm run build`, `npm run lint`, and the
full test suite (225 tests) pass with no changes required.
