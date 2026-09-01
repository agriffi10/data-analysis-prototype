import {describe, expect, it} from 'vitest';
import {contrastRatio, relativeLuminance, type Hex} from './contrast';
import {CONTRAST_PAIRS, DECORATIVE_TOKENS, FIXED_LANDING_CTA, PALETTE, type ContrastPair} from './palette';
import type {EffectiveTheme} from './theme.types';
import {darkBlock, declaredTokens, declaredVars, readCss, rootBlock, themeBlock} from '../test/cssTokens';

// The contrast harness. axe's `color-contrast` rule is disabled in `src/test/axe.ts` because
// jsdom has no layout engine, so nothing else in this suite can see a colour that fails —
// which is exactly why this measures the token VALUES instead of a rendered page.

const THEMES: EffectiveTheme[] = ['light', 'dark'];

function label(pair: ContrastPair): string {
  return pair.kind === 'token' ? `${pair.fg} on ${pair.bg}` : `${pair.fg} on ${pair.bg} (${pair.why})`;
}

function colours(pair: ContrastPair, theme: EffectiveTheme): [Hex, Hex] {
  if (pair.kind === 'raw') return [pair.fg, pair.bg];
  const palette = PALETTE[theme];
  return [pair.fg === '#ffffff' ? pair.fg : palette[pair.fg], palette[pair.bg]];
}

/**
 * Every pairing that misses its floor, named with the ratio it measured.
 *
 * Accumulated rather than asserted one at a time so a run names every failure, not the first.
 *
 * @param pairs - The pairings to measure.
 * @param theme - Which palette to resolve tokens against.
 * @returns One line per failure, empty when they all clear.
 */
function failures(pairs: readonly ContrastPair[], theme: EffectiveTheme): string[] {
  const found: string[] = [];
  for (const pair of pairs) {
    const [fg, bg] = colours(pair, theme);
    const ratio = contrastRatio(fg, bg);
    if (ratio < pair.min) found.push(`${theme}: ${label(pair)} — ${ratio.toFixed(2)} < ${pair.min}`);
  }
  return found;
}

describe('the ratio itself', () => {
  it('reproduces known WCAG ratios and is symmetric', () => {
    expect(contrastRatio('#15191e', '#ffffff')).toBeCloseTo(17.65, 1);
    expect(contrastRatio('#ffffff', '#15191e')).toBeCloseTo(17.65, 1);
    expect(contrastRatio('#15191e', '#f7f8fa')).toBeCloseTo(16.61, 1);
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(relativeLuminance('#fff')).toBeCloseTo(1, 5);
  });

  it('refuses a malformed hex instead of computing a plausible number on it', () => {
    // The failure this exists to prevent: `parseInt` gives NaN for 'zzz', the NaN propagates,
    // and the comparison against a floor comes back false — so a typo'd pairing clears every
    // threshold with nothing red. A five-digit hex is the same trap wearing a real number.
    for (const bad of ['zzz', '#4f46e', '#12345', 'rgb(0,0,0)', '#4f46e5f', '']) {
      expect(() => contrastRatio(bad as Hex, '#ffffff'), bad).toThrow(JSON.stringify(bad));
    }
  });
});

describe('every pairing the design uses, in both themes', () => {
  it.each(THEMES)('%s clears its floors', (theme) => {
    expect(failures(CONTRAST_PAIRS, theme)).toEqual([]);
  });

  it('reports a failing pair rather than passing everything', () => {
    // The one guard mutated on purpose: a contrast harness that silently passes everything is
    // indistinguishable from one that works. Run through the SAME function the sweep above
    // uses, so a change that stops it reporting reddens here.
    const doomed: ContrastPair = {kind: 'raw', fg: '#777777', bg: '#808080', min: 4.5, why: 'deliberate'};
    expect(failures([doomed], 'light')).toEqual(['light: #777777 on #808080 (deliberate) — 1.13 < 4.5']);
  });

  it('measures every token, or names it as decorative with a reason', () => {
    // The completeness guard. Adding a token without deciding whether it carries meaning is
    // what must be impossible — not measuring a hairline.
    const measured = new Set<string>();
    for (const pair of CONTRAST_PAIRS) {
      if (pair.kind !== 'token') continue;
      if (pair.fg !== '#ffffff') measured.add(pair.fg);
      measured.add(pair.bg);
    }
    const classified = [...measured, ...Object.keys(DECORATIVE_TOKENS)].sort();
    expect(classified).toEqual(Object.keys(PALETTE.light).sort());
  });

  it('lets nothing into the decorative list without a reason', () => {
    // "Decorative" must not become the place a failing colour is put, so the list is frozen to
    // these four and each carries the sentence saying why it carries no meaning.
    expect(Object.keys(DECORATIVE_TOKENS).sort()).toEqual(['accent-border', 'border', 'border-2', 'danger-border']);
    for (const [token, why] of Object.entries(DECORATIVE_TOKENS)) {
      expect(why.length, token).toBeGreaterThan(20);
    }
  });
});

describe('the dark palette keeps the shape the components were built around', () => {
  it('declares exactly the light theme’s tokens', () => {
    expect(Object.keys(PALETTE.dark).sort()).toEqual(Object.keys(PALETTE.light).sort());
  });

  it.each(THEMES)('%s orders its text by contrast and lifts surface above bg', (theme) => {
    const p = PALETTE[theme];
    expect(contrastRatio(p.text, p.bg)).toBeGreaterThan(contrastRatio(p['text-2'], p.bg));
    expect(contrastRatio(p['text-2'], p.bg)).toBeGreaterThan(contrastRatio(p['text-3'], p.bg));
    expect(relativeLuminance(p.surface)).toBeGreaterThan(relativeLuminance(p.bg));
  });
});

describe('the palette agrees with the stylesheet that paints it', () => {
  const css = readCss();

  it.each([
    ['light', themeBlock],
    ['dark', darkBlock]
  ] as const)('%s matches index.css token for token', (theme, block) => {
    const declared = declaredTokens(block(css));
    // A path that stopped resolving would hand back an empty string and make every assertion
    // below pass by finding nothing to disagree with.
    expect(declared.size).toBeGreaterThan(10);

    const expected = Object.entries(PALETTE[theme as EffectiveTheme]).sort();
    expect([...declared].filter(([name]) => name in PALETTE.light).sort()).toEqual(expected);
  });

  it('reads only its own block, so one palette cannot overwrite the other', () => {
    // Asserted through the same extractor the checks above run, not on a hand-cut string — a
    // guard on the extractor alone would still pass if the composition around it changed.
    const synthetic = [
      '@theme {',
      '  /* text-3 was #8a93a2 (failed) */',
      '  --color-surface: #ffffff;',
      '}',
      ":root[data-theme='dark'] {",
      '  --color-surface: #14181e;',
      '}'
    ].join('\n');

    expect(declaredTokens(themeBlock(synthetic)).get('surface')).toBe('#ffffff');
    expect(declaredTokens(darkBlock(synthetic)).get('surface')).toBe('#14181e');
    expect(declaredTokens(themeBlock(synthetic)).size, 'a hex inside a comment is not a declaration').toBe(1);
  });

  it('themes the shadow TINT, because a themed --shadow-* would be inert', () => {
    // Tailwind inlines an @theme shadow value into the utility and emits no --shadow-*
    // variable at all, so a dark block redefining --shadow-md changes nothing — silently. What
    // survives inlining is the var() inside the value. This is the guard that stops the silent
    // shape coming back.
    const theme = declaredVars(themeBlock(css), 'shadow');
    for (const size of ['sm', 'md', 'lg']) {
      expect(theme.get(size), `--shadow-${size}`).toContain(`var(--shadow-tint-${size})`);
    }
    expect([...declaredVars(rootBlock(css), 'shadow-tint').keys()].sort()).toEqual(['lg', 'md', 'sm']);
    expect([...declaredVars(darkBlock(css), 'shadow-tint').keys()].sort()).toEqual(['lg', 'md', 'sm']);
    expect([...declaredVars(darkBlock(css), 'shadow').keys()].filter((n) => !n.startsWith('tint-'))).toEqual([]);
  });

  it('keeps the landing call-to-action strip outside both themes', () => {
    // It is a fixed brand surface: its white buttons carry a dark indigo label, and a themed
    // label would go light and vanish against them.
    const declared = declaredVars(rootBlock(css), 'landing-cta');
    expect(Object.fromEntries(declared)).toEqual(FIXED_LANDING_CTA);
    expect([...declaredVars(darkBlock(css), 'landing-cta').keys()]).toEqual([]);
  });
});
