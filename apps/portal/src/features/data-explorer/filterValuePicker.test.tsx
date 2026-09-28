import {describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import {useState} from 'react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {FilterValueList} from './FilterValuePicker';
import {CACHE_HIT_TEXT} from './CostIndicator';
import {
  ALSO_SELECTED,
  LINE_BREAK_VALUE,
  NOT_IN_KEEPS_NO_NULLS,
  UNFILTERABLE_VALUE,
  truncationNote
} from './columnValues';
import type {ColumnValuesListing} from './useColumnValues';
import type {ColumnValueCount, FilterValueKind, ValueSelection} from './dataExplorer.types';

const ready = (entries: ColumnValueCount[], over: Partial<Extract<ColumnValuesListing, {status: 'ready'}>> = {}) =>
  ({
    status: 'ready',
    entries,
    valueCount: entries.length,
    truncated: false,
    bytesScanned: 2048,
    fromCache: false,
    ...over
  }) as const;

const BRANDS: ColumnValueCount[] = [
  {value: 'Abilify', count: 40},
  {value: '', count: 3},
  {value: null, count: 2},
  {value: 'Zoloft', count: 1}
];

/** Holds the selection the list reports, as a dialog would, and records every report. */
function render({
  listing = ready(BRANDS) as ColumnValuesListing,
  selection = {values: [], includesNull: false} as ValueSelection,
  operator = 'in' as 'in' | 'notIn',
  valueKind = 'string' as FilterValueKind
} = {}) {
  const reported = vi.fn<(next: ValueSelection) => void>();
  function Host() {
    const [current, setCurrent] = useState(selection);
    return (
      <FilterValueList
        column="brnd_name"
        valueKind={valueKind}
        operator={operator}
        listing={listing}
        totalBytes={8192}
        selection={current}
        onSelectionChange={(next) => {
          reported(next);
          setCurrent(next);
        }}
      />
    );
  }
  return {...renderWithProviders(<Host />), reported};
}

describe('the values list', () => {
  it('names each value with how many rows hold it, NULL and (empty) as the grid shows them', () => {
    render();

    expect(screen.getByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: '(empty), 3 rows'})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'NULL, 2 rows'})).toBeInTheDocument();
    expect(screen.getByRole('checkbox', {name: 'Zoloft, 1 row'})).toBeInTheDocument();
  });

  it('narrows to what the search matches, and Select all shown ticks only those', async () => {
    const {user, reported} = render();

    await user.type(screen.getByLabelText('Search values'), 'abi');
    await user.click(screen.getByRole('button', {name: 'Select all shown'}));

    expect(screen.getAllByRole('checkbox').map((box) => box.getAttribute('aria-label'))).toEqual(['Abilify, 40 rows']);
    expect(reported).toHaveBeenLastCalledWith({values: ['Abilify'], includesNull: false});
  });

  it('keeps a selected value the listing does not hold, ticked or not, under Also selected', async () => {
    const {user, reported} = render({selection: {values: ['Abilify', 'Zyrtec'], includesNull: false}});
    const also = screen.getByRole('group', {name: ALSO_SELECTED});
    expect(screen.getByRole('checkbox', {name: 'Abilify, 40 rows'})).toBeChecked();

    await user.click(within(also).getByRole('checkbox', {name: 'Zyrtec'}));

    expect(reported).toHaveBeenLastCalledWith({values: ['Abilify'], includesNull: false});
    expect(within(also).getByRole('checkbox', {name: 'Zyrtec'})).not.toBeChecked();
  });

  it('ticks a value under Also selected back in', async () => {
    const {user, reported} = render({selection: {values: ['Zyrtec'], includesNull: false}});
    const also = screen.getByRole('group', {name: ALSO_SELECTED});
    await user.click(within(also).getByRole('checkbox', {name: 'Zyrtec'}));

    await user.click(within(also).getByRole('checkbox', {name: 'Zyrtec'}));

    expect(reported).toHaveBeenLastCalledWith({values: ['Zyrtec'], includesNull: false});
  });

  it('shows every selected value under Also selected while the listing is still running', () => {
    render({listing: {status: 'pending'}, selection: {values: ['Abilify'], includesNull: false}});

    expect(
      within(screen.getByRole('group', {name: ALSO_SELECTED})).getByRole('checkbox', {name: 'Abilify'})
    ).toBeChecked();
    expect(screen.getByText('Counting the values…')).toBeInTheDocument();
  });

  it('shows a selected NULL the listing does not hold under Also selected, and unticks it', async () => {
    const {user, reported} = render({
      listing: ready([{value: 'a', count: 3}]),
      selection: {values: ['a'], includesNull: true}
    });
    const also = screen.getByRole('group', {name: ALSO_SELECTED});

    await user.click(within(also).getByRole('checkbox', {name: 'NULL'}));

    expect(reported).toHaveBeenLastCalledWith({values: ['a'], includesNull: false});
    expect(within(also).getByRole('checkbox', {name: 'NULL'})).not.toBeChecked();
  });

  it('shows a selected NULL under Also selected while the listing is still running', () => {
    render({listing: {status: 'pending'}, selection: {values: [], includesNull: true}});

    expect(
      within(screen.getByRole('group', {name: ALSO_SELECTED})).getByRole('checkbox', {name: 'NULL'})
    ).toBeChecked();
  });

  it.each([
    ['cut at the cap', ready(BRANDS, {valueCount: 12_345, truncated: true}), truncationNote(12_345)],
    ['whole', ready(BRANDS), null]
  ])('says whether a list %s is cut short', (_case, listing, note) => {
    render({listing});

    const shown = screen.queryByText(/most common of/);
    if (note === null) expect(shown).not.toBeInTheDocument();
    else expect(shown).toHaveTextContent('Showing the 1,000 most common of 12,345 values.');
  });

  it('matches a number by value, so the filter’s 10 is the listing’s 10.0', () => {
    render({
      listing: ready([{value: '10.0', count: 4}]),
      valueKind: 'number',
      selection: {values: ['10'], includesNull: false}
    });

    expect(screen.getByRole('checkbox', {name: '10.0, 4 rows'})).toBeChecked();
    expect(screen.queryByRole('group', {name: ALSO_SELECTED})).not.toBeInTheDocument();
  });

  it.each([
    ['says what it scanned', ready(BRANDS), 'This query scanned 2.0 KB'],
    ['says a cache hit scanned nothing', ready(BRANDS, {fromCache: true}), CACHE_HIT_TEXT]
  ])('%s', (_case, listing, sentence) => {
    render({listing});

    expect(screen.getByText(new RegExp(sentence))).toBeInTheDocument();
  });
});

describe('the values that cannot be ticked', () => {
  it.each([
    ['a number column’s NaN', ready([{value: 'NaN', count: 1}]), 'number', 'NaN, 1 row', UNFILTERABLE_VALUE],
    ['a value over two lines', ready([{value: 'a\nb', count: 1}]), 'string', 'a\nb, 1 row', LINE_BREAK_VALUE]
  ] as const)(
    'refuses %s, with its reason, and swallows the click',
    async (_case, listing, valueKind, name, reason) => {
      const {user, reported} = render({listing, valueKind});
      const box = screen.getByRole('checkbox', {name});

      await user.click(box);

      expect(box).toHaveAttribute('aria-disabled', 'true');
      expect(box).toHaveAccessibleDescription(reason);
      expect(box).not.toBeChecked();
      expect(reported).not.toHaveBeenCalled();
    }
  );

  it('locks NULL ticked under is not one of, and Clear selection leaves it', async () => {
    const {user} = render({operator: 'notIn'});
    const nullBox = screen.getByRole('checkbox', {name: 'NULL, 2 rows'});
    expect(nullBox).toHaveAccessibleDescription(NOT_IN_KEEPS_NO_NULLS);

    await user.click(screen.getByRole('button', {name: 'Clear selection'}));

    expect(nullBox).toBeChecked();
  });

  it('has no accessibility violations with a refused value on show', async () => {
    const {container} = render({listing: ready([...BRANDS, {value: 'a\nb', count: 1}])});

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
