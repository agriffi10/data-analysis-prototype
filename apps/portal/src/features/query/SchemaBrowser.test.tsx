import {describe, it, expect, vi, beforeEach} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';

vi.mock('./useSchema', () => ({useSchema: vi.fn()}));

import {useSchema} from './useSchema';
import {SchemaBrowser, type TableActions} from './SchemaBrowser';
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

const tableSchema = {
  isPending: false,
  isError: false,
  data: {
    database: {name: 'alice'},
    tables: [
      {
        name: 'sales_2026',
        location: 's3://bucket/alice/sales/',
        columns: [
          {name: 'order_id', type: 'bigint'},
          {name: 'region', type: 'string'}
        ]
      }
    ]
  }
} as unknown as SchemaState;

const connections: Connection[] = [
  {id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal'},
  {id: 's1', label: 'Project Alpha', database: 'project_alpha', kind: 'shared', status: 'active', role: 'member'}
];

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSchema.mockReturnValue(tableSchema);
});

describe('SchemaBrowser', () => {
  // --- single-database default (the common case) ---

  it('renders a single database expanded by default with its Tables group', () => {
    render(
      <SchemaBrowser
        connections={[connections[0]]}
        actions={makeActions()}
      />
    );
    expect(screen.getByRole('button', {name: /Collapse My workspace/})).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
  });

  it('shows columns as non-interactive rows (browse-only, no click-to-insert)', () => {
    render(
      <SchemaBrowser
        connections={[connections[0]]}
        actions={makeActions()}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'sales_2026'}));
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /region/})).not.toBeInTheDocument();
  });

  it('opens the options menu and fires an action with the node database, without toggling expand', () => {
    const actions = makeActions();
    render(
      <SchemaBrowser
        connections={[connections[0]]}
        actions={actions}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Options for sales_2026'}));
    expect(screen.getByRole('button', {name: 'sales_2026'})).toHaveAttribute('aria-expanded', 'false');
    const menu = screen.getByRole('menu');
    fireEvent.click(within(menu).getByRole('menuitem', {name: 'View data'}));
    expect(actions.onViewData).toHaveBeenCalledWith('alice', expect.objectContaining({name: 'sales_2026'}));
  });

  // --- multiple databases (browse-only, no active selection) ---

  it('expands the first (personal) database by default and fetches its schema', () => {
    render(
      <SchemaBrowser
        connections={connections}
        actions={makeActions()}
      />
    );
    // First node expanded by default → fetches its own schema; the rest collapsed.
    expect(mockUseSchema).toHaveBeenCalledWith('alice');
    expect(screen.getByRole('button', {name: /Collapse My workspace/})).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', {name: /Expand Project Alpha/})).toHaveAttribute('aria-expanded', 'false');
  });

  it('expands another database to browse it (no active-database radio)', () => {
    render(
      <SchemaBrowser
        connections={connections}
        actions={makeActions()}
      />
    );
    // No active-database selection affordance at all.
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: /Expand Project Alpha/}));
    expect(mockUseSchema).toHaveBeenCalledWith('project_alpha');
  });

  it('shows an unusable shared connection but not expandable or selectable (SPEC-052 FR-004)', () => {
    render(
      <SchemaBrowser
        connections={[
          connections[0],
          {
            id: 's2',
            label: 'Project Beta',
            database: 'project_beta',
            kind: 'shared',
            status: 'provisioning',
            role: 'owner'
          }
        ]}
        actions={makeActions()}
      />
    );
    expect(screen.getByText('Project Beta')).toBeInTheDocument();
    expect(screen.getByText(/Provisioning/)).toBeInTheDocument();
    // No disclosure toggle for the unusable node.
    expect(screen.queryByRole('button', {name: /Project Beta/})).not.toBeInTheDocument();
  });

  // --- accessibility ---

  it('has no axe violations', async () => {
    await expectNoA11yViolations(
      <SchemaBrowser
        connections={connections}
        actions={makeActions()}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
