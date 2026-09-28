import {useId, useState, type RefObject} from 'react';
import {Button} from '../../components/Button';
import {ErrorBanner} from '../../components/ErrorBanner';
import {Input} from '../../components/Input';
import {REFUSED_CONTROL} from '../../components/fieldStyles';
import {cx} from '../../lib/cx';
import {CostIndicator} from './CostIndicator';
import {EMPTY_DISPLAY, NULL_DISPLAY} from './cellText';
import {ALSO_SELECTED, NO_VALUES_TO_LIST, refusalOf, sameValue, truncationNote} from './columnValues';
import {operatorListsNull} from './explorationQueryOps';
import {useColumnValues, type ColumnValuesListing} from './useColumnValues';
import type {
  ColumnValueCount,
  ExplorationSource,
  FilterValueKind,
  ValueSelection,
  ValuesNarrowing
} from './dataExplorer.types';

const displayOf = (value: string | null) => (value === null ? NULL_DISPLAY : value === '' ? EMPTY_DISPLAY : value);

export type FilterValueListProps = {
  column: string;
  valueKind: FilterValueKind;
  operator: 'in' | 'notIn';
  listing: ColumnValuesListing;
  /** The asking tab's running total, for the cost line. */
  totalBytes: number;
  selection: ValueSelection;
  onSelectionChange: (next: ValueSelection) => void;
  /** The search field, for a dialog that focuses it on open. */
  searchRef?: RefObject<HTMLInputElement | null>;
};

/**
 * A column's values as checkboxes, most common first, each with how many rows hold it.
 *
 * Presentational: it is handed the listing and runs no query, so search, *Select all shown* and
 * *Clear selection* cost nothing. What it keeps for itself is *Also selected* — every value that
 * has been selected while it is open and that no entry holds — so a value outside the listing is
 * never dropped from a filter silently, and an untick can be undone. While the listing is still
 * running every selected value is there, which is what lets a dialog apply before it lands.
 *
 * A value that cannot be ticked is refused by `aria-disabled` with its reason beside it, not by
 * `disabled`, so the reason stays reachable; the click is swallowed.
 */
export function FilterValueList({
  column,
  valueKind,
  operator,
  listing,
  totalBytes,
  selection,
  onSelectionChange,
  searchRef
}: FilterValueListProps) {
  const listId = useId();
  const [search, setSearch] = useState('');
  const [seen, setSeen] = useState<string[]>(selection.values);
  const unseen = selection.values.filter((value) => !seen.includes(value));
  if (unseen.length > 0) setSeen([...seen, ...unseen]);

  const entries = listing.status === 'ready' ? listing.entries : [];
  const needle = search.trim().toLowerCase();
  const shown =
    needle === '' ? entries : entries.filter((entry) => displayOf(entry.value).toLowerCase().includes(needle));
  const alsoSelected = seen.filter(
    (value) => !entries.some((entry) => entry.value !== null && sameValue(valueKind, entry.value, value))
  );

  const isSelected = (value: string) => selection.values.some((selected) => sameValue(valueKind, selected, value));
  const entryTicked = (entry: ColumnValueCount) =>
    entry.value === null ? !operatorListsNull(operator) || selection.includesNull : isSelected(entry.value);

  const toggleEntry = (entry: ColumnValueCount) => {
    if (refusalOf(entry, valueKind, operator) !== null) return;
    if (entry.value === null) {
      onSelectionChange({...selection, includesNull: !selection.includesNull});
      return;
    }
    const value = entry.value;
    onSelectionChange({
      ...selection,
      values: isSelected(value)
        ? selection.values.filter((selected) => !sameValue(valueKind, selected, value))
        : [...selection.values, value]
    });
  };

  const toggleAlso = (value: string) =>
    onSelectionChange({
      ...selection,
      values: selection.values.includes(value)
        ? selection.values.filter((selected) => selected !== value)
        : [...selection.values, value]
    });

  const selectAllShown = () => {
    const ticked = shown.filter((entry) => refusalOf(entry, valueKind, operator) === null);
    const values = [...selection.values];
    for (const entry of ticked) if (entry.value !== null && !isSelected(entry.value)) values.push(entry.value);
    const includesNull = selection.includesNull || ticked.some((entry) => entry.value === null);
    onSelectionChange({values, includesNull});
  };

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <Input
        ref={searchRef}
        label="Search values"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          variant="default"
          size="sm"
          onClick={selectAllShown}>
          Select all shown
        </Button>
        <Button
          variant="default"
          size="sm"
          onClick={() => onSelectionChange({values: [], includesNull: false})}>
          Clear selection
        </Button>
      </div>

      {listing.status === 'pending' && <p className="text-sm text-text-3">Counting the values…</p>}
      {listing.status === 'error' && (
        <div className="flex flex-col items-start gap-2">
          <ErrorBanner
            error={listing.error}
            role="status"
          />
          {listing.tryAgain && (
            <Button
              variant="default"
              size="sm"
              onClick={listing.tryAgain}>
              Try again
            </Button>
          )}
        </div>
      )}
      {listing.status === 'ready' && entries.length === 0 && <p className="text-sm text-text-2">{NO_VALUES_TO_LIST}</p>}
      {listing.status === 'ready' && listing.truncated && (
        <p className="text-xs text-text-2">{truncationNote(listing.valueCount)}</p>
      )}

      {entries.length > 0 && (
        <fieldset className="max-h-64 overflow-y-auto rounded-md border border-border">
          <legend className="sr-only">{`Values of ${column}`}</legend>
          <ul className="divide-y divide-border">
            {shown.map((entry, index) => {
              const refusal = refusalOf(entry, valueKind, operator);
              const reasonId = `${listId}-reason-${index}`;
              const count = `${entry.count.toLocaleString('en-US')} ${entry.count === 1 ? 'row' : 'rows'}`;
              return (
                <li key={entry.value ?? '\u0000null'}>
                  <label
                    className={cx(
                      'flex min-h-[32px] items-center gap-2 px-3 py-1 text-sm',
                      refusal !== null && 'cursor-not-allowed'
                    )}>
                    <input
                      type="checkbox"
                      className={REFUSED_CONTROL}
                      checked={entryTicked(entry)}
                      aria-label={`${displayOf(entry.value)}, ${count}`}
                      aria-disabled={refusal !== null || undefined}
                      aria-describedby={refusal !== null ? reasonId : undefined}
                      onChange={() => toggleEntry(entry)}
                    />
                    <span
                      aria-hidden="true"
                      // A long value is cut to the row; its whole text is a hover away, so two values
                      // sharing a long prefix can still be told apart.
                      title={displayOf(entry.value)}
                      className={cx(
                        'min-w-0 flex-1 truncate',
                        entry.value === null || entry.value === '' || refusal !== null ? 'text-text-3' : 'text-text',
                        (entry.value === null || entry.value === '') && 'italic'
                      )}>
                      {displayOf(entry.value)}
                    </span>
                    <span
                      aria-hidden="true"
                      className="flex-none tabular-nums text-xs text-text-3">
                      {count}
                    </span>
                  </label>
                  {refusal !== null && (
                    <p
                      id={reasonId}
                      className="px-3 pb-1 text-xs text-text-3">
                      {refusal}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </fieldset>
      )}

      {alsoSelected.length > 0 && (
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-text-2">{ALSO_SELECTED}</legend>
          <ul className="flex flex-col">
            {alsoSelected.map((value) => (
              <li key={value}>
                <label className="flex min-h-[32px] items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selection.values.includes(value)}
                    onChange={() => toggleAlso(value)}
                  />
                  <span
                    title={displayOf(value)}
                    className={cx('min-w-0 truncate', value === '' ? 'italic text-text-3' : 'text-text')}>
                    {displayOf(value)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
      )}

      <CostIndicator
        bytesScanned={listing.status === 'ready' ? listing.bytesScanned : null}
        fromCache={listing.status === 'ready' && listing.fromCache}
        totalBytes={totalBytes}
      />
    </div>
  );
}

export type FilterValuePickerProps = {
  source: ExplorationSource;
  column: string;
  valueKind: FilterValueKind;
  operator: 'in' | 'notIn';
  /** What narrows the listing — the caller's decision; see `ValuesNarrowing`. */
  narrowing: ValuesNarrowing;
  selection: ValueSelection;
  onSelectionChange: (next: ValueSelection) => void;
  /** The search field, for a dialog that focuses it on open. */
  searchRef?: RefObject<HTMLInputElement | null>;
};

/**
 * The inline values picker: lists a column's values and lets the user tick some, for a list
 * operator to filter by.
 *
 * **Mounting it is the billed gesture** — it asks the workspace for the listing — so a surface
 * mounts it only on an explicit user action, never merely because a row with a list operator is
 * on screen. It has no dialog chrome, so a filter dialog and a condition builder can each embed it.
 */
export function FilterValuePicker({
  source,
  column,
  valueKind,
  operator,
  narrowing,
  selection,
  onSelectionChange,
  searchRef
}: FilterValuePickerProps) {
  const {listing, totalBytes} = useColumnValues({source, narrowing, column});
  return (
    <FilterValueList
      column={column}
      valueKind={valueKind}
      operator={operator}
      listing={listing}
      totalBytes={totalBytes}
      selection={selection}
      onSelectionChange={onSelectionChange}
      searchRef={searchRef}
    />
  );
}
