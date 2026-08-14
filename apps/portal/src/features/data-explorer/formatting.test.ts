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
  isRuleApplicable,
  NO_COLOUR_REFUSAL,
  PATTERN_REFUSAL,
  PATTERN_TOO_LONG_REFUSAL,
  ruleRefusal,
  STRIPE_BACKGROUND,
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

/** WCAG 2.2 relative-contrast ratio between two opaque colours. */
function contrastRatio(a: string, b: string): number {
  const [high, low] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
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

  it('records why `warning` is not a foreground — it fails on the soft backgrounds', () => {
    // The measurement that decided the palette, kept so the exclusion is a finding rather
    // than a preference. If this starts FAILING, the tokens have moved and `warning` may
    // be admissible again — revisit the palette, do not delete the test.
    expect(contrastRatio('#b45309', FORMATTING_TOKEN_HEX['accent-soft'])).toBeLessThan(4.5);
    expect(contrastRatio('#b45309', FORMATTING_TOKEN_HEX['danger-soft'])).toBeLessThan(4.5);
    expect(contrastRatio('#b45309', FORMATTING_BASE_SURFACES.surface)).toBeGreaterThan(4.5);
  });

  it('the palette map matches the tokens index.css actually declares', () => {
    // The one thing that would make every measurement above meaningless: a hex here that
    // is not the hex the browser paints. The map exists only because a gradient has to
    // interpolate values and contrast has to be computed from them — so it is a copy, and
    // a copy needs a guard.
    // Read from disk rather than imported. Vitest does not process CSS, so BOTH
    // `import '…?raw'` and a raw `import.meta.glob` of a stylesheet resolve to an empty
    // string — measured, not assumed — and an empty string would make every assertion
    // below pass by finding nothing to disagree with. The size guard is what catches a
    // path that stops resolving.
    const css = readCss();
    const declared = new Map<string, string>();
    for (const [, name, hex] of css.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-f]{6});/g)) {
      declared.set(name, hex);
    }
    expect(declared.size).toBeGreaterThan(10);

    for (const [token, hex] of Object.entries(FORMATTING_TOKEN_HEX)) {
      expect(declared.get(token), `--color-${token}`).toBe(hex);
    }
    expect(declared.get('surface')).toBe(FORMATTING_BASE_SURFACES.surface);
    expect(declared.get('surface-2')).toBe(FORMATTING_BASE_SURFACES['surface-2']);
    expect(declared.get('accent-soft')).toBe(FORMATTING_BASE_SURFACES['accent-soft']);
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

  it('matches LIKE with its own wildcards and nothing else', () => {
    const wildcard = computePageFormatting(
      state({rules: [rule({column: 'status', operator: 'like', value: 'fail%'})]}),
      COLUMNS,
      ROWS
    );
    expect(wildcard.formats[1].status).toBeDefined();
    expect(wildcard.formats[0].status).toBeUndefined();

    // A regex metacharacter is a literal in a LIKE pattern: `.` matches a dot, not any
    // character — so nothing here matches at all.
    const literal = computePageFormatting(
      state({rules: [rule({column: 'status', operator: 'like', value: '..'})]}),
      COLUMNS,
      ROWS
    );
    expect(literal.formats[0].status).toBeUndefined();

    // LIKE is anchored; a bare substring matches nothing without a wildcard.
    const anchored = computePageFormatting(
      state({rules: [rule({column: 'status', operator: 'like', value: 'fail'})]}),
      COLUMNS,
      ROWS
    );
    expect(anchored.formats[1].status).toBeUndefined();
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

  it('searches within the value for REGEX', () => {
    const {formats} = computePageFormatting(
      state({rules: [rule({column: 'status', operator: 'regex', value: 'ai'})]}),
      COLUMNS,
      ROWS
    );
    expect(formats[1].status).toBeDefined();
    expect(formats[0].status).toBeUndefined();
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

  it('leaves a non-numeric or NULL cell unstyled rather than clamping it to an end', () => {
    // The clamp is the tempting bug: it paints a text cell the colour of the minimum,
    // which reads as a measurement of something that was never measured.
    const {formats} = computePageFormatting(state({rules: [{...gradient, column: 'id'}]}), COLUMNS, ROWS);
    expect(formats[0].id).toBeUndefined();

    const nulls = computePageFormatting(state({rules: [gradient]}), COLUMNS, ROWS);
    expect(nulls.formats[2].qty).toBeUndefined();
  });

  it('clamps a numeric value outside the range to the nearest end', () => {
    const {formats} = computePageFormatting(
      state({rules: [{...gradient, gradient: {min: 0, max: 5, from: 'accent-soft', to: 'danger-soft'}}]}),
      COLUMNS,
      ROWS
    );
    expect(formats[0].qty?.backgroundColor).toBe(FORMATTING_TOKEN_HEX['danger-soft']);
  });

  it('paints the row from one column’s value when it is row-scoped', () => {
    const {formats} = computePageFormatting(state({rules: [{...gradient, scope: 'row'}]}), COLUMNS, ROWS);
    const shade = gradientShade('accent-soft', 'danger-soft', 0.5);
    expect(formats[0].id?.backgroundColor).toBe(shade);
    expect(formats[0].status?.backgroundColor).toBe(shade);
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

  it('bands on all chosen columns together', () => {
    expect(bandsOf(BANDED, COLUMNS, ['id', 'status']).bands).toEqual([0, 0, 1, 2]);
    expect(bandsOf(BANDED, COLUMNS, ['status']).bands).toEqual([0, 0, 0, 0]);
  });

  it('is off with no columns chosen rather than every-other-row', () => {
    const {bands, bandStarts} = bandsOf(BANDED, COLUMNS, []);
    expect(bands).toEqual([-1, -1, -1, -1]);
    expect(bandStarts).toEqual([false, false, false, false]);

    const {formats} = computePageFormatting(state(), COLUMNS, BANDED);
    expect(formats.every((row) => Object.keys(row).length === 0)).toBe(true);
  });

  it('tints alternate bands and loses to a conditional rule', () => {
    const {formats} = computePageFormatting(
      state({stripeColumns: ['id'], rules: [rule({column: 'status', value: 'ok', background: 'accent-soft'})]}),
      COLUMNS,
      BANDED
    );
    expect(formats[0].id?.backgroundColor).toBeUndefined(); // band 0 — untinted
    expect(formats[2].id?.backgroundColor).toBe(STRIPE_BACKGROUND); // band 1
    expect(formats[2].status?.backgroundColor).toBe(colourValue('accent-soft')); // the rule wins
  });

  it('tells a NULL apart from the string "NULL" when banding', () => {
    const rows: (string | null)[][] = [
      ['a', null, 'ok'],
      ['a', 'NULL', 'ok']
    ];
    expect(bandsOf(rows, COLUMNS, ['qty']).bands).toEqual([0, 1]);
  });
});

describe('a rule whose column has gone', () => {
  it('is kept, reported inapplicable and evaluated against nothing', () => {
    // A grouping change replaces the column set wholesale (SPEC-182), so this is ordinary
    // rather than a fault — and deleting the rule would discard work the moment a user grouped.
    const orphan = rule({column: 'gone', value: 'ok'});
    expect(isRuleApplicable(orphan, ['id', 'qty'])).toBe(false);
    expect(isRuleApplicable(rule({column: 'id'}), ['id', 'qty'])).toBe(true);
    expect(isRuleApplicable(rule({column: undefined}), ['id'])).toBe(true);

    const {formats} = computePageFormatting(state({rules: [orphan]}), COLUMNS, ROWS);
    expect(formats.every((row) => Object.keys(row).length === 0)).toBe(true);
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

  it('leaves NULL and the empty string untransformed', () => {
    // Both are absences the grid names in words; a base64 rendering of nothing is a cell
    // that says something is there.
    expect(transformCell(null, {kind: 'binary', encoding: 'hex', maxLength: 64})).toBeNull();
    expect(transformCell('', {kind: 'binary', encoding: 'hex', maxLength: 64})).toBeNull();
    expect(transformCell('x', undefined)).toBeNull();
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

  it('resolves nothing at all when no column has a transformer', () => {
    const {transformed} = computePageFormatting(state(), COLUMNS, ROWS);
    expect(transformed.every((row) => Object.keys(row).length === 0)).toBe(true);
  });
});
