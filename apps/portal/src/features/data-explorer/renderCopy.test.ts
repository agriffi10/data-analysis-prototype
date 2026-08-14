import {describe, expect, it} from 'vitest';
import {formatUsesQuoting, renderCopy} from './renderCopy';
import {PLAIN_COPY_OPTIONS} from './dataExplorer.constants';
import type {CellSelection, CopyFormat, CopyOptions} from './dataExplorer.types';
import type {GridColumn} from './useColumnGeometry';

// SPEC-185 FR-001. The renderer is asserted directly rather than through a clipboard: the
// rules worth pinning are what a NULL looks like in six formats and what a gap in a
// selection looks like, and neither is visible through `navigator.clipboard` in jsdom.

const COLUMNS: GridColumn[] = [
  {name: 'region', type: 'varchar', index: 0, width: 100, pinned: false, hidden: false},
  {name: 'qty', type: 'bigint', index: 1, width: 100, pinned: false, hidden: false},
  {name: 'note', type: 'varchar', index: 2, width: 100, pinned: false, hidden: false}
];

// Row 1 carries the pair the whole of AC4 is about: a NULL beside an empty string.
const ROWS: (string | null)[][] = [
  ['north', '10', 'ok'],
  ['south', null, ''],
  ['east', '30', 'a,b']
];

const options = (overrides: Partial<CopyOptions> = {}): CopyOptions => ({...PLAIN_COPY_OPTIONS, ...overrides});

/** One rectangle, from (row, column name) to (row, column name). */
const rect = (fromRow: number, fromColumn: string, toRow: number, toColumn: string): CellSelection => ({
  cursor: {row: fromRow, column: fromColumn},
  ranges: [{from: {row: fromRow, column: fromColumn}, to: {row: toRow, column: toColumn}}]
});

describe('renderCopy — the plain copy (FR-001 AC1)', () => {
  it('copies a rectangle as tab-delimited text, rows in grid order', () => {
    const text = renderCopy(rect(0, 'region', 1, 'qty'), COLUMNS, ROWS, options());
    expect(text).toBe('north\t10\nsouth\tNULL');
  });

  it('takes the DISPLAY order, not the execution order', () => {
    // The grid can reorder columns; every cell is read through `column.index`, so a
    // reordered display copies as displayed rather than as Athena returned it.
    const reordered = [COLUMNS[1], COLUMNS[0]];
    const text = renderCopy(rect(0, 'qty', 0, 'region'), reordered, ROWS, options());
    expect(text).toBe('10\tnorth');
  });

  it('is empty when nothing is selected', () => {
    expect(renderCopy({cursor: {row: 0, column: 'region'}, ranges: []}, COLUMNS, ROWS, options())).toBe('');
  });
});

describe('renderCopy — a discontiguous selection (FR-001 AC5)', () => {
  it('copies the bounding rectangle with the unselected cells blank', () => {
    const selection: CellSelection = {
      cursor: {row: 0, column: 'region'},
      ranges: [
        {from: {row: 0, column: 'region'}, to: {row: 0, column: 'region'}},
        {from: {row: 2, column: 'note'}, to: {row: 2, column: 'note'}}
      ]
    };
    // Three rows by three columns, with exactly two cells filled — the corners.
    expect(renderCopy(selection, COLUMNS, ROWS, options())).toBe('north\t\t\n\t\t\n\t\ta,b');
  });

  it('drops a range lying entirely off the loaded page rather than padding the copy', () => {
    // Reachable only mid-transition (the selection resets on a page or column-set change),
    // but the wrong answer is a copy with blank rows nobody selected — the rectangle must
    // not stretch to meet coordinates that contribute no cells.
    const selection: CellSelection = {
      cursor: {row: 0, column: 'region'},
      ranges: [
        {from: {row: 0, column: 'region'}, to: {row: 0, column: 'region'}},
        {from: {row: 7, column: 'note'}, to: {row: 9, column: 'note'}}
      ]
    };
    // Not `north\t\t` — a range that contributes no cells widens neither axis, so the copy
    // is the one cell that was actually selected.
    expect(renderCopy(selection, COLUMNS, ROWS, options())).toBe('north');
  });

  it('counts a cell once when two ranges overlap', () => {
    const selection: CellSelection = {
      cursor: {row: 0, column: 'region'},
      ranges: [
        {from: {row: 0, column: 'region'}, to: {row: 1, column: 'qty'}},
        {from: {row: 1, column: 'qty'}, to: {row: 1, column: 'qty'}}
      ]
    };
    expect(renderCopy(selection, COLUMNS, ROWS, options())).toBe('north\t10\nsouth\tNULL');
  });
});

describe('renderCopy — NULL and the empty string are distinguishable (FR-001 AC4)', () => {
  // The pair, in one selection, in every format. Row 1 is `south`, NULL, `''`.
  const nullAndEmpty = rect(1, 'region', 1, 'note');

  it.each<[CopyFormat, (text: string) => void]>([
    [
      'tsv',
      (text) => {
        // NULL is the token; the empty string is nothing at all.
        expect(text).toBe('south\tNULL\t');
      }
    ],
    ['csv', (text) => expect(text).toBe('south,NULL,')],
    [
      'json',
      (text) => {
        expect(JSON.parse(text)).toEqual([['south', null, '']]);
      }
    ],
    ['markdown', (text) => expect(text).toContain('| south | NULL |  |')],
    ['sql', (text) => expect(text).toContain("('south', NULL, '')")],
    [
      'xml',
      (text) => {
        expect(text).toContain('<cell null="true" />');
        expect(text).toContain('<cell></cell>');
      }
    ]
  ])('%s', (format, assertion) => {
    assertion(renderCopy(nullAndEmpty, COLUMNS, ROWS, options({format})));
  });

  it('quoting is what separates a NULL from the text “NULL”', () => {
    const rows: (string | null)[][] = [[null, 'NULL', 'x']];
    const plain = renderCopy(rect(0, 'region', 0, 'qty'), COLUMNS, rows, options());
    // Unquoted, the two are the same four characters — the honest limit of a delimited
    // format, and why the dialog offers quoting and says what it is for.
    expect(plain).toBe('NULL\tNULL');
    const quoted = renderCopy(rect(0, 'region', 0, 'qty'), COLUMNS, rows, options({quoteValues: true}));
    expect(quoted).toBe('NULL\t"NULL"');
  });
});

describe('renderCopy — the options', () => {
  it('includes column names, in display order', () => {
    const text = renderCopy(rect(0, 'region', 0, 'qty'), COLUMNS, ROWS, options({includeHeaders: true}));
    expect(text).toBe('region\tqty\nnorth\t10');
  });

  it('includes the grid’s own absolute row numbers, which are the PAGE’s', () => {
    // `rangeStart` 101 is page five of a 25-row pager: the numbers copied are the ones the
    // grid's row header shows, not 1..n within the selection.
    const text = renderCopy(rect(0, 'region', 1, 'region'), COLUMNS, ROWS, options({includeRowNumbers: true}), 101);
    expect(text).toBe('101\tnorth\n102\tsouth');
  });

  it('quotes every value when asked, doubling an embedded quote', () => {
    const rows: (string | null)[][] = [['a"b', '1', '']];
    const text = renderCopy(rect(0, 'region', 0, 'qty'), COLUMNS, rows, options({quoteValues: true}));
    expect(text).toBe('"a""b"\t"1"');
  });

  it('CSV still quotes what the FORMAT requires, whatever the option says', () => {
    // `a,b` unquoted is not ambiguous CSV — it is different CSV, with an extra column.
    const text = renderCopy(rect(2, 'note', 2, 'note'), COLUMNS, ROWS, options({format: 'csv'}));
    expect(text).toBe('"a,b"');
  });

  it('reports which formats quoting applies to', () => {
    expect(['tsv', 'csv', 'markdown'].every((f) => formatUsesQuoting(f as CopyFormat))).toBe(true);
    expect(['json', 'sql', 'xml'].some((f) => formatUsesQuoting(f as CopyFormat))).toBe(false);
  });
});

describe('renderCopy — the structured formats', () => {
  it('JSON without headers is arrays, with headers is objects', () => {
    const selection = rect(0, 'region', 0, 'qty');
    expect(JSON.parse(renderCopy(selection, COLUMNS, ROWS, options({format: 'json'})))).toEqual([['north', '10']]);
    expect(JSON.parse(renderCopy(selection, COLUMNS, ROWS, options({format: 'json', includeHeaders: true})))).toEqual([
      {region: 'north', qty: '10'}
    ]);
  });

  it('a Markdown header row with column names off is EMPTY, row numbers included', () => {
    // The row-number column follows `includeHeaders` like every other format's does — the
    // delimited formats emit no header line at all here, and leaking a `#` into a header the
    // user turned off would label the one column they did not ask to have labelled.
    const text = renderCopy(
      rect(0, 'region', 0, 'qty'),
      COLUMNS,
      ROWS,
      options({format: 'markdown', includeRowNumbers: true})
    );
    expect(text.split('\n')[0]).toBe('|  |  |  |');
  });

  it('a Markdown table keeps its header row even with column names off', () => {
    // A table without a header row is not a table in any Markdown dialect — it renders as
    // a paragraph of pipes. So the row stays and its cells go empty.
    const text = renderCopy(rect(0, 'region', 0, 'qty'), COLUMNS, ROWS, options({format: 'markdown'}));
    expect(text.split('\n')[0]).toBe('|  |  |');
    expect(text.split('\n')[1]).toBe('| --- | --- |');
  });

  it('escapes a pipe inside a Markdown cell', () => {
    const rows: (string | null)[][] = [['a|b', '1', '']];
    expect(renderCopy(rect(0, 'region', 0, 'region'), COLUMNS, rows, options({format: 'markdown'}))).toContain('a\\|b');
  });

  it('a SQL INSERT names a PLACEHOLDER table, never the source', () => {
    // These rows are what a filter, an ordering and possibly a GROUP BY produced, so an
    // INSERT naming the source table would be valid, runnable and wrong.
    const text = renderCopy(rect(0, 'region', 0, 'qty'), COLUMNS, ROWS, options({format: 'sql', includeHeaders: true}));
    expect(text).toBe('INSERT INTO "results" ("region", "qty") VALUES\n  (\'north\', \'10\');');
  });

  it('a SQL INSERT escapes a quote the TRINO way — doubled, never backslashed', () => {
    // The DDL escaper (`cpcommon.ddl.literal`) backslashes it, and the wrong one here does
    // not fail loudly: it produces a statement that runs and matches nothing.
    const rows: (string | null)[][] = [["O'Brien", '1', '']];
    const text = renderCopy(rect(0, 'region', 0, 'region'), COLUMNS, rows, options({format: 'sql'}));
    expect(text).toContain("('O''Brien')");
    expect(text).not.toContain("\\'");
  });

  it('XML puts the column name in an ATTRIBUTE and escapes the five reserved characters', () => {
    // A column name is not required to be a valid XML NAME — `2024_total` is a legal Athena
    // column and an illegal element name — so deriving element names from it produces
    // documents that do not parse.
    const rows: (string | null)[][] = [['a<b&c', '1', '']];
    const columns: GridColumn[] = [{...COLUMNS[0], name: '2024 total'}];
    const text = renderCopy(
      rect(0, '2024 total', 0, '2024 total'),
      columns,
      rows,
      options({format: 'xml', includeHeaders: true})
    );
    expect(text).toContain('<cell name="2024 total">a&lt;b&amp;c</cell>');
  });

  it('a hole and an empty string are the SAME element in XML, and only NULL is marked', () => {
    // The self-closing tag is not a distinction: `<cell/>` and `<cell></cell>` parse
    // identically, so this asserts what a CONSUMER can actually observe — the NULL marker —
    // rather than a serialization difference nothing downstream can read. FR-001 AC4 asks
    // that NULL and the empty string be distinguishable, and that is what holds.
    const selection: CellSelection = {
      cursor: {row: 1, column: 'region'},
      ranges: [
        {from: {row: 1, column: 'region'}, to: {row: 1, column: 'region'}},
        {from: {row: 1, column: 'note'}, to: {row: 1, column: 'note'}}
      ]
    };
    const parsed = new DOMParser().parseFromString(
      renderCopy(selection, COLUMNS, ROWS, options({format: 'xml'})),
      'application/xml'
    );
    const cells = [...parsed.querySelectorAll('cell')];
    // The hole (`qty`, unselected) and the empty string (`note`) — indistinguishable.
    expect(cells[1].getAttribute('null')).toBeNull();
    expect(cells[2].getAttribute('null')).toBeNull();
    expect(cells[1].textContent).toBe(cells[2].textContent);
  });

  it('a NULL is marked in XML where an empty string is not', () => {
    const parsed = new DOMParser().parseFromString(
      renderCopy(rect(1, 'qty', 1, 'note'), COLUMNS, ROWS, options({format: 'xml'})),
      'application/xml'
    );
    const cells = [...parsed.querySelectorAll('cell')];
    expect(cells[0].getAttribute('null')).toBe('true');
    expect(cells[1].getAttribute('null')).toBeNull();
  });

  it('an unselected cell inside the rectangle is an ABSENT cell in XML', () => {
    const selection: CellSelection = {
      cursor: {row: 0, column: 'region'},
      ranges: [
        {from: {row: 0, column: 'region'}, to: {row: 0, column: 'region'}},
        {from: {row: 0, column: 'note'}, to: {row: 0, column: 'note'}}
      ]
    };
    const text = renderCopy(selection, COLUMNS, ROWS, options({format: 'xml'}));
    expect(text).toContain('<cell />');
  });
});
