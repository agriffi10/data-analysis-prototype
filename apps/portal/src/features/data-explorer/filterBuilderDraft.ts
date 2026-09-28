import {isFilterGroup, newExplorationId} from './exploration';
import {
  EMPTY_TEXT_REFUSAL,
  filterValuesText,
  operatorTakesValue,
  operatorTakesValues,
  operatorUsesValueKind,
  parseFilterValues
} from './explorationQueryOps';
import {isBareNumeric} from './renderExplorationSql';
import {NUMERIC_VALUE_REFUSAL} from './FilterValueDialog';
import type {ColumnFilter, FilterItem, FilterJoin, FilterOperator, FilterValueKind} from './dataExplorer.types';

// The builder's staged draft, and every edit it makes, kept pure and apart from the dialog so the
// dialog only renders and dispatches. A draft item carries an `id` the stored filter does not —
// React needs a stable key for a row whose column, operator and value are all being edited — and
// the id never reaches a stored document, because `fromDraft` builds the filter back without it.

/** One condition row as the builder holds it while it is being edited. */
export type DraftCondition = {
  kind: 'condition';
  id: string;
  /** The applied condition this row was made from; null for a row the user added. */
  stored: ColumnFilter | null;
  /** False until the user changes the row; a clean row is handed back as `stored`, untouched. */
  dirty: boolean;
  /** Empty until a column is chosen. */
  column: string;
  /** Empty until a column is chosen, which picks the column's first operator. */
  operator: FilterOperator | '';
  value: string;
  /** A list operator's one-per-line text, held raw so a half-typed line survives until Apply. */
  listText: string;
};

/** One group as the builder holds it. */
export type DraftGroup = {
  kind: 'group';
  id: string;
  join: FilterJoin;
  items: DraftItem[];
};

export type DraftItem = DraftCondition | DraftGroup;

/** Refused when Apply meets a row with no column chosen. */
export const CHOOSE_COLUMN_REFUSAL = 'Choose a column.';

/** Refused when Apply meets a group with nothing in it, which would render `()`. */
export const EMPTY_GROUP_REFUSAL = 'Add a condition to this group, or remove the group.';

function toDraftItem(item: FilterItem): DraftItem {
  if (isFilterGroup(item)) {
    return {kind: 'group', id: newExplorationId(), join: item.join, items: item.items.map(toDraftItem)};
  }
  return {
    kind: 'condition',
    id: newExplorationId(),
    stored: item,
    dirty: false,
    column: item.column,
    operator: item.operator,
    value: item.value ?? '',
    listText: filterValuesText(item.values ?? [])
  };
}

/**
 * The applied filter as a draft the builder can edit.
 *
 * @param filters - The applied top-level items.
 * @returns The same items, each with an id and its stored condition kept beside it.
 */
export function toDraft(filters: FilterItem[]): DraftItem[] {
  return filters.map(toDraftItem);
}

/**
 * A condition row with nothing chosen yet.
 *
 * Starting blank rather than on the first column is deliberate: a default of the first column
 * and `equals` with an empty value is a real filter (`= ''`), and one the user never asked for.
 *
 * @returns The new row.
 */
export function emptyCondition(): DraftCondition {
  return {
    kind: 'condition',
    id: newExplorationId(),
    stored: null,
    dirty: true,
    column: '',
    operator: '',
    value: '',
    listText: ''
  };
}

/**
 * A new group holding one blank condition.
 *
 * @param join - How its items combine; the caller picks the opposite of the group it sits in.
 * @returns The new group.
 */
export function newGroup(join: FilterJoin): DraftGroup {
  return {kind: 'group', id: newExplorationId(), join, items: [emptyCondition()]};
}

/**
 * Replaces one item, found by id at any depth.
 *
 * @param items - A container's items.
 * @param id - The item to replace.
 * @param update - Builds the replacement from the item.
 * @returns New items; the same ones where nothing matched.
 */
export function updateItem(items: DraftItem[], id: string, update: (item: DraftItem) => DraftItem): DraftItem[] {
  return items.map((item) => {
    if (item.id === id) return update(item);
    return item.kind === 'group' ? {...item, items: updateItem(item.items, id, update)} : item;
  });
}

/**
 * Removes one item, found by id at any depth. Removing a group removes everything in it.
 *
 * @param items - A container's items.
 * @param id - The item to remove.
 * @returns New items.
 */
export function removeItem(items: DraftItem[], id: string): DraftItem[] {
  return items
    .filter((item) => item.id !== id)
    .map((item) => (item.kind === 'group' ? {...item, items: removeItem(item.items, id)} : item));
}

/**
 * Appends an item to the top level or to one group.
 *
 * @param items - The top-level items.
 * @param containerId - The group to add to, or null for the top level.
 * @param added - The item to append.
 * @returns New items.
 */
export function addItem(items: DraftItem[], containerId: string | null, added: DraftItem): DraftItem[] {
  if (containerId === null) return [...items, added];
  return updateItem(items, containerId, (group) =>
    group.kind === 'group' ? {...group, items: [...group.items, added]} : group
  );
}

/**
 * A row moved to a new column.
 *
 * The operator is kept when the new column offers it, since `> 5` on one number column is still
 * the question on the next; otherwise it becomes the new column's first. The value is kept either
 * way, as a change of operator keeps it.
 *
 * @param row - The row.
 * @param column - The chosen column.
 * @param offered - The operators that column offers, in offer order.
 * @returns The changed row.
 */
export function withColumn(row: DraftCondition, column: string, offered: FilterOperator[]): DraftCondition {
  const operator = row.operator !== '' && offered.includes(row.operator) ? row.operator : (offered[0] ?? '');
  return {...row, dirty: true, column, operator};
}

/**
 * A row given a new operator. Its single value and its list text both stay where they are, so
 * `= 5` to `> 5` and `is one of` to `is not one of` are one choice each, not a retype.
 *
 * @param row - The row.
 * @param operator - The chosen operator.
 * @returns The changed row.
 */
export function withOperator(row: DraftCondition, operator: FilterOperator): DraftCondition {
  return {...row, dirty: true, operator};
}

/**
 * How a row's value reaches the SQL.
 *
 * A row still on the column it was stored with keeps the stored kind: that column may be one the
 * source no longer lists, and the type lookup would then fall back to text and quote a number
 * Athena compares as one.
 *
 * @param row - The row.
 * @param valueKindOf - How a column's values reach the SQL, from its type.
 * @returns The row's value kind.
 */
export function draftValueKind(row: DraftCondition, valueKindOf: (column: string) => FilterValueKind): FilterValueKind {
  if (row.stored && row.stored.column === row.column) return row.stored.valueKind ?? 'string';
  return valueKindOf(row.column);
}

// A changed row as a filter, or the sentence that refuses it. The predicates are the ones the value
// dialog and Order and filter use, so no surface accepts a value another turns back.
function conditionOf(
  row: DraftCondition,
  valueKindOf: (column: string) => FilterValueKind
): {filter: ColumnFilter} | {refusal: string} {
  if (row.column === '' || row.operator === '') return {refusal: CHOOSE_COLUMN_REFUSAL};
  const valueKind = draftValueKind(row, valueKindOf);
  const base: ColumnFilter = {column: row.column, operator: row.operator, valueKind};
  if (operatorTakesValues(row.operator)) {
    const parsed = parseFilterValues(row.listText, valueKind);
    return 'refusal' in parsed ? parsed : {filter: {...base, values: parsed.values}};
  }
  if (!operatorTakesValue(row.operator)) return {filter: base};
  if (!operatorUsesValueKind(row.operator)) {
    return row.value === '' ? {refusal: EMPTY_TEXT_REFUSAL} : {filter: {...base, value: row.value}};
  }
  if (valueKind === 'number') {
    // Trimmed, as the value dialog trims: surrounding space is never part of a number.
    const trimmed = row.value.trim();
    return isBareNumeric(trimmed) ? {filter: {...base, value: trimmed}} : {refusal: NUMERIC_VALUE_REFUSAL};
  }
  return {filter: {...base, value: row.value}};
}

/**
 * The draft as the filter to apply, or every refusal standing in its way.
 *
 * A row the user did not change comes back as the stored condition itself — every field included,
 * shown by the builder or not — so passing a filter through the builder can never lose part of it.
 *
 * @param items - The draft's top-level items.
 * @param valueKindOf - How a column's values reach the SQL, from its type.
 * @returns The filter, or the refusals keyed by the id of the row or group each belongs to.
 */
export function fromDraft(
  items: DraftItem[],
  valueKindOf: (column: string) => FilterValueKind
): {filters: FilterItem[]} | {refusals: Record<string, string>} {
  const refusals: Record<string, string> = {};
  const build = (list: DraftItem[]): FilterItem[] =>
    list.flatMap((item): FilterItem[] => {
      if (item.kind === 'group') {
        if (item.items.length === 0) refusals[item.id] = EMPTY_GROUP_REFUSAL;
        return [{join: item.join, items: build(item.items)}];
      }
      if (!item.dirty && item.stored) return [item.stored];
      const built = conditionOf(item, valueKindOf);
      if ('refusal' in built) {
        refusals[item.id] = built.refusal;
        return [];
      }
      return [built.filter];
    });
  const filters = build(items);
  return Object.keys(refusals).length > 0 ? {refusals} : {filters};
}
