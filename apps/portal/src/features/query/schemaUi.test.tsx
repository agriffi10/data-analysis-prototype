import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, screen, waitFor, within} from '@testing-library/react';
import {TestProviders, createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import {configValue} from '../../lib/runtimeConfig';
import {DatabaseNode} from './DatabaseNode';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {SchemaBrowser} from './SchemaBrowser';
import type {TableActions} from './SchemaBrowser';
import type {GlueTableSummary} from '../catalog/catalog.types';
import type {Connection} from '../connections/connection.types';
import * as glue from '../catalog/glue.service';

vi.mock('../catalog/glue.service', async (importActual) => {
  const actual = await importActual<typeof glue>();
  return {...actual, getDatabase: vi.fn(), listTables: vi.fn()};
});

// ─── from DatabaseNode.test.tsx ───
describe('DatabaseNode', () => {
  // Integration style (react.md §21): render the REAL DatabaseNode + its real
  // useSchema hook + the real TableActionsMenu, and mock ONLY the AWS boundary —
  // the Glue service (getDatabase/listTables). Schema partitioning, disclosure
  // state and per-node refresh all run for real; assertions are on what the user
  // sees, not on hook call args.
  const mock = vi.mocked(glue);
  const ok = <T,>(data: T) => ({success: true as const, data});

  const table = (name: string, over: Partial<GlueTableSummary> = {}): GlueTableSummary => ({
    name,
    columns: [{name: 'region', type: 'string'}],
    location: `s3://dat-prod-user-space/alice/${name}/`,
    ...over
  });
  const view = (name: string): GlueTableSummary => ({
    name,
    tableType: 'VIRTUAL_VIEW',
    columns: [{name: 'total', type: 'double'}]
  });

  function makeActions(over: Partial<TableActions> = {}): TableActions {
    return {
      onViewSourceFiles: vi.fn(),
      onViewDdl: vi.fn(),
      onViewData: vi.fn(),
      onExploreData: vi.fn(),
      onRefreshTable: vi.fn(),
      onShareTable: vi.fn(),
      onDropTable: vi.fn(),
      canViewSourceFiles: () => true,
      ...over
    };
  }

  const personal: Connection = {id: 'personal', label: 'My workspace', database: 'alice', kind: 'personal'};

  function renderNode(
    props: Partial<React.ComponentProps<typeof DatabaseNode>> = {},
    options: Parameters<typeof renderWithProviders>[1] = {}
  ) {
    return renderWithProviders(
      <DatabaseNode
        connection={personal}
        defaultExpanded
        actions={makeActions()}
        {...props}
      />,
      options
    );
  }

  beforeEach(() => {
    vi.clearAllMocks();
    mock.getDatabase.mockResolvedValue(ok({name: 'alice'}));
    mock.listTables.mockResolvedValue(ok([table('sales_2026'), view('revenue_view')]));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('DatabaseNode', () => {
    it('groups objects into Tables and Views, with no "View" badge on the view row', async () => {
      renderNode();
      expect(await screen.findByRole('button', {name: /Tables \(1\)/})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: /Views \(1\)/})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'revenue_view'})).toBeInTheDocument();
      expect(screen.queryByText('View')).not.toBeInTheDocument();
    });

    it('fetches schema only when expanded (not while collapsed)', async () => {
      const {user} = renderNode({defaultExpanded: false});
      // Collapsed: the schema query is disabled, so no Glue call and no Refresh.
      expect(mock.getDatabase).not.toHaveBeenCalled();
      expect(screen.queryByRole('button', {name: /refresh tables/i})).not.toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: /Expand My workspace/}));
      expect(await screen.findByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
      expect(mock.getDatabase).toHaveBeenCalledWith('alice');
      expect(mock.listTables).toHaveBeenCalledWith('alice');
    });

    it('collapsing hides the groups, and toggling one group hides only it', async () => {
      const {user} = renderNode();
      await screen.findByRole('button', {name: /Tables \(1\)/});

      // Toggling the Tables group hides only its rows.
      await user.click(screen.getByRole('button', {name: /Tables \(1\)/}));
      expect(screen.queryByRole('button', {name: 'sales_2026'})).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'revenue_view'})).toBeInTheDocument();

      // Collapsing the database hides both groups.
      await user.click(screen.getByRole('button', {name: /Collapse My workspace/}));
      expect(screen.queryByRole('button', {name: /Tables \(1\)/})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /Views \(1\)/})).not.toBeInTheDocument();
    });

    it('shows "No tables." / "No views." for an empty database, Views collapsed by default', async () => {
      mock.listTables.mockResolvedValue(ok([]));
      const {user} = renderNode();
      expect(await screen.findByText('No tables.')).toBeInTheDocument();
      // With no views, the Views group defaults collapsed — its empty state is hidden.
      const views = screen.getByRole('button', {name: /Views \(0\)/});
      expect(views).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText('No views.')).not.toBeInTheDocument();
      await user.click(views);
      expect(screen.getByText('No views.')).toBeInTheDocument();
    });

    it('expands a table to show its columns for inspection only (no click-to-insert)', async () => {
      const {user} = renderNode();
      await user.click(await screen.findByRole('button', {name: 'sales_2026'}));
      expect(screen.getByText('region')).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /region/})).not.toBeInTheDocument();
    });

    it('shows the options trigger at rest where the primary input cannot hover', async () => {
      renderNode();
      const trigger = await screen.findByRole('button', {name: 'Options for sales_2026'});
      // jsdom evaluates no media query, so the contract is the class on whatever hides the trigger.
      expect(trigger.closest('.opacity-0')).toHaveClass('[@media(hover:none)]:opacity-100');
    });

    it('offers view-aware actions for a view row and invokes them with (database, table)', async () => {
      const onViewDdl = vi.fn();
      const actions = makeActions({canViewSourceFiles: (_db, t) => t.tableType !== 'VIRTUAL_VIEW', onViewDdl});
      const {user} = renderNode({actions});
      await user.click(await screen.findByRole('button', {name: 'Options for revenue_view'}));
      const menu = screen.getByRole('menu');
      expect(within(menu).getByRole('menuitem', {name: 'Drop view'})).toBeInTheDocument();
      expect(within(menu).getByRole('menuitem', {name: 'View source files'})).toBeDisabled();
      // SPEC-093: views can't be shared — the item is absent, not disabled.
      expect(within(menu).queryByRole('menuitem', {name: 'Share table'})).not.toBeInTheDocument();
      // SPEC-145: a view has no folder to re-read — likewise absent, not disabled.
      expect(within(menu).queryByRole('menuitem', {name: 'Refresh table'})).not.toBeInTheDocument();

      await user.click(within(menu).getByRole('menuitem', {name: 'View DDL'}));
      expect(onViewDdl).toHaveBeenCalledWith(
        'alice',
        expect.objectContaining({name: 'revenue_view', tableType: 'VIRTUAL_VIEW'})
      );
    });

    it('offers Share table on a base table and invokes it with (database, table)', async () => {
      const onShareTable = vi.fn();
      const {user} = renderNode({actions: makeActions({onShareTable})});
      await user.click(await screen.findByRole('button', {name: 'Options for sales_2026'}));
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Share table'}));
      expect(onShareTable).toHaveBeenCalledWith('alice', expect.objectContaining({name: 'sales_2026'}));
    });

    // SPEC-145: the item sits between View data and Share table, and the browser runs
    // no eligibility check of its own — the server owns those and reports them back.
    it('offers Refresh table on a base table and invokes it with (database, table)', async () => {
      const onRefreshTable = vi.fn();
      const {user} = renderNode({actions: makeActions({onRefreshTable})});
      await user.click(await screen.findByRole('button', {name: 'Options for sales_2026'}));
      const items = within(screen.getByRole('menu'))
        .getAllByRole('menuitem')
        .map((item) => item.textContent);
      expect(items).toEqual([
        'View source files',
        'View DDL',
        'View data',
        // SPEC-179: beside View data, and before the two server-side actions.
        'Explore data',
        'Refresh table',
        'Share table',
        'Drop table'
      ]);

      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Refresh table'}));
      expect(onRefreshTable).toHaveBeenCalledWith('alice', expect.objectContaining({name: 'sales_2026'}));
    });

    // SPEC-179 FR-007 AC3. The walking test proves the item DISAPPEARS with the flag off;
    // what only a menu-shaped assertion can prove is that nothing else went with it — a
    // conditional written one bracket wide takes Refresh table and Share table too.
    it('drops only Explore data with the dataExplorer flag off', async () => {
      const client = createTestQueryClient();
      // Seeded through the same key factory the hook reads, with defaults first: the test
      // client runs `gcTime: 0`, so an observer-less seed is evicted before the menu mounts.
      client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
      client.setQueryData(featureFlagKeys.resolved(configValue('environment')), {
        ...FEATURE_FLAG_DEFAULTS,
        dataExplorer: false
      });

      const {user} = renderNode({}, {queryClient: client, seedFeatureFlags: false});
      await user.click(await screen.findByRole('button', {name: 'Options for sales_2026'}));

      const items = within(screen.getByRole('menu'))
        .getAllByRole('menuitem')
        .map((item) => item.textContent);
      expect(items).toEqual([
        'View source files',
        'View DDL',
        'View data',
        'Refresh table',
        'Share table',
        'Drop table'
      ]);
    });

    it('disables Refresh table for a table with no location (no request can be built)', async () => {
      mock.listTables.mockResolvedValue(ok([table('no_files', {location: undefined})]));
      const onRefreshTable = vi.fn();
      const {user} = renderNode({actions: makeActions({onRefreshTable})});
      await user.click(await screen.findByRole('button', {name: 'Options for no_files'}));
      const item = within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Refresh table'});
      expect(item).toBeDisabled();

      await user.click(item);
      expect(onRefreshTable).not.toHaveBeenCalled();
    });

    it('renders a per-node "setting up" state on a NotFound error', async () => {
      mock.getDatabase.mockResolvedValue({
        success: false,
        error: {message: 'Database "alice" does not exist yet.', code: 'NotFound'}
      });
      renderNode();
      expect(await screen.findByText(/Setting up your database/)).toBeInTheDocument();
    });

    // SPEC-086: per-database Refresh re-reads only this node's schema.
    it('re-reads this database on Refresh, reflecting the new table set', async () => {
      mock.listTables.mockResolvedValue(ok([table('old_table', {columns: []})]));
      const {user} = renderNode();
      expect(await screen.findByRole('button', {name: 'old_table'})).toBeInTheDocument();
      expect(mock.listTables).toHaveBeenCalledTimes(1);

      // A refresh picks up a freshly-read table (and drops a removed one).
      mock.listTables.mockResolvedValue(ok([table('new_table', {columns: []})]));
      await user.click(screen.getByRole('button', {name: /refresh tables in My workspace/i}));
      expect(await screen.findByRole('button', {name: 'new_table'})).toBeInTheDocument();
      expect(screen.queryByRole('button', {name: 'old_table'})).not.toBeInTheDocument();
      expect(mock.listTables.mock.calls.length).toBeGreaterThan(1);
    });

    it('disables + spins the Refresh control while a refetch is in flight, re-enabling when it settles', async () => {
      const {user} = renderNode();
      await screen.findByRole('button', {name: 'sales_2026'});

      // Hang the refetch so the in-flight state is observable, then release it.
      let release: (() => void) | undefined;
      mock.getDatabase.mockImplementationOnce(
        () => new Promise((resolve) => (release = () => resolve(ok({name: 'alice'}))))
      );
      await user.click(screen.getByRole('button', {name: /refresh tables in My workspace/i}));
      await waitFor(() => {
        // `toBeDisabled()` IS the contract a user (and a screen reader) meets; the spinner
        // class beside it asserted the same in-flight state a second time, through markup that
        // any equivalent CSS would break (SPEC-154 FR-009).
        expect(screen.getByRole('button', {name: /refresh tables in My workspace/i})).toBeDisabled();
      });

      act(() => release?.());
      await waitFor(() => {
        const btn = screen.getByRole('button', {name: /refresh tables in My workspace/i});
        expect(btn).toBeEnabled();
        expect(btn.querySelector('svg')).not.toHaveClass('animate-spin');
      });
    });
  });
});

// ─── from SchemaBrowser.test.tsx ───
describe('SchemaBrowser', () => {
  // Integration style (react.md §21): render the REAL SchemaBrowser → real
  // DatabaseNode → real useSchema tree and mock ONLY the AWS boundary (the Glue
  // service). Nothing about the rail (disclosure, per-node fetch, action menus)
  // is stubbed.
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
      onExploreData: vi.fn(),
      onRefreshTable: vi.fn(),
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
        // Through the shared stack since SPEC-163: the table row's action menu is gated, so
        // the tree needs the auth context and the seeded flags as well as a query client.
        <TestProviders>
          <SchemaBrowser
            connections={connections}
            actions={makeActions()}
          />
        </TestProviders>,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});
