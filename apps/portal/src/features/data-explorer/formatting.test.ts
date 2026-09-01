import {describe, expect, it} from 'vitest';
import {contrastRatio} from '../../lib/contrast';
import type {Hex} from '../../lib/contrast';
import {PALETTE} from '../../lib/palette';
import type {EffectiveTheme} from '../../lib/theme.types';
import {
  FORMATTING_BACKGROUNDS,
  FORMATTING_FOREGROUNDS,
  FORMATTING_GRADIENT_STEPS,
  FORMATTING_PATTERN_MAX,
  formattingBaseSurfaces,
  formattingTokenHex,
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

const THEMES: EffectiveTheme[] = ['light', 'dark'];

/** The evaluator, under the theme every behaviour test below reads its colours from. */
function formatPage(formatting: FormattingState, columns: FormattingColumn[], rows: (string | null)[][]) {
  return computePageFormatting(formatting, columns, rows, 'light');
}

describe('the formatting palette clears WCAG AA on every surface it can land on', () => {
  // Every surface a formatted cell can sit on: the grid's own two, the SELECTION's fill
  // (a coloured cell is still selectable), and every background a rule may choose.
  function surfacesOf(theme: EffectiveTheme): Record<string, Hex> {
    const tokens = formattingTokenHex(theme);
    return {
      ...formattingBaseSurfaces(theme),
      ...Object.fromEntries(FORMATTING_BACKGROUNDS.map((token) => [token, tokens[token]]))
    };
  }

  // The five the palette offers, plus the one it left out. Which of them a theme admits is
  // COMPUTED below rather than copied between themes: a dark palette can readmit `warning` or
  // expel a colour the light one includes, and the assertion has to be about the palette it is
  // measuring.
  const CANDIDATES = [...FORMATTING_FOREGROUNDS, 'warning'] as const;

  function admissible(theme: EffectiveTheme): string[] {
    const surfaces = Object.values(surfacesOf(theme));
    return CANDIDATES.filter((token) => surfaces.every((bg) => contrastRatio(PALETTE[theme][token], bg) >= 4.5));
  }

  it.each(THEMES)('%s: every offered foreground meets 4.5:1 against every background', (theme) => {
    const failures: string[] = [];
    const tokens = formattingTokenHex(theme);
    for (const foreground of FORMATTING_FOREGROUNDS) {
      for (const [name, background] of Object.entries(surfacesOf(theme))) {
        const ratio = contrastRatio(tokens[foreground], background);
        if (ratio < 4.5) failures.push(`${foreground} on ${name}: ${ratio.toFixed(2)}`);
      }
    }
    expect(failures).toEqual([]);
  });

  it('records which foregrounds each theme admits, and that the offered set is a subset', () => {
    // The measurement that decided the palette, kept so the exclusion is a finding rather than
    // a preference — and recomputed per theme rather than restated. `warning` is out in light
    // (4.49 on `accent-soft`, 4.39 on `danger-soft`) and IN on dark, where every soft tint is
    // dark: the offered set stays five in both, because a colour a user can pick in one theme
    // and not the other is a rule that changes meaning when they switch. If either line starts
    // FAILING the tokens have moved — revisit the palette, do not delete the test.
    expect(admissible('light')).toEqual([...FORMATTING_FOREGROUNDS]);
    expect(admissible('dark')).toEqual([...FORMATTING_FOREGROUNDS, 'warning']);
    // …and the reason `warning` is excluded, from the palette rather than from a literal that
    // would go stale the day the token moved.
    expect(contrastRatio(PALETTE.light.warning, PALETTE.light['accent-soft'])).toBeLessThan(4.5);
    expect(contrastRatio(PALETTE.light.warning, PALETTE.light['danger-soft'])).toBeLessThan(4.5);
    expect(contrastRatio(PALETTE.light.warning, PALETTE.light.surface)).toBeGreaterThan(4.5);
  });

  it.each(THEMES)('%s: every shade a gradient can produce meets 4.5:1 against every foreground', (theme) => {
    // A gradient emits a colour that is in no token, so its contrast has to be measured at
    // every step it can quantise to — including the mixed shades between two tints of
    // different hues, which is where a naive "both ends are pale" argument breaks.
    const failures: string[] = [];
    const tokens = formattingTokenHex(theme);
    for (const from of FORMATTING_BACKGROUNDS) {
      for (const to of FORMATTING_BACKGROUNDS) {
        for (let step = 0; step < FORMATTING_GRADIENT_STEPS; step += 1) {
          const shade = gradientShade(from, to, step / (FORMATTING_GRADIENT_STEPS - 1), theme) as Hex;
          for (const foreground of FORMATTING_FOREGROUNDS) {
            const ratio = contrastRatio(tokens[foreground], shade);
            if (ratio < 4.5) failures.push(`${foreground} on ${from}→${to} @${step}: ${ratio.toFixed(2)}`);
          }
        }
      }
    }
    expect(failures).toEqual([]);
  });

  it('takes every value from the palette declaration, so no literal can creep back in', () => {
    // What used to stand here pinned a hand-written mirror of the palette against `index.css`.
    // There is no mirror any more — both maps resolve from the one declaration — so the guard
    // that matters now is that they still do, for every token the feature paints with.
    for (const theme of THEMES) {
      const declared = Object.entries({...formattingTokenHex(theme), ...formattingBaseSurfaces(theme)});
      for (const [token, hex] of declared) {
        expect(hex, `${theme} --color-${token}`).toBe(PALETTE[theme][token as keyof (typeof PALETTE)['light']]);
      }
      expect(declared.length).toBe(11);
    }
  });
});

// ---------------------------------------------------------------------------------------
// Rule evaluation (FR-002)
// ---------------------------------------------------------------------------------------

describe('conditional colouring', () => {
  it('paints only the cells a cell-scoped rule matched', () => {
    const {formats} = formatPage(state({rules: [rule({column: 'status', value: 'ok'})]}), COLUMNS, ROWS);
    expect(formats[0].status).toEqual({color: colourValue('danger')});
    expect(formats[0].id).toBeUndefined();
    expect(formats[1].status).toBeUndefined();
  });

  it('paints the whole row for a row-scoped rule, from a condition on one column', () => {
    const {formats} = formatPage(
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
    const {formats} = formatPage(state({rules: [rule({value: 'ok'})]}), COLUMNS, ROWS);
    expect(formats[0].status).toBeDefined();
    expect(formats[0].id).toBeUndefined();
    expect(formats[2].status).toBeDefined();
  });

  it('compares numerically when both sides are plain numbers, and textually otherwise', () => {
    const numeric = formatPage(state({rules: [rule({column: 'qty', operator: '>', value: '9'})]}), COLUMNS, ROWS);
    // Text comparison would put '10' before '9'; both rows must match.
    expect(numeric.formats[0].qty).toBeDefined();
    expect(numeric.formats[1].qty).toBeDefined();

    const textual = formatPage(state({rules: [rule({column: 'id', operator: '>', value: 'a'})]}), COLUMNS, ROWS);
    expect(textual.formats[0].id).toBeUndefined();
    expect(textual.formats[1].id).toBeDefined();
  });

  it('leaves a NULL unstyled, including under <>', () => {
    // NULL is the one value Athena does not hand back as a string, and "is not 5" over a
    // value that was never there would paint every empty cell in the column.
    const {formats} = formatPage(state({rules: [rule({column: 'qty', operator: '<>', value: '5'})]}), COLUMNS, ROWS);
    expect(formats[0].qty).toBeDefined();
    expect(formats[2].qty).toBeUndefined();
  });

  it('folds case for ILIKE and not for LIKE', () => {
    const insensitive = formatPage(
      state({rules: [rule({column: 'status', operator: 'ilike', value: 'OK'})]}),
      COLUMNS,
      ROWS
    );
    expect(insensitive.formats[0].status).toBeDefined();

    const sensitive = formatPage(
      state({rules: [rule({column: 'status', operator: 'like', value: 'OK'})]}),
      COLUMNS,
      ROWS
    );
    expect(sensitive.formats[0].status).toBeUndefined();
  });

  it('lets a later rule override an earlier one per property, not wholesale', () => {
    const {formats} = formatPage(
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
    const {formats} = formatPage(state({rules: [broken]}), COLUMNS, ROWS);
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
    const {formats} = formatPage(state({rules: [gradient]}), COLUMNS, ROWS);
    expect(formats[0].qty?.backgroundColor).toBe(gradientShade('accent-soft', 'danger-soft', 0.5, 'light'));
    expect(formats[1].qty?.backgroundColor).toBe(formattingTokenHex('light')['danger-soft']);
  });

  it('clamps a numeric value outside the range to the nearest end', () => {
    const {formats} = formatPage(
      state({rules: [{...gradient, gradient: {min: 0, max: 5, from: 'accent-soft', to: 'danger-soft'}}]}),
      COLUMNS,
      ROWS
    );
    expect(formats[0].qty?.backgroundColor).toBe(formattingTokenHex('light')['danger-soft']);
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
    const {formats} = formatPage(
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

    const {formats} = formatPage(state(), COLUMNS, BANDED);
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
    const {transformed, formats} = formatPage(formatting, COLUMNS, ROWS);
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
    const {formats} = formatPage(
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
    const many = formatPage(state({rules: [rule({column: 'id', operator: 'like', value: '%%%bc'})]}), COLUMNS, rows);
    const one = formatPage(state({rules: [rule({column: 'id', operator: 'like', value: '%bc'})]}), COLUMNS, rows);
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
