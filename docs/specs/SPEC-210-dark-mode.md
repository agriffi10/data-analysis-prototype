# Spec: Dark Mode — the Measured Dark Palette, the Theme Switch and Monaco

**ID:** SPEC-210
**Status:** Draft
**Last Updated:** 2026-08-28
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

- [ ] The harness reads the token values from **one** declaration, so a token changed in `index.css`
      and not in the harness cannot pass. The declaration is the source both the stylesheet and the
      test consume.
- [ ] A declared list of pairings — each a (foreground token, background token, minimum ratio) —
      covers: each of `text`, `text-2`, `text-3` on each of `bg`, `surface`, `surface-2`; each of
      `success`, `warning`, `danger`, `accent-text` on `surface` and on its own `-soft` background;
      white on `accent` and white on `danger`; and `accent` as a focus ring against `bg`, `surface`
      and `surface-2`.
- [ ] Text pairings assert ≥ 4.5:1. The focus-ring and border pairings assert ≥ 3:1 (WCAG 1.4.11).
- [ ] The harness runs over **both** themes and fails naming the failing pair and its measured ratio.
- [ ] A test proves the harness can fail: a deliberately failing pair is asserted to be reported.
      This is the one guard mutated on purpose, because a contrast harness that silently passes
      everything is indistinguishable from one that works.
- [ ] The pairing list is asserted to mention **every** colour token: a token in the palette that
      appears in no pairing fails the test, so adding a token without measuring it is not possible.

### FR-002: The dark palette

#### Description:

Every colour token gains a dark value, defined under `:root[data-theme='dark']`.

#### Acceptance Criteria:

- [ ] Every `--color-*` token declared in `@theme` has a dark counterpart; a test compares the two
      key sets and fails on any token defined in one theme and not the other.
- [ ] Every dark pairing passes FR-001's thresholds.
- [ ] The dark theme keeps the light theme's semantic ordering — `text` is the highest-contrast text
      colour, `text-3` the lowest, `surface` sits above `bg` — asserted numerically, not by eye, so
      a dark palette cannot silently invert the visual hierarchy the components were built around.
- [ ] `--shadow-sm|md|lg` have dark values; a shadow tuned for a white page is invisible on a dark
      one.
- [ ] Non-colour tokens (breakpoints, type scale, radii) are untouched.

### FR-003: The preference and its persistence

#### Description:

A three-state preference, stored in `localStorage`, resolved to an effective theme.

#### Acceptance Criteria:

- [ ] The stored values are exactly `light`, `dark` and `system`; anything else reads as `system`.
- [ ] The default with nothing stored is `system`.
- [ ] `system` resolves through `prefers-color-scheme`, and a change to the OS preference while the
      app is open re-resolves without a reload.
- [ ] `light` and `dark` do not re-resolve when the OS preference changes.
- [ ] With `localStorage` throwing, the app renders at the resolved default and the control still
      switches the theme for the session; both the read and the write are wrapped.
- [ ] The preference is **not** per user — it is per browser, and signing out does not clear it.

### FR-004: The attribute, and no flash of the wrong theme

#### Description:

`<html>` carries `data-theme="light"` or `data-theme="dark"`, set before the first paint by a
same-origin script file loaded synchronously in `<head>`.

#### Acceptance Criteria:

- [ ] `index.html` loads `/theme-init.js` with a blocking `<script src>` in `<head>`, before the
      module script.
- [ ] It is an external file, not inline: the CSP is `script-src 'self'` with no nonce and no hash,
      so an inline initialiser would be blocked in production and would work in dev — the worst
      shape of failure available. A test asserts `index.html` contains no inline `<script>` with a
      body.
- [ ] `theme-init.js` sets `data-theme` and the `color-scheme` style property from the stored
      preference, resolving `system` itself, and throws on nothing — a failure inside it must not
      block the module script.
- [ ] The container serves `/theme-init.js` with the same cache policy as `index.html`, asserted in
      the image's behaviour matrix. A long-cached initialiser would pin a stale resolution.
- [ ] Switching the theme at runtime updates the attribute on `<html>` and no component re-mounts;
      a test asserts a controlled input keeps its value across a switch.

### FR-005: The theme control

#### Acceptance Criteria:

- [ ] At `tablet` and above, the header renders one `IconButton` named `Change theme` that opens a
      `Menu` with three items: Light, Dark and System.
- [ ] The menu marks the current selection to assistive technology, not by colour alone.
- [ ] Below `tablet` the same three options appear as a group in `AppNavDrawer`, and the header
      renders no theme button — the header is already at its width budget on mobile.
- [ ] The control is present when signed out as well as signed in; the landing page is themed too.
- [ ] Selecting an option applies it immediately and persists it.
- [ ] `expectNoA11yViolations` runs against the driven container with the menu open.

### FR-006: Monaco follows the theme

#### Description:

`SqlEditor.tsx` already defines a custom Monaco theme with hard-coded colours. It gains a dark
sibling, and the editor switches between them.

#### Acceptance Criteria:

- [ ] A dark Monaco theme is defined whose `editor.background`, line-number foreground and gutter
      background are derived from the same token values the dark palette declares — not chosen
      separately.
- [ ] The editor switches theme when the app theme changes, without remounting the editor or losing
      the buffer's content, cursor or scroll position.
- [ ] The Monaco token colours are included in FR-001's pairing list, so editor text is measured
      against the editor background like everything else.
- [ ] The Data Explorer, the results grid and the schema rail are readable in dark mode; each has an
      assertion that its surface and text tokens are the themed ones rather than literals.

### FR-007: The hard-coded-colour sweep

#### Description:

Twenty colour literals in the source bypass the tokens. Each is either themed or justified.

#### Acceptance Criteria:

- [ ] `features/data-explorer/dataExplorer.constants.ts`'s `FORMATTING_TOKEN_HEX` and its surface
      map resolve per theme rather than holding one theme's hexes. These are applied as **inline
      styles** on grid cells, so they cannot inherit a CSS variable through a class — the resolution
      has to happen where the style is built.
- [ ] User-chosen row colours are unchanged in meaning: a rule the user set still paints the cell it
      painted, and the spec states plainly whether a user-picked colour is adjusted for the dark
      surface or left exactly as picked, with the reasoning. (It is left exactly as picked — the
      user chose a colour, and silently changing it is a worse failure than a low-contrast cell they
      can re-pick.)
- [ ] `features/query/SqlEditor.tsx`'s three literals are replaced per FR-006.
- [ ] `features/help/HelpGuideCard.tsx`'s `#f6caca` border becomes a token.
- [ ] `routes/LandingPage.tsx`'s `#dfe0fb` and `#f3f4ff` sit on a fixed accent gradient that does
      not change with the theme; they are asserted to pass contrast against that gradient's own
      background and are then exempt, with the exemption named in the harness rather than omitted
      from it.
- [ ] A lint rule or test fails on a **new** colour literal in `.tsx`/`.ts` outside the exemption
      list, so this sweep does not have to be repeated.

### FR-008: The container and the config document are untouched

#### Acceptance Criteria:

- [ ] No new runtime-configuration key is added. The theme is a browser preference, not
      configuration, and the six wiring sites are not touched.
- [ ] The CSP is unchanged — no new host, no new directive.
- [ ] `npm run check:bundle` still passes.

### FR-009: One dark axe pass, and the cap is stated

#### Description:

The axe suite runs in light mode. Running all of it twice would roughly double an already long
suite for a rule that is disabled anyway.

#### Acceptance Criteria:

- [ ] One axe assertion renders the authenticated app shell with `data-theme="dark"` and passes.
- [ ] The suite's own documentation states that the remaining axe assertions run in light mode only,
      and that dark-mode contrast is covered by FR-001's harness rather than by axe — so the
      coverage boundary is written down rather than inferred from what is absent.
- [ ] `color-contrast` stays disabled in `axe.ts`, and its comment is updated to point at the
      harness instead of describing contrast as a manual concern.

### FR-010: Help content

#### Acceptance Criteria:

- [ ] A short guide covers choosing the theme and what System means.
- [ ] The guide is added to a section that already exists; no new section is created for it.

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

/** A pairing the design uses, and the ratio it must clear. */
export type ContrastPair = {fg: ColorToken | '#ffffff'; bg: ColorToken; min: 4.5 | 3};
export const CONTRAST_PAIRS: readonly ContrastPair[];
```

> **`index.css` is generated from `PALETTE`, or `PALETTE` is generated from `index.css` — one of the
> two, and the build asserts they agree.** Two hand-maintained copies of a palette is the shape this
> project has been bitten by before (the API contract, the deploy matrix), and the failure here is
> silent: the app paints one set of colours and the harness measures another, and every test is green.

## API / Interface Contract

```ts
// apps/portal/src/lib/useTheme.ts
export function useTheme(): {
  preference: ThemePreference;
  effective: EffectiveTheme;
  setPreference: (next: ThemePreference) => void;
};

// apps/portal/src/lib/contrast.ts  — pure, no DOM
export function contrastRatio(foreground: string, background: string): number;
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

- `contrast.ts`, `palette.ts` and the harness, run first against the **light** palette alone, to
  confirm it reproduces the ratios recorded in `index.css`'s comments before it is trusted.
- The agreement check between `palette.ts` and `index.css`.
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
