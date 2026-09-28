import {EXPLORER_FILTER_VALUES_MAX} from './dataExplorer.constants';
import {operatorListsNull} from './explorationQueryOps';
import {isBareNumeric} from './renderExplorationSql';
import type {ColumnValueCount, FilterValueKind} from './dataExplorer.types';

// The rules the values picker and the dialog around it share: which listed values can be ticked,
// when a selected value and a listed one are the same, and the sentences that say so. Kept apart
// from both so the dialog's "every value kept" test and the picker's ticks cannot disagree.

/** A numeric column's value the renderer would refuse to emit bare, such as `NaN` from a `double`. */
export const UNFILTERABLE_VALUE = 'This value can’t be used as a filter on a numeric column.';

/** A value no list can hold, because the typed field would read it back as two lines. */
export const LINE_BREAK_VALUE = 'This value runs over more than one line, so it can’t be ticked. Use contains instead.';

/** Why the NULL entry is ticked and locked while the list hides the ticked values. */
export const NOT_IN_KEEPS_NO_NULLS = 'Is not one of always leaves out the NULL rows.';

/** Shown when the other filters leave no rows at all. */
export const NO_VALUES_TO_LIST = 'No rows match the other filters, so there are no values to list.';

/** The group of selected values the listing does not hold. */
export const ALSO_SELECTED = 'Also selected';

/**
 * The note under a list cut at the cap.
 *
 * @param valueCount - How many values the column has in all.
 * @returns The sentence.
 */
export function truncationNote(valueCount: number): string {
  return (
    `Showing the ${EXPLORER_FILTER_VALUES_MAX.toLocaleString('en-US')} most common of ` +
    `${valueCount.toLocaleString('en-US')} values. Search looks only at these. To filter on another ` +
    'value, use Filter: is one of… and type it.'
  );
}

/**
 * Whether a selected value and a listed one are the same value.
 *
 * On a numeric column by number, so a filter's `10` is the listing's `10.0`; otherwise as exact
 * text, since `'a '` and `'a'` are different cells.
 *
 * @param valueKind - How the column's values reach the SQL.
 * @param a - One value.
 * @param b - The other.
 * @returns Whether they name the same value.
 */
export function sameValue(valueKind: FilterValueKind, a: string, b: string): boolean {
  if (a === b) return true;
  return valueKind === 'number' && isBareNumeric(a) && isBareNumeric(b) && Number(a) === Number(b);
}

/**
 * Why a listed value cannot be ticked, or null when it can.
 *
 * @param entry - The listed value.
 * @param valueKind - How the column's values reach the SQL.
 * @param operator - The list operator.
 * @returns The reason, or null.
 */
export function refusalOf(
  entry: ColumnValueCount,
  valueKind: FilterValueKind,
  operator: 'in' | 'notIn'
): string | null {
  if (entry.value === null) return operatorListsNull(operator) ? null : NOT_IN_KEEPS_NO_NULLS;
  if (/[\n\r]/.test(entry.value)) return LINE_BREAK_VALUE;
  return valueKind === 'number' && !isBareNumeric(entry.value) ? UNFILTERABLE_VALUE : null;
}
