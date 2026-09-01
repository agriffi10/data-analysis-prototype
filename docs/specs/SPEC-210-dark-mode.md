# Spec: Dark Mode — the Measured Dark Palette, the Theme Switch and Monaco

**ID:** SPEC-210
**Status:** Completed
**Last Updated:** 2026-08-28
**Interacts with:** SPEC-211 also adds a header control, and SPEC-207 adds none. SPEC-211 FR-007
owns the mobile header-width measurement all three depend on; this spec's FR-005 mobile placement
follows whatever that measurement establishes.

**Depends On:** SPEC-021 (the design-token baseline in `index.css`), SPEC-023/024/026/027/029 (the surfaces the tokens paint), SPEC-035 (the Monaco editor and its existing custom theme), SPEC-045 (the axe suite), SPEC-095 (the breakpoints), SPEC-155 (`Menu`, `IconButton`), SPEC-184 (the Data Explorer's `FORMATTING_TOKEN_HEX` mirror of the palette), SPEC-192/194 (the runtime config document and the container that serves the shell)

## Overview

The portal is light-only. Every colour is a Tailwind v4 `@theme` token in `index.css`, each one
chosen against a white surface and annotated with its measured contrast ratio. People who work in a
dark environment — which for a query tool is most of an afternoon — have no option but to be
brightly lit by it.

This spec adds a dark theme the user chooses: Light, Dark, or System, remembered in the browser. The
work is not the switch; it is the palette. This project's standing rule is that **a palette is
measured, not chosen**, and the light palette earned that rule — `text-3` shipped at 2.96:1 and had
to be darkened, and three status colours failed against their own soft backgrounds. A dark palette
invented by eye would repeat all of it, and there is nothing in the test suite that would notice:
axe's `color-contrast` rule is **disabled** in `src/test/axe.ts`, because jsdom has no layout engine.

So the first thing this spec builds is the measurement — a harness that computes WCAG contrast from
the token values themselves, for the pairings the design actually uses, in **both** themes. The dark
palette is then whatever passes it. The same harness immediately covers the light palette, whose
ratios have only ever been comments.

## Scope

### In Scope

- A dark value for every colour token, derived under a contrast harness that runs in CI.
- A contrast harness asserting every declared foreground/background pairing in both themes.
- A three-state preference — Light / Dark / System — persisted in `localStorage`, per browser.
- The `data-theme` attribute on `<html>`, and a pre-paint initialiser that avoids a light flash.
- A theme control in the header at `tablet` and above, and in the mobile nav drawer.
- A dark Monaco theme built from the same tokens, switched with the app theme.
- The sweep of every hard-coded colour that bypasses the tokens, including the Data Explorer's
  `FORMATTING_TOKEN_HEX` mirror.
- One axe pass over the app shell in dark mode.

### Out of Scope

- **Cross-device persistence.** The preference is `localStorage`, per browser. A per-user document
  would need a read before first paint, which means either a flash or a blocked render, and it is a
  browser-side S3 write on a path Arc B may want to own. Revisit if users ask for it.
- **A high-contrast or reduced-motion theme.** Two palettes, not a theming system.
- **Per-surface theme overrides** — no "keep the editor light in dark mode" switch.
- **Re-deciding the light palette's hues.** The harness measures the existing light tokens and they
  must pass; if one does not, that is a finding to raise, and the fix is its own decision.
- **Theming the Hosted UI.** Cognito's sign-in pages are not ours to paint.
- **Running the whole axe suite twice.** One dark pass over the app shell, and the reason is stated
  in FR-009 rather than left as a silent cap.

---

## Functional Requirements

### FR-001: The contrast harness

#### Description:

A test computes WCAG 2.2 relative luminance and contrast ratios directly from the token hex values
and asserts every pairing the design uses. It needs no DOM, which is exactly why it can exist where
axe's rule cannot.

#### Acceptance Criteria:

- [x] The harness reads the token values from **one** declaration, so a token changed in `index.css`
      and not in the harness cannot pass. The declaration is the source both the stylesheet and the
      test consume.
- [x] A declared list of pairings — each a (foreground, background, minimum ratio) — covers: each of
      `text`, `text-2`, `text-3` on each of `bg`, `surface`, `surface-2`; each of `success`,
      `warning`, `danger`, `accent-text` on `surface` and on its own `-soft` background where it has
      one; the editor's `syntax-fn` on `surface`; the two accent FILLS under the foreground each
      actually carries; and `accent` as a focus ring against `bg`, `surface` and `surface-2`.

      **Two of these changed shape while being built, and the reason is the dark theme.** As
      drafted this measured `accent-hover` as text and white on `danger`. Neither pairing is one
      the design uses, and in the dark theme neither is satisfiable beside the pairing that IS:
      `accent-hover` appears only as `hover:bg-accent-hover` and as a gradient stop, always under
      white, so measuring it as text forces a value too light to carry white; and `danger` has to
      be light enough to read as text on a dark surface, which leaves it too light to back a white
      button. So `accent` and `accent-hover` are measured as `#ffffff` on the fill, and the one
      danger BUTTON gained `--color-on-danger` — white in the light theme, near-black in the dark
      one. In the light palette all three read exactly as drafted.
- [x] Text pairings assert ≥ 4.5:1; the focus-ring pairing asserts ≥ 3:1 (WCAG 1.4.11).
- [x] **`border`, `border-2`, `accent-border` and `danger-border` are declared DECORATIVE and are exempt from a ratio
      floor**, in a named exemption list carrying the reason. This is not a convenience: measured
      against the light palette they are 1.16–1.23, 1.06–1.13 and 1.20–1.27 respectively, so any
      floor at all — 3:1 included — fails the shipped palette that Out of Scope says must pass. WCAG
      1.4.11 governs the boundary of a user-interface *component* whose shape carries meaning, not a
      hairline separator, and `index.css` already records `accent-border` as "decorative
      reinforcement, never the sole state signal". A component boundary that IS the only thing
      identifying a control is a pairing, not an exemption, and belongs in the list above.
- [x] Every colour token is **either** in a pairing **or** in the exemption list; a token in neither
      fails the test. That is the completeness guard — adding a token without deciding whether it
      carries meaning is what must be impossible, not measuring a hairline.
- [x] The harness runs over **both** themes and fails naming the failing pair and its measured ratio.
- [x] A test proves the harness can fail: a deliberately failing pair is asserted to be reported.
      This is the one guard mutated on purpose, because a contrast harness that silently passes
      everything is indistinguishable from one that works.
- [x] The exemption list is asserted non-growable without a reason string, so "decorative" cannot
      become the place a failing colour is put.

### FR-002: The dark palette

#### Description:

Every colour token gains a dark value, defined under `:root[data-theme='dark']`.

#### Acceptance Criteria:

- [x] Every `--color-*` token declared in `@theme` has a dark counterpart; a test compares the two
      key sets and fails on any token defined in one theme and not the other.
- [x] Every dark pairing passes FR-001's thresholds.
- [x] The dark theme keeps the light theme's semantic ordering — `text` is the highest-contrast text
      colour, `text-3` the lowest, `surface` sits above `bg` — asserted numerically, not by eye, so
      a dark palette cannot silently invert the visual hierarchy the components were built around.
- [x] `--shadow-sm|md|lg` have dark values; a shadow tuned for a white page is invisible on a dark
      one. **Not by redefining `--shadow-*`, which is inert and silently so:** Tailwind inlines an
      `@theme` shadow value into the utility and emits no `--shadow-*` custom property at all
      (measured in the built CSS), so a dark block redefining one changes nothing while the
      stylesheet check beside it passes. What survives inlining is a `var()` **inside** the value,
      so each shadow references a `--shadow-tint-*` and the theme overrides the tint. A harness
      guard asserts that shape, and asserts the dark block declares no `--shadow-*` of its own.
- [x] Non-colour tokens (breakpoints, type scale, radii) are untouched.

### FR-003: The preference and its persistence

#### Description:

A three-state preference, stored in `localStorage`, resolved to an effective theme.

#### Acceptance Criteria:

- [x] The stored values are exactly `light`, `dark` and `system`; anything else reads as `system`.
- [x] The default with nothing stored is `system`.
- [x] `system` resolves through `prefers-color-scheme`, and a change to the OS preference while the
      app is open re-resolves without a reload.
- [x] `light` and `dark` do not re-resolve when the OS preference changes.
- [x] With `localStorage` throwing, the app renders at the resolved default and the control still
      switches the theme for the session; both the read and the write are wrapped.
- [x] The preference is **not** per user — it is per browser, and signing out does not clear it.

### FR-004: The attribute, and no flash of the wrong theme

#### Description:

`<html>` carries `data-theme="light"` or `data-theme="dark"`, set before the first paint by a
same-origin script file loaded synchronously in `<head>`.

#### Acceptance Criteria:

- [x] `index.html` loads `/theme-init.js` with a blocking `<script src>` in `<head>`, before the
      module script.
- [x] It is an external file, not inline: the CSP is `script-src 'self'` with no nonce and no hash,
      so an inline initialiser would be blocked in production and would work in dev — the worst
      shape of failure available. A test asserts `index.html` contains no inline `<script>` with a
      body.
- [x] `theme-init.js` sets `data-theme` and the `color-scheme` style property from the stored
      preference, resolving `system` itself, and throws on nothing — a failure inside it must not
      block the module script.
- [x] The container serves `/theme-init.js` with the same cache policy as `index.html`, asserted in
      the image's behaviour matrix. A long-cached initialiser would pin a stale resolution.
- [x] Switching the theme at runtime updates the attribute on `<html>` and no component re-mounts;
      a test asserts a controlled input keeps its value across a switch.

### FR-005: The theme control

#### Acceptance Criteria:

- [x] At `tablet` and above, the header renders one `IconButton` named `Change theme` that opens a
      `Menu` with three items: Light, Dark and System.
- [x] The menu marks the current selection to assistive technology, not by colour alone.
- [x] Below `tablet` the same three options appear as a group in `AppNavDrawer`, and the
      **authenticated** header renders no theme button — that header is over its width budget at
      375px before anything is added, measured in SPEC-211 FR-007. **The signed-out header keeps
      it at every width**, because `AppNavDrawer` is mounted only for an authenticated user, so
      there is no drawer to move it into — and that header carries a brand mark and one button,
      which is not what the measurement is about. The rule as built is one sentence: the header
      renders the control unless the drawer is showing it.
- [x] The control is present when signed out as well as signed in; the landing page is themed too.
      The landing route suppresses the app header (`RootLayout`) and carries its own nav, so it
      gets its own copy of the control — it is the one surface a signed-out visitor normally sees.
- [x] Selecting an option applies it immediately and persists it.
- [x] `expectNoA11yViolations` runs against the driven container with the menu open.

### FR-006: Monaco follows the theme

#### Description:

`SqlEditor.tsx` already defines a custom Monaco theme with hard-coded colours. It gains a dark
sibling, and the editor switches between them.

#### Acceptance Criteria:

- [x] **Monaco's LIGHT theme stops holding private copies of the palette, in this spec.** Its rules
      carry `string: #0f9d6e`, `number: #c2820a` and `comment: #8a93a2`, measuring **3.46**, **3.24**
      and **3.10** on white, with `editorLineNumber.foreground` at **2.99** on its own gutter — all
      below 4.5:1. Two of those hexes are the exact values `index.css`'s comments record as *already
      rejected and darkened* ("was #0f9d6e ≈ 3.5:1 — failed", "was #c2820a ≈ 3.3:1 — failed"): Monaco
      kept the pre-fix palette when the tokens moved. Pointing them at the current tokens
      (`success` 5.48, `warning` 5.02, `text-3` 5.36 on white) is **removing a fork, not re-deciding
      a hue**, so it does not collide with this spec's Out of Scope — but it must be said out loud,
      because FR-006's next criterion would otherwise make the harness red against a shipped surface
      the spec promised not to touch. `editorLineNumber.foreground` is the **fourth** of those and
      is fixed the same way: it becomes `text-3`, 5.18 on the gutter's own `surface-2`.
- [x] `predefined.sql`'s `#7c3aed` is not in the token set. It measures 5.70 on white and **becomes
      a token** (`--color-syntax-fn`) rather than joining the exemption list — that way it gains a
      dark counterpart, a key-set check and a measured pairing, instead of being a literal the
      harness does not see. Every colour Monaco is given is then a token, which is what FR-006's
      last-but-two criterion asks for.
- [x] A dark Monaco theme is defined whose `editor.background`, line-number foreground and gutter
      background are derived from the same token values the dark palette declares — not chosen
      separately.
- [x] The editor switches theme when the app theme changes, without remounting the editor or losing
      the buffer's content, cursor or scroll position.
- [x] The Monaco token colours are included in FR-001's pairing list, so editor text is measured
      against the editor background like everything else.
- [x] The Data Explorer, the results grid and the schema rail are readable in dark mode; each has an
      assertion that its surface and text tokens are the themed ones rather than literals.

### FR-007: The hard-coded-colour sweep

#### Description:

Nineteen colour literals in non-test source bypass the tokens. Each is either themed or justified.
(A twentieth hex occurrence is prose inside a comment in `features/data-explorer/explorationTabs.ts`
discussing `#ff0000`; it is not a literal, and the lint rule below must not fire on it.)

#### Acceptance Criteria:

- [x] `features/data-explorer/dataExplorer.constants.ts`'s `FORMATTING_TOKEN_HEX` and its surface
      map resolve per theme rather than holding one theme's hexes. These are applied as **inline
      styles** on grid cells, so they cannot inherit a CSS variable through a class — the resolution
      has to happen where the style is built.
- [x] **`formatting.test.ts`'s cross-product contrast test is re-derived per theme, not left
      measuring the light palette.** It is a stronger check than FR-001's pairing list on exactly the
      axis that matters here: it walks every foreground against every surface *including the sampled
      gradient between two tints of different hues*, which the pairing list does not, and it pins the
      settled decision that `warning` was **measured out** of the Data Explorer's foreground set
      (4.49 on `accent-soft`, 4.39 on `danger-soft`) with an assertion that those pairs stay below
      4.5 so a token that moves reddens CI. Left as-is, the dark palette ships with that whole
      criterion unasserted while FR-001's "runs over both themes" reads as though it were covered.
- [x] The exclusion set is **recomputed** for the dark palette rather than copied: a dark palette may
      readmit `warning` or expel a foreground the light palette includes, and the test must assert
      whichever is true of the palette it is measuring.
- [x] The hard-coded `#b45309` in that test's exclusion assertions resolves from the palette
      declaration for the theme under test, so it cannot go stale against a token that moved.
- [x] User-chosen row colours are unchanged in meaning: a rule the user set still paints the cell it
      painted, and the spec states plainly whether a user-picked colour is adjusted for the dark
      surface or left exactly as picked, with the reasoning. (It is left exactly as picked — the
      user chose a colour, and silently changing it is a worse failure than a low-contrast cell they
      can re-pick.)
- [x] `features/query/SqlEditor.tsx`'s three literals are replaced per FR-006.
- [x] `features/help/HelpGuideCard.tsx`'s `#f6caca` border becomes a token.
- [x] `routes/LandingPage.tsx`'s `#dfe0fb` and `#f3f4ff` sit on a fixed accent strip that does not
      change with the theme; they are asserted to pass contrast against that strip's own
      background, named in the harness rather than omitted from it. **Measured rather than exempt,
      and the strip is made fixed rather than assumed to be:** it was `bg-accent`, which themes,
      and its white buttons carry `text-accent-text`, which in the dark theme goes light and
      vanishes against them. So the strip's six colours are plain custom properties declared
      outside `@theme` and outside every theme block, `palette.ts` declares the same six, a test
      pins the two together, and four raw pairings measure the strip's own text and buttons.

- [x] **The sweep covers Tailwind's own colour scales, not only hexes.** `routes/NotFoundPage.tsx`
      painted itself with `text-gray-900`, `text-gray-600` and `text-gray-700` — as unreachable by
      a theme as a hex, invisible to a hex-only sweep, and on a public route that renders the
      themed shell to a signed-out visitor. They become `text` and `text-2`. `white` and `black`
      are swept separately and exempted per file with a reason: a scrim and white-on-accent are
      right in both themes, a `text-white` on a themed surface is not.
- [x] A lint rule or test fails on a **new** colour literal in `.tsx`/`.ts` outside the exemption
      list, so this sweep does not have to be repeated.

### FR-008: The container and the config document are untouched

#### Acceptance Criteria:

- [x] No new runtime-configuration key is added. The theme is a browser preference, not
      configuration, and the six wiring sites are not touched.
- [x] The CSP is unchanged — no new host, no new directive.
- [x] `npm run check:bundle` still passes.

### FR-009: One dark axe pass, and the cap is stated

#### Description:

The axe suite runs in light mode. Running all of it twice would roughly double an already long
suite for a rule that is disabled anyway.

#### Acceptance Criteria:

- [x] One axe assertion renders the authenticated app shell with `data-theme="dark"` and passes.
- [x] The suite's own documentation states that the remaining axe assertions run in light mode only,
      and that dark-mode contrast is covered by FR-001's harness rather than by axe — so the
      coverage boundary is written down rather than inferred from what is absent.
- [x] `color-contrast` stays disabled at **both** sites in `axe.ts` — the base config and
      `ROUTE_AXE_OPTIONS` — and the comment at each is updated to point at the harness instead of
      describing contrast as a manual concern.

### FR-010: Help content

#### Acceptance Criteria:

- [x] A short guide covers choosing the theme and what System means.
- [x] The guide is added to a section that already exists; no new section is created for it.

---

## Data Model

```ts
// apps/portal/src/lib/theme.types.ts

/** What the user chose. */
export type ThemePreference = 'light' | 'dark' | 'system';

/** What is actually painted, after resolving `system`. */
export type EffectiveTheme = 'light' | 'dark';
```

```ts
// apps/portal/src/lib/palette.ts — the ONE declaration FR-001 and index.css both consume.

export type ColorToken = 'bg' | 'surface' | 'surface-2' | 'border' | 'border-2'
  | 'text' | 'text-2' | 'text-3'
  | 'accent' | 'accent-hover' | 'accent-soft' | 'accent-text' | 'accent-border'
  | 'success' | 'success-soft' | 'warning' | 'warning-soft' | 'danger' | 'danger-soft';

export const PALETTE: Record<EffectiveTheme, Record<ColorToken, string>>;

/**
 * A pairing the design uses, and the ratio it must clear. Either side may be a raw hex —
 * FR-006 measures Monaco's own token colours and FR-007 measures the landing hero's fixed
 * gradient, and neither is a `ColorToken`.
 */
export type Hex = `#${string}`;
export type ContrastPair =
  | {kind: 'token'; fg: ColorToken | '#ffffff'; bg: ColorToken; min: 4.5 | 3}
  | {kind: 'raw'; fg: Hex; bg: Hex; min: 4.5 | 3; why: string};
// NOT `ColorToken | string`: that union absorbs the literal type entirely, and `tsc --strict`
// then accepts {fg: 'txet', bg: 'surfce'} without complaint.
export const CONTRAST_PAIRS: readonly ContrastPair[];

/** Tokens that carry no meaning and are measured against no floor. Reason required. */
export const DECORATIVE_TOKENS: Readonly<Record<'border' | 'border-2' | 'accent-border', string>>;
```

> **`index.css` is the source; `palette.ts` is asserted against it by reading the file at test
> time.** Not the other way round, and not a generator.
>
> **CORRECTION, made while building: the guard was NOT missing.** The paragraph below was written
> against commit `a41bda69` and had gone stale — the check, the block-scoped parse and the
> synthetic second-block test were all live in `features/data-explorer/formatting.test.ts`, and
> `src/test/node-fs.d.ts` named two live consumers rather than none. So this spec did not rewrite a
> deleted guard; it **moved** the working one into `src/test/cssTokens.ts`, which the contrast
> harness and the Data Explorer's tests now share, and added the dark half. Writing it fresh would
> have forked the parse. The reasoning below is still why the mechanism is what it is, and is kept
> for that.
>
> **What the spec believed had been deleted:**
> `features/data-explorer/formatting.test.ts` used to pin `FORMATTING_TOKEN_HEX` this way — it read
> `src/index.css` with `readFileSync` through a one-function ambient declaration and carried a test
> named *"the palette map matches the tokens index.css actually declares"*. Commit `a41bda69` (the
> 2026-08-28 suite reduction) removed all of it. What survives is `src/test/node-fs.d.ts`, orphaned,
> whose docstring still explains why the palette *has to* be checked against `index.css` and why a
> `?raw` import cannot do it — `?raw` resolves to the empty string under Vitest, which makes the
> guard pass by finding nothing. **The declaration without the check.** The reasoning in that
> docstring is still correct and is why this mechanism is chosen; the check itself has to be written
> again, and Phase 1 writes it.
>
> **The parse must be BLOCK-SCOPED, and this is the part that is easy to get wrong.** The deleted
> version matched `--color-*` across the whole file, which was safe while `index.css` declared one
> `@theme` block: it correctly ignored the hexes inside comments and the `--breakpoint-*: initial`
> lines. FR-002 adds a second block. A whole-file scan then reads the dark values **over** the light
> ones and every "light" assertion silently measures dark-on-dark, passing. So the parse resolves
> `@theme` and `:root[data-theme='dark']` separately, and a test asserts that appending a dark block
> does not change the light map.
>
> Two hand-maintained copies of a palette is a shape this project has been bitten by before, and the
> failure is silent: the app paints one set of colours while the harness measures another, and every
> test is green.

## API / Interface Contract

```ts
// apps/portal/src/lib/useTheme.ts
export function useTheme(): {
  preference: ThemePreference;
  effective: EffectiveTheme;
  setPreference: (next: ThemePreference) => void;
};

// apps/portal/src/lib/contrast.ts  — pure, no DOM.
// EXTRACTED from features/data-explorer/formatting.test.ts, which still implements it;
// that test then imports it here rather than keeping a second copy.
//
// It MUST reject a malformed hex rather than compute on it. The existing implementation
// returns 21 for 'zzz' (NaN propagating through the min/max) and a plausible 1.48 for a
// five-digit '#4f46e' — so a typo'd pairing on the raw-hex side clears every floor with
// nothing red, which is the failure the harness exists to prevent.
export function contrastRatio(foreground: Hex, background: Hex): number;
```

## File & Folder Structure

```
apps/portal/
├── public/theme-init.js               # pre-paint resolver, CSP-clean
├── index.html                         # loads it, blocking, in <head>
└── src/
    ├── lib/
    │   ├── palette.ts                 # the one palette declaration
    │   ├── contrast.ts                # relative luminance + ratio
    │   ├── contrast.test.ts           # the harness: every pair, both themes
    │   ├── theme.types.ts
    │   ├── useTheme.ts
    │   └── useTheme.test.ts
    ├── components/ThemeMenu.tsx
    ├── index.css                      # dark token block under :root[data-theme='dark']
    └── features/query/SqlEditor.tsx   # the dark Monaco theme
```

## Implementation Phases

### Phase 1: Measurement, then the palette

- `contrast.ts` (extracted, with the malformed-hex guard), `palette.ts` and the harness, run first
  against the **light** palette alone, to confirm it reproduces the ratios recorded in `index.css`'s
  comments before it is trusted.
- Re-write the deleted `index.css` agreement check, block-scoped, with its own test that appending a
  dark block leaves the light map unchanged. `src/test/node-fs.d.ts` stops being an orphan.
- The deliberate-failure test.
- Then derive the dark values until every pair passes.

### Phase 2: The preference, the attribute and the control

- `theme-init.js`, the `index.html` change, the no-inline-script assertion.
- `useTheme`, the storage wrapping, the `system` re-resolution.
- `ThemeMenu` in the header and the drawer; axe.

### Phase 3: Monaco and the literal sweep

- The dark Monaco theme and the switch without remount.
- `FORMATTING_TOKEN_HEX` per theme, and the user-picked-colour decision.
- The remaining literals, the exemption list, and the lint rule that stops new ones.
- The one dark axe pass, the `axe.ts` comment, and the Help guide.
