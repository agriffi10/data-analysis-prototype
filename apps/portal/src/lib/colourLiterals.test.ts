import {describe, expect, it} from 'vitest';
import {readCss} from '../test/cssTokens';
import {CONTRAST_PAIRS} from './palette';

// The sweep that stops this one being needed again. Every colour in the app comes from a token
// so that a theme can move it; a literal is a colour the theme cannot reach and the contrast
// harness cannot see, and nineteen of them had accumulated before anybody counted.
//
// WHAT IT DOES NOT READ, stated so nobody trusts it further than it goes: `rgb()`/`hsl()`
// functions, CSS named colours (`red`, `rebeccapurple`), and Tailwind arbitrary values that name
// one (`bg-[red]`). None appears in the tree today. The three forms below are the ones that
// actually accumulated, and widening the sweep is a deliberate edit here, not a rewrite.

const SOURCES = import.meta.glob('/src/**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
  string,
  string
>;

/** Not app code: the test suite, its harness, and the file the API contract emits. */
const NOT_APP_CODE = /\.test\.tsx?$|^\/src\/test\/|^\/src\/test-setup\.ts$|^\/src\/types\/apiContract\.generated\.ts$/;

/**
 * Source with its comments removed, so prose about a colour is not read as a colour.
 *
 * A `//` preceded by `:` is left alone — that is the `https://` in a URL, and cutting there
 * would drop the rest of a real line of code along with it.
 */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
}

const HEX = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g;

// Tailwind's own colour scales. `text-gray-900` themes no better than `#15191e` does, and it
// is invisible to a sweep that only looks for hexes — which is how the 404 page kept three of
// them through a review that found every literal in the app.
const STOCK_SCALE =
  /\b(?:text|bg|border|from|to|via|ring|divide|fill|stroke|placeholder|caret|accent|outline|decoration|shadow)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/g;

// A foreground carrying an ALPHA modifier. `text-danger/80` is not `danger`: it is `danger`
// blended toward whatever is behind it, so it lands below the ratio the harness measured for the
// token and there is no pairing that describes it. One shipped at 4.19:1 on its own `danger-soft`
// fill and no guard could see it — the sweep looks for literals, and the harness measures tokens
// at full strength.
//
// MATCHED BY SHAPE, and this is the part worth keeping. The first version listed the token names
// and ended `/\d+`; a review walked past it with `text-text-2/[0.6]` on the first try, and past
// the background sweep with `bg-accent/[0.5]`, and past the opacity sweep with `opacity-[0.7]`.
// Every escape was a SPELLING that had not been enumerated, so the three sweeps here match the
// shape a colour-with-alpha has — token, arbitrary value or custom property, then any of the
// three ways to write the amount — and decide afterwards. A foreground never carries alpha in
// any of them, which leaves nothing to list.
const FADED_FOREGROUND =
  /\b(?:text|fill|stroke|decoration|caret|placeholder)-(?:\[[^\]\s]*]|\([^)\s]*\)|[\w.-]+)\/(?:\d+|\[[^\]\s]*]|\([^)\s]*\))/g;

// A BACKGROUND or an EDGE carrying one. Every colour utility, not just `bg-`: a ring, a border,
// a gradient stop and an SVG fill each paint a colour, and `ring-accent/40` is exactly the
// 40%-opacity focus tint `index.css` records as rejected. These may exist — a scrim is one, and
// so is a frosted bar — but each is either a declared `over` pairing that names what is behind
// it, or an entry below saying why it carries no meaning.
// `shadow-*` is deliberately absent: a coloured shadow is never a surface a foreground is read
// against, so demanding a pairing or an exemption for `shadow-black/20` would be friction with
// nothing behind it. Gradient stops stay, because a gradient IS a background text can sit on.
const ALPHA_SURFACE =
  /\b(?:bg|border|ring|divide|outline|from|via|to|accent)-(?:\[[^\]\s]*]|\([^)\s]*\)|[\w.-]+)\/(?:\d+|\[[^\]\s]*]|\([^)\s]*\))/g;

// `white` and `black` are the two absolutes rather than a palette, so they are swept
// separately and exempted by file with a reason — a scrim and white-on-accent are correct in
// both themes, and a `text-white` on a themed surface is not.
const ABSOLUTE =
  /\b(?:text|bg|border|from|to|via|ring|divide|fill|stroke|placeholder|caret|accent|outline|decoration|shadow)-(?:white|black)\b/g;

// The same spending, written the other way. `opacity-70` dims the WHOLE element — its text, its
// icon, its border — against whatever is behind it, and the sweep above cannot see it because no
// colour is named. Two of these shipped: a banner's Dismiss at 2.80:1 and a toast's close at
// 2.91:1, both on the soft fill their own banner painted.
//
// An INACTIVE control is the exception WCAG 1.4.3 grants, so a `disabled:` variant passes by rule
// and the files that dim on a condition instead are exempted below, by the exact utility rather
// than by the file: `Button` and `Menu` are the app's two most-reused controls, and exempting
// them wholesale would let a `hover:opacity-80` live in either one untouched.
//
// The chain is captured and read, not merely allowed to be present. `disabled:` must be a whole
// SEGMENT of it — `not-disabled:opacity-60` contains the string and is the exact inversion of the
// exemption, dimming a control only while it is live. `opacity-0` and `opacity-100` are a reveal.
//
// `[\w:-]*` rather than the `(?:[a-z-]+:)*` that reads more naturally, because
// `security/detect-unsafe-regex` rejects the nested quantifier and `npm run lint` is a blocking
// gate. (Timed, the nested form is not in fact slower here — the rule is a shape rule, and this
// is the shape that passes it.)
const DIMMED = /[\w:-]*opacity-(?:\d+|\[[^\]\s]*]|\([^)\s]*\))/g;

/** An opacity utility split into its variant chain and the utility itself. */
function splitOpacity(hit: string): {chain: string; utility: string} {
  const at = hit.indexOf('opacity-');
  return {chain: hit.slice(0, at), utility: hit.slice(at)};
}

/**
 * Whether one variant segment marks the element INACTIVE, which is WCAG 1.4.3's own exemption.
 *
 * The family rather than a list of spellings, for the reason the sweeps themselves match shapes:
 * `aria-disabled:` is the variant form of what three of the exempted files do with a `cx()`
 * conditional, and `group-disabled:` and `peer-disabled:` are how a child is dimmed with its
 * control — rejecting any of them would redden a suite for code BETTER than what is already
 * exempted here, and the cheap fix in front of that author is to loosen the rule.
 *
 * `not-` is what the family must not swallow: `not-disabled:` is this exemption inverted, dimming
 * a control only while it is live, and a substring test on `disabled:` honours it.
 *
 * @param segment - One variant, without its colon.
 * @returns Whether it names an inactive state.
 */
function marksInactive(segment: string): boolean {
  if (segment.startsWith('not-')) return false;
  return segment === 'disabled' || segment.endsWith('-disabled');
}

/**
 * Every opacity utility in a source that is neither a reveal nor an inactive control.
 *
 * @param source - One file's code, comments already stripped.
 * @returns The offending utilities, with their variant chains.
 */
function dimmed(source: string): string[] {
  const hits = source.match(DIMMED) ?? [];
  return hits.filter((hit) => {
    const {chain, utility} = splitOpacity(hit);
    if (utility === 'opacity-0' || utility === 'opacity-100') return false;
    // `backdrop-opacity-*` filters what is BEHIND the element and dims no foreground of its own.
    if (chain.endsWith('backdrop-')) return false;
    return !chain.split(':').filter(Boolean).some(marksInactive);
  });
}

/** The one file allowed to write a colour down: the declaration the harness pins to `index.css`. */
const DECLARATION = '/src/lib/palette.ts';

/**
 * The bare `accent` token used as a foreground — `text-accent`, never `text-accent-text`.
 *
 * The negative lookahead is what keeps the two apart: `-` is not a word character, so a plain
 * `\b` after `accent` matches inside `text-accent-text` and the sweep would read every correct
 * use as a violation.
 */
const BARE_ACCENT = /\btext-accent(?![\w-])/g;

/**
 * Every file allowed to paint with the bare `accent` token, and what it paints.
 *
 * `accent` is a fill, a focus ring and an icon colour. The dark palette derives it for WCAG
 * 1.4.11's 3:1 and it clears that against every surface; it clears 1.4.3's 4.5 against none of
 * them. So as normal-size TEXT it passes in light and fails in dark, which is how two of them
 * shipped — a help-rail count and the landing page's mock SQL. Each entry below is a glyph or a
 * heading large enough for the 3:1 floor; a sixth is a decision, and text belongs in
 * `accent-text`.
 */
const ACCENT_AS_PAINT: Record<string, string> = {
  '/src/components/icons.tsx': 'the filled folder glyph on a file-list row — an icon, at the 3:1 floor',
  '/src/features/file-browser/UploadDropzone.tsx':
    'the dropzone glyph while a file is dragged over it — an icon, at the 3:1 floor',
  '/src/features/file-browser/DestinationPicker.tsx':
    'the folder and selection glyphs in the destination tree — icons, at the 3:1 floor',
  '/src/features/query/QueryTabStrip.tsx':
    'the role="img" dot marking a tab with unsaved changes — a graphic, at the 3:1 floor',
  '/src/routes/LandingPage.tsx':
    'the hero word at 32px and up, which is large text, plus two 40px icon tiles — all at 3:1'
};

/**
 * Every file that dims a live element, and the exact utility it is allowed.
 *
 * Keyed by utility and not merely by file, because `Button` and `Menu` are the app's two
 * most-reused controls: a whole-file pass would let a `hover:opacity-80` live in either one with
 * nothing to catch it. Each is an inactive control written as a condition rather than as the
 * `disabled:` variant — an `aria-disabled` checkbox, a button and a menu item carrying a reason
 * instead of the attribute, and a dropzone that stops taking drops.
 */
const DIMMED_EXEMPT: Record<string, {utilities: readonly string[]; why: string}> = {
  '/src/components/Button.tsx': {
    utilities: ['opacity-45'],
    why: 'a button given a disabledReason: aria-disabled, onClick dropped, and dimmed to match'
  },
  '/src/components/Menu.tsx': {
    utilities: ['opacity-45'],
    why: 'a menu item given a disabledReason, dimmed the same way as the button'
  },
  '/src/features/data-explorer/AdvancedCopyDialog.tsx': {
    utilities: ['opacity-45'],
    why: 'the quoting checkbox while quoting cannot apply — aria-disabled, set two lines above the class'
  },
  '/src/features/file-browser/UploadDropzone.tsx': {
    utilities: ['opacity-60'],
    why: 'the dropzone while uploads are disabled; it also stops pointer events'
  }
};

/**
 * Translucent surfaces that carry no meaning, and why each one does not.
 *
 * The counterpart to a declared `over` pairing: a surface whose blend nothing reads against. A
 * boundary that IS the only thing identifying a control is a pairing, not an exemption.
 */
const ALPHA_SURFACE_EXEMPT: Record<string, string> = {
  'bg-black/30': 'the scrim behind a drawer or the mobile navigation sheet — a shadow rather than a colour',
  'bg-black/40': 'the scrim behind a modal dialog, deliberately darker than the drawer’s',
  'border-white/25': 'the seam between the two halves of a split accent button; both halves carry their own label',
  'border-(--landing-cta-text)/40':
    'the edge of the brand strip’s secondary button, which its own white label identifies'
};

/**
 * Every file allowed a colour that is not a token, and why.
 *
 * A new entry is a deliberate edit, which is the point: the alternative is a sweep that has to
 * be run again by hand the next time somebody wonders.
 */
const HEX_EXEMPT: Record<string, string> = {
  '/src/lib/palette.ts':
    'the declaration itself — the one place a colour is written down, pinned to index.css by contrast.test.ts'
};

const EXEMPT: Record<string, string> = {
  '/src/components/BrandMark.tsx': 'the mark itself — a white glyph on the accent fill',
  '/src/components/Button.tsx': 'white on the accent fill, which the harness measures',
  '/src/components/Drawer.tsx': 'the scrim behind an overlay, which is a shadow rather than a colour',
  '/src/components/AppNavDrawer.tsx': 'the scrim behind the mobile navigation sheet',
  '/src/components/Modal.tsx': 'the scrim behind a modal dialog, deliberately darker than the drawer’s',
  '/src/components/UserMenu.tsx': 'white initials on the avatar’s accent gradient',
  '/src/components/RootLayout.tsx': 'white on the accent skip-link',
  '/src/features/notifications/NotificationsBell.tsx': 'white on the accent unread badge',
  '/src/features/query/QueryResultsMobile.tsx': 'white on the accent “save results” button',
  '/src/features/query/QueryToolbar.tsx': 'the divider between the two halves of a split accent button',
  '/src/features/shared-spaces/MembersList.tsx': 'white initials on an accent gradient',
  '/src/routes/LandingPage.tsx': 'white on the accent badges; the fixed brand strip is custom properties'
};

function offenders(pattern: RegExp): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  for (const [path, source] of Object.entries(SOURCES)) {
    if (NOT_APP_CODE.test(path)) continue;
    const hits = code(source).match(pattern);
    if (hits) found[path] = [...new Set(hits)].sort();
  }
  return found;
}

describe('no colour bypasses the tokens', () => {
  it('carries no hex literal outside the one declaration', () => {
    expect(Object.keys(offenders(HEX))).toEqual(Object.keys(HEX_EXEMPT));
  });

  it('carries no colour from a scale the theme cannot move', () => {
    expect(offenders(STOCK_SCALE)).toEqual({});
  });

  it('allows white and black only where a file says why', () => {
    expect(Object.keys(offenders(ABSOLUTE)).sort()).toEqual(Object.keys(EXEMPT).sort());
    for (const [path, why] of Object.entries(EXEMPT)) expect(why.length, path).toBeGreaterThan(20);
  });

  it('covers the three surfaces a dark theme is hardest on, by name', () => {
    // Named rather than left to "the sweep covers everything": the Data Explorer, its results
    // grid and the query workspace's schema rail are the surfaces that paint the most of their
    // own colour, and each is asserted to be in the population this sweep actually reads.
    for (const path of [
      '/src/features/data-explorer/ExplorationResultsRegion.tsx',
      '/src/features/data-explorer/dataExplorer.constants.ts',
      '/src/features/query/SchemaBrowser.tsx'
    ]) {
      const source = SOURCES[path];
      expect(source, path).toBeTypeOf('string');
      expect(code(source).match(HEX), path).toBeNull();
      expect(code(source).match(STOCK_SCALE), path).toBeNull();
      // …and its surfaces and text are painted with the tokens, not with something fixed.
      expect(source, path).toMatch(/bg-surface|text-text|PALETTE|var\(--color-/);
    }
  });

  it('fades no foreground below the ratio its token was measured at', () => {
    // Full strength or a different token — never a tint of one. A modifier here silently spends
    // contrast the pairing list has already counted, which is the one way to fail the harness
    // while passing it.
    expect(offenders(FADED_FOREGROUND)).toEqual({});
  });

  it('dims no live element, and allows an inactive one only the utility it was allowed', () => {
    const found: Record<string, string[]> = {};
    for (const [path, source] of Object.entries(SOURCES)) {
      if (NOT_APP_CODE.test(path)) continue;
      const hits = dimmed(code(source));
      if (hits.length) found[path] = [...new Set(hits)].sort();
    }

    const allowed = Object.fromEntries(
      Object.entries(DIMMED_EXEMPT).map(([path, entry]) => [path, [...entry.utilities].sort()])
    );
    expect(found).toEqual(allowed);
    for (const [path, entry] of Object.entries(DIMMED_EXEMPT)) expect(entry.why.length, path).toBeGreaterThan(20);
  });

  it('reads a dimming through its variant chain, in whatever spelling it is written', () => {
    // The fixture corpus. Half of these are escapes a review actually walked out through: the
    // first version matched `opacity-` followed by bare digits and exempted anything whose chain
    // merely CONTAINED `disabled:`, so an arbitrary value and the negated variant both passed.
    expect(dimmed("'disabled:cursor-not-allowed disabled:opacity-45 hover:opacity-80'")).toEqual(['hover:opacity-80']);
    expect(dimmed("'disabled:opacity-45'")).toEqual([]);
    expect(dimmed("'hover:disabled:opacity-45'")).toEqual([]);
    expect(dimmed("'opacity-0 group-hover:opacity-100'")).toEqual([]);
    expect(dimmed("'ml-auto text-xs opacity-70 hover:opacity-100'")).toEqual(['opacity-70']);
    // The inactive FAMILY, each of which is correct code a list of spellings would have rejected.
    for (const variant of ['aria-disabled', 'group-disabled', 'peer-disabled', 'in-disabled']) {
      expect(dimmed(`'${variant}:opacity-45'`), variant).toEqual([]);
    }
    // …and its near-misses. `not-disabled:` is the exemption inverted — dimmed only while the
    // control is LIVE — and `not-` must not be swallowed at any depth.
    expect(dimmed("'not-disabled:opacity-60'")).toEqual(['not-disabled:opacity-60']);
    expect(dimmed("'not-group-disabled:opacity-60'")).toEqual(['not-group-disabled:opacity-60']);
    expect(dimmed("'disabledish:opacity-60'")).toEqual(['disabledish:opacity-60']);
    // `backdrop-opacity-*` filters what is behind the element; it dims no foreground of its own.
    expect(dimmed("'backdrop-opacity-50'")).toEqual([]);
    // …and the three spellings of an amount, which a digits-only matcher let straight through.
    expect(dimmed("'opacity-[0.7]'")).toEqual(['opacity-[0.7]']);
    expect(dimmed("'opacity-[70%]'")).toEqual(['opacity-[70%]']);
    expect(dimmed("'opacity-(--dim)'")).toEqual(['opacity-(--dim)']);
  });

  it('declares or explains every translucent surface, in whatever spelling it is written', () => {
    // A colour carrying alpha is one the palette does not contain, and the token it is spelled
    // with always measures the kinder number. So each is either an `over` pairing that names what
    // is behind it, or an entry saying it carries no meaning. Read from the sources rather than
    // from a token list: `bg-(--landing-cta-text)/10` is neither a token nor a hex.
    const painted = new Set<string>();
    for (const [path, source] of Object.entries(SOURCES)) {
      if (NOT_APP_CODE.test(path) || path === DECLARATION) continue;
      for (const hit of code(source).match(ALPHA_SURFACE) ?? []) painted.add(hit);
    }

    const declared = new Set(CONTRAST_PAIRS.filter((pair) => pair.kind === 'over').map((pair) => pair.utility));

    expect([...painted].filter((u) => !declared.has(u) && !(u in ALPHA_SURFACE_EXEMPT)).sort()).toEqual([]);
    // Both directions: a pairing that no longer describes anything painted is a fence around a
    // gap, and it is how a declaration outlives the class it was written for.
    expect([...declared].filter((u) => !painted.has(u)).sort()).toEqual([]);
    expect(
      Object.keys(ALPHA_SURFACE_EXEMPT)
        .filter((u) => !painted.has(u))
        .sort()
    ).toEqual([]);
    // …and the sweep is reading something, rather than agreeing with an empty declaration.
    expect(painted.size).toBeGreaterThan(4);
    for (const [utility, why] of Object.entries(ALPHA_SURFACE_EXEMPT)) expect(why.length, utility).toBeGreaterThan(20);
  });

  it('paints with the bare accent token only where a file says what it paints', () => {
    // The third class the six failures split into, and the one nothing caught: `accent` clears
    // 3:1 against every dark surface and 4.5:1 against none, so it is safe as a glyph and unsafe
    // as body text — and a light-only reading of it passes.
    expect(Object.keys(offenders(BARE_ACCENT)).sort()).toEqual(Object.keys(ACCENT_AS_PAINT).sort());
    for (const [path, why] of Object.entries(ACCENT_AS_PAINT)) expect(why.length, path).toBeGreaterThan(20);
    // The lookahead, asserted rather than trusted: a plain word boundary reads every correct use
    // as a violation, because `-` is not a word character.
    expect('text-accent-text hover:text-accent-text'.match(BARE_ACCENT)).toBeNull();
    expect('flex text-accent'.match(BARE_ACCENT)).toEqual(['text-accent']);
  });

  it('dims in no stylesheet and no inline style, which no class sweep could see', () => {
    // Two escapes from a sweep that reads Tailwind classes in .tsx — and both get the SAME rule
    // the classes get, rather than a blanket refusal. A blanket one is what the first draft had,
    // and it would have reddened for a `@keyframes` fade or a props type with an `opacity` field:
    // correct code, no exemption path, and the cheap fix in front of that author is to delete the
    // check. 0 and 1 are a reveal here exactly as `opacity-0` and `opacity-100` are there.
    const reveal = /^(?:0|1|0%|100%)$/;
    const stylesheet = readCss().replace(/\/\*[\s\S]*?\*\//g, '');
    const dimmedInCss = [...stylesheet.matchAll(/opacity\s*:\s*([^;}]+)/g)]
      .map(([, value]) => value.trim())
      .filter((value) => !reveal.test(value));
    expect(dimmedInCss).toEqual([]);

    // The stylesheet check reads `index.css` alone, which is enough only while that is the one
    // stylesheet the app imports. Matched on the whole specifier, not just its basename: a
    // `'./styles/theme.css'` one directory down satisfied the first version of this.
    const imported = new Set<string>();
    for (const [path, source] of Object.entries(SOURCES)) {
      if (NOT_APP_CODE.test(path)) continue;
      for (const [, specifier] of code(source).matchAll(/import\s+'([^']+\.css)'/g)) imported.add(specifier);
    }
    expect([...imported]).toEqual(['./index.css']);

    // An inline style, which is the shape the comment above names. A style object held in a
    // variable is NOT reached, stated so nobody trusts this further than it goes.
    expect(offenders(/style=\{\{[^}]*\bopacity\b/g)).toEqual({});
  });

  it('reads prose about a colour as prose', () => {
    // The one case that would make this whole sweep unusable if it fired: a comment discussing
    // `#ff0000` as an example of what a user-chosen colour can be.
    const prose = SOURCES['/src/features/data-explorer/explorationTabs.ts'];
    expect(prose).toMatch(/#ff0000/);
    expect(code(prose)).not.toMatch(/#ff0000/);

    // …and a `//` inside a URL is not a comment, so the rest of that line is still scanned.
    expect(code("const a = 'https://x/y'; const b = '#abcdef';")).toContain('#abcdef');
  });

  it('actually reads the sources, rather than finding nothing because the glob missed', () => {
    // Every assertion above passes vacuously against an empty file set.
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect(SOURCES['/src/lib/palette.ts']).toContain('CONTRAST_PAIRS');
  });
});
