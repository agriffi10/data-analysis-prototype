import {sqlIdentifier, sqlLiteral} from '../../lib/sql';
import {SQL_SOURCE_ALIAS} from './dataExplorer.constants';
import type {
  ColumnFilter,
  ExplorationQuery,
  ExplorationSource,
  Grouping,
  GroupingAggregate,
  SortEntry
} from './dataExplorer.types';

/**
 * A description that cannot be rendered. Thrown rather than returned, because the
 * signature promises a `string` and there is no half-rendered SQL worth handing back.
 *
 * Every case is a caller bug rather than a user typo — the panels that build a
 * description refuse the gesture before it reaches here. The message
 * is operator text: it names the offending column so a failing test says which one, and
 * the error-wording rule forbids rendering it to a user.
 */
export class ExplorationRenderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExplorationRenderError';
  }
}

// The characters a bare number may contain, and nothing else. This check is LOAD-BEARING
// rather than a fast path: `Number` alone accepts `0x1f`, `0b11` and `Infinity`, and the
// charset is what keeps those — and every quote, space, semicolon and comment marker —
// out. One quantifier over one class, so it cannot backtrack.
const NUMERIC_CHARS_RE = /^[-+0-9.eE]+$/;

/**
 * Whether a value may be emitted into SQL UNQUOTED as a number.
 *
 * This is the one place the renderer does not escape what it emits, so what this admits
 * IS the trust boundary. Two gates, and both are needed: the charset above bounds the
 * alphabet, and `Number.isFinite` bounds the grammar — a hand-written numeric grammar is
 * exactly the kind of regex that is subtly wrong (and the one written first here tripped
 * `security/detect-unsafe-regex`), where the engine's own parser cannot be.
 *
 * **Exported so the surfaces that build a numeric filter refuse exactly what the renderer
 * refuses**. The renderer throws an `ExplorationRenderError` whose message
 * names a column and an operator — operator text the error-wording rule forbids rendering — so a value
 * that would reach it has to be turned back at the input, and a second numeric rule at
 * the input is a rule that can disagree with this one.
 *
 * @param value - The raw filter value.
 * @returns True when the value is a plain decimal or exponent-form number.
 */
export function isBareNumeric(value: string): boolean {
  if (value === '') return false;
  if (!NUMERIC_CHARS_RE.test(value)) return false;
  return Number.isFinite(Number(value));
}

const OPERATOR_SQL: Record<Exclude<ColumnFilter['operator'], 'isNull' | 'isNotNull'>, string> = {
  '=': '=',
  '<>': '<>',
  '>': '>',
  '>=': '>=',
  '<': '<',
  '<=': '<='
};

/**
 * The column name an aggregate produces, and the name an `ORDER BY` may reference.
 *
 * Exported because the panel must label a grouped column with the name the SQL
 * actually emits — a second naming scheme at the view would disagree with the result set
 * the moment either changed.
 *
 * @param aggregate - The aggregate to name.
 * @returns Its output column name, unquoted.
 */
export function aggregateAlias(aggregate: GroupingAggregate): string {
  return `${aggregate.fn.toLowerCase()}_${aggregate.column === '*' ? 'all' : aggregate.column}`;
}

function renderValue(filter: ColumnFilter): string {
  const value = filter.value;
  if (value === undefined) {
    throw new ExplorationRenderError(`Filter on "${filter.column}" uses ${filter.operator} but carries no value.`);
  }
  if (filter.valueKind !== 'number') return sqlLiteral(value);
  if (!isBareNumeric(value)) {
    // Refused, never quoted as a fallback: quoting it would restore exactly the
    // varchar-vs-bigint comparison the numeric kind exists to avoid, and the query would
    // fail against Athena instead of here.
    throw new ExplorationRenderError(`Filter on "${filter.column}" is numeric but its value is not a number.`);
  }
  return value;
}

function renderFilter(filter: ColumnFilter): string {
  const column = sqlIdentifier(filter.column);
  if (filter.operator === 'isNull') return `${column} IS NULL`;
  if (filter.operator === 'isNotNull') return `${column} IS NOT NULL`;
  return `${column} ${OPERATOR_SQL[filter.operator]} ${renderValue(filter)}`;
}

function renderFrom(source: ExplorationSource): string {
  if (source.kind === 'table') {
    return `${sqlIdentifier(source.database)}.${sqlIdentifier(source.table)}`;
  }
  // Trino requires a subquery in a FROM be aliased. The body is the user's own SQL and is
  // composed verbatim, exactly as the expression is — the save path owns refusing a
  // multi-statement or non-SELECT file before it ever becomes a source.
  //
  // The NEWLINES are not formatting. A saved query ending in a `--` line comment swallows
  // whatever follows it on the same line, so `(${body}) AS t` would put the closing paren
  // and the alias inside the comment and hand Athena an unbalanced statement — reported as
  // a syntax error with nothing on screen to explain it.
  return `(\n${source.body}\n) AS ${SQL_SOURCE_ALIAS}`;
}

function renderProjection(grouping: Grouping | null): string {
  // `SELECT *` always, when not grouping. Narrowing to the visible columns would
  // cut bytes scanned on Parquet — and would make un-hiding a column a billed, several-
  // second re-run, so cost would depend on a gesture users read as cosmetic. The renderer
  // cannot see which columns are visible anyway; that is the point of its signature.
  if (!grouping) return '*';
  const columns = grouping.columns.map(sqlIdentifier);
  const aggregates = grouping.aggregates.map(
    (a) => `${a.fn}(${a.column === '*' ? '*' : sqlIdentifier(a.column)}) AS ${sqlIdentifier(aggregateAlias(a))}`
  );
  return [...columns, ...aggregates].join(', ');
}

function renderWhere(filters: ColumnFilter[], expression: string | null): string | null {
  const filterSql = filters.map(renderFilter);
  const trimmed = expression?.trim();

  // Both sides parenthesized when both are present, so an expression
  // containing a top-level OR cannot capture a filter. `a = 1 AND b OR c` is not
  // `a = 1 AND (b OR c)`, and the difference is rows the user did not ask for.
  const clauses: string[] = [];
  if (filterSql.length > 0) clauses.push(filterSql.length === 1 ? filterSql[0] : `(${filterSql.join(' AND ')})`);
  if (trimmed) clauses.push(`(${trimmed})`);

  if (clauses.length === 0) return null;
  return clauses.join(' AND ');
}

/**
 * The first ordered column a grouping cannot serve, if any.
 *
 * Trino rejects an `ORDER BY` on a column that is neither grouped nor aggregated. It
 * rejects it at ANALYSIS, so nothing is scanned and AWS does not bill a failed query —
 * what refusing buys is not money but immediacy: the gesture is refused where the user
 * made it, instead of surfacing seconds later as an engine error the app is forbidden to
 * render.
 *
 * **Exported so the Grouping panel refuses exactly what the renderer refuses**,
 * on the `isBareNumeric` precedent. It returns the offending COLUMN rather
 * than a message, because the two callers have to word it differently: this file wraps it
 * in operator text naming the column, and the panel wraps it in a sentence a user is
 * allowed to read. A second rule at the panel is a rule that can disagree with this one —
 * and the way it would disagree is a grouping the panel accepts and the renderer throws
 * on, which takes the whole exploration down.
 *
 * @param ordering - The description's sort entries.
 * @param grouping - The grouping in force.
 * @returns The first column that is neither a grouping column nor an aggregate's output, else null.
 */
export function groupingOrderingViolation(ordering: SortEntry[], grouping: Grouping): string | null {
  const grouped = new Set(grouping.columns);
  const aggregated = new Set(grouping.aggregates.map(aggregateAlias));
  return ordering.find((entry) => !grouped.has(entry.column) && !aggregated.has(entry.column))?.column ?? null;
}

function assertOrderingIsGroupable(ordering: SortEntry[], grouping: Grouping): void {
  const offender = groupingOrderingViolation(ordering, grouping);
  if (offender !== null) {
    throw new ExplorationRenderError(`Cannot order by "${offender}": it is neither grouped nor aggregated.`);
  }
}

/**
 * The output column name a grouping would produce twice, if any.
 *
 * Seeded with the GROUPING COLUMNS rather than the aggregates alone: they are projected
 * beside the aggregates under their own names, so grouping by a column called `count_all`
 * while `COUNT(*)` is present yields two result columns of one name — which share one
 * geometry entry in the grid and make `groupingOrderingViolation` answer for whichever the
 * reader meant. The panel made that reachable, because any column can be grouped by.
 *
 * **Exported for the same reason `groupingOrderingViolation` is**: the panel has to turn
 * the collision back at the gesture, and the message thrown below is operator text.
 *
 * @param grouping - The grouping to check.
 * @returns The first duplicated output name, or null when every column is distinct.
 */
export function groupingNameCollision(grouping: Grouping): string | null {
  const names = new Set<string>(grouping.columns);
  for (const aggregate of grouping.aggregates) {
    const alias = aggregateAlias(aggregate);
    if (names.has(alias)) return alias;
    names.add(alias);
  }
  return null;
}

function assertGroupingIsRenderable(grouping: Grouping): void {
  for (const aggregate of grouping.aggregates) {
    if (aggregate.column === '*' && aggregate.fn !== 'COUNT') {
      throw new ExplorationRenderError(`${aggregate.fn}(*) is not a valid aggregate; only COUNT(*) is.`);
    }
  }
  const collision = groupingNameCollision(grouping);
  if (collision !== null) {
    // Cheaper to refuse than to disambiguate: a result set with two columns of one name
    // has no ordering rule and no geometry key that can tell them apart.
    throw new ExplorationRenderError(`Two columns of this grouping would both be called "${collision}".`);
  }
  if (grouping.columns.length === 0 && grouping.aggregates.length === 0) {
    throw new ExplorationRenderError('A grouping must have at least one column or aggregate.');
  }
}

function renderOrderBy(ordering: SortEntry[]): string | null {
  if (ordering.length === 0) return null;
  // Priority is the user's sort order, not array order — a grid that lets a column be
  // promoted to primary sort reorders priorities, never the array.
  const sorted = [...ordering].sort((a, b) => a.priority - b.priority);
  return sorted.map((e) => `${sqlIdentifier(e.column)} ${e.direction === 'desc' ? 'DESC' : 'ASC'}`).join(', ');
}

/**
 * The ONE SQL builder for the Data Explorer.
 *
 * Takes the source and the query description **and nothing else**. That parameter list is
 * the feature's central rule made structural: column visibility, order, pinning, width,
 * colour and transformers are presentation, they must never change the rendered SQL, and
 * a function that cannot reach them cannot be made to depend on them by a later edit.
 *
 * The two source arms differ only in the `FROM`; filters, the expression, ordering and
 * grouping compose identically over either, which is what lets a saved exploration load
 * `.sql` file as a source without the rest of the feature knowing.
 *
 * @param source - Where the rows come from: a catalog table, or a `.sql` body.
 * @param query - The four dimensions that render SQL.
 * @returns The rendered statement, with no trailing semicolon.
 * @throws ExplorationRenderError - The description cannot be rendered (a caller bug):
 *   a valueless comparison, a non-numeric numeric value, an invalid or ambiguous
 *   grouping, or an ordering Trino would reject after billing for it.
 */
export function renderExplorationSql(source: ExplorationSource, query: ExplorationQuery): string {
  const {filters, expression, ordering, grouping} = query;

  if (grouping) {
    assertGroupingIsRenderable(grouping);
    assertOrderingIsGroupable(ordering, grouping);
  }

  const parts = [`SELECT ${renderProjection(grouping)}`, `FROM ${renderFrom(source)}`];

  const where = renderWhere(filters, expression);
  if (where) parts.push(`WHERE ${where}`);

  if (grouping && grouping.columns.length > 0) {
    parts.push(`GROUP BY ${grouping.columns.map(sqlIdentifier).join(', ')}`);
  }

  // The duplicate finder. `COUNT(*)` is written out rather than referencing an
  // aggregate's alias, because the predicate must hold whether or not the user kept the
  // default `COUNT(*)` among the aggregates — and Trino does not accept a SELECT alias in
  // a HAVING clause anyway. It follows the GROUP BY and precedes the ORDER BY, which is
  // the only order Trino parses.
  if (grouping?.duplicatesOnly) parts.push('HAVING COUNT(*) > 1');

  const orderBy = renderOrderBy(ordering);
  if (orderBy) parts.push(`ORDER BY ${orderBy}`);

  // No trailing semicolon: this string is handed to StartQueryExecution, not to an
  // editor, and Athena rejects a batch.
  return parts.join('\n');
}
