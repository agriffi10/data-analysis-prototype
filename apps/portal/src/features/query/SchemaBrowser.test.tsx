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
    expect(screen.getByRole('button', { name: 'sales_2026' })).toHaveAttribute('aria-expanded', 'false');

    const menu = screen.getByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', { name: 'View data' }));
    expect(actions.onViewData).toHaveBeenCalledWith(expect.objectContaining({ name: 'sales_2026' }));
  });

  it('disables View source files when the location is out of the user space', () => {
    const actions = makeActions({ canViewSourceFiles: () => false });
    mockUseSchema.mockReturnValue(tableSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={actions} />);

    fireEvent.click(screen.getByRole('button', { name: 'Options for sales_2026' }));
    expect(screen.getByRole('menuitem', { name: 'View source files' })).toBeDisabled();
  });

  it('closes the menu on Escape', () => {
    mockUseSchema.mockReturnValue(tableSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={makeActions()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Options for sales_2026' }));
    expect(screen.getByRole('menu')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  // --- SPEC-047 database switcher ---

  const connections = [
    { id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal' as const },
    {
      id: 's1',
      label: 'Project Alpha',
      database: 'project_alpha',
      kind: 'shared' as const,
      status: 'active' as const,
      role: 'member' as const,
    },
  ];

  it('keys the schema query off the active database', () => {
    mockUseSchema.mockReturnValue(tableSchema);
    render(
      <SchemaBrowser
        database="project_alpha"
        connections={connections}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    expect(mockUseSchema).toHaveBeenCalledWith('project_alpha');
  });

  it('lists the databases and marks the active one with aria-current', () => {
    mockUseSchema.mockReturnValue(tableSchema);
    render(
      <SchemaBrowser
        database="alice"
        connections={connections}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    const active = screen.getByRole('button', { name: /My workspace/ });
    expect(active).toHaveAttribute('aria-current', 'true');
    // The non-active one carries no aria-current (state conveyed, not color-only).
    expect(screen.getByRole('button', { name: 'Project Alpha' })).not.toHaveAttribute('aria-current');
  });

  it('selecting a different database calls onSelectDatabase', () => {
    const onSelectDatabase = vi.fn();
    mockUseSchema.mockReturnValue(tableSchema);
    render(
      <SchemaBrowser
        database="alice"
        connections={connections}
        onSelectDatabase={onSelectDatabase}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Project Alpha' }));
    expect(onSelectDatabase).toHaveBeenCalledWith('project_alpha');
  });

  it('shows a provisioning shared connection disabled, not selectable (SPEC-052 FR-004)', () => {
    const onSelectDatabase = vi.fn();
    mockUseSchema.mockReturnValue(tableSchema);
    render(
      <SchemaBrowser
        database="alice"
        connections={[
          connections[0],
          {
            id: 's2',
            label: 'Project Beta',
            database: 'project_beta',
            kind: 'shared' as const,
            status: 'provisioning' as const,
            role: 'owner' as const,
          },
        ]}
        onSelectDatabase={onSelectDatabase}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    const beta = screen.getByRole('button', { name: /Project Beta/ });
    expect(beta).toBeDisabled();
    expect(beta).toHaveTextContent('Provisioning');
    fireEvent.click(beta);
    expect(onSelectDatabase).not.toHaveBeenCalled();
  });

  // --- SPEC-048 views ---

  const viewSchema = {
    isPending: false,
    isError: false,
    data: {
      database: { name: 'alice' },
      tables: [
        {
          name: 'revenue_view',
          tableType: 'VIRTUAL_VIEW',
          columns: [{ name: 'total', type: 'double' }],
        },
      ],
    },
  } as unknown as SchemaState;

  it('renders a view with a View badge', () => {
    mockUseSchema.mockReturnValue(viewSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={makeActions()} />);
    expect(screen.getByText('View')).toBeInTheDocument();
    // The row toggle's accessible name leads with the view name (the badge follows).
    expect(screen.getByRole('button', { name: /^revenue_view/ })).toBeInTheDocument();
  });

  it('a view row offers "Drop view" and a disabled "View source files"', () => {
    // Mirrors the workspace wiring: a view has no S3 location → source files off.
    const actions = makeActions({
      canViewSourceFiles: (t) => t.tableType !== 'VIRTUAL_VIEW',
    });
    mockUseSchema.mockReturnValue(viewSchema);
    render(<SchemaBrowser database="alice" onInsert={vi.fn()} actions={actions} />);

    fireEvent.click(screen.getByRole('button', { name: 'Options for revenue_view' }));
    const menu = screen.getByRole('menu');
    expect(within(menu).getByRole('menuitem', { name: 'Drop view' })).toBeInTheDocument();
    expect(within(menu).queryByRole('menuitem', { name: 'Drop table' })).not.toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: 'View source files' })).toBeDisabled();
  });

  it('shows a single current item with only the personal database', () => {
    mockUseSchema.mockReturnValue(tableSchema);
    render(
      <SchemaBrowser
        database="alice"
        connections={[connections[0]]}
        onSelectDatabase={vi.fn()}
        onInsert={vi.fn()}
        actions={makeActions()}
      />
    );
    const dbList = screen.getByRole('list', { name: 'Databases' });
    expect(within(dbList).getAllByRole('button')).toHaveLength(1);
    expect(within(dbList).getByRole('button', { name: /My workspace/ })).toHaveAttribute('aria-current', 'true');
  });
});
