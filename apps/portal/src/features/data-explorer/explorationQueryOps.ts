import {aggregateAlias, groupingNameCollision, groupingOrderingViolation} from './renderExplorationSql';
import type {
  ColumnFilter,
  ExplorationQuery,
  FilterOperator,
  FilterValueKind,
  Grouping,
  SortEntry
} from './dataExplorer.types';

// The pure edits every filtering and ordering surface makes to a query description
//. They live apart from the components for the reason `exploration.ts` gives
// for its constructors: a header menu, a cell action and a settings dialog all "add a
// filter", and three implementations of that is how two of them come to disagree about
// whether adding a second filter on one column replaces the first.
//
// Every function here is total and returns a NEW description — nothing mutates, so a
// staged edit in a dialog cannot leak into the running exploration before Apply.

/** Operators that carry no value; `IS NULL` and `IS NOT NULL` apply straight from a menu. */
const VALUELESS_OPERATORS = new Set<FilterOperator>(['isNull', 'isNotNull']);

/**
 * Whether an operator needs a value, i.e. whether choosing it must open an input.
 *
 * @param operator - The filter operator.
 * @returns True for the six comparisons, false for the two null tests.
 */
export function operatorTakesValue(operator: FilterOperator): boolean {
  return !VALUELESS_OPERATORS.has(operator);
}

/** Menu and select wording for each operator, so one label is never spelt two ways. */
export const FILTER_OPERATOR_LABELS: Record<FilterOperator, string> = {
  '=': 'equals',
  '<>': 'does not equal',
  '>': 'greater than',
  '>=': 'greater than or equal to',
  '<': 'less than',
  '<=': 'less than or equal to',
  isNull: 'is null',
  isNotNull: 'is not null'
};

/** The order the header menu and the settings dialog both offer them in. */
export const FILTER_OPERATORS: FilterOperator[] = ['=', '<>', '>', '>=', '<', '<=', 'isNull', 'isNotNull'];

// Trino and Hive spell several of these differently and only one side is normalised —
// `useSourceColumns` maps Glue's names, while an execution's own metadata arrives raw
// from Athena — so both spellings are listed rather than normalising at the call site.
const NUMERIC_TYPES = new Set([
  'tinyint',
  'smallint',
  'int',
  'integer',
  'bigint',
  'float',
  'real',
  'double',
  'numeric'
]);

/**
 * How a value filtered against this column must be rendered into SQL.
 *
 * Trino does not coerce: `WHERE "qty" > '5'` against a `bigint` is a query-time error
 * rather than a comparison, so a numeric column's value has to reach the SQL bare. The
 * column's declared type is the only thing that knows which, which is why this is picked
 * here and carried on the filter rather than guessed by the renderer from the value —
 * `'5'` filtered against a `varchar` column is a string and must stay quoted.
 *
 * A type this does not recognise is `'string'`: quoting is the safe direction (it is
 * escaped, and a mismatch is a query error the user can read), where emitting bare would
 * be the unescaped one.
 *
 * @param type - The column's Athena or Glue type, e.g. `bigint`, `decimal(10,2)`, `varchar`.
 * @returns The kind a filter on this column should carry.
 */
export function filterValueKind(type: string): FilterValueKind {
  const normalized = type.trim().toLowerCase();
  if (NUMERIC_TYPES.has(normalized)) return 'number';
  return normalized.startsWith('decimal(') || normalized === 'decimal' ? 'number' : 'string';
}

/**
 * A description with nothing to clear: no filters, no expression, no ordering, no grouping.
 *
 * Grouping counts, superseding the earlier deliberate exclusion:
 * Clear all now clears the grouping too, so a grouped view with no filters is no longer
 * "empty" — a control that refused there would refuse the only thing left to clear.
 */
export function isEmptyQuery(query: ExplorationQuery): boolean {
  return (
    query.filters.length === 0 && query.ordering.length === 0 && !query.expression?.trim() && query.grouping === null
  );
}

// A grouping's ARRAYS are not sorted, unlike the filters and the ordering below: their
// order is the projection's and the GROUP BY's, so two groupings listing the same columns
// differently render different SQL and are different queries. Only the two flags are
// normalised — a document written before these fields existed carries neither, and an absent flag
// comparing unequal to `false` would push a history entry for an apply that changed
// nothing.
function canonicalGrouping(grouping: ExplorationQuery['grouping']) {
  if (!grouping) return null;
  return {
    columns: grouping.columns,
    aggregates: grouping.aggregates.map((a) => [a.fn, a.column]),
    duplicatesOnly: grouping.duplicatesOnly === true,
    showPercentage: grouping.showPercentage === true
  };
}

// Compared on a CANONICAL form rather than field by field: `filters` and `ordering` are
// arrays whose order carries no meaning (priority does), so two descriptions that render
// identical SQL must compare equal or an apply that changed nothing would push a history
// entry and the Back button would step through duplicates.
function canonical(query: ExplorationQuery): string {
  return JSON.stringify({
    filters: [...query.filters]
      .map((f) => ({
        column: f.column,
        operator: f.operator,
        value: f.value ?? null,
        valueKind: f.valueKind ?? 'string'
      }))
      .sort((a, b) => a.column.localeCompare(b.column) || a.operator.localeCompare(b.operator)),
    expression: query.expression?.trim() || null,
    ordering: [...query.ordering].sort((a, b) => a.priority - b.priority).map((e) => [e.column, e.direction]),
    grouping: canonicalGrouping(query.grouping)
  });
}

/**
 * Whether two descriptions would render the same SQL.
 *
 * @param a - One description.
 * @param b - The other.
 * @returns True when they are the same query, however their arrays are arranged.
 */
export function sameQuery(a: ExplorationQuery, b: ExplorationQuery): boolean {
  return canonical(a) === canonical(b);
}

/**
 * Adds or replaces the filter on one column (FR-002 AC4).
 *
 * One filter per column, always — a second filter on a column is far more often a user
 * refining the first than asking for `x = 1 AND x = 2`, and the second reading is
 * reachable through the expression bar where it is written out in full.
 *
 * @param query - The description to edit.
 * @param filter - The filter to apply; its `column` decides what it replaces.
 * @returns A new description.
 */
export function setFilter(query: ExplorationQuery, filter: ColumnFilter): ExplorationQuery {
  const others = query.filters.filter((f) => f.column !== filter.column);
  return {...query, filters: [...others, filter]};
}

/** Drops any filter on one column. */
export function clearFilter(query: ExplorationQuery, column: string): ExplorationQuery {
  return {...query, filters: query.filters.filter((f) => f.column !== column)};
}

/** The filter currently applied to a column, or null. */
export function filterOf(query: ExplorationQuery, column: string): ColumnFilter | null {
  return query.filters.find((f) => f.column === column) ?? null;
}

// Priorities are re-stamped from the sorted order on every edit, so they stay 0-based and
// CONTIGUOUS (FR-004 AC3). Left alone, clearing the middle of three sorts would leave
// 0 and 2 — which renders the same ORDER BY but shows the user a "3rd" with no second.
function stamp(ordering: SortEntry[]): SortEntry[] {
  return ordering.map((entry, index) => ({...entry, priority: index}));
}

function restamp(ordering: SortEntry[]): SortEntry[] {
  return stamp([...ordering].sort((a, b) => a.priority - b.priority));
}

/**
 * Sorts by a column, appending it at the next priority (FR-004 AC1).
 *
 * A column that is already sorted keeps its PLACE and only changes direction — flipping
 * ascending to descending is not a request to make it the primary sort, and promoting it
 * would silently re-order a multi-column sort the user built deliberately.
 *
 * @param query - The description to edit.
 * @param column - The column to sort by.
 * @param direction - Which way.
 * @returns A new description.
 */
export function setSort(query: ExplorationQuery, column: string, direction: 'asc' | 'desc'): ExplorationQuery {
  const existing = query.ordering.find((e) => e.column === column);
  if (existing) {
    return {
      ...query,
      ordering: restamp(query.ordering.map((e) => (e.column === column ? {...e, direction} : e)))
    };
  }
  const next: SortEntry = {column, direction, priority: query.ordering.length};
  return {...query, ordering: restamp([...query.ordering, next])};
}

/** Removes one column from the ordering, leaving the rest in the same relative order. */
export function clearSort(query: ExplorationQuery, column: string): ExplorationQuery {
  return {...query, ordering: restamp(query.ordering.filter((e) => e.column !== column))};
}

/**
 * How a column is sorted, and where in the priority list it sits.
 *
 * @param query - The description to read.
 * @param column - The column.
 * @returns Its direction and 1-based position, or null when it is not sorted.
 */
export function sortOf(query: ExplorationQuery, column: string): {direction: 'asc' | 'desc'; position: number} | null {
  const sorted = [...query.ordering].sort((a, b) => a.priority - b.priority);
  const at = sorted.findIndex((e) => e.column === column);
  if (at === -1) return null;
  return {direction: sorted[at].direction, position: at + 1};
}

/**
 * Moves a sorted column one place up or down the priority list (FR-004 AC2).
 *
 * @param query - The description to edit.
 * @param column - The sorted column to move.
 * @param direction - -1 to sort earlier, 1 to sort later.
 * @returns A new description, or the same one when the move is off either end.
 */
export function moveSortPriority(query: ExplorationQuery, column: string, direction: -1 | 1): ExplorationQuery {
  const sorted = [...query.ordering].sort((a, b) => a.priority - b.priority);
  const at = sorted.findIndex((e) => e.column === column);
  const to = at + direction;
  if (at === -1 || to < 0 || to >= sorted.length) return query;
  [sorted[at], sorted[to]] = [sorted[to], sorted[at]];
  // Stamped by ARRAY POSITION, never re-sorted by priority first: the entries still carry
  // the priorities they had, so sorting by them would put the two back where they were and
  // the move would be a silent no-op (found by the test that drives the ↑ control).
  return {...query, ordering: stamp(sorted)};
}

/**
 * Applies a grouping to a description, or leaves grouping mode.
 *
 * **Grouping mode is exactly "at least one grouping column"** (AC6). A grouping with no
 * columns is legal SQL — a global aggregate over the whole table — but it is not what the
 * panel is for, and expressing "no columns left" as anything other than "not grouped"
 * would leave the user in a mode with nothing in it.
 *
 * Leaving grouping mode **drops any sort on an aggregate's output column**, which is the
 * half that is easy to miss: `count_all` exists only while the grouping does, so an
 * ORDER BY carrying it onto the ungrouped table is a query Athena rejects — and it would
 * also miss the cached ungrouped execution AC6 promises to return to.
 *
 * @param query - The description to edit.
 * @param grouping - The grouping to apply, or null to leave grouping mode.
 * @returns A new description.
 */
export function setGrouping(query: ExplorationQuery, grouping: Grouping | null): ExplorationQuery {
  if (grouping && grouping.columns.length > 0) return {...query, grouping};

  const aliases = new Set((query.grouping?.aggregates ?? []).map(aggregateAlias));
  return {...query, grouping: null, ordering: restamp(query.ordering.filter((e) => !aliases.has(e.column)))};
}

/**
 * Why applying a grouping would be refused, for `Button.disabledReason`.
 *
 * The reachable way to build this conflict is to sort a column and then group it away, so
 * the refusal belongs on the Grouping panel's own Apply and names the offending sort —
 * "clear that sort first" is the only way out. It is **not** the only guard the rule needs:
 * a grouped result also carries the calculated percentage column, which is in no statement
 * at all, so every per-column sort and filter surface asks `queryRefusalOf` first
 * (`ColumnQueryActions`). Found in review — the header menu offered that column a sort,
 * and taking it put the whole exploration behind an error banner.
 *
 * The rule is the RENDERER's (`groupingOrderingViolation`), not a copy of it: the message
 * the renderer throws names a column and an operator, which the error-wording rule forbids showing
 * anyone, so the refusal has to be worded here — but a second rule here could disagree,
 * and the way it would disagree is a grouping this accepts and the renderer throws on.
 *
 * @param query - The description the grouping would be applied to.
 * @param grouping - The proposed grouping, or null to leave grouping mode.
 * @returns The reason, or null when the grouping can be applied.
 */
export function groupingApplyRefusal(query: ExplorationQuery, grouping: Grouping | null): string | null {
  // Leaving grouping mode drops the sorts that could not survive it, so it never refuses.
  if (!grouping || grouping.columns.length === 0) return null;
  const collision = groupingNameCollision(grouping);
  if (collision !== null) {
    return `Two of these would both be called “${collision}” — remove one of them.`;
  }
  const offender = groupingOrderingViolation(query.ordering, grouping);
  if (offender === null) return null;
  return `Remove the sort on “${offender}” first — a grouped result can only be sorted by a grouping column or an aggregate.`;
}

/**
 * Why a priority move is unavailable, for `Button.disabledReason`.
 *
 * @param query - The description.
 * @param column - The sorted column.
 * @param direction - -1 for earlier, 1 for later.
 * @returns The reason, or null when the move is allowed.
 */
export function moveSortRefusal(query: ExplorationQuery, column: string, direction: -1 | 1): string | null {
  const sort = sortOf(query, column);
  if (!sort) return `“${column}” is not sorted.`;
  if (direction === -1 && sort.position === 1) return `“${column}” is already the first sort.`;
  if (direction === 1 && sort.position === query.ordering.length) return `“${column}” is already the last sort.`;
  return null;
}
