import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';

vi.mock('./useSchema', () => ({useSchema: vi.fn(), invalidateSchema: vi.fn()}));

import {useSchema, invalidateSchema} from './useSchema';
import {DatabaseNode} from './DatabaseNode';
import type {TableActions} from './SchemaBrowser';
import type {Connection} from './query.types';

const mockUseSchema = vi.mocked(useSchema);
const mockInvalidateSchema = vi.mocked(invalidateSchema);
type SchemaState = ReturnType<typeof useSchema>;

function makeActions(over: Partial<TableActions> = {}): TableActions {
  return {
    onViewSourceFiles: vi.fn(),
    onViewDdl: vi.fn(),
    onViewData: vi.fn(),
    onDropTable: vi.fn(),
    canViewSourceFiles: () => true,
    ...over
  };
}

const personal: Connection = {id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal'};

const mixedSchema = {
  isPending: false,
  isError: false,
  data: {
    database: {name: 'alice'},
    tables: [
      {name: 'sales_2026', columns: [{name: 'region', type: 'string'}]},
      {name: 'revenue_view', tableType: 'VIRTUAL_VIEW', columns: [{name: 'total', type: 'double'}]}
    ]
  }
} as unknown as SchemaState;

function renderNode(props: Partial<React.ComponentProps<typeof DatabaseNode>> = {}) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(
    <QueryClientProvider client={client}>
      <DatabaseNode
        connection={personal}
        defaultExpanded
        actions={makeActions()}
        {...props}
      />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSchema.mockReturnValue(mixedSchema);
  mockInvalidateSchema.mockResolvedValue(undefined);
});

describe('DatabaseNode', () => {
  it('partitions objects into Tables and Views groups by tableType', () => {
    renderNode();
    expect(screen.getByRole('button', {name: /Tables \(1\)/})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: /Views \(1\)/})).toBeInTheDocument();
    // The table sits in the Tables group; the view in the Views group — no "View" badge.
    expect(screen.getByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'revenue_view'})).toBeInTheDocument();
    expect(screen.queryByText('View')).not.toBeInTheDocument();
  });

  it('does not fetch schema while collapsed; fetches on expand', () => {
    mockUseSchema.mockReturnValue(mixedSchema);
    renderNode({defaultExpanded: false});
    // Collapsed: useSchema disabled (null).
    expect(mockUseSchema).toHaveBeenCalledWith(null);
    expect(mockUseSchema).not.toHaveBeenCalledWith('alice');

    fireEvent.click(screen.getByRole('button', {name: /Expand My workspace/}));
    expect(mockUseSchema).toHaveBeenCalledWith('alice');
  });

  it('collapsing the database hides both the Tables and Views groups', () => {
    renderNode();
    expect(screen.getByRole('button', {name: /Tables \(1\)/})).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: /Collapse My workspace/}));
    expect(screen.queryByRole('button', {name: /Tables \(1\)/})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /Views \(1\)/})).not.toBeInTheDocument();
  });

  it('toggling a group hides only that group', () => {
    renderNode();
    fireEvent.click(screen.getByRole('button', {name: /Tables \(1\)/}));
    expect(screen.queryByRole('button', {name: 'sales_2026'})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'revenue_view'})).toBeInTheDocument();
  });

  it('shows "No tables." for an empty Tables group and "No views." for empty views', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      data: {database: {name: 'alice'}, tables: []}
    } as unknown as SchemaState);
    renderNode();
    expect(screen.getByText('No tables.')).toBeInTheDocument();
    // Views (0) defaults collapsed; expanding it reveals the empty state.
    fireEvent.click(screen.getByRole('button', {name: /Views \(0\)/}));
    expect(screen.getByText('No views.')).toBeInTheDocument();
  });

  it('defaults Views collapsed when the database has no views', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      data: {database: {name: 'alice'}, tables: [{name: 'sales_2026', columns: []}]}
    } as unknown as SchemaState);
    renderNode();
    // Views (0) header present but its empty state is collapsed by default.
    expect(screen.getByRole('button', {name: /Views \(0\)/})).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('No views.')).not.toBeInTheDocument();
  });

  it('expanding a table reveals its columns as non-interactive rows (no click-to-insert)', () => {
    renderNode();
    fireEvent.click(screen.getByRole('button', {name: 'sales_2026'}));
    // The column name + type show for inspection, but there is no button/insert affordance.
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /region/})).not.toBeInTheDocument();
  });

  it('offers view-aware actions for a view row and invokes them with (database, table)', () => {
    const onViewDdl = vi.fn();
    const actions = makeActions({
      canViewSourceFiles: (t) => t.tableType !== 'VIRTUAL_VIEW',
      onViewDdl
    });
    renderNode({actions});
    fireEvent.click(screen.getByRole('button', {name: 'Options for revenue_view'}));
    const menu = screen.getByRole('menu');
    expect(within(menu).getByRole('menuitem', {name: 'Drop view'})).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', {name: 'View source files'})).toBeDisabled();

    fireEvent.click(within(menu).getByRole('menuitem', {name: 'View DDL'}));
    expect(onViewDdl).toHaveBeenCalledWith(
      'alice',
      expect.objectContaining({name: 'revenue_view', tableType: 'VIRTUAL_VIEW'})
    );
  });

  it('renders a per-node "setting up" state on a NotFound error', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: true,
      error: new Error('Database "alice" does not exist yet.'),
      data: undefined
    } as unknown as SchemaState);
    renderNode();
    expect(screen.getByText(/Setting up your database/)).toBeInTheDocument();
  });

  // SPEC-086: per-database Refresh.
  it('shows a Refresh control on an expanded node', () => {
    renderNode();
    expect(screen.getByRole('button', {name: /refresh tables in My workspace/i})).toBeInTheDocument();
  });

  it('shows no Refresh control while the node is collapsed (nothing loaded to refresh)', () => {
    renderNode({defaultExpanded: false});
    expect(screen.queryByRole('button', {name: /refresh tables/i})).not.toBeInTheDocument();
  });

  it('refreshing invalidates only this database’s schema (scoped)', () => {
    renderNode();
    fireEvent.click(screen.getByRole('button', {name: /refresh tables in My workspace/i}));
    expect(mockInvalidateSchema).toHaveBeenCalledTimes(1);
    expect(mockInvalidateSchema).toHaveBeenCalledWith(expect.anything(), 'alice');
  });

  it('disables + spins the Refresh control while the node’s refetch is in flight', () => {
    mockUseSchema.mockReturnValue({...mixedSchema, isFetching: true} as unknown as SchemaState);
    renderNode();
    const refresh = screen.getByRole('button', {name: /refresh tables in My workspace/i});
    expect(refresh).toBeDisabled();
    expect(refresh.querySelector('svg')).toHaveClass('animate-spin');
  });

  it('re-enables the Refresh control once the refetch settles', () => {
    mockUseSchema.mockReturnValue({...mixedSchema, isFetching: false} as unknown as SchemaState);
    renderNode();
    const refresh = screen.getByRole('button', {name: /refresh tables in My workspace/i});
    expect(refresh).toBeEnabled();
    expect(refresh.querySelector('svg')).not.toHaveClass('animate-spin');
  });

  it('surfaces a freshly-read table after a refresh (drops a removed one)', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      isFetching: false,
      data: {database: {name: 'alice'}, tables: [{name: 'old_table', columns: []}]}
    } as unknown as SchemaState);
    const {rerender} = renderNode();
    expect(screen.getByRole('button', {name: 'old_table'})).toBeInTheDocument();

    // Simulate the refetch returning a new object set (new table in, old table out).
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      isFetching: false,
      data: {database: {name: 'alice'}, tables: [{name: 'new_table', columns: []}]}
    } as unknown as SchemaState);
    rerender(
      <QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}>
        <DatabaseNode
          connection={personal}
          defaultExpanded
          actions={makeActions()}
        />
      </QueryClientProvider>
    );
    expect(screen.getByRole('button', {name: 'new_table'})).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'old_table'})).not.toBeInTheDocument();
  });
});
