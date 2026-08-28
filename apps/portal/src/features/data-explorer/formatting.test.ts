import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';
import {
  FORMATTING_BACKGROUNDS,
  FORMATTING_BASE_SURFACES,
  FORMATTING_FOREGROUNDS,
  FORMATTING_GRADIENT_STEPS,
  FORMATTING_PATTERN_MAX,
  FORMATTING_TOKEN_HEX,
  NUMERIC_TRANSFORMER_ERROR,
  TRUNCATION_INDICATOR
} from './dataExplorer.constants';
import {
  bandsOf,
  colourValue,
  computePageFormatting,
  GRADIENT_COLUMN_REFUSAL,
  GRADIENT_RANGE_REFUSAL,
  gradientShade,
  NO_COLOUR_REFUSAL,
  PATTERN_REFUSAL,
  PATTERN_TOO_LONG_REFUSAL,
  ruleRefusal,
  transformCell,
  typeColour
} from './formatting';
import {emptyFormattingState} from './exploration';
import type {ColourRule, FormattingState} from './dataExplorer.types';
import type {FormattingColumn} from './formatting';

// SPEC-184 FR-002/003/004. Two kinds of assertion live here and they are different in
// kind: the evaluator's answers, and the PALETTE's contrast — which is computed from the
// token values rather than asserted about, because a hard-coded "these pass" is a claim
// that stops being true the moment a token moves and says nothing when it does.

const COLUMNS: FormattingColumn[] = [
  {name: 'id', index: 0, type: 'varchar'},
  {name: 'qty', index: 1, type: 'bigint'},
  {name: 'status', index: 2, type: 'varchar'}
];

const ROWS: (string | null)[][] = [
  ['a', '10', 'ok'],
  ['b', '20', 'failed'],
  ['c', null, 'ok']
];

function state(overrides: Partial<FormattingState> = {}): FormattingState {
  return {...emptyFormattingState(), ...overrides};
}

function rule(overrides: Partial<ColourRule> = {}): ColourRule {
  return {id: 'r1', operator: '=', value: 'ok', foreground: 'danger', ...overrides};
}

// ---------------------------------------------------------------------------------------
// Contrast (FR-002 AC8)
// ---------------------------------------------------------------------------------------

function relativeLuminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

/** WCAG 2.2 relative-contrast ratio between two opaque colours. */
function contrastRatio(a: string, b: string): number {
  const [high, low] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/**
 * The token stylesheet, from whichever directory the runner was started in.
 *
 * Two literal paths rather than a loop over a list: `security/detect-non-literal-fs-filename`
 * is on, and a constructed path is exactly what it exists to flag — even here, where the
 * only inputs are these two constants.
 */
function readCss(): string {
  try {
    return readFileSync('src/index.css', 'utf8');
  } catch {
    return readFileSync('apps/portal/src/index.css', 'utf8');
  }
}

/**
 * The body of `index.css`'s `@theme` block, with comments removed.
 *
 * Scoped to the block rather than matched across the whole file, because a whole-file scan
 * reads every `--color-*` anywhere in the stylesheet: a second token block — which is what a
 * dark theme adds — would overwrite these values with its own, and every assertion below
 * would go on passing while measuring a palette the light theme never paints.
 */
function themeBlock(css: string): string {
  // Comments come out FIRST, before the braces are counted. Stripping afterwards leaves the
  // scan reading punctuation inside prose: a `}` in a comment truncates the block, and — the
  // only case that fails open rather than loudly — an `@theme` mentioned in a comment with no
  // real block returns the NEXT block's body as though it were the theme. On today's
  // stylesheet both orders give byte-identical output, which is exactly why the order has to
  // be chosen deliberately rather than discovered later.
  const source = css.replace(/\/\*[\s\S]*?\*\//g, '');

  const declaration = source.indexOf('@theme');
  const start = declaration < 0 ? -1 : source.indexOf('{', declaration);
  if (start < 0) throw new Error('index.css declares no @theme block');

  let depth = 0;
  for (let i = start; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start + 1, i);
    }
  }
  throw new Error('index.css has no closed @theme block');
}

describe('the formatting palette clears WCAG AA on every surface it can land on', () => {
  // Every surface a formatted cell can sit on: the grid's own two, the SELECTION's fill
  // (a coloured cell is still selectable), and every background a rule may choose.
  const surfaces = {
    ...FORMATTING_BASE_SURFACES,
    ...Object.fromEntries(FORMATTING_BACKGROUNDS.map((token) => [token, FORMATTING_TOKEN_HEX[token]]))
  };

  it('every foreground meets 4.5:1 against every background', () => {
    const failures: string[] = [];
    for (const foreground of FORMATTING_FOREGROUNDS) {
      for (const [name, background] of Object.entries(surfaces)) {
        const ratio = contrastRatio(FORMATTING_TOKEN_HEX[foreground], background);
        if (ratio < 4.5) failures.push(`${foreground} on ${name}: ${ratio.toFixed(2)}`);
      }
    }
    expect(failures).toEqual([]);
  });

  it('records why `warning` is not a foreground — it fails on the soft backgrounds', () => {
    // The measurement that decided the palette, kept so the exclusion is a finding rather
    // than a preference. If this starts FAILING, the tokens have moved and `warning` may
    // be admissible again — revisit the palette, do not delete the test.
    expect(contrastRatio('#b45309', FORMATTING_TOKEN_HEX['accent-soft'])).toBeLessThan(4.5);
    expect(contrastRatio('#b45309', FORMATTING_TOKEN_HEX['danger-soft'])).toBeLessThan(4.5);
    expect(contrastRatio('#b45309', FORMATTING_BASE_SURFACES.surface)).toBeGreaterThan(4.5);
  });

  it('every shade a gradient can produce meets 4.5:1 against every foreground', () => {
    // A gradient emits a colour that is in no token, so its contrast has to be measured at
    // every step it can quantise to — including the mixed shades between two tints of
    // different hues, which is where a naive "both ends are pale" argument breaks.
    const failures: string[] = [];
    for (const from of FORMATTING_BACKGROUNDS) {
      for (const to of FORMATTING_BACKGROUNDS) {
        for (let step = 0; step < FORMATTING_GRADIENT_STEPS; step += 1) {
          const shade = gradientShade(from, to, step / (FORMATTING_GRADIENT_STEPS - 1));
          for (const foreground of FORMATTING_FOREGROUNDS) {
            const ratio = contrastRatio(FORMATTING_TOKEN_HEX[foreground], shade);
            if (ratio < 4.5) failures.push(`${foreground} on ${from}→${to} @${step}: ${ratio.toFixed(2)}`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('the palette map matches the tokens index.css actually declares', () => {
    // The one thing that would make every measurement above meaningless: a hex here that is
    // not the hex the browser paints. The map exists only because a gradient has to
    // interpolate values and contrast has to be computed from them — so it is a copy, and a
    // copy needs a guard.
    // Read from disk rather than imported. Vitest does not process CSS, so BOTH
    // `import '…?raw'` and a raw `import.meta.glob` of a stylesheet resolve to an empty
    // string — measured, not assumed — and an empty string would make every assertion below
    // pass by finding nothing to disagree with. The size guard is what catches a path that
    // stops resolving.
    const declared = new Map<string, string>();
    for (const [, name, hex] of themeBlock(readCss()).matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-f]{6});/g)) {
      declared.set(name, hex);
    }
    expect(declared.size).toBeGreaterThan(10);

    for (const [token, hex] of Object.entries(FORMATTING_TOKEN_HEX)) {
      expect(declared.get(token), `--color-${token}`).toBe(hex);
    }

    // The SECOND mirror, and the one with no other cover: `surface` and `surface-2` appear in
    // no other map, and they are the backgrounds every contrast number above is measured
    // against. Pinning both maps to the same source is also what makes `accent-soft` — the one
    // token they share — agree by construction rather than by a fourth assertion.
    expect(declared.get('surface')).toBe(FORMATTING_BASE_SURFACES.surface);
    expect(declared.get('surface-2')).toBe(FORMATTING_BASE_SURFACES['surface-2']);
    expect(declared.get('accent-soft')).toBe(FORMATTING_BASE_SURFACES['accent-soft']);
  });

  it('reads only the @theme block, so a second token block cannot overwrite it', () => {
    // The scoping is the whole reason the parse above is not a whole-file regex, and
    // `index.css` does not exercise it yet — a dark theme is what adds the second block. So
    // it is asserted against a synthetic stylesheet, which is the only way to have the guard
    // before the case it guards against exists.
    const body = themeBlock(
      [
        '@theme {',
        '  /* text-3 was #8a93a2 (failed) */',
        '  --color-surface: #ffffff;',
        '}',
        ":root[data-theme='dark'] {",
        '  --color-surface: #14171c;',
        '}'
      ].join('\n')
    );

    // Asserted through the SAME matchAll the real check runs, not on the extracted text — a
    // guard on the extractor alone would still pass if the composition around it changed.
    const declared = new Map<string, string>();
    for (const [, name, hex] of body.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-f]{6});/g)) {
      declared.set(name, hex);
    }

    expect(declared.get('surface'), 'a later block must not reach the light palette').toBe('#ffffff');
    expect(declared.size, 'a hex inside a comment is not a declaration').toBe(1);
  });
});

// ---------------------------------------------------------------------------------------
// Rule evaluation (FR-002)
// ---------------------------------------------------------------------------------------

describe('conditional colouring', () => {
  it('paints only the cells a cell-scoped rule matched', () => {
    const {formats} = computePageFormatting(state({rules: [rule({column: 'status', value: 'ok'})]}), COLUMNS, ROWS);
    expect(formats[0].status).toEqual({color: colourValue('danger')});
    expect(formats[0].id).toBeUndefined();
    expect(formats[1].status).toBeUndefined();
  });

  it('paints the whole row for a row-scoped rule, from a condition on one column', () => {
    const {formats} = computePageFormatting(
      state({rules: [rule({column: 'status', value: 'failed', scope: 'row', background: 'danger-soft'})]}),
      COLUMNS,
      ROWS
    );
    for (const column of ['id', 'qty', 'status']) {
      expect(formats[1][column]).toEqual({color: colourValue('danger'), backgroundColor: colourValue('danger-soft')});
    }
    expect(formats[0].id).toBeUndefined();
  });

  it('tests every cell in the row when no column is named', () => {
    const {formats} = computePageFormatting(state({rules: [rule({value: 'ok'})]}), COLUMNS, ROWS);
    expect(formats[0].status).toBeDefined();
    expect(formats[0].id).toBeUndefined();
    expect(formats[2].status).toBeDefined();
  });

  it('compares numerically when both sides are plain numbers, and textually otherwise', () => {
    const numeric = computePageFormatting(
      state({rules: [rule({column: 'qty', operator: '>', value: '9'})]}),
      COLUMNS,
      ROWS
    );
    // Text comparison would put '10' before '9'; both rows must match.
    expect(numeric.formats[0].qty).toBeDefined();
    expect(numeric.formats[1].qty).toBeDefined();

    const textual = computePageFormatting(
      state({rules: [rule({column: 'id', operator: '>', value: 'a'})]}),
      COLUMNS,
      ROWS
    );
    expect(textual.formats[0].id).toBeUndefined();
    expect(textual.formats[1].id).toBeDefined();
  });

  it('leaves a NULL unstyled, including under <>', () => {
    // NULL is the one value Athena does not hand back as a string, and "is not 5" over a
    // value that was never there would paint every empty cell in the column.
    const {formats} = computePageFormatting(
      state({rules: [rule({column: 'qty', operator: '<>', value: '5'})]}),
      COLUMNS,
      ROWS
    );
    expect(formats[0].qty).toBeDefined();
    expect(formats[2].qty).toBeUndefined();
  });

  it('folds case for ILIKE and not for LIKE', () => {
    const insensitive = computePageFormatting(
      state({rules: [rule({column: 'status', operator: 'ilike', value: 'OK'})]}),
      COLUMNS,
      ROWS
    );
    expect(insensitive.formats[0].status).toBeDefined();

    const sensitive = computePageFormatting(
      state({rules: [rule({column: 'status', operator: 'like', value: 'OK'})]}),
      COLUMNS,
      ROWS
    );
    expect(sensitive.formats[0].status).toBeUndefined();
  });

  it('lets a later rule override an earlier one per property, not wholesale', () => {
    const {formats} = computePageFormatting(
      state({
        rules: [
          rule({id: 'a', column: 'status', value: 'ok', foreground: 'success', background: 'success-soft'}),
          rule({id: 'b', column: 'status', value: 'ok', foreground: 'danger', background: undefined})
        ]
      }),
      COLUMNS,
      ROWS
    );
    // The second rule sets only a foreground, so the first's background survives it.
    expect(formats[0].status).toEqual({
      color: colourValue('danger'),
      backgroundColor: colourValue('success-soft')
    });
  });

  it('never applies an invalid rule, even if one reaches it from storage', () => {
    const broken = rule({column: 'status', operator: 'regex', value: '('});
    expect(ruleRefusal(broken)).toBe(PATTERN_REFUSAL);
    const {formats} = computePageFormatting(state({rules: [broken]}), COLUMNS, ROWS);
    expect(formats.every((row) => Object.keys(row).length === 0)).toBe(true);
  });

  it('refuses a rule at entry with user wording, never the engine’s', () => {
    expect(ruleRefusal(rule({operator: 'regex', value: '[a-'}))).toBe(PATTERN_REFUSAL);
    expect(ruleRefusal(rule({value: 'x'.repeat(FORMATTING_PATTERN_MAX + 1)}))).toBe(PATTERN_TOO_LONG_REFUSAL);
    expect(ruleRefusal(rule({foreground: undefined, background: undefined}))).toBe(NO_COLOUR_REFUSAL);
    expect(ruleRefusal(rule({gradient: {min: 0, max: 10, from: 'accent-soft', to: 'danger-soft'}}))).toBe(
      GRADIENT_COLUMN_REFUSAL
    );
    expect(ruleRefusal(rule({column: 'qty', gradient: {min: 5, max: 5, from: 'accent-soft', to: 'danger-soft'}}))).toBe(
      GRADIENT_RANGE_REFUSAL
    );
    expect(ruleRefusal(rule({column: 'status'}))).toBeNull();
  });
});

describe('gradients', () => {
  const gradient = rule({
    id: 'g',
    column: 'qty',
    foreground: undefined,
    gradient: {min: 0, max: 20, from: 'accent-soft', to: 'danger-soft'}
  });

  it('interpolates a numeric cell across the range', () => {
    const {formats} = computePageFormatting(state({rules: [gradient]}), COLUMNS, ROWS);
    expect(formats[0].qty?.backgroundColor).toBe(gradientShade('accent-soft', 'danger-soft', 0.5));
    expect(formats[1].qty?.backgroundColor).toBe(FORMATTING_TOKEN_HEX['danger-soft']);
  });

  it('clamps a numeric value outside the range to the nearest end', () => {
    const {formats} = computePageFormatting(
      state({rules: [{...gradient, gradient: {min: 0, max: 5, from: 'accent-soft', to: 'danger-soft'}}]}),
      COLUMNS,
      ROWS
    );
    expect(formats[0].qty?.backgroundColor).toBe(FORMATTING_TOKEN_HEX['danger-soft']);
  });
});

// ---------------------------------------------------------------------------------------
// Type colours (FR-003) and striping (FR-004)
// ---------------------------------------------------------------------------------------

describe('colour by data type', () => {
  it('tints by type family, leaving strings at the default', () => {
    expect(typeColour('bigint')).toBe('accent-text');
    expect(typeColour('decimal(10,2)')).toBe('accent-text');
    expect(typeColour('TIMESTAMP')).toBe('success');
    expect(typeColour('boolean')).toBe('danger');
    expect(typeColour('array<varchar>')).toBe('text-2');
    expect(typeColour('varchar')).toBe('text');
    expect(typeColour('something-new')).toBe('text');
  });

  it('loses to a conditional rule where both apply', () => {
    const {formats} = computePageFormatting(
      state({colourByType: true, rules: [rule({column: 'qty', operator: '>', value: '5'})]}),
      COLUMNS,
      ROWS
    );
    expect(formats[0].qty?.color).toBe(colourValue('danger'));
    // …and still applies everywhere the rule did not.
    expect(formats[0].status?.color).toBe(colourValue('text'));
  });
});

describe('group row striping', () => {
  const BANDED: (string | null)[][] = [
    ['a', '1', 'ok'],
    ['a', '2', 'ok'],
    ['b', '3', 'ok'],
    ['a', '4', 'ok']
  ];

  it('bands consecutive rows sharing every chosen column, and alternates', () => {
    const {bands, bandStarts} = bandsOf(BANDED, COLUMNS, ['id']);
    // Row 3 repeats a value from band 0 but is not adjacent to it — a band is a run, not
    // a grouping, which is the whole point of using it on sorted data.
    expect(bands).toEqual([0, 0, 1, 2]);
    expect(bandStarts).toEqual([true, false, true, true]);
  });

  it('is off with no columns chosen rather than every-other-row', () => {
    const {bands, bandStarts} = bandsOf(BANDED, COLUMNS, []);
    expect(bands).toEqual([-1, -1, -1, -1]);
    expect(bandStarts).toEqual([false, false, false, false]);

    const {formats} = computePageFormatting(state(), COLUMNS, BANDED);
    expect(formats.every((row) => Object.keys(row).length === 0)).toBe(true);
  });

  it('tells a NULL apart from the string "NULL" when banding', () => {
    const rows: (string | null)[][] = [
      ['a', null, 'ok'],
      ['a', 'NULL', 'ok']
    ];
    expect(bandsOf(rows, COLUMNS, ['qty']).bands).toEqual([0, 1]);
  });
});

// ---------------------------------------------------------------------------------------
// Transformers (FR-005)
// ---------------------------------------------------------------------------------------

describe('transformers change the rendering and nothing else', () => {
  it('renders a numeric column to a chosen precision', () => {
    expect(transformCell('10', {kind: 'numeric', precision: 2, lenient: true})?.text).toBe('10.00');
    expect(transformCell('1.05', {kind: 'numeric', precision: 1, lenient: true})?.text).toBe('1.1');
    expect(transformCell('-3', {kind: 'numeric', precision: 0, lenient: true})?.text).toBe('-3');
  });

  it('leaves an unparseable value alone when lenient, and marks it when not', () => {
    // Neither mode blanks the cell: it HAS a value, and erasing it would be
    // indistinguishable from an empty column.
    expect(transformCell('lots', {kind: 'numeric', precision: 2, lenient: true})?.text).toBe('lots');
    expect(transformCell('lots', {kind: 'numeric', precision: 2, lenient: false})?.text).toBe(
      NUMERIC_TRANSFORMER_ERROR
    );
    // The renderer's own numeric rule, so a value Calc will not average is not one this
    // silently rounds either.
    expect(transformCell('0x1f', {kind: 'numeric', precision: 2, lenient: false})?.text).toBe(
      NUMERIC_TRANSFORMER_ERROR
    );
  });

  it('encodes to hex or base64 and says when it cut the rendering short', () => {
    expect(transformCell('AB', {kind: 'binary', encoding: 'hex', maxLength: 64})?.text).toBe('4142');
    expect(transformCell('AB', {kind: 'binary', encoding: 'base64', maxLength: 64})?.text).toBe('QUI=');
    // Multi-byte input goes through UTF-8 BYTES, not code units.
    expect(transformCell('é', {kind: 'binary', encoding: 'hex', maxLength: 64})?.text).toBe('c3a9');

    // Silently showing the first N characters of a hash is how two different values come
    // to look identical.
    expect(transformCell('ABCDEF', {kind: 'binary', encoding: 'hex', maxLength: 4})?.text).toBe(
      `4142${TRUNCATION_INDICATOR}`
    );
    expect(transformCell('AB', {kind: 'binary', encoding: 'hex', maxLength: 4})?.text).toBe('4142');
  });

  it('is resolved beside the raw values a rule is tested against, never in place of them', () => {
    // The property FR-005 AC4 turns on: a colour rule, Calc and a filter all read `rows`,
    // and the transformed rendering lives beside them rather than in them.
    const formatting = state({
      transformers: {qty: {kind: 'numeric', precision: 2, lenient: true}},
      rules: [rule({column: 'qty', operator: '=', value: '10'})]
    });
    const {transformed, formats} = computePageFormatting(formatting, COLUMNS, ROWS);
    expect(transformed[0].qty.text).toBe('10.00');
    // The rule matched the RAW `10`, not the rendered `10.00` — a rule tested against the
    // rendering would need the user to write the transformer's own output as its value.
    expect(formats[0].qty).toEqual({color: colourValue('danger')});
  });
});

describe('a LIKE pattern cannot be made to backtrack catastrophically', () => {
  // Found in review. Translated one wildcard at a time, `%%%%` becomes four NESTED
  // unbounded quantifiers: `%%%%%%%%x` against a 60-character value measured at **32
  // seconds** before the fix, inside a `useMemo` that runs once per cell. Runs of `%` now
  // collapse to one, which removes the pathology rather than bounding it.
  const value = 'a'.repeat(60);

  it('finishes promptly on a pattern of repeated wildcards', () => {
    const started = Date.now();
    const {formats} = computePageFormatting(
      state({rules: [rule({column: 'id', operator: 'like', value: '%%%%%%%%x'})]}),
      COLUMNS,
      [[value, '1', 'ok']]
    );
    expect(formats[0].id).toBeUndefined();
    // Three orders of magnitude below the pre-fix measurement — a bound this loose cannot
    // be flaky and still catches a return to nested quantifiers.
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it('means exactly what a single wildcard means', () => {
    // The collapse must not change WHICH values match, only how long deciding takes.
    const rows: (string | null)[][] = [
      ['abc', '1', 'ok'],
      ['xbc', '1', 'ok']
    ];
    const many = computePageFormatting(
      state({rules: [rule({column: 'id', operator: 'like', value: '%%%bc'})]}),
      COLUMNS,
      rows
    );
    const one = computePageFormatting(
      state({rules: [rule({column: 'id', operator: 'like', value: '%bc'})]}),
      COLUMNS,
      rows
    );
    expect(many.formats.map((f) => Boolean(f.id))).toEqual(one.formats.map((f) => Boolean(f.id)));
    expect(many.formats[0].id).toBeDefined();
  });
});

describe('hostile column names and values do not escape', () => {
  it('does not throw on a lone surrogate reaching the url transformer', () => {
    // `encodeURIComponent('\uD800')` throws `URIError`, which would come straight out of
    // the grid's render rather than out of a refusal.
    expect(() => transformCell('\uD800', {kind: 'url', template: 'https://example.com/${value}'})).not.toThrow();
    expect(transformCell('\uD800', {kind: 'url', template: 'https://example.com/${value}'})?.href).toBeUndefined();
  });
});
