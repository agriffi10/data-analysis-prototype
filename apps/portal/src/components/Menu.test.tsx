import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import {Menu, type MenuItem} from './Menu';
import {renderWithProviders} from '../test/renderWithProviders';

describe('Menu', () => {
  // The first item is the Query rail's: its table menu leads with "View source files", natively
  // disabled for every view. A disabled button cannot take focus, so while it sat in the roving
  // order, Arrow Up from the next item and Arrow Down from the last each went nowhere.
  it('steps Arrow keys past a natively disabled item and wraps, but keeps an aria-disabled one', async () => {
    const items: MenuItem[] = [
      {kind: 'action', label: 'View source files', onSelect: vi.fn(), disabled: true},
      {kind: 'action', label: 'View DDL', onSelect: vi.fn()},
      {kind: 'action', label: 'Share table', onSelect: vi.fn(), disabledReason: 'Only the owner can share it'},
      {kind: 'action', label: 'Refresh table', onSelect: vi.fn(), disabled: true},
      {kind: 'action', label: 'Export table', onSelect: vi.fn(), disabled: true},
      {kind: 'separator'},
      {kind: 'action', label: 'Drop view', onSelect: vi.fn(), tone: 'danger'}
    ];
    const {user} = renderWithProviders(
      <Menu
        ariaLabel="Actions for orders"
        items={items}
        trigger={({open, toggle, ref}) => (
          <button
            ref={ref}
            type="button"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={toggle}>
            Table actions
          </button>
        )}
      />,
      {auth: null}
    );
    await user.click(screen.getByRole('button', {name: 'Table actions'}));
    const focusTrail: Array<string | null> = [document.activeElement?.textContent ?? null];

    // Opening lands on "View DDL", the second item. The last step crosses two disabled items in a
    // row, so skipping a single one would not reach "Drop view".
    for (const key of ['{ArrowUp}', '{ArrowDown}', '{ArrowDown}', '{ArrowDown}']) {
      await user.keyboard(key);
      focusTrail.push(document.activeElement?.textContent ?? null);
    }

    expect(focusTrail).toEqual(['View DDL', 'Drop view', 'View DDL', 'Share table', 'Drop view']);
  });
});
