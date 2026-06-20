import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';

vi.mock('./useSchema', () => ({ useSchema: vi.fn() }));

import { useSchema } from './useSchema';
import { SchemaBrowser, type TableActions } from './SchemaBrowser';

const mockUseSchema = vi.mocked(useSchema);

type SchemaState = ReturnType<typeof useSchema>;

function makeActions(over: Partial<TableActions> = {}): TableActions {
  return {
    onViewSourceFiles: vi.fn(),
    onViewDdl: vi.fn(),
    onViewData: vi.fn(),
    onDropTable: vi.fn(),
    canViewSourceFiles: () => true,
    ...over,
  };
}

const tableSchema = {
  isPending: false,
  isError: false,
  data: {
    database: { name: 'alice' },
    tables: [
      {
        name: 'sales_2026',
        location: 's3://bucket/alice/sales/',
        columns: [
          { name: 'order_id', type: 'bigint' },
          { name: 'region', type: 'string' },
        ],
      },
    ],
  },
} as unknown as SchemaState;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SchemaBrowser', () => {
  it('shows a loading state while pending', () => {
    mockUseSchema.mockReturnValue({
      isPending: true,
      isError: false,
      data: undefined,
    } as unknown as SchemaState);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={makeActions()} />);
    expect(screen.getByText(/Loading schema/)).toBeInTheDocument();
  });

  it('lists tables and inserts a column name on click', () => {
    const onInsert = vi.fn();
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        database: { name: 'alice' },
        tables: [
          {
            name: 'sales_2026',
            columns: [
              { name: 'order_id', type: 'bigint' },
              { name: 'region', type: 'string' },
            ],
          },
        ],
      },
    } as unknown as SchemaState);

    render(<SchemaBrowser database="alice" onInsert={onInsert} actions={makeActions()} />);

    // Expand the table, then click a column.
    fireEvent.click(screen.getByRole('button', { name: 'sales_2026' }));
    fireEvent.click(screen.getByRole('button', { name: /region/ }));
    expect(onInsert).toHaveBeenCalledWith('region');
  });

  it('shows a no-tables hint when the database is empty', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      data: { database: { name: 'alice' }, tables: [] },
    } as unknown as SchemaState);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={makeActions()} />);
    expect(screen.getByText(/No tables yet/)).toBeInTheDocument();
  });

  it('shows a friendly "setting up" state when the database is not found', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: true,
      error: new Error('Database "alice" does not exist yet.'),
      data: undefined,
    } as unknown as SchemaState);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={makeActions()} />);
    expect(screen.getByText(/Setting up your database/)).toBeInTheDocument();
  });

  // --- SPEC-044 table options menu ---

  it('opens the options menu and fires each action (without toggling expand)', () => {
    const actions = makeActions();
    mockUseSchema.mockReturnValue(tableSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={actions} />);

    // Opening the menu must not expand the table row.
    fireEvent.click(screen.getByRole('button', { name: 'Options for sales_2026' }));
    expect(
      screen.getByRole('button', { name: 'sales_2026' }),
    ).toHaveAttribute('aria-expanded', 'false');

    const menu = screen.getByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'View data' }));
    expect(actions.onViewData).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'sales_2026' }),
    );
  });

  it('disables View source files when the location is out of the user space', () => {
    const actions = makeActions({ canViewSourceFiles: () => false });
    mockUseSchema.mockReturnValue(tableSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={actions} />);

    fireEvent.click(screen.getByRole('button', { name: 'Options for sales_2026' }));
    expect(
      screen.getByRole('menuitem', { name: 'View source files' }),
    ).toBeDisabled();
  });

  it('closes the menu on Escape', () => {
    mockUseSchema.mockReturnValue(tableSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={makeActions()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Options for sales_2026' }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });
});
