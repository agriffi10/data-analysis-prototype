import {describe, expect, it, vi} from 'vitest';
import {cleanup, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {ExplorationOptionsMenu} from './ExplorationOptionsMenu';

/**
 * The toolbar carried thirteen controls and wrapped onto three lines at a laptop width. A first
 * pass moved the nine that do not change which rows are on screen; user feedback then asked for
 * the rest, so the bar now keeps only undo/redo and the view switch. These pin the resulting
 * split and the one property that had to survive both moves: a refused control still says why.
 *
 * The existing suites already drive every moved control THROUGH the menu, so this file does not
 * re-prove that any of them work — only the things that are true of the menu and of nothing else.
 */

const NOOP = () => {};

function props(over: Partial<React.ComponentProps<typeof ExplorationOptionsMenu>> = {}) {
  return {
    onOrderAndFilter: NOOP,
    clearAllLabel: 'Remove all filters and sorts',
    onClearAll: NOOP,
    onFilterByCell: NOOP,
    onColumns: NOOP,
    onColours: NOOP,
    onTransformers: NOOP,
    onCopy: NOOP,
    onExport: NOOP,
    valueOpen: false,
    onToggleValue: NOOP,
    calcOpen: false,
    onToggleCalc: NOOP,
    groupingOpen: false,
    onToggleGrouping: NOOP,
    savedQueriesEnabled: true,
    onSaveQuery: NOOP,
    createViewEnabled: true,
    onCreateView: NOOP,
    ...over
  };
}

async function open(over: Partial<React.ComponentProps<typeof ExplorationOptionsMenu>> = {}) {
  const user = userEvent.setup({delay: null});
  renderWithProviders(<ExplorationOptionsMenu {...props(over)} />);
  await user.click(screen.getByRole('button', {name: 'Options'}));
  return {user, menu: screen.getByRole('menu', {name: 'Exploration options'})};
}

describe('the Data Explorer options menu', () => {
  it('carries every action, query-changing ones first', async () => {
    const {menu} = await open();
    expect(
      within(menu)
        .getAllByRole('menuitem')
        .map((i) => i.textContent)
    ).toEqual([
      // The query-changing group leads: these are what the screen is for.
      'Order and filter',
      'Remove all filters and sorts',
      'Filter by this value',
      'Columns',
      'Colors',
      'Transformers',
      'Value',
      'Calc',
      'Grouping',
      'Copy…',
      'Save results…',
      'Save as query',
      // The sibling of the one above it: `Save as query` writes a `.sql` file into a space,
      // `Create view…` writes a view into the catalog. It sits here rather than in the source
      // picker's Create section because a view is made from a statement, and the picker has
      // none — the statement is the thing in front of the user on this screen.
      'Create view…'
    ]);
  });

  // The reason a refusal had to survive the move: an item that merely greyed out inside a menu
  // is strictly worse than the button it replaced, because the reason is now further from the
  // user rather than closer.
  it('refuses an item with its reason reachable, and drops the handler', async () => {
    const onExport = vi.fn();
    const {user, menu} = await open({onExport, exportRefusal: 'Nothing to export yet.'});

    const item = within(menu).getByRole('menuitem', {name: 'Save results…'});
    expect(item).toHaveAttribute('aria-disabled', 'true');
    // `aria-disabled`, never `disabled` — a `disabled` item leaves the roving focus order and
    // takes its `title` out of reach of everyone not using a mouse.
    expect(item).not.toHaveAttribute('disabled');
    expect(item).toHaveAttribute('title', 'Nothing to export yet.');

    await user.click(item);
    expect(onExport).not.toHaveBeenCalled();
  });

  // The half of `aria-disabled` that `disabled` would have destroyed: the item stays in the
  // roving order, so a keyboard user reaches it and hears the reason.
  //
  // The OPENING-focus skip is not asserted here and cannot be: no item this menu can refuse is
  // ever first, so any assertion about `items[0]` holds with the skip reverted. It is pinned in
  // `Menu`'s own suite, where the item list is the fixture.
  it('keeps a refused item reachable by Arrow', async () => {
    const {user, menu} = await open({copyRefusal: 'Select some cells first.'});
    const items = within(menu).getAllByRole('menuitem');
    const copy = within(menu).getByRole('menuitem', {name: 'Copy…'});

    for (let i = 0; i < items.indexOf(copy); i += 1) await user.keyboard('{ArrowDown}');

    expect(document.activeElement).toBe(copy);
    expect(copy).toHaveAttribute('title', 'Select some cells first.');
  });

  // Focus must not fall to `document.body` — the item unmounts with the menu, so releasing it
  // there restarts the next Tab from the top of the page (WCAG 2.4.3). Invisible while every
  // item opened a dialog; not invisible once items opened side panels.
  it('returns focus to the trigger after a selection', async () => {
    const {user, menu} = await open();
    await user.click(within(menu).getByRole('menuitem', {name: 'Columns'}));
    expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Options'}));
  });

  // `menuitem` carries no pressed state, and `menuitemcheckbox` is the wrong shape: these open
  // panels rather than setting an option, and two are the same gesture as the panel's own close
  // button. So the state is in the label, where a screen reader gets it for free.
  it.each([
    ['valueOpen', 'Hide the value panel', 'Value'],
    ['calcOpen', 'Hide Calc', 'Calc'],
    ['groupingOpen', 'Hide Grouping', 'Grouping']
  ])('says a toggle’s state in its label (%s)', async (flag, whenOpen, whenClosed) => {
    const {menu} = await open({[flag]: true});
    expect(within(menu).getByRole('menuitem', {name: whenOpen})).toBeInTheDocument();
    expect(within(menu).queryByRole('menuitem', {name: whenClosed})).not.toBeInTheDocument();
  });

  // REMOVED rather than refused, both of them: a reason cannot explain a state the user has no
  // way to change. They follow the SAME flag — creating a Glue view is a Query capability
  // wherever the control lives, so exempting this one would hand it back through another door.
  it('drops both Query capabilities when the query flag is off', async () => {
    const {menu: withFlag} = await open();
    const enabledCount = within(withFlag).getAllByRole('menuitem').length;
    cleanup();

    const {menu} = await open({savedQueriesEnabled: false, createViewEnabled: false});
    expect(within(menu).queryByRole('menuitem', {name: 'Save as query'})).not.toBeInTheDocument();
    expect(within(menu).queryByRole('menuitem', {name: 'Create view…'})).not.toBeInTheDocument();
    // Derived from the flag-on render rather than written as a literal: the point is that
    // EXACTLY those two went, and a hard-coded number has to be edited by whoever adds an
    // unrelated item — at which moment the cheapest fix is to bump it, which is also the one
    // that stops it noticing a third item vanishing.
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(enabledCount - 2);
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const {user} = await open();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', {name: 'Exploration options'})).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Options'}));
  });
});
