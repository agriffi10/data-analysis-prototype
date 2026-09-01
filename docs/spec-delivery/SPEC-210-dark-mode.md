# Completed Spec — SPEC-210: Dark Mode

## What was completed?

- **A contrast harness, and the dark palette derived under it.** `lib/contrast.ts` (WCAG luminance
  and ratio, refusing a malformed hex rather than computing a plausible number on it),
  `lib/palette.ts` (both themes, `CONTRAST_PAIRS`, `DECORATIVE_TOKENS`, the fixed landing strip) and
  `lib/contrast.test.ts`, which measures every declared pairing in **both** themes and fails naming
  the pair and its ratio. It ran against the light palette first and reproduced every ratio
  `index.css`'s comments record; the dark values are then whatever passed it.
- **A three-state preference** — Light / Dark / System, `localStorage`, per browser — as a module
  store read through `useSyncExternalStore` (`lib/useTheme.ts`, `lib/theme.types.ts`), plus
  `public/theme-init.js`, loaded blocking from `<head>` so nothing flashes light. The store is
  chosen because the preference resolves **before React mounts** and so can share the
  initialiser's resolution. **A Context provider would have worked too** — two successive
  justifications for preferring the store were written and both were false (see the register
  entry); the honest difference is that the state is reachable without a render.
- **The control**: `components/ThemeMenu.tsx` — an `IconButton` + `Menu` in the header, and the same
  three choices as a `SegmentedFilter` group in `AppNavDrawer`. `Menu`'s items gained an optional
  `selected`, which makes one a `menuitemradio` with `aria-checked` and a tick.
- **Monaco follows the theme.** Both editor themes are built from `PALETTE` by one expression
  evaluated twice, registered in `beforeMount` (which runs once), and switched through the `theme`
  prop — `editor.setTheme` in an effect, no remount.
- **The literal sweep.** `lib/colourLiterals.test.ts` reads every non-test source through
  `import.meta.glob('?raw')` and fails on a hex, a Tailwind numbered scale, or a `white`/`black`
  utility outside a per-file exemption carrying its reason.
- **Help**: one guide under Query — *Switch between light and dark*.

### Deliberate deviations

- **`accent-hover` and `danger` are measured against the foreground each actually carries**, not as
  text. Grep-verified: `accent-hover` appears only as `hover:bg-*` and as a gradient stop, always
  under white. In the dark theme the drafted pairings are unsatisfiable beside the ones the design
  uses, so the one danger button gained `--color-on-danger`. Reasoned in FR-001 in the spec.
- **`predefined.sql`'s violet became `--color-syntax-fn`** rather than joining the exemption list —
  the spec offered both, and a token gets a dark counterpart and a measured pairing for free.
- **The landing call-to-action strip is made fixed rather than assumed to be.** It was `bg-accent`
  with `text-accent-text` buttons; both theme. Its six colours are now custom properties outside
  every theme block, and four raw pairings measure them.
- **The sweep covers Tailwind's numbered scales too.** `NotFoundPage.tsx` carried three `text-gray-*`
  — a real dark-mode hole on a public route, invisible to a hex-only sweep.
- **The theme control stays in the header when signed out at mobile**, because `AppNavDrawer` mounts
  only for an authenticated user and the signed-out header is not the one the width measurement is
  about. The landing route, which suppresses the app header, carries its own copy.
- **Shadows theme through a `--shadow-tint-*` indirection.** Redefining `--shadow-*` in a theme block
  is inert and silent — Tailwind inlines the value. Measured in the built CSS, not assumed.

## What changed from earlier specs?

- **SPEC-184**: `FORMATTING_TOKEN_HEX` and `FORMATTING_BASE_SURFACES` are gone, replaced by
  `formattingTokenHex(theme)` / `formattingBaseSurfaces(theme)` resolving from `lib/palette.ts`.
  There is no longer a copy of the palette to pin, so that spec's `index.css` agreement test is
  subsumed by `lib/contrast.test.ts`; its block-scoped parse moved to `src/test/cssTokens.ts`, which
  both suites now read. `gradientShade` and `computePageFormatting` take an `EffectiveTheme` — a
  gradient is the one colour in the app emitted as a literal. The cross-product contrast test runs
  per theme, with the admissible foreground set **recomputed**: `warning` is measured out in light
  and back in on dark, while the offered set stays five in both.
- **SPEC-155**: `Menu`'s item type gained `selected?: boolean`; existing callers are unchanged.
- **SPEC-045**: `test/axe.ts` states its light-mode cap explicitly and points `color-contrast` at the
  harness at both sites.
- **The suite's `matchMedia` stub** answered `innerWidth >= 0` — true — for any query that was not a
  width, so the first `prefers-color-scheme` query would have silently run the whole suite in dark.
  It now answers width queries, colour-scheme queries (driven by `test/colorScheme.ts`), and false.
- **SPEC-194**: one section in `.github/scripts/spa-image-matrix.sh` for `/theme-init.js`. No nginx
  change was needed — `location /` already serves root files with the shell's `no-cache`.

### Raised, not fixed

- **`text-danger/80` over `danger-soft` measures 4.19 in light and 4.42 in dark** (the metadata
  panel's error detail). Pre-existing, sub-AA in **both** themes, and dark is the better of the
  two — so it is not something this spec introduced or worsened. Out of Scope says a light pairing
  that fails is "a finding to raise, and the fix is its own decision", so it is raised here. The
  fix is one modifier (`/80`), but it is a light-palette decision and belongs to whoever takes it.
  Found by building the app and measuring every rendered pairing, not by the pairing list.

## Verification

`format:check`, `lint`, `build`, `test` (2217 tests), `test:coverage` (90.79% statements, floors 85)
and `check:bundle` all exit 0 locally, plus `validate_docs.py` and `ruff`. Five guards were
mutation-tested rather than argued: breaking the harness's failure reporter reddens its
deliberate-failure test; a `key` that remounts the editor reddens the Monaco no-remount count; a
`--color-*` added to `index.css` alone, and one added to the dark block alone, each redden the
stylesheet check naming the token; inverting `theme-init.js`'s `system` resolution reddens three
of its tests; and pointing a Monaco rule at a decorative token reddens the pairing guard naming
the rule. The second and third of those closed holes a reviewer found — the stylesheet pin was
one-directional, and the initialiser was pinned by substring rather than run. Deferred to a browser: that Monaco keeps
the **cursor and scroll position** across a switch (jsdom stubs the editor, so only the buffer and
the absence of a re-create are assertable here) and that no light flash occurs before first paint —
both recorded in `docs/testing/owed.md`.
