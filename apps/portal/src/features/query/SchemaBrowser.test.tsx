import {describe, it, expect, vi, beforeEach, afterEach} from 'vitest';
import {screen, within, waitFor} from '@testing-library/react';
import {QueryClientProvider} from '@tanstack/react-query';
import {renderWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {SchemaBrowser, type TableActions} from './SchemaBrowser';
import * as glue from './glue.service';
import type {Connection, GlueTableSummary} from './query.types';

// Integration style (react.md §21): render the REAL SchemaBrowser → real
// DatabaseNode → real useSchema tree and mock ONLY the AWS boundary (the Glue
// service). Nothing about the rail (disclosure, per-node fetch, action menus)
// is stubbed.
vi.mock('./glue.service', async (importActual) => {
  const actual = await importActual<typeof glue>();
  return {...actual, getDatabase: vi.fn(), listTables: vi.fn()};
});

const mock = vi.mocked(glue);
const ok = <T,>(data: T) => ({success: true as const, data});

const salesTable: GlueTableSummary = {
  name: 'sales_2026',
  location: 's3://bucket/alice/sales/',
  columns: [
    {name: 'order_id', type: 'bigint'},
    {name: 'region', type: 'string'}
  ]
};

function makeActions(over: Partial<TableActions> = {}): TableActions {
  return {
    onViewSourceFiles: vi.fn(),
    onViewDdl: vi.fn(),
    onViewData: vi.fn(),
    onShareTable: vi.fn(),
    onDropTable: vi.fn(),
    canViewSourceFiles: () => true,
    ...over
  };
}

const connections: Connection[] = [
  {id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal'},
  {id: 's1', label: 'Project Alpha', database: 'project_alpha', kind: 'shared', status: 'active', role: 'member'}
];

beforeEach(() => {
  vi.clearAllMocks();
  mock.getDatabase.mockImplementation(async (db) => ok({name: db}));
  mock.listTables.mockResolvedValue(ok([salesTable]));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('SchemaBrowser', () => {
  it('expands a lone database by default, showing its tables and non-interactive columns', async () => {
    const {user} = renderWithProviders(
      <SchemaBrowser
        connections={[connections[0]]}
        actions={makeActions()}
      />
    );
    expect(screen.getByRole('button', {name: /Collapse My workspace/})).toHaveAttribute('aria-expanded', 'true');
    await user.click(await screen.findByRole('button', {name: 'sales_2026'}));
    // Columns show for inspection only — no click-to-insert affordance.
    expect(screen.getByText('region')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /region/})).not.toBeInTheDocument();
  });

  it('fires a table action with the node database, without toggling the row', async () => {
    const actions = makeActions();
    const {user} = renderWithProviders(
      <SchemaBrowser
        connections={[connections[0]]}
        actions={actions}
      />
    );
    await user.click(await screen.findByRole('button', {name: 'Options for sales_2026'}));
    // Opening the menu doesn't expand the table row.
    expect(screen.getByRole('button', {name: 'sales_2026'})).toHaveAttribute('aria-expanded', 'false');
    await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'View data'}));
    expect(actions.onViewData).toHaveBeenCalledWith('alice', expect.objectContaining({name: 'sales_2026'}));
  });

  it('expands the first database by default and browses another on demand (no active-database radio)', async () => {
    const {user} = renderWithProviders(
      <SchemaBrowser
        connections={connections}
        actions={makeActions()}
      />
    );
    // First node expanded → fetches its own schema; the rest collapsed.
    await waitFor(() => expect(mock.listTables).toHaveBeenCalledWith('alice'));
    expect(screen.getByRole('button', {name: /Collapse My workspace/})).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', {name: /Expand Project Alpha/})).toHaveAttribute('aria-expanded', 'false');
    // Browse-only: no active-database selection affordance.
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', {name: /Expand Project Alpha/}));
    await waitFor(() => expect(mock.listTables).toHaveBeenCalledWith('project_alpha'));
  });

  it('shows an unusable shared connection but not expandable or selectable (SPEC-052 FR-004)', () => {
    renderWithProviders(
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

  it('has no axe violations', async () => {
    await expectNoA11yViolations(
      <QueryClientProvider client={createTestQueryClient()}>
        <SchemaBrowser
          connections={connections}
          actions={makeActions()}
        />
      </QueryClientProvider>,
      COMPONENT_AXE_OPTIONS
    );
  });
});
