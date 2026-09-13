import {NavRailProvider} from '../../components/NavRailProvider';
import {QueryWorkspace} from './QueryWorkspace';
import {authenticated} from '../../test/authFixtures';
import {renderWithProviders} from '../../test/renderWithProviders';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {
  LocationProbe,
  NavRailProbe,
  fail,
  installWorkspaceMocks,
  mockGetResults,
  mockGetRowCount,
  mockGetStatus,
  mockListSaved,
  mockReadSaved,
  mockRunQuery,
  ok,
  queueRuns,
  renderWorkspace,
  resetViewport,
  savedListing,
  seedSingle,
  statusMap
} from '../../test/queryWorkspaceSupport';
import {catalogKeys} from '../catalog/catalogKeys';

// The below-`tablet` surface, driven through the workspace: the browse-first home, the results
// view and the crossing back up.
vi.mock('./SqlEditor', () => import('../../test/sqlEditorStub'));

// ── AWS service boundary (the only real seam) ────────────────────────────────
vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  stopQuery: vi.fn(),
  getTableDdl: vi.fn(),
  runStatementToCompletion: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn(),
  getQueryRowCount: vi.fn()
}));

vi.mock('../catalog/glue.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/glue.service')>()),
  getDatabase: vi.fn(),
  listTables: vi.fn()
}));

vi.mock('./queryHistory.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./queryHistory.service')>()),
  getQueryHistory: vi.fn(),
  appendQueryHistory: vi.fn(),
  updateQueryHistoryEntry: vi.fn()
}));

vi.mock('../saved-queries/savedQueries.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../saved-queries/savedQueries.service')>()),
  // The name/key helpers stay REAL — a tab label and a list row must not be able to
  // disagree about what a file is called, and a mocked `savedQueryName` would hide it.
  ensureSavedQueriesFolder: vi.fn(),
  listSavedQueries: vi.fn(),
  readSavedQuery: vi.fn(),
  writeSavedQuery: vi.fn(),
  deleteSavedQuery: vi.fn()
}));

vi.mock('../shared-spaces/sharedSpaces.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../shared-spaces/sharedSpaces.service')>()),
  readSharedConnectionsCache: vi.fn()
}));

vi.mock('../file-browser/fileBrowser.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser/fileBrowser.service')>()),
  copyObject: vi.fn(),
  listFiles: vi.fn()
}));

vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));

vi.mock('../table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));

describe('QueryWorkspace responsive (SPEC-100)', () => {
  beforeEach(installWorkspaceMocks);
  afterEach(resetViewport);

  /** Renders inside a NavRailProvider so the mobile drawer's contextual slot is observable. */
  function renderMobileWorkspace() {
    window.innerWidth = 390;
    return renderWithProviders(
      <NavRailProvider>
        <QueryWorkspace />
        <NavRailProbe />
        <LocationProbe />
      </NavRailProvider>,
      {auth: authenticated('alice')}
    );
  }

  it('pares the workspace to a browse-first surface below tablet — no editor, toolbar or tab strip', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    renderMobileWorkspace();

    // Saved is the default surface (FR-004).
    expect(await screen.findByRole('button', {name: 'Run saved query Revenue'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Saved'})).toHaveAttribute('aria-pressed', 'true');

    expect(screen.queryByLabelText('SQL editor')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Run statement'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Clear query'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Create view'})).not.toBeInTheDocument();
    expect(screen.queryByRole('tablist', {name: 'Query tabs'})).not.toBeInTheDocument();
  });

  it('moves the schema rail off-canvas below tablet, and keeps it inline above', async () => {
    const {unmount} = renderMobileWorkspace();
    // Not in the inline layout…
    expect(screen.queryByRole('complementary', {name: 'Schema browser'})).not.toBeInTheDocument();
    // …but the same tree is handed to the mobile nav drawer's contextual slot.
    const rail = await screen.findByLabelText('mobile nav rail');
    expect(await within(rail).findByRole('button', {name: 'Collapse alice'})).toBeInTheDocument();
    expect(await within(rail).findByText('sales_2026')).toBeInTheDocument();
    unmount();

    window.innerWidth = 1024;
    renderWorkspace();
    expect(await screen.findByRole('complementary', {name: 'Schema browser'})).toBeInTheDocument();
  });

  it('runs a saved query from a card and shows row cards with a pager', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    // The card carries no SQL — the file is read when the card is CHOSEN (FR-006).
    mockReadSaved.mockResolvedValue(ok('SELECT region FROM alice.sales'));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

    // The shared run path, not a mobile-only one.
    await waitFor(() =>
      expect(mockRunQuery).toHaveBeenCalledWith({sql: 'SELECT region FROM alice.sales', username: 'alice'})
    );
    expect(await screen.findByRole('heading', {name: 'Revenue'})).toBeInTheDocument();
    // One card per row of the page, read-only SQL, and a fixed pager.
    expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Row 1')).getByText('us-east')).toBeInTheDocument();
    expect(screen.queryByLabelText('SQL editor')).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();

    // Back returns to the browse-first home.
    await user.click(screen.getByRole('button', {name: 'Back to queries'}));
    expect(await screen.findByRole('button', {name: 'Run saved query Revenue'})).toBeInTheDocument();
  });

  // The mobile view is handed the workspace's one total, and its pager no longer combines a second
  // one of its own — so this wiring is the only thing keeping its strip and pager on the grid. The
  // default page is the last page (two rows, no token), so its own count must win over Athena's 5.
  it('shows the pager’s own total over a disagreeing count, as the desktop does', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    mockReadSaved.mockResolvedValue(ok('SELECT region FROM alice.sales'));
    mockGetRowCount.mockResolvedValue(ok({rowCount: 5, pending: false}));
    const {user, queryClient} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

    await waitFor(() => expect(queryClient.getQueryData(catalogKeys.rowCount('q-1'))).toBe(5));
    expect(await screen.findByText(/2 rows ·/)).toBeInTheDocument();
    expect(screen.getByText(/Rows 1–2 of 2/)).toBeInTheDocument();
    expect(screen.queryByText(/5 rows/)).not.toBeInTheDocument();
  });

  // The mobile surface submits the WHOLE buffer at `script-single`, so a saved query holding
  // more than one statement lands here too. A trailing DDL earns no result tab, so the row
  // cards keep showing the SELECT while the tab's status has moved on to the CREATE — and the
  // status bar is the same component the editor shell renders. There is no tab strip to flip,
  // which is exactly why nothing else can see this call site.
  it('reports the displayed statement in the status bar, not a trailing DDL', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    mockReadSaved.mockResolvedValue(ok('SELECT region FROM alice.sales; CREATE TABLE alice.t (id int);'));
    queueRuns('q-1', 'q-2');
    statusMap['q-1'] = {dataScannedBytes: 8192, engineExecutionTimeMillis: 1750};
    statusMap['q-2'] = {dataScannedBytes: 1024, engineExecutionTimeMillis: 250};
    mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
      ok({
        columns: [{name: 'region', type: 'string'}],
        rows: queryExecutionId === 'q-1' ? [['us-east'], ['eu-west']] : [['ap-south']]
      })
    );
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

    await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByText(/scanned ·/)).toHaveTextContent('2 rows · 8.0 KB scanned · 1.8s'));
  });

  // Mobile passes `canSaveResults={false}` outright — there is no destination-picker flow
  // below tablet. Pinned because the desktop affordance widened to every terminal state and
  // nothing else asserts the divergence, so mobile could gain or lose it unnoticed.
  it('offers no Save results below tablet, even on a succeeded run', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
    expect(await screen.findByText('Succeeded')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Save results to my files'})).not.toBeInTheDocument();
  });

  it('never shows one query’s results under another query’s name', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue', 'Costs'));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
    expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: 'Back to queries'}));

    // The second run never reaches Athena, so no run is installed on the tab.
    mockRunQuery.mockResolvedValueOnce(fail('Rate exceeded', 'ThrottlingException'));
    await user.click(await screen.findByRole('button', {name: 'Run saved query Costs'}));

    expect(await screen.findByRole('heading', {name: 'Costs'})).toBeInTheDocument();
    expect(await screen.findByText('Query failed.')).toBeInTheDocument();
    // Costs' failure must not be dressed in Revenue's succeeded status or rows.
    expect(screen.queryByLabelText('Row 1')).not.toBeInTheDocument();
    expect(screen.queryByText('Succeeded')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Prev'})).not.toBeInTheDocument();
  });

  it('says why in the results view when a run’s status cannot be read', async () => {
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    queueRuns('q-1');
    mockGetStatus.mockResolvedValue(fail('raw: execution q-1 is outside alice/', 'NotFound'));
    const {user} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));

    expect(await screen.findByRole('heading', {name: 'Revenue'})).toBeInTheDocument();
    expect(await screen.findByText('That item no longer exists. Refresh and try again.')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.queryByText(/is outside alice/)).not.toBeInTheDocument();
  });

  it('runs a table’s data from the drawer into the mobile results view', async () => {
    const {user} = renderMobileWorkspace();
    const rail = await screen.findByLabelText('mobile nav rail');

    await user.click(await within(rail).findByRole('button', {name: 'Options for sales_2026'}));
    await user.click(await screen.findByRole('menuitem', {name: 'View data'}));

    // On a phone there is no editor tab to open into — the run has to land
    // somewhere the user can see it.
    expect(await screen.findByRole('heading', {name: 'sales_2026'})).toBeInTheDocument();
    expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();
    expect(mockRunQuery).toHaveBeenCalledWith({sql: 'SELECT * FROM alice.sales_2026', username: 'alice'});
  });

  it('hands a tab back to the editor cleanly when the viewport grows past tablet', async () => {
    seedSingle('SELECT my_unsaved_draft');
    mockListSaved.mockResolvedValue(savedListing('Revenue'));
    const {user, rerender} = renderMobileWorkspace();

    await user.click(await screen.findByRole('button', {name: 'Run saved query Revenue'}));
    expect(await screen.findByLabelText('Row 1')).toBeInTheDocument();

    // Rotate/resize past the breakpoint: `useBreakpoint` re-reads the width on
    // the next render, so re-rendering the same tree crosses the tier.
    window.innerWidth = 1400;
    rerender(
      <NavRailProvider>
        <QueryWorkspace />
        <NavRailProbe />
      </NavRailProvider>
    );

    // The editor holds the draft, so it must not wear the mobile run's results —
    // nor claim the run returned nothing. The run itself is still in history.
    expect(await screen.findByLabelText('SQL editor')).toHaveValue('SELECT my_unsaved_draft');
    expect(screen.getByText('Run a query to see results.')).toBeInTheDocument();
    expect(screen.queryByText('The run finished without returning rows.')).not.toBeInTheDocument();
    expect(screen.queryByText('us-east')).not.toBeInTheDocument();
  });
});

// ── SPEC-154 FR-001: table share, driven end to end ─────────────────────────
//
// `enqueueTableShare` was mocked in this file and never asserted, and the flow's three
// fragments each tested a stub: `TableShareDialog.test.tsx` asserted a `vi.fn()` prop,
// `useTableShare.test.ts` was a bare `renderHook`, `DatabaseNode.test.tsx` asserted
// `onShareTable` was called. Every half was green and the WIRE between them was untested — a
// dialog that never mounts, a wrong `source`, or a dropped `onSubmit` all passed.
//
// Structured on the SPEC-145 refresh block above, deliberately: menu → dialog → submit →
// service → toast, plus the failure path and the control's absence where it must not appear.
