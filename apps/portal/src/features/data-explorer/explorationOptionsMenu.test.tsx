import {describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {ExplorationOptionsMenu} from './ExplorationOptionsMenu';

/**
 * The toolbar carried thirteen controls and wrapped onto three lines at a laptop width, which
 * made the four that alter the query no easier to find than the nine that do not. These pin the
 * split itself and the one property that had to survive the move: a refused control still says
 * why.
 *
 * The existing suites already drive every moved control THROUGH the menu, so this file does not
 * re-prove that any of them work — only the things that are true of the menu and of nothing else.
 */

const NOOP = () => {};

function props(over: Partial<React.ComponentProps<typeof ExplorationOptionsMenu>> = {}) {
  return {
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
  it('carries every control that does not change which rows are on screen', async () => {
    const {menu} = await open();
    expect(
      within(menu)
        .getAllByRole('menuitem')
        .map((i) => i.textContent)
    ).toEqual([
      'Columns',
      'Colours',
      'Transformers',
      'Value',
      'Calc',
      'Grouping',
      'Copy…',
      'Export',
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

    const item = within(menu).getByRole('menuitem', {name: 'Export'});
    expect(item).toHaveAttribute('aria-disabled', 'true');
    // `aria-disabled`, never `disabled` — a `disabled` item leaves the roving focus order and
    // takes its `title` out of reach of everyone not using a mouse.
    expect(item).not.toHaveAttribute('disabled');
    expect(item).toHaveAttribute('title', 'Nothing to export yet.');

    await user.click(item);
    expect(onExport).not.toHaveBeenCalled();
  });

  // The half of `aria-disabled` that `disabled` would have destroyed: the item stays in the
  // roving focus order, so a keyboard user arrives at it and hears the reason. Opening focus
  // still skips it — landing on a control that does nothing is a worse first impression than
  // landing on one that works.
  it('keeps a refused item reachable by Arrow, while opening focus elsewhere', async () => {
    const {user, menu} = await open({copyRefusal: 'Select some cells first.'});
    const items = within(menu).getAllByRole('menuitem');
    expect(document.activeElement).toBe(items[0]);

    const copy = within(menu).getByRole('menuitem', {name: 'Copy…'});
    for (let i = 0; i < items.indexOf(copy); i += 1) await user.keyboard('{ArrowDown}');

    expect(document.activeElement).toBe(copy);
    expect(copy).toHaveAttribute('title', 'Select some cells first.');
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

  // REMOVED rather than refused: a reason cannot explain a state the user has no way to change.
  it('drops Save as query entirely when the query flag is off', async () => {
    const {menu} = await open({savedQueriesEnabled: false});
    expect(within(menu).queryByRole('menuitem', {name: 'Save as query'})).not.toBeInTheDocument();
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(9);
    // `Create view…` stays: it writes a CATALOG object, not one in the Query workspace's own
    // store, so it does not follow that store's flag.
    expect(within(menu).getByRole('menuitem', {name: 'Create view…'})).toBeInTheDocument();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const {user} = await open();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu', {name: 'Exploration options'})).not.toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Options'}));
  });
});
