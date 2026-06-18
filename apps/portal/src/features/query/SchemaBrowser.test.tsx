import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('./useSchema', () => ({ useSchema: vi.fn() }));

import { useSchema } from './useSchema';
import { SchemaBrowser } from './SchemaBrowser';

const mockUseSchema = vi.mocked(useSchema);

type SchemaState = ReturnType<typeof useSchema>;

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
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} />);
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

    render(<SchemaBrowser database="alice" onInsert={onInsert} />);

    // Expand the table, then click a column.
    fireEvent.click(screen.getByRole('button', { name: /sales_2026/ }));
    fireEvent.click(screen.getByRole('button', { name: /region/ }));
    expect(onInsert).toHaveBeenCalledWith('region');
  });

  it('shows a no-tables hint when the database is empty', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      data: { database: { name: 'alice' }, tables: [] },
    } as unknown as SchemaState);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} />);
    expect(screen.getByText(/No tables yet/)).toBeInTheDocument();
  });

  it('shows a friendly "setting up" state when the database is not found', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: true,
      error: new Error('Database "alice" does not exist yet.'),
      data: undefined,
    } as unknown as SchemaState);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} />);
    expect(screen.getByText(/Setting up your database/)).toBeInTheDocument();
  });
});
