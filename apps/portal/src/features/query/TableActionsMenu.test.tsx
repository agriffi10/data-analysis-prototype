import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TableActionsMenu, type TableMenuItem } from './TableActionsMenu';

function items(over: Partial<Record<string, () => void>> = {}): TableMenuItem[] {
  return [
    { key: 'a', label: 'View data', onSelect: over.a ?? vi.fn() },
    {
      key: 'b',
      label: 'Drop table',
      onSelect: over.b ?? vi.fn(),
      danger: true,
      separatorBefore: true,
    },
  ];
}

describe('TableActionsMenu', () => {
  it('is closed initially and opens on click', () => {
    render(<TableActionsMenu tableName="sales" items={items()} />);
    const trigger = screen.getByRole('button', { name: 'Options for sales' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('fires the item onSelect and closes', () => {
    const onSelect = vi.fn();
    render(<TableActionsMenu tableName="sales" items={items({ a: onSelect })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Options for sales' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'View data' }));
    expect(onSelect).toHaveBeenCalled();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes on Escape and on outside click', () => {
    render(
      <div>
        <button>outside</button>
        <TableActionsMenu tableName="sales" items={items()} />
      </div>,
    );
    const open = () =>
      fireEvent.click(screen.getByRole('button', { name: 'Options for sales' }));

    open();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    open();
    fireEvent.mouseDown(screen.getByRole('button', { name: 'outside' }));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('moves focus between items with arrow keys', () => {
    render(<TableActionsMenu tableName="sales" items={items()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Options for sales' }));

    const first = screen.getByRole('menuitem', { name: 'View data' });
    const second = screen.getByRole('menuitem', { name: 'Drop table' });
    expect(first).toHaveFocus(); // first item focused on open

    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowDown' });
    expect(second).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'ArrowUp' });
    expect(first).toHaveFocus();
  });
});
