import {COPY_NULL_TOKEN, COPY_SQL_TABLE, COPY_XML_NULL_ATTRIBUTE, ROW_NUMBER_HEADER} from './dataExplorer.constants';
import {sqlIdentifier, sqlLiteral} from '../../lib/sql';
import type {CellRange, CellSelection, CopyFormat, CopyOptions} from './dataExplorer.types';
import type {GridColumn} from './useColumnGeometry';

// Turning a selection into text, and nothing else — no clipboard, no React,
// no query. Copy is the one way out of this feature that costs nothing, and it stays that way
// because everything here reads rows that are already on screen.
//
// **The values are RAW.** Not `cellText`, which renders a NULL as the word NULL for a human
// to read, and not `transformCell`, which can turn a value into an anchor's label
// — a URL-transformed column pasted into a spreadsheet has to carry the underlying value or
// the paste is of the presentation rather than of the data. The two are formatted here, per
// format, and the formatting is the part worth asserting directly.

/**
 * The bounding rectangle of a selection, or null when nothing is selected.
 *
 * FR-001 AC5: a discontiguous selection copies as its BOUNDING RECTANGLE with the
 * unselected cells inside it blank. The alternative — packing the selected cells together —
 * silently moves values into columns they were never in, which is worse than a hole in a
 * paste the user can see. The surfaces say so out loud rather than leaving it to be found.
 *
 * @param ranges - The selection's inclusive rectangles, in selection order.
 * @param positionOf - Each column's display position, by name.
 * @param rowCount - Rows on the loaded page; the row bound is clamped to it.
 * @returns The inclusive rectangle, or null when no range names a column that still exists.
 */
function boundingRectangle(
  ranges: CellRange[],
  positionOf: Map<string, number>,
  rowCount: number
): {firstRow: number; lastRow: number; firstColumn: number; lastColumn: number} | null {
  let firstRow = Infinity;
  let lastRow = -Infinity;
  let firstColumn = Infinity;
  let lastColumn = -Infinity;

  for (const range of ranges) {
    const from = positionOf.get(range.from.column);
    const to = positionOf.get(range.to.column);
    // A range naming a column the result no longer has is skipped rather than guessed at,
    // exactly as `selectedCellValues` skips it: the selection resets on a column-set change,
    // so this is reachable only mid-transition.
    if (from === undefined || to === undefined) continue;
    const top = Math.max(Math.min(range.from.row, range.to.row), 0);
    const bottom = Math.min(Math.max(range.from.row, range.to.row), rowCount - 1);
    // A range lying entirely off the loaded page contributes NOTHING rather than stretching
    // the rectangle to meet it: `selectedCells` already fills none of those rows, so keeping
    // it would pad the copy with blank rows nobody selected.
    if (top > bottom) continue;
    firstRow = Math.min(firstRow, top);
    lastRow = Math.max(lastRow, bottom);
    firstColumn = Math.min(firstColumn, Math.min(from, to));
    lastColumn = Math.max(lastColumn, Math.max(from, to));
  }

  if (firstRow > lastRow || firstColumn > lastColumn) return null;
  return {firstRow, lastRow, firstColumn, lastColumn};
}

/** Every selected coordinate, so a cell inside the rectangle but outside the selection is blank. */
function selectedCells(ranges: CellRange[], positionOf: Map<string, number>, rowCount: number): Set<string> {
  const selected = new Set<string>();
  for (const range of ranges) {
    const from = positionOf.get(range.from.column);
    const to = positionOf.get(range.to.column);
    if (from === undefined || to === undefined) continue;
    const firstRow = Math.max(Math.min(range.from.row, range.to.row), 0);
    const lastRow = Math.min(Math.max(range.from.row, range.to.row), rowCount - 1);
    for (let row = firstRow; row <= lastRow; row += 1) {
      for (let position = Math.min(from, to); position <= Math.max(from, to); position += 1) {
        selected.add(`${row}:${position}`);
      }
    }
  }
  return selected;
}

/**
 * The block a selection copies: its columns, and its rows as raw values.
 *
 * `undefined` is what an unselected cell inside the rectangle carries — a third state beside
 * the string and the NULL, and the only reason a hole can render as blank in a format where
 * a NULL renders as something.
 */
type CopyBlock = {
  columns: GridColumn[];
  /** Absolute row numbers, as the grid's row header shows them. Empty unless asked for. */
  rowNumbers: number[];
  rows: (string | null | undefined)[][];
};

/**
 * The selection, resolved against the rows on screen.
 *
 * @param selection - The grid's selection.
 * @param columns - The VISIBLE columns in display order; a hidden column is not on screen and
 *   is not copied.
 * @param rows - The loaded page's rows, in the execution's column order.
 * @param rangeStart - The 1-based row number of the first row on the page.
 * @returns The block, or null when nothing is selected.
 */
function blockOf(
  selection: CellSelection,
  columns: GridColumn[],
  rows: (string | null)[][],
  rangeStart: number
): CopyBlock | null {
  const positionOf = new Map(columns.map((column, position) => [column.name, position]));
  const rectangle = boundingRectangle(selection.ranges, positionOf, rows.length);
  if (!rectangle) return null;
  const selected = selectedCells(selection.ranges, positionOf, rows.length);

  const blockColumns = columns.slice(rectangle.firstColumn, rectangle.lastColumn + 1);
  const rowNumbers: number[] = [];
  const blockRows: (string | null | undefined)[][] = [];
  for (let row = rectangle.firstRow; row <= rectangle.lastRow; row += 1) {
    rowNumbers.push(rangeStart + row);
    blockRows.push(
      blockColumns.map((column, offset) =>
        selected.has(`${row}:${rectangle.firstColumn + offset}`) ? (rows[row][column.index] ?? null) : undefined
      )
    );
  }
  return {columns: blockColumns, rowNumbers, rows: blockRows};
}

/** Doubles the quote and wraps, the one escaping every text format here shares. */
function quoted(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

/**
 * A value as delimited text.
 *
 * **This is where FR-001 AC4 is paid for in the formats that have no native null.** A NULL
 * becomes the token, an empty string becomes nothing, and a hole becomes nothing — so NULL
 * and `''` are always distinguishable, while a value whose TEXT is literally `NULL` is
 * distinguishable only once `quoteValues` is on. That is the honest limit of a delimited
 * format, and the dialog says it rather than leaving the user to find it in a spreadsheet.
 */
function delimitedValue(value: string | null | undefined, options: CopyOptions, delimiter: string): string {
  if (value === undefined) return '';
  if (value === null) return COPY_NULL_TOKEN;
  if (options.quoteValues) return quoted(value);
  // CSV still quotes what the format REQUIRES quoting, whatever the option says: an
  // unescaped comma or newline does not produce ambiguous CSV, it produces different CSV.
  if (delimiter === ',' && /[",\r\n]/.test(value)) return quoted(value);
  // A tab or a newline inside a TSV value breaks the row apart the same way, and the
  // convention there is to quote it too rather than to strip it.
  if (delimiter === '\t' && /["\t\r\n]/.test(value)) return quoted(value);
  return value;
}

function delimited(block: CopyBlock, options: CopyOptions, delimiter: string): string {
  const lines: string[] = [];
  const headers = block.columns.map((column) => column.name);
  if (options.includeHeaders) {
    lines.push([...(options.includeRowNumbers ? [ROW_NUMBER_HEADER] : []), ...headers].join(delimiter));
  }
  block.rows.forEach((row, index) => {
    const cells = row.map((value) => delimitedValue(value, options, delimiter));
    lines.push([...(options.includeRowNumbers ? [String(block.rowNumbers[index])] : []), ...cells].join(delimiter));
  });
  return lines.join('\n');
}

/**
 * JSON, where NULL and the empty string need no convention — the format has both.
 *
 * Without headers a row is an ARRAY, because an object keyed by position would be an object
 * whose keys mean nothing. `quoteValues` is inert here and the dialog disables it rather
 * than offering a control that does nothing.
 */
function json(block: CopyBlock, options: CopyOptions): string {
  const rows = block.rows.map((row, index) => {
    // A hole is `null` in JSON as well, and that is a genuine ambiguity the delimited
    // formats do not have — so the surfaces say the rectangle is filled with blanks, which
    // is the fact a user needs to read either rendering correctly.
    const values = row.map((value) => (value === undefined ? null : value));
    if (!options.includeHeaders) {
      return options.includeRowNumbers ? [block.rowNumbers[index], ...values] : values;
    }
    const object: Record<string, string | number | null> = options.includeRowNumbers
      ? {[ROW_NUMBER_HEADER]: block.rowNumbers[index]}
      : {};
    block.columns.forEach((column, position) => {
      object[column.name] = values[position];
    });
    return object;
  });
  return JSON.stringify(rows, null, 2);
}

/** Pipes and newlines inside a value would end the cell, so they are escaped rather than dropped. */
function markdownValue(value: string | null | undefined, options: CopyOptions): string {
  if (value === undefined) return '';
  if (value === null) return COPY_NULL_TOKEN;
  const escaped = value.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ');
  return options.quoteValues ? quoted(escaped) : escaped;
}

/**
 * A GitHub-flavoured table.
 *
 * A Markdown table cannot exist without a header row, so `includeHeaders: false` renders an
 * EMPTY header rather than dropping it — the alternative is output that renders as a
 * paragraph of pipes wherever it is pasted. **Empty means empty, the row-number column
 * included**: leaking a `#` into a header the user turned off is the one cell that would then
 * be labelled, and the delimited formats drop it in exactly this case.
 */
function markdown(block: CopyBlock, options: CopyOptions): string {
  const headers = [
    ...(options.includeRowNumbers ? [options.includeHeaders ? ROW_NUMBER_HEADER : ''] : []),
    ...block.columns.map((column) => (options.includeHeaders ? column.name : ''))
  ];
  const lines = [`| ${headers.join(' | ')} |`, `| ${headers.map(() => '---').join(' | ')} |`];
  block.rows.forEach((row, index) => {
    const cells = [
      ...(options.includeRowNumbers ? [String(block.rowNumbers[index])] : []),
      ...row.map((value) => markdownValue(value, options))
    ];
    lines.push(`| ${cells.join(' | ')} |`);
  });
  return lines.join('\n');
}

/**
 * An `INSERT` statement, over a NEUTRAL table name.
 *
 * Deliberately not the exploration's own table: the rows here are what a filter, an ordering
 * and possibly a `GROUP BY` produced, so an INSERT naming the source would be a statement
 * that is syntactically fine and semantically a lie — and one a user could paste and run.
 * `COPY_SQL_TABLE` is a placeholder the user is expected to replace, which is the only
 * honest thing a clipboard format can offer here.
 *
 * Values go through `sqlLiteral` — the TRINO/DML escaper that doubles the quote, never
 * `cpcommon.ddl`'s backslash form (the rule, and the wrong one fails silently). A
 * NULL is the keyword and an empty string is `''`, which is the distinction FR-001 AC4 asks
 * for, native to the format. A hole is NULL too; see `json` above.
 */
function sqlInsert(block: CopyBlock, options: CopyOptions): string {
  const columns = [
    ...(options.includeRowNumbers ? [ROW_NUMBER_HEADER] : []),
    ...block.columns.map((column) => column.name)
  ];
  // `sqlIdentifier`, not a second quoter written out here: the feature already has ONE, and
  // two that agree today are a divergence waiting rather than a duplication that shows.
  const columnList = options.includeHeaders ? ` (${columns.map(sqlIdentifier).join(', ')})` : '';
  const values = block.rows.map((row, index) => {
    const cells = [
      ...(options.includeRowNumbers ? [String(block.rowNumbers[index])] : []),
      ...row.map((value) => (value === undefined || value === null ? 'NULL' : sqlLiteral(value)))
    ];
    return `  (${cells.join(', ')})`;
  });
  return `INSERT INTO ${sqlIdentifier(COPY_SQL_TABLE)}${columnList} VALUES\n${values.join(',\n')};`;
}

/** The five characters that cannot appear raw in XML text. */
function xmlText(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * XML, with the column name as an ATTRIBUTE rather than as an element name.
 *
 * An Athena column name is not required to be a valid XML name — it may start with a digit,
 * and a grouping alias may carry characters no element name admits — so deriving element
 * names from it produces documents that do not parse. The attribute form has no such
 * constraint, and a NULL gets an explicit `null="true"` rather than an empty element,
 * which is what keeps it distinguishable from `''` (FR-001 AC4).
 *
 * **A hole is NOT distinguishable from an empty string here**, and the self-closing tag does
 * not make it one — `<cell/>` and `<cell></cell>` are the same element to every parser, so
 * only the serialization differs. That is the same ambiguity `json` has and it is stated for
 * the same reason: the surfaces say the copy is a rectangle with the gaps blank, which is the
 * fact a reader needs to interpret either rendering.
 */
function xml(block: CopyBlock, options: CopyOptions): string {
  const lines = ['<rows>'];
  block.rows.forEach((row, index) => {
    lines.push(options.includeRowNumbers ? `  <row number="${block.rowNumbers[index]}">` : '  <row>');
    row.forEach((value, position) => {
      const name = options.includeHeaders ? ` name="${xmlText(block.columns[position].name)}"` : '';
      // Blank, exactly as an empty string is — see the note above; nothing here can tell a
      // reader which of the two it was.
      if (value === undefined) lines.push(`    <cell${name} />`);
      else if (value === null) lines.push(`    <cell${name} ${COPY_XML_NULL_ATTRIBUTE}="true" />`);
      else lines.push(`    <cell${name}>${xmlText(value)}</cell>`);
    });
    lines.push('  </row>');
  });
  lines.push('</rows>');
  return lines.join('\n');
}

/** Whether `quoteValues` changes anything in a format — the delimited ones and Markdown. */
export function formatUsesQuoting(format: CopyFormat): boolean {
  return format === 'tsv' || format === 'csv' || format === 'markdown';
}

/**
 * A selection as clipboard text.
 *
 * Pure, and issues nothing: the rows are the page already fetched, so copying — in any
 * format, with any options, however many times — starts no execution and scans no bytes.
 *
 * @param selection - The grid's selection; its bounding rectangle is what gets copied.
 * @param columns - The VISIBLE columns in display order, carrying their row-array index.
 * @param rows - The loaded page's rows, in the execution's column order.
 * @param options - Format and the three toggles.
 * @param rangeStart - 1-based row number of the page's first row, for `includeRowNumbers`.
 * @returns The clipboard text; an empty string when nothing is selected.
 */
export function renderCopy(
  selection: CellSelection,
  columns: GridColumn[],
  rows: (string | null)[][],
  options: CopyOptions,
  rangeStart = 1
): string {
  const block = blockOf(selection, columns, rows, rangeStart);
  if (!block) return '';
  switch (options.format) {
    case 'tsv':
      return delimited(block, options, '\t');
    case 'csv':
      return delimited(block, options, ',');
    case 'json':
      return json(block, options);
    case 'markdown':
      return markdown(block, options);
    case 'sql':
      return sqlInsert(block, options);
    case 'xml':
      return xml(block, options);
  }
}
