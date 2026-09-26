import {
  FORMATTING_GRADIENT_STEPS,
  FORMATTING_PATTERN_MAX,
  formattingTokenHex,
  NUMERIC_TRANSFORMER_ERROR,
  TRUNCATION_INDICATOR
} from './dataExplorer.constants';
import type {EffectiveTheme} from '../../lib/theme.types';
import {isBareNumeric} from './renderExplorationSql';
import {colourOperatorTakesValue} from './dataExplorer.constants';
import {resolveUrl} from './urlTransformer';
import type {
  ColourOperator,
  ColourRule,
  ColourToken,
  FormattingState,
  SurfaceToken,
  Transformer
} from './dataExplorer.types';

// the arithmetic: which cells a rule paints, what shade a gradient gives them, and
// where one band of equal rows ends and the next begins.
//
// **Nothing here renders SQL and nothing here can.** That is the whole spec, and it is
// structural rather than promised: `renderExplorationSql` takes the source and the query
// description and nothing else, so a module that only presentation reaches is a module the
// SQL cannot depend on. `sqlBuilderSweep.test.ts` walks the renderer's import closure and
// asserts this file is not in it.
//
// Every comparison here is against the RAW cell value. A transformer changes only what a
// cell looks like, so a rule tested against the transformed rendering would
// match on a URL a user cannot see and miss the number they typed.

/** Resolved colours for one cell. Absent properties mean "leave it alone". */
export type CellFormat = {color?: string; backgroundColor?: string};

/** What a transformer makes of one value. */
export type TransformedValue = {
  /** What the cell shows in place of the raw value. */
  text: string;
  /** An `https:` destination, when a URL transformer resolved one. */
  href?: string;
  /** Why there is no link, available where the plain text is shown. */
  reason?: string;
};

export type PageFormatting = {
  /** Zero-based band index per row; every entry is -1 when striping is off. */
  bands: number[];
  /**
   * Whether a row opens a new band.
   *
   * The alternating tint is `surface-2`, which is faint by design — it is the same shade
   * the grid already hovers with, and this spec adds no tokens. So the boundary carries a
   * rule as well as a tint: colour is never the only thing marking it (1.4.1).
   */
  bandStarts: boolean[];
  /** `formats[row][columnName]`, absent wherever a cell is unstyled. */
  formats: Record<string, CellFormat>[];
  /**
   * `transformed[row][columnName]`, absent wherever a cell renders as itself.
   *
   * Resolved here rather than at each cell so one prop carries everything a page's cells
   * need — the grid, the Record view and the Value panel all read the same rendering, and
   * a panel that transformed a value differently from the cell beside it would be the
   * bug this spec is most likely to ship.
   */
  transformed: Record<string, TransformedValue>[];
};

/** Adds an own property under a key that may be `__proto__`, which assignment would not. */
function define<T>(target: Record<string, T>, key: string, value: T): void {
  Object.defineProperty(target, key, {value, enumerable: true, writable: true, configurable: true});
}

/** One column, as the evaluator needs it: its name, where its values sit, and its type. */
export type FormattingColumn = {name: string; index: number; type: string};

export const PATTERN_REFUSAL = 'That isn’t a pattern this can use.';
export const PATTERN_TOO_LONG_REFUSAL = `A value to match can be at most ${FORMATTING_PATTERN_MAX} characters.`;
export const GRADIENT_COLUMN_REFUSAL = 'A gradient needs one column to measure.';
export const GRADIENT_RANGE_REFUSAL = 'A gradient needs a range, with the two ends different numbers.';
export const NO_COLOUR_REFUSAL = 'Choose a text color, a background, or both.';

/** The alternating band's fill — the grid's own second surface, not a new token. */
export const STRIPE_BACKGROUND = 'var(--color-surface-2)';

/**
 * A token as a CSS colour.
 *
 * `var(--color-…)` rather than the hex beside it, so a rule follows the design token the
 * way every class in the app does; the hex map exists for the two things a variable cannot
 * do — interpolate a gradient, and be measured for contrast.
 *
 * @param token - The palette entry to render.
 * @returns A CSS colour value.
 */
export function colourValue(token: ColourToken | SurfaceToken): string {
  return `var(--color-${token})`;
}

function channels(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * The shade a gradient gives at `position` along its scale.
 *
 * Quantised to {@link FORMATTING_GRADIENT_STEPS} rather than continuous: a distinct colour
 * per row is a scale nobody can read, and a decile scale is one people already know.
 *
 * The one colour this module emits as a LITERAL rather than as `var(--color-…)`: a mixed
 * shade is in no token, so there is no variable to name it and the theme has to be resolved
 * here, where the style is built.
 *
 * @param from - The colour at the low end.
 * @param to - The colour at the high end.
 * @param position - Where the value falls, 0 to 1 inclusive; clamped.
 * @param theme - The theme being painted, whose tints are mixed.
 * @returns A `#rrggbb` colour.
 */
export function gradientShade(from: SurfaceToken, to: SurfaceToken, position: number, theme: EffectiveTheme): string {
  const clamped = Math.min(1, Math.max(0, position));
  const step = Math.round(clamped * (FORMATTING_GRADIENT_STEPS - 1)) / (FORMATTING_GRADIENT_STEPS - 1);
  const tints = formattingTokenHex(theme);
  const a = channels(tints[from]);
  const b = channels(tints[to]);
  const mixed = a.map((channel, i) => Math.round(channel * (1 - step) + b[i] * step));
  return `#${mixed.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}

/**
 * The colour family an Athena type is tinted with.
 *
 * Six type families are folded into five colours because the palette has five that stay
 * legible on every surface a cell can have (see `FORMATTING_FOREGROUNDS`) — binary and the
 * structured types share the muted one, which is the pairing that loses least. Strings map
 * to the default text colour: they are the baseline the other families are read against,
 * and tinting everything tints nothing.
 *
 * Colour is never the only carrier of this: the type is written under every column
 * header and shown in the Value panel.
 *
 * @param type - The Glue/Athena type, in any case.
 * @returns The token to paint values of that type in.
 */
export function typeColour(type: string): ColourToken {
  const base = type.toLowerCase().trim();
  if (/^(tinyint|smallint|int|integer|bigint|float|double|real|decimal|numeric)/.test(base)) return 'accent-text';
  if (/^(date|time|timestamp|interval)/.test(base)) return 'success';
  if (/^bool/.test(base)) return 'danger';
  if (/^(array|map|struct|row|json|varbinary|binary)/.test(base)) return 'text-2';
  return 'text';
}

const LIKE_META_RE = /[.*+?^${}()|[\]\\]/g;

/**
 * A SQL `LIKE` pattern as a regular expression.
 *
 * `%` and `_` are the two wildcards; everything else — including every regex metacharacter
 * — is matched literally, which is what the escape below is for. Anchored at both ends,
 * because `LIKE` matches the whole value where `REGEX` searches within it.
 *
 * There is no escape character: `LIKE 'a\%b'` matches a literal backslash here rather than
 * a literal percent. Athena's own `ESCAPE` clause is not offered, and a rule is a browser
 * filter over a loaded page rather than a predicate anything is billed for.
 *
 * @param pattern - The user's pattern.
 * @param caseInsensitive - True for `ILIKE`.
 * @returns The compiled expression.
 */
function likeExpression(pattern: string, caseInsensitive: boolean): RegExp {
  // Runs of `%` COLLAPSE TO ONE. `%%` means exactly what `%` means, but translated one for
  // one it becomes two nested unbounded quantifiers — and three or four of them, which a
  // user types without a second thought, backtrack catastrophically: `%%%%%%%%x` against a
  // 60-character value measured at 32 SECONDS, inside a `useMemo` that runs per cell. The
  // pattern-length cap bounds the input, not the runtime; this removes the pathology
  // instead of bounding it.
  const body = pattern
    .replace(/%+/g, '%')
    .split('')
    .map((character) => {
      if (character === '%') return '[\\s\\S]*';
      if (character === '_') return '[\\s\\S]';
      return character.replace(LIKE_META_RE, '\\$&');
    })
    .join('');
  // The pattern IS the feature: the rule offers LIKE/ILIKE/REGEX over the user's own loaded
  // rows. Every metacharacter above is escaped, so the only expression this can build is
  // the one the wildcards describe; `FORMATTING_PATTERN_MAX` bounds its size.
  // eslint-disable-next-line security/detect-non-literal-regexp
  return new RegExp(`^${body}$`, caseInsensitive ? 'i' : '');
}

/**
 * Why a rule cannot be applied, or null when it can.
 *
 * Called at ENTRY by the rules dialog, and again here before evaluation — an invalid
 * pattern must never be applied, and a rule that reached storage from an older build
 * or a hand-edited document has not been through the dialog. Every message is user text:
 * the engine's own `SyntaxError` names character offsets in a pattern the user is still
 * writing, which the error-wording rule forbids showing.
 *
 * @param rule - The rule to check.
 * @returns The refusal, or null.
 */
export function ruleRefusal(rule: ColourRule): string | null {
  if (rule.gradient) {
    if (!rule.column) return GRADIENT_COLUMN_REFUSAL;
    const {min, max} = rule.gradient;
    if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return GRADIENT_RANGE_REFUSAL;
  } else if (colourOperatorTakesValue(rule.operator)) {
    // Skipped WHOLE for an operator that reads no value: the two presence tests ignore
    // whatever the field last held, and a rule refused for the length of a string it does
    // not look at is a rule that vanishes for a reason nothing on screen can explain.
    if (rule.value.length > FORMATTING_PATTERN_MAX) return PATTERN_TOO_LONG_REFUSAL;
    if (rule.operator === 'regex') {
      try {
        // A user-authored pattern over their own loaded rows is what asks for.
        // Compiled here so an invalid one is refused at the input rather than thrown from
        // a render.
        // eslint-disable-next-line security/detect-non-literal-regexp
        new RegExp(rule.value);
      } catch {
        return PATTERN_REFUSAL;
      }
    }
  }
  if (!rule.foreground && !rule.background && !rule.gradient) return NO_COLOUR_REFUSAL;
  return null;
}

/**
 * Whether a rule can still be evaluated against the columns in front of it.
 *
 * A grouping change replaces the column set wholesale, so a rule naming a column that is
 * no longer there is the ordinary case rather than a fault. It is kept and shown as
 * inapplicable rather than deleted — dropping it would silently discard work the moment a
 * user grouped, and un-grouping brings the column back.
 *
 * @param rule - The rule to place.
 * @param columns - The names the current result actually has.
 * @returns True when the rule has something to test.
 */
export function isRuleApplicable(rule: ColourRule, columns: string[]): boolean {
  return rule.column === undefined || columns.includes(rule.column);
}

/** How a rule's condition is tested, compiled once per page rather than once per cell. */
type Compiled = {rule: ColourRule; matches: (value: string | null) => boolean};

function matchesPattern(target: string, ignoreCase: boolean): Compiled['matches'] {
  const expression = likeExpression(target, ignoreCase);
  return (value) => value !== null && expression.test(value);
}

function matchesRegex(target: string): Compiled['matches'] {
  let expression: RegExp;
  try {
    // See `ruleRefusal`, which has already refused anything that does not compile.
    // eslint-disable-next-line security/detect-non-literal-regexp
    expression = new RegExp(target);
  } catch {
    return () => false;
  }
  return (value) => value !== null && expression.test(value);
}

// Ordering comparisons read as numbers when BOTH sides are plainly numeric and as text
// otherwise, using the renderer's own numeric predicate rather than a second one — a
// panel that disagreed with the filter about which values are numbers would order a
// column one way and colour it another. Text comparison is by code unit: deterministic,
// and the same order the Text view already prints.
function ordering(target: string, decide: (left: string | number, right: string | number) => boolean) {
  const numericTarget = isBareNumeric(target) ? Number(target) : null;
  return (value: string | null) => {
    if (value === null) return false;
    const numeric = numericTarget !== null && isBareNumeric(value);
    return decide(numeric ? Number(value) : value, numeric ? numericTarget : target);
  };
}

/**
 * One predicate builder per colour operator, exhaustive over the union by TYPE.
 *
 * It was a chain of `if`s ending in a `default` that treated anything unrecognised as
 * `<=`, so an operator added to the union and missed here coloured cells by a comparison
 * nobody asked for, silently and with nothing to fail.
 */
const COMPILE_RULE: Record<ColourOperator, (target: string) => Compiled['matches']> = {
  '=': (target) => (value) => value !== null && value === target,
  '<>': (target) => (value) => value !== null && value !== target,
  '>': (target) => ordering(target, (left, right) => left > right),
  '>=': (target) => ordering(target, (left, right) => left >= right),
  '<': (target) => ordering(target, (left, right) => left < right),
  '<=': (target) => ordering(target, (left, right) => left <= right),
  like: (target) => matchesPattern(target, false),
  ilike: (target) => matchesPattern(target, true),
  regex: (target) => matchesRegex(target),
  // The ONE operator that matches a NULL cell, and the only reason the paragraph above
  // has an exception: finding absent values is the whole job it was added for. A table
  // built from CSV files holds a blank field as `''` rather than NULL, so both spellings
  // of "nothing here" have to match or the rule finds half the empty cells.
  isEmpty: () => (value) => value === null || value === '',
  isNotEmpty: () => (value) => value !== null && value !== ''
};

/**
 * A rule's condition as a predicate over a raw cell value.
 *
 * **A NULL cell matches nothing except `is empty`**, including under `<>`. Athena hands
 * every value back as a string and NULL is the one thing that is not one, so "is not equal
 * to `x`" over an absent value is a question about a value that was never there — the
 * honest answer is to leave it unstyled rather than to paint every empty cell in the
 * column. `is empty` is the exception because it asks that question directly.
 *
 * @param rule - The rule to compile.
 * @returns The predicate.
 */
function compile(rule: ColourRule): Compiled['matches'] {
  return COMPILE_RULE[rule.operator](rule.value);
}

/**
 * Band indexes for the page: consecutive rows equal in every striping column share one.
 *
 * Computed over the CURRENT PAGE and only ever claimed about it — a band
 * touching the first or last row of the page may well continue beyond it, and nothing here
 * can know. The surface says so.
 *
 * @param rows - The loaded page's rows, in the execution's column order.
 * @param columns - The current columns, for resolving names to row positions.
 * @param stripeColumns - The chosen columns; empty turns striping off.
 * @returns One band index per row, or -1 per row when striping is off.
 */
export function bandsOf(
  rows: (string | null)[][],
  columns: FormattingColumn[],
  stripeColumns: string[]
): {bands: number[]; bandStarts: boolean[]} {
  const positions = stripeColumns
    .map((name) => columns.find((column) => column.name === name)?.index)
    .filter((index): index is number => index !== undefined);
  // No chosen columns — or none of them present — is striping OFF, never every-other-row:
  // an alternating tint that means nothing is a pattern people read meaning into.
  if (positions.length === 0) return {bands: rows.map(() => -1), bandStarts: rows.map(() => false)};

  const bands: number[] = [];
  const bandStarts: boolean[] = [];
  let band = -1;
  let previous: string | null = null;
  for (const row of rows) {
    // JSON rather than a join, so no two different rows can be made to share a key: a
    // separator can appear inside a value, and any placeholder chosen for NULL is a string
    // some cell somewhere actually holds.
    const key = JSON.stringify(positions.map((index) => row[index] ?? null));
    const starts = key !== previous;
    if (starts) band += 1;
    bands.push(band);
    bandStarts.push(starts);
    previous = key;
  }
  return {bands, bandStarts};
}

/**
 * Every cell's resolved colours for one page.
 *
 * Precedence runs weakest to strongest — the type tint, then the band, then the rules in
 * their own order — and each layer overrides only the PROPERTY it sets, so a rule that
 * chooses a background leaves a type tint's foreground alone. That is what "a later
 * matching rule overrides an earlier one on the same property" means, and it is also what
 * makes "conditional rules win" true without a special case.
 *
 * A rule whose `scope` is `'row'` paints every cell of a row in which its condition held
 * anywhere; a `'cell'` rule paints only the cells that matched. A rule with no `column`
 * tests every cell in the row.
 *
 * @param formatting - The tab's formatting state.
 * @param columns - The visible columns, carrying their row-array index and type.
 * @param rows - The loaded page's rows, in the execution's column order.
 * @param theme - The theme being painted; only a gradient's mixed shade needs it, every
 *   other colour here is a CSS variable that resolves itself.
 * @returns Bands and per-cell colours for the page.
 */
export function computePageFormatting(
  formatting: FormattingState,
  columns: FormattingColumn[],
  rows: (string | null)[][],
  theme: EffectiveTheme
): PageFormatting {
  const {bands, bandStarts} = bandsOf(rows, columns, formatting.stripeColumns);

  // An unusable rule is skipped rather than applied loosely. `ruleRefusal` has
  // already run at the input; this is the second gate, for a rule restored from a document
  // that never went through it.
  const names = columns.map((column) => column.name);
  const applicable = formatting.rules
    .filter((rule) => ruleRefusal(rule) === null && isRuleApplicable(rule, names))
    .map((rule): Compiled => ({rule, matches: compile(rule)}));

  const formats = rows.map((row, rowIndex): Record<string, CellFormat> => {
    const cells: Record<string, CellFormat> = {};
    // `defineProperty` rather than assignment: a column named `__proto__` would otherwise
    // invoke the inherited setter and set this object's PROTOTYPE instead of adding a key,
    // silently dropping every format for that column. Column names come from Athena and
    // are not catalog-safe.
    const set = (column: string, format: CellFormat) => {
      define(cells, column, {...cells[column], ...format});
    };

    if (formatting.colourByType) {
      for (const column of columns) set(column.name, {color: colourValue(typeColour(column.type))});
    }
    if (bands[rowIndex] >= 0 && bands[rowIndex] % 2 === 1) {
      for (const column of columns) set(column.name, {backgroundColor: STRIPE_BACKGROUND});
    }

    for (const {rule, matches} of applicable) {
      const tested = rule.column ? columns.filter((column) => column.name === rule.column) : columns;

      if (rule.gradient) {
        // A gradient is measured on ONE column (its refusal says so), and paints either
        // that cell or the row. A non-numeric or NULL value is left alone rather than
        // clamped to an end of the scale — a clamp would paint text the colour of
        // the minimum, which reads as a measurement of something that was never measured.
        const value = tested.length === 1 ? row[tested[0].index] : undefined;
        if (value === undefined || value === null || !isBareNumeric(value)) continue;
        const {min, max, from, to} = rule.gradient;
        const shade = gradientShade(from, to, (Number(value) - min) / (max - min), theme);
        const painted = rule.scope === 'row' ? columns : tested;
        for (const column of painted) {
          set(column.name, {backgroundColor: shade, ...(rule.foreground ? {color: colourValue(rule.foreground)} : {})});
        }
        continue;
      }

      const matched = tested.filter((column) => matches(row[column.index] ?? null));
      if (matched.length === 0) continue;
      const painted = rule.scope === 'row' ? columns : matched;
      const format: CellFormat = {
        ...(rule.foreground ? {color: colourValue(rule.foreground)} : {}),
        ...(rule.background ? {backgroundColor: colourValue(rule.background)} : {})
      };
      for (const column of painted) set(column.name, format);
    }

    return cells;
  });

  // Skipped entirely for the ordinary case of no transformers, rather than calling a
  // no-op over every cell of every page.
  const anyTransformer = Object.keys(formatting.transformers).length > 0;
  const transformed = rows.map((row): Record<string, TransformedValue> => {
    const cells: Record<string, TransformedValue> = {};
    if (!anyTransformer) return cells;
    for (const column of columns) {
      const rendering = transformCell(row[column.index] ?? null, formatting.transformers[column.name]);
      if (rendering) define(cells, column.name, rendering);
    }
    return cells;
  });

  return {bands, bandStarts, formats, transformed};
}

// ---------------------------------------------------------------------------------------
// Transformers
// ---------------------------------------------------------------------------------------

const HEX_DIGITS = '0123456789abcdef';

/** The value's UTF-8 bytes as lowercase hex. */
function toHex(bytes: Uint8Array): string {
  let out = '';
  for (const byte of bytes) out += HEX_DIGITS[byte >> 4] + HEX_DIGITS[byte & 15];
  return out;
}

/**
 * The value's UTF-8 bytes as base64.
 *
 * Chunked because `String.fromCharCode(...bytes)` spreads one argument per byte, and a
 * long cell is enough arguments to overflow the call stack.
 */
function toBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let at = 0; at < bytes.length; at += 4096) {
    binary += String.fromCharCode(...bytes.subarray(at, at + 4096));
  }
  return btoa(binary);
}

/**
 * How one cell is rendered under a transformer, or null where it is rendered as itself.
 *
 * **A transformer changes only the rendering** Nothing calls this on the way
 * into a filter, a colour rule, a Calc selection or a copy — those all read the raw row,
 * and a transformed value reaching any of them would be a silent wrong answer rather than
 * a visible one.
 *
 * NULL and the empty string are returned untransformed: both are absences the grid already
 * names in words, and a base64 rendering of nothing is a cell that says something is there.
 *
 * @param value - The raw cell value.
 * @param transformer - The column's transformer, if it has one.
 * @returns The rendering, or null to render the value as it is.
 */
export function transformCell(value: string | null, transformer: Transformer | undefined): TransformedValue | null {
  if (!transformer || value === null || value === '') return null;

  if (transformer.kind === 'numeric') {
    if (!isBareNumeric(value)) {
      // Lenient shows the value itself; strict shows a marker. Neither shows a blank —
      // the cell HAS a value, and erasing it would be indistinguishable from an empty
      // column.
      return {text: transformer.lenient ? value : NUMERIC_TRANSFORMER_ERROR};
    }
    return {text: Number(value).toFixed(transformer.precision)};
  }

  if (transformer.kind === 'binary') {
    const bytes = new TextEncoder().encode(value);
    const encoded = transformer.encoding === 'hex' ? toHex(bytes) : toBase64(bytes);
    // The cap is on the RENDERING, and a cut one says so: silently showing the first 64
    // characters of a hash is how two different values come to look identical.
    return {
      text:
        encoded.length > transformer.maxLength
          ? encoded.slice(0, transformer.maxLength) + TRUNCATION_INDICATOR
          : encoded
    };
  }

  // The link text stays the RAW value: a row of identical URLs is unreadable, and the
  // value is what the user recognises. `resolveUrl` owns the scheme allowlist.
  const resolved = resolveUrl(transformer.template, value);
  return {text: value, href: resolved.href, reason: resolved.reason};
}
