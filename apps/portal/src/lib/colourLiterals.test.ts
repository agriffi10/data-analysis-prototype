import {describe, expect, it} from 'vitest';

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

// A foreground carrying an OPACITY modifier. `text-danger/80` is not `danger`: it is `danger`
// blended toward whatever is behind it, so it lands below the ratio the harness measured for the
// token and there is no pairing that describes it. One shipped at 4.19:1 on its own `danger-soft`
// fill and no guard could see it — the sweep looks for literals, and the harness measures tokens
// at full strength. Backgrounds are deliberately NOT swept: `bg-black/30` is a scrim and
// `bg-danger/90` is a hover state whose foreground is measured against the result.
const FADED_FOREGROUND =
  /\btext-(?:text|text-2|text-3|accent|accent-text|accent-hover|success|warning|danger|on-danger|syntax-fn|white|black)\/\d+\b/g;

// `white` and `black` are the two absolutes rather than a palette, so they are swept
// separately and exempted by file with a reason — a scrim and white-on-accent are correct in
// both themes, and a `text-white` on a themed surface is not.
const ABSOLUTE =
  /\b(?:text|bg|border|from|to|via|ring|divide|fill|stroke|placeholder|caret|accent|outline|decoration|shadow)-(?:white|black)\b/g;

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
  '/src/components/Header.tsx': 'white initials on the avatar’s accent gradient',
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
