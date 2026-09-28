import {describe, expect, it} from 'vitest';
import {
  ATHENA_QUERY_STRING_MAX,
  exceedsAthenaQueryLimit,
  ExplorationRenderError,
  groupingOrderingViolation,
  renderColumnValuesSql,
  renderExplorationSql,
  rendersFromSqlBody
} from './renderExplorationSql';
import {EXPLORER_FILTER_VALUES_MAX} from './dataExplorer.constants';
import {
  FILTER_OPERATORS,
  narrowingFor,
  operatorTakesValue,
  operatorTakesValues,
  operatorUsesValueKind
} from './explorationQueryOps';
import {emptyExplorationQuery, newExploration} from './exploration';
import type {ColumnFilter, ExplorationQuery, ExplorationSource, Grouping} from './dataExplorer.types';

const TABLE: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};
const SQL_SOURCE: ExplorationSource = {kind: 'sql', body: 'SELECT * FROM alice.orders', label: 'Monthly'};

const q = (over: Partial<ExplorationQuery> = {}): ExplorationQuery => ({...emptyExplorationQuery(), ...over});
/** A grouping with SPEC-182's flags off unless a case is about them. */
const g = (over: Partial<Grouping> = {}): Grouping => ({
  columns: [],
  aggregates: [],
  duplicatesOnly: false,
  showPercentage: false,
  ...over
});

describe('renderExplorationSql — the source arms (FR-002)', () => {
  it('renders a table source as a quoted, qualified FROM', () => {
    expect(renderExplorationSql(TABLE, q())).toBe('SELECT *\nFROM "alice"."orders"');
  });

  it('renders a sql source as an aliased subquery, on its own lines', () => {
    expect(renderExplorationSql(SQL_SOURCE, q())).toBe('SELECT *\nFROM (\nSELECT * FROM alice.orders\n) AS t');
  });

  it('survives a body ending in a semicolon the same way', () => {
    const terminated: ExplorationSource = {kind: 'sql', body: 'SELECT 1;', label: 'One'};
    expect(renderExplorationSql(terminated, q())).toBe('SELECT *\nFROM (\nSELECT 1;\n) AS t');
  });

  it('quotes an identifier containing a double quote rather than trusting the catalog', () => {
    const nasty: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'a"b', table: 'c"d'};
    expect(renderExplorationSql(nasty, q())).toBe('SELECT *\nFROM "a""b"."c""d"');
  });

  it('carries no trailing semicolon', () => {
    // The string goes to StartQueryExecution, not to an editor, and Athena rejects a batch.
    expect(renderExplorationSql(TABLE, q())).not.toMatch(/;\s*$/);
  });
});

describe('rendersFromSqlBody — which statement an execution read', () => {
  const body = 'SELECT name FROM db.orders';
  const over = (source: string, query: ExplorationQuery = q()) =>
    renderExplorationSql({kind: 'sql', body: source, label: 'x'}, query);

  it('recognises every description over the body, filtered, sorted or grouped', () => {
    expect(rendersFromSqlBody(over(body), body)).toBe(true);
    expect(rendersFromSqlBody(over(body, q({expression: 'name IS NOT NULL'})), body)).toBe(true);
    expect(
      rendersFromSqlBody(
        over(body, q({grouping: {columns: ['name'], aggregates: [], duplicatesOnly: false, showPercentage: false}})),
        body
      )
    ).toBe(true);
  });

  it.each([
    ['a longer body that begins with it', `${body} WHERE name <> ''`],
    ['a body that holds its whole subquery', over(body, q({expression: "name <> ''"}))]
  ])('refuses %s', (_case, other) => {
    expect(rendersFromSqlBody(over(other), body)).toBe(false);
  });
});

describe('renderExplorationSql — presentation can never reach it (FR-002 AC2 / FR-003)', () => {
  it('renders byte-identical SQL for two explorations differing ONLY in presentation', () => {
    const plain = newExploration(TABLE);
    const dressed = {
      ...plain,
      presentation: {
        hiddenColumns: ['status', 'qty'],
        columnOrder: ['placed_at', 'id'],
        pinnedColumns: ['id'],
        columnWidths: {id: 320}
      }
    };

    expect(renderExplorationSql(dressed.source, dressed.query)).toBe(renderExplorationSql(plain.source, plain.query));
  });

  it('projects SELECT * even when columns are hidden — the signature admits no presentation', () => {
    // FR-003. Narrowing to the visible columns would cut bytes scanned on Parquet and
    // would make un-hiding a column a billed re-run. The structural guarantee is the
    // parameter list: `renderExplorationSql` takes exactly two arguments.
    expect(renderExplorationSql.length).toBe(2);
    expect(renderExplorationSql(TABLE, q())).toContain('SELECT *');
  });
});

describe('renderExplorationSql — filters and the value asymmetry (FR-004 / FR-005)', () => {
  it('quotes a filter value, doubling an embedded single quote', () => {
    const sql = renderExplorationSql(TABLE, q({filters: [{column: 'name', operator: '=', value: "O'Brien"}]}));
    expect(sql).toBe(`SELECT *\nFROM "alice"."orders"\nWHERE "name" = 'O''Brien'`);
    // Well-formed: an odd number of quote characters would mean the literal never closed.
    expect((sql.match(/'/g) ?? []).length % 2).toBe(0);
  });

  it('renders IS NULL / IS NOT NULL with no value at all', () => {
    expect(renderExplorationSql(TABLE, q({filters: [{column: 'note', operator: 'isNull'}]}))).toContain(
      'WHERE "note" IS NULL'
    );
    expect(renderExplorationSql(TABLE, q({filters: [{column: 'note', operator: 'isNotNull'}]}))).toContain(
      'WHERE "note" IS NOT NULL'
    );
  });

  it('emits a numeric value BARE, because Trino does not coerce varchar to bigint', () => {
    // `WHERE "qty" > '5'` is a query-time error against a bigint column, not a comparison.
    // The repo's Python Trino renderer already interpolates counts unquoted for this
    // reason (dqcommon/sql.py) — this is the TypeScript half of the same rule.
    const sql = renderExplorationSql(
      TABLE,
      q({filters: [{column: 'qty', operator: '>', value: '5', valueKind: 'number'}]})
    );
    expect(sql).toContain('WHERE "qty" > 5');
    expect(sql).not.toContain("'5'");
  });

  it('refuses the forms `Number` alone would have accepted', () => {
    // The charset gate is load-bearing, not a fast path: `Number('0x1f')` is 31,
    // `Number('0b11')` is 3, and `Number('Infinity')` is Infinity. A check written as
    // `Number.isFinite(Number(v))` alone passes the first two straight into the SQL.
    const numeric = (value: string) =>
      renderExplorationSql(TABLE, q({filters: [{column: 'qty', operator: '=', value, valueKind: 'number'}]}));

    expect(Number('0x1f')).toBe(31);
    expect(Number('0b11')).toBe(3);
    for (const value of ['0x1f', '0b11', '0o17', 'Infinity', '-Infinity']) {
      expect(() => numeric(value)).toThrow(ExplorationRenderError);
    }
    // And the grammar gate catches what the charset lets through.
    for (const value of ['5e', '--5', '1e5e5', '.', 'e5', '1e400']) {
      expect(() => numeric(value)).toThrow(ExplorationRenderError);
    }
  });
});

describe('renderExplorationSql — WHERE composition (FR-005)', () => {
  it('parenthesizes BOTH sides so an expression’s OR cannot capture a filter', () => {
    // Unparenthesized this reads `status = 'open' AND a OR b`, which is
    // `(status = 'open' AND a) OR b` — rows the user did not ask for.
    const sql = renderExplorationSql(
      TABLE,
      q({filters: [{column: 'status', operator: '=', value: 'open'}], expression: 'a OR b'})
    );
    expect(sql).toContain(`WHERE "status" = 'open' AND (a OR b)`);
  });

  it('parenthesizes the filter side too when there is more than one filter', () => {
    const sql = renderExplorationSql(
      TABLE,
      q({
        filters: [
          {column: 'status', operator: '=', value: 'open'},
          {column: 'qty', operator: '>', value: '0', valueKind: 'number'}
        ],
        expression: 'a OR b'
      })
    );
    expect(sql).toContain(`WHERE ("status" = 'open' AND "qty" > 0) AND (a OR b)`);
  });

  it('passes the expression through VERBATIM — it is the user’s own SQL', () => {
    const sql = renderExplorationSql(TABLE, q({expression: "lower(name) LIKE '%o''brien%'"}));
    expect(sql).toContain(`WHERE (lower(name) LIKE '%o''brien%')`);
  });
});

describe('renderExplorationSql — ordering (FR-002)', () => {
  it('orders by PRIORITY, not by array position', () => {
    const sql = renderExplorationSql(
      TABLE,
      q({
        ordering: [
          {column: 'qty', direction: 'asc', priority: 1},
          {column: 'placed_at', direction: 'desc', priority: 0}
        ]
      })
    );
    expect(sql).toContain('ORDER BY "placed_at" DESC, "qty" ASC');
  });

  it('does not mutate the caller’s ordering array while sorting it', () => {
    const ordering = [
      {column: 'qty', direction: 'asc' as const, priority: 1},
      {column: 'placed_at', direction: 'desc' as const, priority: 0}
    ];
    renderExplorationSql(TABLE, q({ordering}));
    expect(ordering[0].column).toBe('qty');
  });
});

describe('renderExplorationSql — grouping (FR-002 AC5)', () => {
  it('projects the grouping columns then the aggregates, and emits GROUP BY', () => {
    const sql = renderExplorationSql(
      TABLE,
      q({
        grouping: g({
          columns: ['status'],
          aggregates: [
            {fn: 'COUNT', column: '*'},
            {fn: 'SUM', column: 'qty'}
          ]
        })
      })
    );
    expect(sql).toBe(
      'SELECT "status", COUNT(*) AS "count_all", SUM("qty") AS "sum_qty"\n' +
        'FROM "alice"."orders"\n' +
        'GROUP BY "status"'
    );
  });

  it('allows an ORDER BY on a grouped column or an aggregate alias', () => {
    const grouping = g({columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]});
    expect(
      renderExplorationSql(TABLE, q({grouping, ordering: [{column: 'status', direction: 'asc', priority: 0}]}))
    ).toContain('ORDER BY "status" ASC');
    expect(
      renderExplorationSql(TABLE, q({grouping, ordering: [{column: 'count_all', direction: 'desc', priority: 0}]}))
    ).toContain('ORDER BY "count_all" DESC');
  });

  it('REFUSES an ORDER BY on a column that is neither grouped nor aggregated', () => {
    // Trino rejects this too — but only after the scan has been paid for. Refusing here
    // makes it free, which is the whole reason the check exists rather than letting
    // Athena be the validator.
    expect(() =>
      renderExplorationSql(
        TABLE,
        q({
          grouping: g({columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]}),
          ordering: [{column: 'placed_at', direction: 'asc', priority: 0}]
        })
      )
    ).toThrow(/neither grouped nor aggregated/);
  });

  it('refuses a non-COUNT aggregate over `*`', () => {
    expect(() =>
      renderExplorationSql(TABLE, q({grouping: g({columns: ['status'], aggregates: [{fn: 'SUM', column: '*'}]})}))
    ).toThrow(ExplorationRenderError);
  });

  it('refuses a grouping COLUMN whose name an aggregate would also produce', () => {
    // The half the aggregate-vs-aggregate check above misses: grouping columns are
    // projected beside the aggregates under their own names, so a column called
    // `count_all` beside the default COUNT(*) yields two result columns of one name —
    // one geometry key in the grid, and an ORDER BY that cannot say which it means.
    // SPEC-182's panel made this reachable, because ANY column can be grouped by.
    expect(() =>
      renderExplorationSql(TABLE, q({grouping: g({columns: ['count_all'], aggregates: [{fn: 'COUNT', column: '*'}]})}))
    ).toThrow(/both be called "count_all"/);

    // And the pair: the same column with no colliding aggregate renders fine, so the
    // check cannot be passing by refusing every grouping.
    expect(
      renderExplorationSql(TABLE, q({grouping: g({columns: ['count_all'], aggregates: [{fn: 'SUM', column: 'qty'}]})}))
    ).toContain('GROUP BY "count_all"');
  });

  it('renders aggregates with no grouping columns and emits NO GROUP BY', () => {
    const sql = renderExplorationSql(TABLE, q({grouping: g({aggregates: [{fn: 'COUNT', column: '*'}]})}));
    expect(sql).toBe('SELECT COUNT(*) AS "count_all"\nFROM "alice"."orders"');
    expect(sql).not.toContain('GROUP BY');
  });

  it('emits HAVING COUNT(*) > 1 for duplicates only, between the GROUP BY and the ORDER BY', () => {
    // SPEC-182 FR-004 AC1. The clause order is the only one Trino parses, and `COUNT(*)`
    // is written out rather than referencing an alias — Trino does not accept a SELECT
    // alias in a HAVING, and the predicate must hold whether or not the user kept the
    // default aggregate.
    const sql = renderExplorationSql(
      TABLE,
      q({
        grouping: g({columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}], duplicatesOnly: true}),
        ordering: [{column: 'count_all', direction: 'desc', priority: 0}]
      })
    );
    expect(sql).toBe(
      'SELECT "status", COUNT(*) AS "count_all"\n' +
        'FROM "alice"."orders"\n' +
        'GROUP BY "status"\n' +
        'HAVING COUNT(*) > 1\n' +
        'ORDER BY "count_all" DESC'
    );
  });

  it('names the offending ordered column through the same rule the refusal uses', () => {
    // Exported so SPEC-182's panel refuses exactly what this refuses — the thrown message
    // names a column and an operator, which SPEC-106 forbids showing a user, so the panel
    // has to word its own refusal from the column alone.
    const grouping = g({columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]});
    expect(groupingOrderingViolation([{column: 'placed_at', direction: 'asc', priority: 0}], grouping)).toBe(
      'placed_at'
    );
    expect(groupingOrderingViolation([{column: 'status', direction: 'asc', priority: 0}], grouping)).toBeNull();
    expect(groupingOrderingViolation([{column: 'count_all', direction: 'asc', priority: 0}], grouping)).toBeNull();
    expect(groupingOrderingViolation([], grouping)).toBeNull();
  });

  it('composes grouping over the sql arm identically', () => {
    const sql = renderExplorationSql(
      SQL_SOURCE,
      q({grouping: g({columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]})})
    );
    expect(sql).toBe(
      'SELECT "status", COUNT(*) AS "count_all"\n' +
        'FROM (\nSELECT * FROM alice.orders\n) AS t\n' +
        'GROUP BY "status"'
    );
  });
});

describe('newExploration (FR-001)', () => {
  it('yields an EMPTY query description from a table source', () => {
    const exploration = newExploration(TABLE);
    expect(exploration.query).toEqual({filters: [], expression: null, ordering: [], grouping: null});
    expect(exploration.source).toEqual(TABLE);
    expect(exploration.id).toBeTruthy();
  });

  it('does not carry the bucket or the S3 location — those are the file browser’s concern', () => {
    const exploration = newExploration(TABLE);
    expect(Object.keys(exploration.source).sort()).toEqual(['database', 'kind', 'spaceId', 'table']);
  });
});

// The eight operators SPEC-238 adds. Every case asserts the WHOLE `WHERE` clause rather
// than a fragment of it: a substring assertion passes on a clause that also carries
// something it did not expect, and what reaches Athena is the whole string.
const whereOf = (query: ExplorationQuery): string => {
  const [, , where] = renderExplorationSql(TABLE, query).split('\n');
  return where;
};
const filtered = (filter: ExplorationQuery['filters'][number]): string => whereOf(q({filters: [filter]}));

describe('the text operators (FR-001)', () => {
  it('escapes the wildcards and the escape character itself, in that order', () => {
    expect(filtered({column: 'name', operator: 'contains', value: 'a%b_c\\d'})).toBe(
      "WHERE lower(\"name\") LIKE lower('%a\\%b\\_c\\\\d%') ESCAPE '\\'"
    );
  });

  it('anchors starts with at the front and ends with at the back', () => {
    expect(filtered({column: 'name', operator: 'startsWith', value: "O'Brien"})).toBe(
      "WHERE lower(\"name\") LIKE lower('O''Brien%') ESCAPE '\\'"
    );
    expect(filtered({column: 'name', operator: 'endsWith', value: 'x'})).toBe(
      "WHERE lower(\"name\") LIKE lower('%x') ESCAPE '\\'"
    );
  });

  it('keeps an injection attempt inside the literal under NOT LIKE', () => {
    const where = filtered({column: 'name', operator: 'notContains', value: "' OR 1=1 --"});
    expect(where).toBe("WHERE lower(\"name\") NOT LIKE lower('%'' OR 1=1 --%') ESCAPE '\\'");
    // The real claim, and the one a golden string alone would not make: every quote in the
    // statement is part of a literal, so nothing the user typed is being parsed as SQL.
    const outside = renderExplorationSql(
      TABLE,
      q({filters: [{column: 'name', operator: 'notContains', value: "' OR 1=1 --"}]})
    ).replace(/'(?:[^']|'')*'/g, '');
    expect(outside).not.toContain("'");
  });

  it('refuses an empty pattern, which would match every non-NULL row', () => {
    expect(() => filtered({column: 'name', operator: 'contains', value: ''})).toThrow(ExplorationRenderError);
    expect(() => filtered({column: 'name', operator: 'contains'})).toThrow(ExplorationRenderError);
  });

  it('quotes its value on a NUMERIC column, where a comparison would emit it bare', () => {
    expect(filtered({column: 'name', operator: 'contains', value: '5', valueKind: 'number'})).toBe(
      "WHERE lower(\"name\") LIKE lower('%5%') ESCAPE '\\'"
    );
  });
});

describe('the list operators (FR-002)', () => {
  it('de-duplicates and sorts by code unit, so two orders render one statement', () => {
    expect(filtered({column: 'brnd_name', operator: 'in', values: ['Abilify', 'Abacavir', 'Abilify']})).toBe(
      "WHERE \"brnd_name\" IN ('Abacavir', 'Abilify')"
    );
    expect(filtered({column: 'c', operator: 'notIn', values: ['b', 'a']})).toBe("WHERE \"c\" NOT IN ('a', 'b')");
  });

  it('emits a numeric column’s values bare, and refuses one that is not a number', () => {
    expect(filtered({column: 'qty', operator: 'in', values: ['10', '2.5'], valueKind: 'number'})).toBe(
      'WHERE "qty" IN (10, 2.5)'
    );
    expect(() => filtered({column: 'qty', operator: 'in', values: ['10', '0x1f'], valueKind: 'number'})).toThrow(
      ExplorationRenderError
    );
  });

  it('refuses an empty list, an absent one, and one over the cap — and renders AT the cap', () => {
    expect(() => filtered({column: 'c', operator: 'in', values: []})).toThrow(ExplorationRenderError);
    expect(() => filtered({column: 'c', operator: 'in'})).toThrow(ExplorationRenderError);
    const atCap = Array.from({length: EXPLORER_FILTER_VALUES_MAX}, (_, i) => `v${i}`);
    expect(filtered({column: 'c', operator: 'in', values: atCap})).toContain('"c" IN (');
    expect(() => filtered({column: 'c', operator: 'in', values: [...atCap, 'one-more']})).toThrow(
      ExplorationRenderError
    );
  });
});

describe('a list holding the empty string and naming NULL', () => {
  it.each<[string, ColumnFilter, string]>([
    [
      'is one of, with NULL beside the values',
      {column: 'c', operator: 'in', values: ['b', '', 'a'], includesNull: true},
      `WHERE ("c" IN ('', 'a', 'b') OR "c" IS NULL)`
    ],
    ['is one of, naming only NULL', {column: 'c', operator: 'in', values: [], includesNull: true}, 'WHERE "c" IS NULL'],
    [
      'is not one of, holding the empty string',
      {column: 'c', operator: 'notIn', values: ['', 'x']},
      `WHERE "c" NOT IN ('', 'x')`
    ],
    [
      'is not one of, ignoring a NULL it cannot list',
      {column: 'c', operator: 'notIn', values: ['x'], includesNull: true},
      `WHERE "c" NOT IN ('x')`
    ]
  ])('renders %s', (_case, filter, where) => {
    expect(filtered(filter)).toBe(where);
  });
});

describe('the empty operators (FR-003)', () => {
  it('tests both spellings of absent, parenthesized so a neighbour cannot capture the OR', () => {
    expect(filtered({column: 'last_name', operator: 'isEmpty'})).toBe(
      'WHERE ("last_name" IS NULL OR "last_name" = \'\')'
    );
    expect(filtered({column: 'c', operator: 'isNotEmpty'})).toBe('WHERE ("c" IS NOT NULL AND "c" <> \'\')');
  });

  it('keeps the OR bound to its own column when a second filter joins it', () => {
    const where = whereOf(
      q({
        filters: [
          {column: 'a', operator: 'isEmpty'},
          {column: 'b', operator: '=', value: 'x'}
        ]
      })
    );
    expect(where).toBe('WHERE (("a" IS NULL OR "a" = \'\') AND "b" = \'x\')');
  });
});

describe('every operator renders (FR-001–FR-003)', () => {
  it('has a rendering for each member of the union, and none of them is undefined', () => {
    // A POPULATION guard, and the count is asserted first: `[].every` is true, so a loop
    // over an empty list would pass while proving nothing. It is the runtime half of the
    // claim `Record<FilterOperator, …>` makes at compile time.
    expect(FILTER_OPERATORS).toHaveLength(16);
    for (const operator of FILTER_OPERATORS) {
      const filter = {
        column: 'c',
        operator,
        ...(operatorTakesValue(operator) ? {value: 'x'} : {}),
        ...(operatorTakesValues(operator) ? {values: ['x']} : {})
      };
      const where = filtered(filter);
      // The quoted column, not a prefix match on `WHERE`: every renderer emits
      // `sqlIdentifier(column)`, and a pattern loose enough to match any clause at all
      // would pass on the `undefined` this exists to catch.
      expect(where, operator).toContain('"c"');
      expect(where, operator).not.toContain('undefined');
    }
  });

  it('never emits a value bare for an operator whose spec says the column’s kind does not apply', () => {
    // The flag the renderer and both value inputs read. If it were flipped for a text
    // operator, this is where a non-numeric value on a numeric column would start throwing
    // instead of being quoted — and the inputs would start refusing what the renderer takes.
    const unaffected = FILTER_OPERATORS.filter((o) => operatorTakesValue(o) && !operatorUsesValueKind(o));
    expect(unaffected).toEqual(['contains', 'notContains', 'startsWith', 'endsWith']);
    for (const operator of unaffected) {
      expect(() => filtered({column: 'c', operator, value: 'not a number', valueKind: 'number'})).not.toThrow();
    }
  });
});

describe('exceedsAthenaQueryLimit (FR-005)', () => {
  it('counts UTF-8 BYTES, not characters', () => {
    expect(exceedsAthenaQueryLimit('a'.repeat(ATHENA_QUERY_STRING_MAX))).toBe(false);
    expect(exceedsAthenaQueryLimit('a'.repeat(ATHENA_QUERY_STRING_MAX + 1))).toBe(true);
    // 131,073 two-byte characters is 262,146 bytes — over the limit on a count this
    // assertion would miss entirely if the check counted characters (131,073 of them).
    const twoByte = 'é'.repeat(131_073);
    expect(twoByte).toHaveLength(131_073);
    expect(exceedsAthenaQueryLimit(twoByte)).toBe(true);
  });
});

describe('renderColumnValuesSql — the values listing', () => {
  const NONE = {filters: [], expression: null};

  it('narrows by every other filter and the expression, never grouping, ordering or the column’s own filter', () => {
    const query = q({
      filters: [
        {column: 'state', operator: '=', value: 'NY'},
        {column: 'brnd_name', operator: 'contains', value: 'ab'}
      ],
      expression: 'qty > 5',
      ordering: [{column: 'state', direction: 'desc', priority: 0}],
      grouping: g({columns: ['state'], aggregates: [{fn: 'COUNT', column: '*'}]})
    });

    const sql = renderColumnValuesSql(TABLE, narrowingFor(query, 'brnd_name'), 'brnd_name');

    expect(sql).toBe(
      'SELECT "brnd_name" AS "value", COUNT(*) AS "row_count", COUNT(*) OVER () AS "value_count"\n' +
        'FROM "alice"."orders"\n' +
        `WHERE "state" = 'NY' AND (qty > 5)\n` +
        'GROUP BY 1\n' +
        'ORDER BY 2 DESC, 1 ASC NULLS LAST\n' +
        `LIMIT ${EXPLORER_FILTER_VALUES_MAX}`
    );
  });

  it('has no WHERE line when nothing narrows it', () => {
    expect(renderColumnValuesSql(TABLE, NONE, 'c')).not.toContain('WHERE');
  });

  it('reads a statement source through the exploration’s own subquery', () => {
    const exploration = renderExplorationSql(SQL_SOURCE, q());
    const listing = renderColumnValuesSql(SQL_SOURCE, NONE, 'c');

    expect(listing.slice(listing.indexOf('\nFROM '), listing.indexOf('\nGROUP BY'))).toBe(
      exploration.slice(exploration.indexOf('\nFROM '))
    );
  });

  it('keeps its ordinals when a column is named like one of its outputs', () => {
    const sql = renderColumnValuesSql(TABLE, NONE, 'row_count');

    expect(sql.startsWith('SELECT "row_count" AS "value", COUNT(*) AS "row_count", ')).toBe(true);
    expect(sql).toContain('GROUP BY 1\nORDER BY 2 DESC, 1 ASC NULLS LAST');
  });
});
