import type {Hex} from './contrast';
import type {EffectiveTheme} from './theme.types';

/** Every colour token `index.css` declares, in both themes. */
export type ColorToken =
  | 'bg'
  | 'surface'
  | 'surface-2'
  | 'border'
  | 'border-2'
  | 'text'
  | 'text-2'
  | 'text-3'
  | 'accent'
  | 'accent-hover'
  | 'accent-soft'
  | 'accent-text'
  | 'accent-border'
  | 'success'
  | 'success-soft'
  | 'warning'
  | 'warning-soft'
  | 'danger'
  | 'danger-soft'
  | 'danger-border'
  | 'on-danger'
  | 'syntax-fn';

/**
 * The token values, exactly as `src/index.css` declares them, per theme.
 *
 * `index.css` is the source and this is a copy, because two things need the VALUES rather
 * than the names: contrast has to be computed from them, and the Data Explorer's gradient has
 * to interpolate between two of them. A copy needs a guard, and `contrast.test.ts` reads the
 * stylesheet and pins every entry of both themes against it.
 */
export const PALETTE: Record<EffectiveTheme, Record<ColorToken, Hex>> = {
  light: {
    bg: '#f7f8fa',
    surface: '#ffffff',
    'surface-2': '#fafbfc',
    border: '#e6e8eb',
    'border-2': '#f0f1f3',
    text: '#15191e',
    'text-2': '#5b6573',
    'text-3': '#646b78',
    accent: '#4f46e5',
    'accent-hover': '#4338ca',
    'accent-soft': '#eef2ff',
    'accent-text': '#4338ca',
    'accent-border': '#dfe3fb',
    success: '#047857',
    'success-soft': '#e7f7f0',
    warning: '#b45309',
    'warning-soft': '#fdf4e3',
    danger: '#b91c1c',
    'danger-soft': '#fdeceb',
    'danger-border': '#f6caca',
    'on-danger': '#ffffff',
    'syntax-fn': '#7c3aed'
  },
  dark: {
    bg: '#0d1014',
    surface: '#14181e',
    'surface-2': '#191e25',
    border: '#2b323c',
    'border-2': '#1f242c',
    text: '#e9edf3',
    'text-2': '#a5aeba',
    'text-3': '#98a1ad',
    accent: '#615ae9',
    'accent-hover': '#4f46e5',
    'accent-soft': '#191b36',
    'accent-text': '#a5b4fc',
    'accent-border': '#383c6b',
    success: '#34d399',
    'success-soft': '#0a231b',
    warning: '#f0b429',
    'warning-soft': '#271e0a',
    danger: '#f87171',
    'danger-soft': '#2f1517',
    'danger-border': '#4a2427',
    'on-danger': '#1a0c0c',
    'syntax-fn': '#c4b5fd'
  }
};

/**
 * A pairing the design uses, and the ratio it must clear.
 *
 * Either side may be a raw hex: the landing page's call-to-action strip is a fixed brand
 * surface declared outside the theme, and its four colours are measured here rather than
 * exempted.
 *
 * An `over` pairing is one whose BACKGROUND is translucent, so it names the `base` behind it
 * as well: the colour the user sees is the blend, not the token, and the token always measures
 * the kinder of the two. Where more than one thing can end up back there, each candidate is its
 * own pairing — a sticky bar is declared over the accent fill AND over the fixed brand strip,
 * because which of them is worse is a fact about the theme and changes between the two.
 *
 * TWO THINGS IT DOES NOT DO, stated so nobody trusts it further than it goes. It does not model
 * a backdrop FILTER: `backdrop-blur` only averages neighbouring pixels of the same backdrop, but
 * `backdrop-saturate` changes the base before the blend, and the number here is computed from
 * the unfiltered colour — a pairing that leans on a filter for its margin is one to widen rather
 * than to measure more precisely. And it does not tie `fg` to the element: `utility` pins the
 * BACKGROUND to a class the sweep can find, but the foreground is the author's claim about what
 * sits on it, and recolouring that text in the markup reddens nothing here.
 *
 * The union is discriminated rather than `ColorToken | string`, which would absorb the
 * literal type entirely and let `tsc --strict` accept `{fg: 'txet', bg: 'surfce'}`.
 */
export type ContrastPair =
  | {kind: 'token'; fg: ColorToken | '#ffffff'; bg: ColorToken; min: 4.5 | 3}
  | {kind: 'raw'; fg: Hex; bg: Hex; min: 4.5 | 3; why: string}
  | {
      kind: 'over';
      fg: ColorToken | '#ffffff';
      bg: ColorToken | Hex;
      alpha: number;
      base: ColorToken | Hex;
      /** The utility this describes, variants stripped — what `colourLiterals.test.ts` matches. */
      utility: string;
      min: 4.5 | 3;
      why: string;
    };

/**
 * The landing page's call-to-action strip, which does not follow the theme.
 *
 * It is a fixed brand surface — the one place the product paints its own indigo rather than
 * the app's — so its colours are declared once here and once in `index.css` as plain custom
 * properties outside `@theme`, where no theme block can reach them. Fixing it is what makes
 * the white buttons on it safe: a themed `accent-text` label would go light in dark mode and
 * disappear against a white button.
 */
export const FIXED_LANDING_CTA = {
  bg: '#4f46e5',
  text: '#ffffff',
  'text-muted': '#dfe0fb',
  'button-bg': '#ffffff',
  'button-hover': '#f3f4ff',
  'button-text': '#4338ca'
} as const satisfies Record<string, Hex>;

const TEXT_SURFACES = ['bg', 'surface', 'surface-2'] as const;

/** Every foreground/background the design puts together, and the ratio each must clear. */
export const CONTRAST_PAIRS: readonly ContrastPair[] = [
  ...(['text', 'text-2', 'text-3'] as const).flatMap((fg) =>
    TEXT_SURFACES.map((bg): ContrastPair => ({kind: 'token', fg, bg, min: 4.5}))
  ),

  // Each status colour reads on the app's own surface AND on its own soft fill, which is the
  // pairing that darkened all three in the light palette.
  {kind: 'token', fg: 'success', bg: 'surface', min: 4.5},
  {kind: 'token', fg: 'success', bg: 'success-soft', min: 4.5},
  {kind: 'token', fg: 'warning', bg: 'surface', min: 4.5},
  {kind: 'token', fg: 'warning', bg: 'warning-soft', min: 4.5},
  {kind: 'token', fg: 'danger', bg: 'surface', min: 4.5},
  {kind: 'token', fg: 'danger', bg: 'danger-soft', min: 4.5},
  {kind: 'token', fg: 'accent-text', bg: 'surface', min: 4.5},
  {kind: 'token', fg: 'accent-text', bg: 'accent-soft', min: 4.5},
  // The file toolbar's Delete — red text and a red outline — sits on the selection bar's accent
  // fill while anything is selected. The text's 4.5 covers the outline's 3.
  {kind: 'token', fg: 'danger', bg: 'accent-soft', min: 4.5},

  // A banner's Dismiss and a toast's close sit ON the variant's soft fill and are deliberately
  // quieter than its message. Quieter is a different TOKEN here, never a tint of the same one:
  // dimming the variant colour to 70% put four of them between 2.80 and 3.68, and nothing
  // measuring tokens at full strength could see it. `text` is the hover state of the same
  // controls, which is the direction a hover should move contrast.
  ...(['success-soft', 'warning-soft', 'danger-soft', 'accent-soft'] as const).flatMap((bg) =>
    (['text-2', 'text'] as const).map((fg): ContrastPair => ({kind: 'token', fg, bg, min: 4.5}))
  ),

  // The editor's function colour, on the editor's background.
  {kind: 'token', fg: 'syntax-fn', bg: 'surface', min: 4.5},

  // The three fills, each measured against the foreground it is actually given. `accent` and
  // `accent-hover` are never text — they are a button's resting and hover fill and the two
  // stops of the avatar gradient, all under white — so measuring either AS text would force a
  // dark value that cannot carry white, which is the state they exist in.
  {kind: 'token', fg: '#ffffff', bg: 'accent', min: 4.5},
  {kind: 'token', fg: '#ffffff', bg: 'accent-hover', min: 4.5},
  {kind: 'token', fg: 'on-danger', bg: 'danger', min: 4.5},

  // The focus ring is a non-text indicator: WCAG 1.4.11, 3:1. It lands on the soft fills too —
  // every hoverable row, chip and menu item that takes focus is filled with one — and the ring is
  // every one of the five tightest pairings in the dark palette, 3.25–3.34, the soft fills
  // interleaved with `surface-2`. They are declared rather than left out precisely because the
  // margin is thin: a token nudged by a few points reddens here instead of quietly dropping the
  // one indicator a keyboard user has.
  ...([...TEXT_SURFACES, 'accent-soft', 'success-soft', 'warning-soft', 'danger-soft'] as const).map(
    (bg): ContrastPair => ({kind: 'token', fg: 'accent', bg, min: 3})
  ),

  // The fills the app paints at less than full strength. Each backdrop that can end up behind one
  // is a pairing of its own rather than a single worst case chosen up front: a translucent colour
  // is only as good as what it fails to hide, and which backdrop hides least is not the same in
  // the two themes.
  ...(['surface', 'bg'] as const).map((base): ContrastPair => ({
    kind: 'over',
    fg: 'on-danger',
    bg: 'danger',
    alpha: 0.9,
    base,
    utility: 'bg-danger/90',
    min: 4.5,
    why: `the danger button's label under the pointer, on a fill that lets the ${base} through`
  })),
  ...([FIXED_LANDING_CTA.bg, 'accent'] as const).map((base): ContrastPair => ({
    kind: 'over',
    fg: 'text-2',
    bg: 'surface',
    alpha: 0.95,
    base,
    utility: 'bg-surface/95',
    min: 4.5,
    why: `the landing page's sticky navigation links, over ${base === 'accent' ? 'an accent fill' : 'the fixed brand strip'} scrolling beneath`
  })),
  {
    kind: 'over',
    fg: FIXED_LANDING_CTA.text,
    bg: FIXED_LANDING_CTA.text,
    alpha: 0.1,
    base: FIXED_LANDING_CTA.bg,
    utility: 'bg-(--landing-cta-text)/10',
    min: 4.5,
    why: "the brand strip's secondary button: a white wash over the indigo, carrying a white label"
  },

  {
    kind: 'raw',
    fg: FIXED_LANDING_CTA.text,
    bg: FIXED_LANDING_CTA.bg,
    min: 4.5,
    why: 'the landing call-to-action heading, on the fixed brand strip'
  },
  {
    kind: 'raw',
    fg: FIXED_LANDING_CTA['text-muted'],
    bg: FIXED_LANDING_CTA.bg,
    min: 4.5,
    why: 'the supporting copy under that heading'
  },
  {
    kind: 'raw',
    fg: FIXED_LANDING_CTA['button-text'],
    bg: FIXED_LANDING_CTA['button-bg'],
    min: 4.5,
    why: "the strip's buttons at rest"
  },
  {
    kind: 'raw',
    fg: FIXED_LANDING_CTA['button-text'],
    bg: FIXED_LANDING_CTA['button-hover'],
    min: 4.5,
    why: "the strip's buttons under the pointer"
  }
];

/**
 * Tokens that carry no meaning and are measured against no floor, each with its reason.
 *
 * Not a convenience. Measured against the light palette these are 1.06–1.27, so **any** floor
 * — 3:1 included — fails the palette that ships. WCAG 1.4.11 governs the boundary of a
 * component whose shape carries meaning, not a hairline separator or a tint reinforcing a fill
 * that already says the same thing. A boundary that IS the only thing identifying a control is
 * a pairing, not an exemption, and belongs in {@link CONTRAST_PAIRS}.
 */
export const DECORATIVE_TOKENS: Readonly<Record<'border' | 'border-2' | 'accent-border' | 'danger-border', string>> = {
  border: 'the hairline between panels and rows; the panel it separates carries the meaning',
  'border-2': 'the lighter hairline inside a panel, between rows of one table',
  'accent-border': 'the visible edge of an accent-soft fill; reinforcement, never the sole state signal',
  'danger-border': 'the same reinforcement for a danger-soft fill, and never the sole signal either'
};
