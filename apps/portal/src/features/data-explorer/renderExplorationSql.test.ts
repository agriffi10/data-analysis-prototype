import {describe, expect, it} from 'vitest';
import {
  ExplorationRenderError,
  aggregateAlias,
  groupingOrderingViolation,
  renderExplorationSql
} from './renderExplorationSql';
import {emptyExplorationQuery, emptyGrouping, newExploration} from './exploration';
import type {ExplorationQuery, ExplorationSource, Grouping} from './dataExplorer.types';

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

  it('survives a body ending in a `--` line comment', () => {
    // Composed on one line, `(${body}) AS t` puts the closing paren and the alias INSIDE
    // the comment and hands Athena an unbalanced statement — a syntax error with nothing
    // on screen to explain it. A saved query ending in a trailing comment is ordinary.
    const commented: ExplorationSource = {
      kind: 'sql',
      body: "SELECT * FROM alice.orders WHERE status = 'open' -- only the open ones",
      label: 'Open orders'
    };
    const sql = renderExplorationSql(commented, q({ordering: [{column: 'qty', direction: 'asc', priority: 0}]}));

    // The closing paren and the alias survive on a line the comment cannot reach.
    expect(sql).toContain('\n) AS t');
    const opens = (sql.match(/\(/g) ?? []).length;
    const closes = (sql.match(/\)/g) ?? []).length;
    expect(opens).toBe(closes);
  });

  it('survives a body ending in a semicolon the same way', () => {
    const terminated: ExplorationSource = {kind: 'sql', body: 'SELECT 1;', label: 'One'};
    expect(renderExplorationSql(terminated, q())).toBe('SELECT *\nFROM (\nSELECT 1;\n) AS t');
  });

  it('composes the SAME clauses over either arm — only the FROM differs', () => {
    // This is what lets SPEC-183 load a `.sql` file as a source without the filter,
    // ordering and grouping code learning that the union exists.
    const query = q({
      filters: [{column: 'status', operator: '=', value: 'open'}],
      expression: 'qty > 0',
      ordering: [{column: 'placed_at', direction: 'desc', priority: 0}]
    });
    const fromTable = renderExplorationSql(TABLE, query);
    const fromSql = renderExplorationSql(SQL_SOURCE, query);

    // Substituting each arm's OWN from-clause out must leave two identical statements —
    // which says "identical apart from the FROM" exactly, rather than dropping lines by
    // prefix (the `sql` arm's from-clause spans three lines, one of them a `SELECT`).
    const normalized = (sql: string, from: string) => sql.replace(from, 'FROM <source>');
    expect(normalized(fromTable, 'FROM "alice"."orders"')).toEqual(
      normalized(fromSql, 'FROM (\nSELECT * FROM alice.orders\n) AS t')
    );
    expect(normalized(fromTable, 'FROM "alice"."orders"')).toBe(
      ['SELECT *', 'FROM <source>', `WHERE "status" = 'open' AND (qty > 0)`, 'ORDER BY "placed_at" DESC'].join('\n')
    );
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

  it('renders the SAME STRING differently as an expression than as a filter value', () => {
    // The one thing a reader of this feature must not get backwards. The expression is
    // authored AS SQL; a filter value arrives FROM DATA and is quoted on the user's behalf.
    const shared = "name = 'x'";
    const asExpression = renderExplorationSql(TABLE, q({expression: shared}));
    const asValue = renderExplorationSql(TABLE, q({filters: [{column: 'note', operator: '=', value: shared}]}));

    expect(asExpression).toContain(`WHERE (name = 'x')`);
    expect(asValue).toContain(`WHERE "note" = 'name = ''x'''`);
    expect(asExpression).not.toBe(asValue);
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

  it('accepts the numeric forms Athena emits and refuses everything else', () => {
    const numeric = (value: string) =>
      renderExplorationSql(TABLE, q({filters: [{column: 'qty', operator: '=', value, valueKind: 'number'}]}));

    for (const value of ['5', '-5', '+5', '5.25', '-0.5', '1e10', '2.5E-3']) {
      expect(numeric(value)).toContain(`WHERE "qty" = ${value}`);
    }
    // The bare literal is the ONE thing the renderer does not escape, so what the check
    // admits IS the trust boundary. A refusal here, never a fall back to quoting — which
    // would restore the type error the numeric kind exists to avoid.
    for (const hostile of [
      '5 OR 1=1',
      "5'",
      '5;DROP',
      "5' OR '1'='1",
      '5)--',
      '5 UNION SELECT 1',
      '',
      ' 5',
      '5 ',
      '5\n',
      'qty'
    ]) {
      expect(() => numeric(hostile)).toThrow(ExplorationRenderError);
    }
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

  it('refuses a comparison carrying no value rather than rendering half a predicate', () => {
    expect(() => renderExplorationSql(TABLE, q({filters: [{column: 'qty', operator: '>'}]}))).toThrow(
      ExplorationRenderError
    );
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

  it('contributes no clause and no stray AND for an empty or whitespace-only expression', () => {
    expect(renderExplorationSql(TABLE, q({expression: ''}))).toBe('SELECT *\nFROM "alice"."orders"');
    expect(renderExplorationSql(TABLE, q({expression: '   \n\t '}))).toBe('SELECT *\nFROM "alice"."orders"');
    expect(renderExplorationSql(TABLE, q({expression: null}))).toBe('SELECT *\nFROM "alice"."orders"');

    const filtered = renderExplorationSql(
      TABLE,
      q({filters: [{column: 'status', operator: '=', value: 'open'}], expression: '  '})
    );
    expect(filtered).toBe(`SELECT *\nFROM "alice"."orders"\nWHERE "status" = 'open'`);
    expect(filtered).not.toContain('AND');
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

  it('names an aggregate’s output column once, for the SQL and the panel alike', () => {
    // SPEC-182's panel labels a column with this; a second naming scheme at the view
    // would disagree with the result set the moment either changed.
    expect(aggregateAlias({fn: 'COUNT', column: '*'})).toBe('count_all');
    expect(aggregateAlias({fn: 'AVG', column: 'qty'})).toBe('avg_qty');
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

  it('allows that same ORDER BY when there is NO grouping', () => {
    // The pair matters: a check that refused it unconditionally would break every
    // ungrouped sort, and every ungrouped test here would still pass.
    expect(
      renderExplorationSql(TABLE, q({ordering: [{column: 'placed_at', direction: 'asc', priority: 0}]}))
    ).toContain('ORDER BY "placed_at" ASC');
  });

  it('refuses a non-COUNT aggregate over `*`', () => {
    expect(() =>
      renderExplorationSql(TABLE, q({grouping: g({columns: ['status'], aggregates: [{fn: 'SUM', column: '*'}]})}))
    ).toThrow(ExplorationRenderError);
  });

  it('refuses two aggregates that would produce one column name', () => {
    expect(() =>
      renderExplorationSql(
        TABLE,
        q({
          grouping: g({
            columns: [],
            aggregates: [
              {fn: 'COUNT', column: 'qty'},
              {fn: 'COUNT', column: 'qty'}
            ]
          })
        })
      )
    ).toThrow(/both produce the column/);
  });

  it('refuses an empty grouping rather than rendering a bare GROUP BY', () => {
    expect(() => renderExplorationSql(TABLE, q({grouping: g()}))).toThrow(ExplorationRenderError);
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

  it('emits no HAVING when duplicates-only is off, and none from the percentage flag ever', () => {
    // `showPercentage` is computed in the browser from rows already fetched — if it ever
    // reached the SQL it would be a second scan for a column the user asked to SEE.
    const sql = renderExplorationSql(
      TABLE,
      q({grouping: g({columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}], showPercentage: true})})
    );
    expect(sql).not.toContain('HAVING');
    expect(sql).toBe('SELECT "status", COUNT(*) AS "count_all"\nFROM "alice"."orders"\nGROUP BY "status"');
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

  it('starts a panel’s draft with COUNT(*) and no columns — which is NOT grouping mode', () => {
    const draft = emptyGrouping();
    expect(draft).toEqual({
      columns: [],
      aggregates: [{fn: 'COUNT', column: '*'}],
      duplicatesOnly: false,
      showPercentage: false
    });
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

  it('keeps source, query and presentation as three separate fields', () => {
    // Never a flattened bag — the split is what lets the renderer's parameter list
    // exclude one of them.
    const exploration = newExploration(TABLE);
    expect(Object.keys(exploration).sort()).toEqual(['id', 'presentation', 'query', 'source']);
  });

  it('does not carry the bucket or the S3 location — those are the file browser’s concern', () => {
    const exploration = newExploration(TABLE);
    expect(Object.keys(exploration.source).sort()).toEqual(['database', 'kind', 'spaceId', 'table']);
  });
});
