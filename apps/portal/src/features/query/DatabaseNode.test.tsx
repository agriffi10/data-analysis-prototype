import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';

vi.mock('./useSchema', () => ({useSchema: vi.fn()}));

import {useSchema} from './useSchema';
import {DatabaseNode} from './DatabaseNode';
import type {TableActions} from './SchemaBrowser';
import type {Connection} from './query.types';

const mockUseSchema = vi.mocked(useSchema);
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
  return render(
    <DatabaseNode
      connection={personal}
      isActive
      defaultExpanded
      onSetActive={vi.fn()}
      onInsert={vi.fn()}
      actions={makeActions()}
      {...props}
    />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSchema.mockReturnValue(mixedSchema);
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
    // Views group is unaffected.
    expect(screen.getByRole('button', {name: 'revenue_view'})).toBeInTheDocument();
  });

  it('shows the create-table guidance for an empty Tables group and "No views." for empty views', () => {
    mockUseSchema.mockReturnValue({
      isPending: false,
      isError: false,
      data: {database: {name: 'alice'}, tables: []}
    } as unknown as SchemaState);
    renderNode();
    expect(screen.getByText(/No tables yet/)).toBeInTheDocument();
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

  it('inserts a column name on click', () => {
    const onInsert = vi.fn();
    renderNode({onInsert});
    fireEvent.click(screen.getByRole('button', {name: 'sales_2026'}));
    fireEvent.click(screen.getByRole('button', {name: /region/}));
    expect(onInsert).toHaveBeenCalledWith('region');
  });

  it('offers view-aware actions for a view row', () => {
    const actions = makeActions({canViewSourceFiles: (t) => t.tableType !== 'VIRTUAL_VIEW'});
    renderNode({actions});
    fireEvent.click(screen.getByRole('button', {name: 'Options for revenue_view'}));
    const menu = screen.getByRole('menu');
    expect(within(menu).getByRole('menuitem', {name: 'Drop view'})).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', {name: 'View source files'})).toBeDisabled();
  });

  it('the active radio is checked and selecting it does not toggle expansion', () => {
    const onSetActive = vi.fn();
    renderNode({onSetActive});
    const radio = screen.getByRole('radio', {name: /Use My workspace as the active database/});
    expect(radio).toHaveAttribute('aria-checked', 'true');
    const disclosure = screen.getByRole('button', {name: /Collapse My workspace/});
    fireEvent.click(radio);
    expect(onSetActive).toHaveBeenCalledWith('alice');
    // Expansion unchanged (still expanded → still "Collapse").
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
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
});
