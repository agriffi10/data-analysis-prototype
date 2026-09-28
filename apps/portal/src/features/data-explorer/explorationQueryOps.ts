import {aggregateAlias, groupingNameCollision, groupingOrderingViolation, isBareNumeric} from './renderExplorationSql';
import {EXPLORER_FILTER_VALUES_MAX, FILTER_OPERATOR_SPECS} from './dataExplorer.constants';
import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
import {isFilterGroup} from './exploration';
import type {
  ColumnFilter,
  ExplorationQuery,
  FilterItem,
  FilterOperator,
  FilterValueKind,
  Grouping,
  SortEntry,
  ValuesNarrowing
} from './dataExplorer.types';

// The pure edits every filtering and ordering surface makes to a query description.
// They live apart from the components for the reason `exploration.ts` gives
// for its constructors: a header menu, a cell action and a settings dialog all "add a
// filter", and three implementations of that is how two of them come to disagree about
// whether adding a second filter on one column replaces the first.
//
// Every function here is total and returns a NEW description — nothing mutates, so a
// staged edit in a dialog cannot leak into the running exploration before Apply.

/** Every operator, in the one order every surface offers them in. */
export const FILTER_OPERATORS = Object.keys(FILTER_OPERATOR_SPECS) as FilterOperator[];

/** Menu and select wording for each operator, so one label is never spelt two ways. */
export const FILTER_OPERATOR_LABELS = Object.fromEntries(
  FILTER_OPERATORS.map((operator) => [operator, FILTER_OPERATOR_SPECS[operator].label])
) as Record<FilterOperator, string>;

/**
 * Whether a string is an operator this app knows.
 *
 * `Object.hasOwn`, never the `in` operator: `in` walks the prototype chain, so `'toString'`
 * and `'constructor'` would both pass and the renderer would splice one into a statement.
 * The stored-document check is the only caller that matters, and a document is the one
 * untrusted input this model has.
 *
 * @param value - Any string, typically off a restored document.
 * @returns True when it names a filter operator.
 */
export function isFilterOperator(value: string): value is FilterOperator {
  return Object.hasOwn(FILTER_OPERATOR_SPECS, value);
}

/**
 * Whether an operator needs a single value, i.e. whether choosing it must open an input.
 *
 * @param operator - The filter operator.
 * @returns True for the six comparisons and the six text operators.
 */
export function operatorTakesValue(operator: FilterOperator): boolean {
  return FILTER_OPERATOR_SPECS[operator].takes === 'value';
}

/**
 * Whether an operator needs a LIST of values, i.e. whether its input is the multi-line one.
 *
 * @param operator - The filter operator.
 * @returns True for `in` and `notIn`, false for everything else.
 */
export function operatorTakesValues(operator: FilterOperator): boolean {
  return FILTER_OPERATOR_SPECS[operator].takes === 'values';
}

/**
 * Whether an operator's list may name NULL, carried as `includesNull`.
 *
 * @param operator - The filter operator.
 * @returns True for `in` alone; see `FILTER_OPERATOR_SPECS` for why `notIn` is not.
 */
export function operatorListsNull(operator: FilterOperator): boolean {
  return FILTER_OPERATOR_SPECS[operator].listsNull;
}

/**
 * Whether the column's `valueKind` decides how this operator's value reaches the SQL.
 *
 * The renderer reads the same field, so a value input refuses exactly what the renderer
 * refuses. It matters for the text operators: they build a pattern and quote it
 * whatever the column holds, so a numeric column must NOT refuse text typed into one —
 * a refusal there would turn back a filter the renderer accepts.
 *
 * @param operator - The filter operator.
 * @returns True when a numeric column's value must be a number.
 */
export function operatorUsesValueKind(operator: FilterOperator): boolean {
  return FILTER_OPERATOR_SPECS[operator].valueKindApplies;
}

/**
 * What the value field says beneath it for this operator, if anything.
 *
 * @param operator - The filter operator.
 * @returns The hint, or null when the operator needs none.
 */
export function operatorHint(operator: FilterOperator): string | null {
  return FILTER_OPERATOR_SPECS[operator].hint ?? null;
}

/**
 * Whether a column holds text, and so can be asked the text and empty questions.
 *
 * Glue and Athena spell these differently and only one side is normalised, so both
 * spellings are listed here for the reason `filterValueKind` lists both of its own.
 *
 * @param type - The column's Athena or Glue type.
 * @returns True for `string`, `varchar`, `char` and the parameterised forms of the last two.
 */
export function isTextType(type: string): boolean {
  const normalized = type.trim().toLowerCase();
  if (normalized === 'string' || normalized === 'varchar' || normalized === 'char') return true;
  return normalized.startsWith('varchar(') || normalized.startsWith('char(');
}

/**
 * The operators a column of this type offers, in offer order.
 *
 * Derived from the one table rather than listed at each surface: the header menu and the
 * settings dialog both call this, so neither can offer an operator the other does not, and
 * neither can offer one against a column type Trino would reject it on.
 *
 * @param type - The column's Athena or Glue type.
 * @returns The operators to offer, in the order to offer them.
 */
export function operatorsFor(type: string): FilterOperator[] {
  const text = isTextType(type);
  const numeric = filterValueKind(type) === 'number';
  return FILTER_OPERATORS.filter((operator) => {
    const offeredOn = FILTER_OPERATOR_SPECS[operator].offeredOn;
    if (offeredOn === 'any') return true;
    if (offeredOn === 'text') return text;
    return text || numeric;
  });
}

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

/** Refused when the multi-line field holds no value at all. */
export const NO_VALUES_REFUSAL = 'Enter at least one value.';

/** Refused when a text operator is applied with nothing typed; an empty `contains` matches every row. */
export const EMPTY_TEXT_REFUSAL = 'Enter the text to match.';

/** Refused when more distinct values would be stored than one filter may hold. */
export const TOO_MANY_VALUES_REFUSAL = `Enter at most ${EXPLORER_FILTER_VALUES_MAX.toLocaleString('en-US')} values.`;

/**
 * Refused when a line of a numeric column's list is not a number.
 *
 * @param line - The line's 1-based number as the FIELD shows it, blank lines counted.
 * @returns The sentence to show.
 */
export function numericLineRefusal(line: number): string {
  return `Line ${line} is not a number — this column holds numbers.`;
}

/**
 * What a list filter's values look like in the multi-line field: one per line, in stored order.
 *
 * The empty string is left out — a blank line is one the field ignores, so it is carried by
 * the field's (empty) checkbox instead.
 */
export function filterValuesText(values: string[]): string {
  return values.filter((value) => value !== '').join('\n');
}

/**
 * The whole state of the one-value-per-line field: its text, and the two values a line
 * cannot hold, each a checkbox beneath it.
 */
export type ListFieldValue = {text: string; empty: boolean; includesNull: boolean};

/**
 * Pre-fills the list field from a column's filter, so an edit gets back the list it opened.
 *
 * @param filter - The column's filter, or null for a fresh field.
 * @returns The non-empty values one per line in stored order, and the two boxes ticked where
 *   the list holds the empty string or names NULL.
 */
export function listFieldOf(filter: ColumnFilter | null): ListFieldValue {
  const values = filter && operatorTakesValues(filter.operator) ? (filter.values ?? []) : [];
  return {
    text: filterValuesText(values),
    empty: values.includes(''),
    includesNull: filter !== null && operatorListsNull(filter.operator) && filter.includesNull === true
  };
}

/**
 * The ONE reading of the list field, for both surfaces that show it.
 *
 * The lines are parsed by `parseFilterValues`; the empty string joins them when its box is
 * ticked, and NULL only where the operator can list it — a box left ticked while the user
 * switched a row to `is not one of` is dropped rather than stored on an operator that cannot
 * render it. The count refusal counts what reaches the `IN` list, which is the lines and the
 * empty string, never NULL.
 *
 * @param field - The field's text and boxes.
 * @param valueKind - How the column's values reach the SQL.
 * @param operator - The list operator the field is for.
 * @returns The list to store, or the sentence to show instead.
 */
export function readListField(
  field: ListFieldValue,
  valueKind: FilterValueKind,
  operator: FilterOperator
): {values: string[]; includesNull?: true} | {refusal: string} {
  const parsed = parseFilterValues(field.text, valueKind);
  if ('refusal' in parsed) return parsed;
  const values = field.empty && valueKind === 'string' ? [...parsed.values, ''] : parsed.values;
  const includesNull = field.includesNull && operatorListsNull(operator);
  if (values.length === 0 && !includesNull) return {refusal: NO_VALUES_REFUSAL};
  if (values.length > EXPLORER_FILTER_VALUES_MAX) return {refusal: TOO_MANY_VALUES_REFUSAL};
  return includesNull ? {values, includesNull: true} : {values};
}

/**
 * The ONE reading of the multi-line value field's LINES; `readListField` adds its boxes.
 *
 * Both surfaces that offer a list operator reach this, so neither can accept a list the
 * other refuses — and the renderer's own numeric gate is the predicate used, rather than a
 * second numeric rule that could disagree with it. It refuses a bad line and too many lines;
 * whether the list as a whole is empty is `readListField`'s question, since a box can supply
 * its only value.
 *
 * Lines are numbered as the FIELD shows them, blank lines included, because the number in
 * the refusal is what the user counts down to. A line of length zero is ignored; on a
 * numeric column a line is trimmed first and ignored if it is then empty, since surrounding
 * space is never part of a number. A text column's line is a value verbatim, spaces
 * included — a trailing space is something a cell can genuinely hold.
 *
 * @param text - The field's raw text.
 * @param valueKind - How the column's values reach the SQL.
 * @returns The values to store, or the sentence to show instead.
 */
export function parseFilterValues(text: string, valueKind: FilterValueKind): {values: string[]} | {refusal: string} {
  // Split on every line ending, not on `\n` alone: a `\r` left on the end of a value is one
  // the stored-document check refuses, so the tab would restore without the filter.
  const lines = text.split(/\r\n|\r|\n/);
  const values: string[] = [];
  const seen = new Set<string>();
  for (const [index, line] of lines.entries()) {
    if (line === '') continue;
    const value = valueKind === 'number' ? line.trim() : line;
    if (value === '') continue;
    if (valueKind === 'number' && !isBareNumeric(value)) return {refusal: numericLineRefusal(index + 1)};
    if (seen.has(value)) continue;
    seen.add(value);
    values.push(value);
  }
  if (values.length > EXPLORER_FILTER_VALUES_MAX) return {refusal: TOO_MANY_VALUES_REFUSAL};
  return {values};
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

// Each operator is compared on the field it actually READS, and the other is dropped rather than
// compared as absent: a document written before an operator changed can carry a stray `value`
// beside a list, and comparing it would make an apply that changed nothing push a history entry.
// The list itself is compared de-duplicated and sorted the way the renderer sorts it, since that
// is what decides the SQL.
function canonicalCondition(f: ColumnFilter) {
  return {
    column: f.column,
    operator: f.operator,
    value: operatorTakesValue(f.operator) ? (f.value ?? null) : null,
    values: operatorTakesValues(f.operator) ? [...new Set(f.values ?? [])].sort() : null,
    includesNull: operatorListsNull(f.operator) && f.includesNull === true,
    valueKind: f.valueKind ?? 'string'
  };
}

// Every container's items are sorted by their own canonical text, so the order of a list says
// nothing at any depth. Sorting on the FULL text rather than on column and operator is what lets
// two conditions on one column with one operator — `qty > 5` beside `qty > 3` — compare equal in
// either order.
function canonicalItems(items: FilterItem[]): string[] {
  return items
    .map((item) =>
      JSON.stringify(
        isFilterGroup(item) ? {join: item.join, items: canonicalItems(item.items)} : canonicalCondition(item)
      )
    )
    .sort();
}

// Compared on a CANONICAL form rather than field by field: `filters` and `ordering` are
// arrays whose order carries no meaning (priority does), so two descriptions that render
// identical SQL must compare equal or an apply that changed nothing would push a history
// entry and the Back button would step through duplicates.
function canonical(query: ExplorationQuery): string {
  return JSON.stringify({
    filters: canonicalItems(query.filters),
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

// Whether a top-level item is a condition on this column. A group never is, whatever it holds.
function isTopLevelConditionOn(item: FilterItem, column: string): item is ColumnFilter {
  return !isFilterGroup(item) && item.column === column;
}

/**
 * Adds or replaces the column's filter at the TOP LEVEL.
 *
 * Every top-level condition on the column is replaced, and every group is left alone. A second
 * filter set from a menu is far more often a user refining the first than asking for
 * `x = 1 AND x = 2`, so the menus replace — and they stop at the top level because a condition
 * inside an OR group means something the menu cannot show, and changing it would change what
 * the whole group matches. Several conditions on one column, and groups, are built in the
 * filter builder.
 *
 * @param query - The description to edit.
 * @param filter - The filter to apply; its `column` decides what it replaces.
 * @returns A new description.
 */
export function setFilter(query: ExplorationQuery, filter: ColumnFilter): ExplorationQuery {
  const others = query.filters.filter((item) => !isTopLevelConditionOn(item, filter.column));
  // Only the field the operator READS is written, whatever the caller passed: a surface
  // that left a value behind on the way to `is one of` would store a filter carrying both,
  // and the two would then disagree about what the column is filtered by.
  // `includesNull` the same way: kept only where the operator can list NULL and only as
  // `true`, so a row switched to `is not one of` cannot carry it into a render that ignores it.
  const {value, values, includesNull, ...rest} = filter;
  return {
    ...query,
    filters: [
      ...others,
      {
        ...rest,
        ...(operatorTakesValue(filter.operator) ? {value} : {}),
        ...(operatorTakesValues(filter.operator) ? {values} : {}),
        ...(operatorListsNull(filter.operator) && includesNull === true ? {includesNull} : {})
      }
    ]
  };
}

/** Drops the column's top-level conditions, leaving every group as it is. */
export function clearFilter(query: ExplorationQuery, column: string): ExplorationQuery {
  return {...query, filters: query.filters.filter((item) => !isTopLevelConditionOn(item, column))};
}

/**
 * The column's top-level conditions, in the order they are applied.
 *
 * @param query - The description to read.
 * @param column - The column.
 * @returns Every top-level condition naming it; none inside a group.
 */
export function topLevelConditionsOn(query: ExplorationQuery, column: string): ColumnFilter[] {
  return query.filters.filter((item) => isTopLevelConditionOn(item, column));
}

/**
 * The column's filter as a menu shows it: its top-level condition, when that is its only one.
 *
 * Null for two or more, because a single-filter surface that showed one of them would edit it as
 * if it were the whole filter — and `setFilter` would then replace both.
 *
 * @param query - The description to read.
 * @param column - The column.
 * @returns The one top-level condition, else null.
 */
export function filterOf(query: ExplorationQuery, column: string): ColumnFilter | null {
  const conditions = topLevelConditionsOn(query, column);
  return conditions.length === 1 ? conditions[0] : null;
}

function namesColumn(item: FilterItem, column: string): boolean {
  return isFilterGroup(item) ? item.items.some((inner) => namesColumn(inner, column)) : item.column === column;
}

/**
 * Whether any condition, at any depth, filters on the column.
 *
 * What the header's filter mark and its accessible name both read, so the two never disagree about
 * a column whose only conditions sit inside a group.
 *
 * @param query - The description to read.
 * @param column - The column.
 * @returns True when a condition anywhere names it.
 */
export function isFilteredAnywhere(query: ExplorationQuery, column: string): boolean {
  return query.filters.some((item) => namesColumn(item, column));
}

/**
 * Why a column's menu cannot clear its filter, when its conditions are all inside groups.
 *
 * Clear filter acts on the top level only, for the reason `setFilter` gives, so a column filtered
 * only inside a group has nothing there to clear.
 */
export const GROUPED_ONLY_REFUSAL = 'This column’s conditions are inside a group — change them in Filter rows.';

/**
 * What Order and filter shows in place of a column's select when it holds several top-level
 * conditions, which one select cannot show.
 *
 * @param count - How many top-level conditions the column holds.
 * @returns The sentence to show.
 */
export function severalConditionsNote(count: number): string {
  return `${count} conditions — change them in Filter rows`;
}

/**
 * Removes one top-level item — a condition, or a whole group — by its position.
 *
 * @param query - The description to edit.
 * @param index - The item's position at the top level.
 * @returns A new description; the same one when the index is out of range.
 */
export function removeFilterItem(query: ExplorationQuery, index: number): ExplorationQuery {
  if (index < 0 || index >= query.filters.length) return query;
  return {...query, filters: query.filters.filter((_, at) => at !== index)};
}

/**
 * What narrows a column's values listing when a menu asks for it: every other filter and the
 * expression, never the column's own filter.
 *
 * The user is choosing values for this column, so every value the other filters leave must
 * be on offer — including the ones its current filter excludes. Grouping and ordering do not
 * change which values exist, so neither is part of it.
 *
 * @param query - The applied description.
 * @param column - The column whose values are listed.
 * @returns The filters without the column's own top-level conditions, and the expression.
 */
export function narrowingFor(query: ExplorationQuery, column: string): ValuesNarrowing {
  // Only the column's TOP-LEVEL conditions leave: a group stays whole, since dropping one of its
  // conditions would change what the rest of it matches.
  return {filters: query.filters.filter((item) => !isTopLevelConditionOn(item, column)), expression: query.expression};
}

/** How many of a list's values a filter's chip names before it says how many more there are. */
const CHIP_LIST_SHOWN = 3;

/**
 * One column filter in words, as its chip shows it.
 *
 * The operator reads as the menu offers it, so a chip never words a filter differently from the
 * gesture that set it. A value is quoted exactly when the statement quotes it — the same
 * `operatorUsesValueKind` test the renderer applies — so a number column's comparison reads bare
 * and every text value shows its leading and trailing spaces inside the quotes. An empty string
 * reads `(empty)`, as the grid shows one. A list is named in the renderer's de-duplicated, sorted
 * order, so the chip agrees with the SQL rather than with the order the values were typed in,
 * and a list that names NULL says `NULL` after its values.
 *
 * @param filter - A filter from the applied description.
 * @returns E.g. `state equals “NY”`, `qty greater than 5`, `c is one of “a”, “b”, “c” and 2 more`.
 */
export function filterChipLabel(filter: ColumnFilter): string {
  const head = `${filter.column} ${FILTER_OPERATOR_LABELS[filter.operator]}`;
  const bare = filter.valueKind === 'number' && operatorUsesValueKind(filter.operator);
  const shown = (value: string) => (value === '' ? EMPTY_DISPLAY : bare ? value : `“${value}”`);
  if (operatorTakesValue(filter.operator)) return `${head} ${shown(filter.value ?? '')}`;
  if (!operatorTakesValues(filter.operator)) return head;
  // NULL is named LAST, after the values in the renderer's order, as the statement's
  // `OR c IS NULL` follows its `IN` list.
  const names = [...new Set(filter.values ?? [])].sort().map(shown);
  if (operatorListsNull(filter.operator) && filter.includesNull === true) names.push(NULL_DISPLAY);
  const more = names.length - CHIP_LIST_SHOWN;
  return `${head} ${names.slice(0, CHIP_LIST_SHOWN).join(', ')}${more > 0 ? ` and ${more} more` : ''}`;
}

/**
 * One top-level item in words, for its chip.
 *
 * A condition reads as `filterChipLabel` words it. A group reads its items joined by the word its
 * join means, in parentheses, and a group inside it in parentheses of its own — the same brackets
 * the statement carries, so the chip and the SQL agree about what goes with what.
 *
 * @param item - A top-level item of the applied description.
 * @returns E.g. `(region equals “EU” or region equals “US”)`.
 */
export function filterItemLabel(item: FilterItem): string {
  if (!isFilterGroup(item)) return filterChipLabel(item);
  return `(${item.items.map(filterItemLabel).join(item.join === 'or' ? ' or ' : ' and ')})`;
}

// Priorities are re-stamped from the sorted order on every edit, so they stay 0-based and
// CONTIGUOUS. Left alone, clearing the middle of three sorts would leave
// 0 and 2 — which renders the same ORDER BY but shows the user a "3rd" with no second.
function stamp(ordering: SortEntry[]): SortEntry[] {
  return ordering.map((entry, index) => ({...entry, priority: index}));
}

function restamp(ordering: SortEntry[]): SortEntry[] {
  return stamp([...ordering].sort((a, b) => a.priority - b.priority));
}

/**
 * Sorts by a column, appending it at the next priority.
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
 * Moves a sorted column one place up or down the priority list.
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
 * **Grouping mode is exactly "at least one grouping column"** A grouping with no
 * columns is legal SQL — a global aggregate over the whole table — but it is not what the
 * panel is for, and expressing "no columns left" as anything other than "not grouped"
 * would leave the user in a mode with nothing in it.
 *
 * Leaving grouping mode **drops any sort on an aggregate's output column**, which is the
 * half that is easy to miss: `count_all` exists only while the grouping does, so an
 * ORDER BY carrying it onto the ungrouped table is a query Athena rejects — and it would
 * also miss the cached ungrouped execution the rule promises to return to.
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
