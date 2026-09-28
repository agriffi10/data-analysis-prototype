import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {DEFAULT_RESULTS_PAGE_SIZE, QUERY_TABS_MAX, SAVE_RESULTS_STATEMENT_REFUSAL} from './query.constants';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS, ROW_COUNT_PAGE_SIZE} from '../catalog/catalog.constants';
import {withFakeTimers} from '../../test/fakeTimers';
import {
  editor,
  fail,
  installWorkspaceMocks,
  mockAppend,
  mockCopyObject,
  mockDeleteSaved,
  mockEnqueueRefresh,
  mockEnqueueShare,
  mockGetHistory,
  mockGetResults,
  mockGetRowCount,
  mockGetStatus,
  mockGetTableDdl,
  mockListFiles,
  mockListSaved,
  mockReadCache,
  mockReadSaved,
  mockRunQuery,
  mockRunToCompletion,
  mockStopQuery,
  mockUpdate,
  mockWriteSaved,
  ok,
  openTableMenu,
  queueRuns,
  renderWorkspace,
  resetViewport,
  runScriptSingle,
  runScriptTabs,
  salesTable,
  savedFile,
  savedListing,
  seedSingle,
  seedTabs,
  statusMap,
  succeeded
} from '../../test/queryWorkspaceSupport';
import {MemoryRouter} from 'react-router';
import {createTestQueryClient} from '../../test/renderWithProviders';
import {QueryClient, QueryClientProvider, onlineManager} from '@tanstack/react-query';
import {authValue} from '../../test/authFixtures';
import {politeAnnouncements} from '../../test/liveRegions';
import {getDatabase, listTables} from '../catalog/glue.service';
import {runQuery} from '../catalog/athena.service';
import {getQueryHistory} from './queryHistory.service';
import {
  ensureSavedQueriesFolder,
  listSavedQueries,
  savedQueryKey,
  savedQueryName
} from '../saved-queries/savedQueries.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {objectExists} from '../file-browser/fileBrowser.service';
import {QueryWorkspace} from './QueryWorkspace';
import {ROUTE_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {ToastProvider} from '../../components/ToastProvider';
import {AuthContext} from '../auth/authContext';
import {queryKeys} from './queryKeys';
import {savedQueryKeys} from '../saved-queries/savedQueryKeys';
import {catalogKeys} from '../catalog/catalogKeys';
import {connectionKeys} from '../connections/connectionKeys';
import type {ReactElement} from 'react';

// Integration style (react.md §21): render the REAL QueryWorkspace tree — real hooks and real
// child components — mocking ONLY the AWS service boundary; the pure helpers stay real via
// importOriginal. The editor stub, the fixtures and the render live in
// `src/test/queryWorkspaceSupport.tsx`; the divider and the below-`tablet` surface have suites
// of their own beside this one.
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
  listFiles: vi.fn(),
  objectExists: vi.fn()
}));

vi.mock('../table-share/tableShare.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-share/tableShare.service')>()),
  enqueueTableShare: vi.fn()
}));

vi.mock('../table-builder/tableBuild.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../table-builder/tableBuild.service')>()),
  enqueueTableRefresh: vi.fn()
}));

describe('QueryWorkspace', () => {
  beforeEach(installWorkspaceMocks);
  afterEach(resetViewport);

  describe('QueryWorkspace', () => {
    it('renders the real schema rail + tabs and runs the active statement to a result set (SPEC-077 shape)', async () => {
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();

      // Real SchemaBrowser → DatabaseNode fetched sales_2026 from the mocked glue boundary.
      expect(await screen.findByRole('button', {name: 'sales_2026'})).toBeInTheDocument();
      await screen.findByLabelText('SQL editor');
      expect(screen.getByRole('tab', {name: /Query 1/})).toBeInTheDocument();
      // History sits on the global bar; Saved queries sits in the toolbar beside Save, and keeps
      // its words in the tablet band, where the toolbar's other labels are hidden.
      expect(within(screen.getByRole('button', {name: 'Saved queries'})).getByText('Saved queries')).not.toHaveClass(
        'hidden'
      );
      expect(within(screen.getByRole('button', {name: 'Save query'})).getByText('Save')).toHaveClass('hidden');
      expect(screen.getAllByRole('button', {name: /History/})).toHaveLength(1);
      expect(screen.getByRole('button', {name: 'Save query'})).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(await screen.findByText('Succeeded')).toBeInTheDocument();
      expect(await screen.findByText('us-east')).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      // No execution-database context — just sql + username (fully-qualified tables).
      expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 1', username: 'alice'});
      expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('database');
      expect(mockAppend).toHaveBeenCalledWith('alice', expect.objectContaining({sql: 'SELECT 1'}));
    });

    // SPEC-150 FR-010. The keybindings themselves are SqlEditor.test's subject; what
    // this asserts is the other half — that the workspace actually HANDS the editor a
    // handler for each of SPEC-078's three scopes. Deleting one at the call site used
    // to change nothing any test could observe, because the stub discarded them.
    it('wires all three SPEC-078 run scopes into the editor', async () => {
      seedSingle('SELECT 1');
      renderWorkspace();
      await screen.findByLabelText('SQL editor');

      expect(screen.getByRole('button', {name: 'editor: Run Statement'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'editor: Run Script → single result'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'editor: Run Script → tab per statement'})).toBeInTheDocument();
    });

    it('de-dupes a rapid double-submit and keeps Clear/Run disabled while in flight [SPEC-083 FR-009]', async () => {
      seedSingle('SELECT 1');
      statusMap['q-1'] = {state: 'RUNNING'}; // stays in flight
      let resolveRun: (v: Awaited<ReturnType<typeof runQuery>>) => void = () => {};
      mockRunQuery.mockReturnValue(new Promise((resolve) => (resolveRun = resolve)));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      const run = screen.getByRole('button', {name: 'Run statement'});
      await user.click(run);
      await user.click(run); // second trigger before the run is recorded
      expect(mockRunQuery).toHaveBeenCalledTimes(1);

      resolveRun(ok({queryExecutionId: 'q-1'}));
      expect(await screen.findByRole('button', {name: /Stop/})).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('button', {name: 'Clear query'})).toBeDisabled();
    });

    it('offers Copy and Download only when the tab has SQL to copy', async () => {
      seedSingle('');
      renderWorkspace();
      await screen.findByLabelText('SQL editor');

      expect(screen.getByRole('button', {name: 'Copy query'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Download query'})).toBeDisabled();
    });

    it('downloads the active tab’s SQL as a .sql file named after the saved query it holds', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(ok('SELECT region\nFROM alice.sales;'));
      // jsdom has no object URLs, and an anchor click there navigates; the file is what the
      // browser is handed, so the blob and the anchor are captured instead. The stubs stay in
      // place: the revoke runs a minute after the click, after this test has finished.
      const blobs: Blob[] = [];
      Object.assign(URL, {
        createObjectURL: (blob: Blob) => (blobs.push(blob), 'blob:query'),
        revokeObjectURL: () => {}
      });
      const anchors: HTMLAnchorElement[] = [];
      const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
        this: HTMLAnchorElement
      ) {
        anchors.push(this);
      });
      try {
        const {user} = renderWorkspace();
        await screen.findByLabelText('SQL editor');
        await user.click(screen.getByRole('button', {name: 'Saved queries'}));
        await user.click(await screen.findByRole('button', {name: 'Open saved query Revenue'}));
        await screen.findByRole('tab', {name: /Revenue/});

        await user.click(screen.getByRole('button', {name: 'Download query'}));

        expect(anchors.map((a) => [a.download, a.getAttribute('href')])).toEqual([['Revenue.sql', 'blob:query']]);
        expect(await blobs[0].text()).toBe('SELECT region\nFROM alice.sales;');
      } finally {
        click.mockRestore();
      }
    });

    it('copies the whole of the active tab’s SQL from the toolbar', async () => {
      seedSingle('SELECT region, count(*)\nFROM alice.sales\nGROUP BY region');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Copy query'}));

      expect(await navigator.clipboard.readText()).toBe('SELECT region, count(*)\nFROM alice.sales\nGROUP BY region');
      expect(await screen.findByText('Query copied')).toBeInTheDocument();
    });

    it('surfaces a runQuery error in a danger banner and keeps Run available', async () => {
      seedSingle('SELECT bad');
      // `InvalidRequestException` is the name Athena actually returns for a rejected
      // StartQueryExecution, and it carries no code rule — so this exercises the ENGINE-MESSAGE
      // path, which is what the assertion below is about. (The bare `InvalidRequest` this used
      // to send is now one of the API's declared codes, and a code rule wins over a message
      // match by design.)
      mockRunQuery.mockResolvedValue(fail('COLUMN_NOT_FOUND: amont', 'InvalidRequestException'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      // SPEC-106: friendly, mapped guidance — never the raw Athena engine text.
      expect(await screen.findByText(/A column in your query wasn’t found/)).toBeInTheDocument();
      expect(screen.queryByText(/COLUMN_NOT_FOUND/)).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Run statement'})).toBeInTheDocument();
    });

    it('shows Athena’s own words for a failed statement once Details is opened', async () => {
      const engineText = 'TYPE_MISMATCH: line 1:28: Cannot apply operator: varchar = integer';
      queueRuns('q-1');
      statusMap['q-1'] = {state: 'FAILED', stateChangeReason: engineText};
      seedSingle('SELECT * FROM alice.t WHERE name = 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      const banner = (await screen.findByText('Athena couldn’t run this query. Check the SQL and try again.')).closest(
        '[role="alert"]'
      ) as HTMLElement;
      await user.click(within(banner).getByText('Details'));

      expect(within(banner).getByText(engineText).closest('details')).toHaveAttribute('open');
      expect(within(banner).queryByText(/Contact the Administrator/)).not.toBeInTheDocument();
    });

    it('restores tabs from persisted state on mount, showing the active tab', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT one;'},
          {id: 'b', label: 'Scratch', sql: 'SELECT two;'}
        ],
        activeTabId: 'b',
        nextQueryNumber: 2
      });
      renderWorkspace();

      expect(await screen.findByLabelText('SQL editor')).toHaveValue('SELECT two;');
      expect(screen.getByRole('tab', {name: /Scratch/})).toHaveAttribute('aria-selected', 'true');
    });

    it('opens a new blank Query 2 tab and isolates text per tab', async () => {
      seedSingle('SELECT a');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      expect(editor()).toHaveValue('SELECT a');

      await user.click(screen.getByRole('button', {name: 'New query tab'}));
      expect(screen.getByRole('tab', {name: /Query 2/})).toBeInTheDocument();
      expect(editor()).toHaveValue(''); // a blank second tab
      await user.type(editor(), 'SELECT b');

      await user.click(screen.getByRole('tab', {name: /Query 1/}));
      expect(editor()).toHaveValue('SELECT a');
      await user.click(screen.getByRole('tab', {name: /Query 2/}));
      expect(editor()).toHaveValue('SELECT b');
    });

    it('closes an empty tab immediately but confirms a non-empty one', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
          {id: 'b', label: 'Query 2', sql: ''},
          {id: 'c', label: 'Query 3', sql: 'SELECT bye;'}
        ],
        activeTabId: 'a',
        nextQueryNumber: 4
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByTitle('Close Query 2'));
      expect(screen.queryByRole('tab', {name: /Query 2/})).not.toBeInTheDocument();

      await user.click(screen.getByTitle('Close Query 3'));
      const dialog = await screen.findByRole('alertdialog', {name: /confirm close tab/i});
      await user.click(within(dialog).getByRole('button', {name: 'Close tab'}));
      expect(screen.queryByRole('tab', {name: /Query 3/})).not.toBeInTheDocument();
    });

    // Focus moves to the next tab after a close, so a held Delete's repeats would close tab after tab.
    it('closes one tab for one held Delete', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: ''},
          {id: 'b', label: 'Query 2', sql: ''},
          {id: 'c', label: 'Query 3', sql: ''},
          {id: 'd', label: 'Query 4', sql: ''}
        ],
        activeTabId: 'd',
        nextQueryNumber: 5
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      screen.getByRole('tab', {name: /Query 4/}).focus();

      await user.keyboard('{Delete>6/}');

      expect(screen.getAllByRole('tab')).toHaveLength(3);
    });

    // The dialog hands focus back to what opened it, and that is the tab it just removed.
    it('puts focus on the tab that becomes active when Delete closes the focused one', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
          {id: 'b', label: 'Query 2', sql: 'SELECT bye;'}
        ],
        activeTabId: 'b',
        nextQueryNumber: 3
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      screen.getByRole('tab', {name: /Query 2/}).focus();
      await user.keyboard('{Delete}');
      const dialog = await screen.findByRole('alertdialog', {name: /confirm close tab/i});
      await user.click(within(dialog).getByRole('button', {name: 'Close tab'}));

      await waitFor(() => expect(screen.getByRole('tab', {name: /Query 1/})).toHaveFocus());
      expect(screen.getByRole('tab', {name: /Query 1/})).toHaveAttribute('aria-selected', 'true');
    });

    it('shows the tab-limit dialog at the cap and opens no further tab', async () => {
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      const newTab = screen.getByRole('button', {name: 'New query tab'});
      for (let i = 0; i < 9; i++) await user.click(newTab);
      expect(screen.getAllByRole('tab')).toHaveLength(10);

      await user.click(newTab);
      expect(screen.getByRole('alertdialog', {name: /query tab limit reached/i})).toBeInTheDocument();
      expect(screen.getAllByRole('tab')).toHaveLength(10);
    });

    it('opens a View DDL tab and clears its own loading notice', async () => {
      let land = () => {};
      mockGetTableDdl.mockReturnValueOnce(
        new Promise((resolve) => (land = () => resolve(ok('CREATE EXTERNAL TABLE sales_2026 (region string)'))))
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await openTableMenu(user, 'sales_2026');
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'View DDL'}));
      await screen.findByText('Loading DDL for sales_2026…');

      await act(async () => land());

      expect(await screen.findByRole('tab', {name: /DDL: sales_2026/})).toHaveAttribute('aria-selected', 'true');
      expect(screen.queryByText('Loading DDL for sales_2026…')).not.toBeInTheDocument();
    });

    // Both requests leave from renders that counted one tab fewer than the cap, so only a count
    // that is current when each one lands can tell the second there is no room.
    it('raises the tab limit for the second of two View DDLs started one below the cap', async () => {
      seedTabs({
        version: 1,
        tabs: Array.from({length: QUERY_TABS_MAX - 1}, (_, i) => ({id: `t${i}`, label: `Query ${i + 1}`, sql: ''})),
        activeTabId: 't0',
        nextQueryNumber: QUERY_TABS_MAX
      });
      let land = () => {};
      mockGetTableDdl.mockReturnValue(
        new Promise((resolve) => (land = () => resolve(ok('CREATE EXTERNAL TABLE t (region string)'))))
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      for (const table of ['sales_2026', 'revenue_view']) {
        await openTableMenu(user, table);
        await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'View DDL'}));
      }

      await act(async () => land());

      expect(await screen.findByRole('alertdialog', {name: /query tab limit reached/i})).toBeInTheDocument();
      expect(screen.getAllByRole('tab')).toHaveLength(QUERY_TABS_MAX);
    });

    // --- saved queries (SPEC-173: files, not a JSON store) ---

    it('saves a new query: prompts, writes a .sql file, links + relabels the active tab', async () => {
      seedSingle('SELECT r;');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      const dialog = screen.getByRole('dialog', {name: 'Save query'});
      await user.type(within(dialog).getByLabelText('Name'), 'My report');
      await user.click(within(dialog).getByRole('button', {name: 'Save'}));

      expect(mockWriteSaved).toHaveBeenCalledWith(
        expect.objectContaining({
          space: expect.objectContaining({id: 'personal', rootPrefix: 'alice/'}),
          name: 'My report',
          sql: 'SELECT r;',
          overwrite: false
        })
      );
      expect(await screen.findByRole('tab', {name: /My report/})).toBeInTheDocument();
    });

    it('turns a write COLLISION into a replace confirm, and only then overwrites', async () => {
      // FR-004: the collision is a HEAD on the exact key inside the write, because a scan
      // of the loaded list stopped being sound once it is paginated and the target space
      // may not be the one on screen.
      seedSingle('SELECT r;');
      // Models the real service: the key exists, so every non-overwrite write collides and
      // only an explicit Replace gets through. A single `…Once` would let the second
      // attempt succeed and quietly skip the half this test exists for.
      mockWriteSaved.mockImplementation(async ({space, name, sql, overwrite}) =>
        overwrite
          ? ok(savedFile(name, {spaceId: space.id, bucket: space.bucket, size: sql.length}))
          : fail(`“${name}” already exists.`, 'Collision')
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.type(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name'), 'My report');
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      const confirm = await screen.findByRole('alertdialog', {name: /confirm replace saved query/i});
      expect(mockWriteSaved).toHaveBeenCalledTimes(1);
      expect(mockWriteSaved).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: false}));

      // Backing out returns the user to what they TYPED, not to an empty field.
      await user.click(within(confirm).getByRole('button', {name: 'Cancel'}));
      expect(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name')).toHaveValue('My report');

      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));
      const confirmAgain = await screen.findByRole('alertdialog', {name: /confirm replace saved query/i});
      await user.click(within(confirmAgain).getByRole('button', {name: 'Replace'}));
      expect(mockWriteSaved).toHaveBeenLastCalledWith(expect.objectContaining({name: 'My report', overwrite: true}));
      expect(await screen.findByRole('tab', {name: /My report/})).toBeInTheDocument();
    });

    it('speaks a failed Replace, which reopens the dialog already carrying it', async () => {
      seedSingle('SELECT r;');
      mockWriteSaved.mockImplementation(async ({name, overwrite}) =>
        overwrite ? fail('nope', 'AccessDenied') : fail(`“${name}” already exists.`, 'Collision')
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.type(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name'), 'My report');
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      const confirm = await screen.findByRole('alertdialog', {name: /confirm replace saved query/i});
      await user.click(within(confirm).getByRole('button', {name: 'Replace'}));

      const dialog = await screen.findByRole('dialog', {name: 'Save query'});
      await waitFor(() =>
        expect(politeAnnouncements()).toContainEqual(expect.stringMatching(/^Name: You don’t have permission/))
      );
      expect(within(dialog).getByLabelText('Name')).toHaveAccessibleDescription(/don’t have permission/i);
    });

    it('keeps the dialog OPEN on a write failure, with the name, the space and a mapped message', async () => {
      // SPEC-175 FR-006: the realistic failure is a shared space whose membership was
      // revoked mid-session, so the dialog has to survive it — the buffer is still
      // unsaved, and the user's next move is to pick another destination. The message is
      // `toUserMessage`'s, inline on the field, never raw AWS text (SPEC-106).
      seedSingle('SELECT r;');
      mockWriteSaved.mockResolvedValue(fail('nope', 'AccessDenied'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.type(within(screen.getByRole('dialog', {name: 'Save query'})).getByLabelText('Name'), 'My report');
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      const dialog = await screen.findByRole('dialog', {name: 'Save query'});
      await waitFor(() =>
        expect(within(dialog).getByLabelText('Name')).toHaveAccessibleDescription(/don’t have permission/i)
      );
      expect(within(dialog).getByLabelText('Name')).toHaveValue('My report');
      expect(within(dialog).getByLabelText('Space')).toBeEnabled();
      expect(screen.queryByText('nope')).not.toBeInTheDocument();
      // No toast claims success, and the tab is neither relabelled nor linked.
      expect(screen.queryByText(/^Saved “/)).not.toBeInTheDocument();
      expect(screen.queryByRole('tab', {name: /My report/})).not.toBeInTheDocument();
    });

    it('holds the saved_queries/ folder open when the workspace mounts, without blocking it', async () => {
      vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(fail('no', 'AccessDenied'));
      renderWorkspace();

      // The editor still renders: FR-001's marker is best effort, because writing a
      // saved query creates the prefix on its own.
      await screen.findByLabelText('SQL editor');
      await waitFor(() =>
        expect(ensureSavedQueriesFolder).toHaveBeenCalledWith(expect.objectContaining({rootPrefix: 'alice/'}))
      );
    });

    it('shows a dirty marker once a tab’s buffer diverges from the file it was opened from', async () => {
      // A `.sql` object carries no body until it is READ, so the comparison is against
      // what this session last saw — the body fetched on open — rather than a `sql`
      // field on a list row that no longer exists.
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(ok('SELECT original;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: /open saved query/i}));
      expect(screen.queryByLabelText('Unsaved changes')).not.toBeInTheDocument();

      await user.clear(editor());
      await user.type(editor(), 'SELECT edited;');

      expect(await screen.findByLabelText('Unsaved changes')).toBeInTheDocument();
    });

    it('opens a saved query with ONE GetObject, labels the tab by filename, and records it in history', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(ok('SELECT 1;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      // Merely opening the drawer fetches no bodies — the list is name/time/size only.
      expect(mockReadSaved).not.toHaveBeenCalled();

      await user.click(await screen.findByRole('button', {name: /open saved query/i}));
      expect(mockReadSaved).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('tab', {name: /Revenue/})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT 1;');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
      expect(mockAppend).toHaveBeenCalledWith(
        'alice',
        expect.objectContaining({savedQueryKey: 'alice/saved_queries/Revenue.sql', savedQueryName: 'Revenue'})
      );
    });

    it('Open and run opens the saved query in a new tab, runs all of it there and records it in history', async () => {
      queueRuns('q-1', 'q-2');
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(ok('SELECT 1;\nSELECT 2;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: 'Open and run saved query Revenue'}));

      expect(await screen.findByRole('tab', {name: /Revenue/, selected: true})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT 1;\nSELECT 2;');
      await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));
      expect(mockRunQuery.mock.calls.map(([args]) => args.sql)).toEqual(['SELECT 1', 'SELECT 2']);
      // The tab it ran in was opened in the same click, so the link has to travel with the run.
      expect(mockAppend).toHaveBeenCalledWith(
        'alice',
        expect.objectContaining({savedQueryKey: 'alice/saved_queries/Revenue.sql', savedQueryName: 'Revenue'})
      );
      expect(screen.queryByRole('button', {name: 'Open and run saved query Revenue'})).not.toBeInTheDocument();
    });

    // The row stays on screen until the body arrives, so a double-click lands twice on it.
    it('opens and runs a saved query once when Open and run is double-clicked', async () => {
      let resolveRead: (v: Awaited<ReturnType<typeof mockReadSaved>>) => void = () => {};
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockReturnValue(new Promise((resolve) => (resolveRead = resolve)));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Saved queries'}));

      await user.dblClick(await screen.findByRole('button', {name: 'Open and run saved query Revenue'}));
      resolveRead(ok('SELECT 1;'));

      expect(await screen.findByText('Succeeded')).toBeInTheDocument();
      expect(screen.getAllByRole('tab', {name: /Revenue/})).toHaveLength(1);
      expect(mockReadSaved).toHaveBeenCalledTimes(1);
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
    });

    it('opens NO tab and says which file is gone when its body cannot be read', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      mockReadSaved.mockResolvedValue(fail('“Revenue” no longer exists.', 'SavedQueryNotFound'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: /open saved query/i}));

      expect(await screen.findByText(/“Revenue” no longer exists/)).toBeInTheDocument();
      expect(screen.queryByRole('tab', {name: /Revenue/})).not.toBeInTheDocument();
      // The drawer is still open, because the user asked for this file.
      expect(screen.getByRole('button', {name: /open saved query/i})).toBeInTheDocument();
    });

    it('deletes a saved query (confirm) and deletes the OBJECT', async () => {
      mockListSaved.mockResolvedValue(savedListing('Revenue'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: /delete saved query/i}));
      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm delete saved query/i})).getByRole('button', {
          name: 'Delete'
        })
      );

      expect(mockDeleteSaved).toHaveBeenCalledWith(
        expect.objectContaining({bucket: 'user-bucket', key: 'alice/saved_queries/Revenue.sql'})
      );
    });

    // ── SPEC-174: loading from a chosen space ──

    it('lists the CHOSEN space, remembers it, and opens a shared query into a tab linked to that space', async () => {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]})
      );
      mockListSaved.mockImplementation(async ({space}) =>
        space.id === 'teamspace'
          ? ok({
              queries: [
                {
                  spaceId: 'teamspace',
                  bucket: 'shared-bucket',
                  key: 'teamspace/saved_queries/Theirs.sql',
                  name: 'Theirs',
                  updatedAt: '2026-07-01T10:00:00.000Z',
                  size: 12
                }
              ],
              isTruncated: false
            })
          : savedListing('Mine')
      );
      mockReadSaved.mockResolvedValue(ok('SELECT shared;'));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      expect(await screen.findByRole('button', {name: 'Open saved query Mine'})).toBeInTheDocument();

      await user.selectOptions(await screen.findByLabelText('Space'), 'teamspace');
      expect(await screen.findByRole('button', {name: 'Open saved query Theirs'})).toBeInTheDocument();
      // The previous space's rows do not persist into the new space's list.
      expect(screen.queryByRole('button', {name: 'Open saved query Mine'})).not.toBeInTheDocument();
      expect(sessionStorage.getItem('s3portal.query.savedQuerySpace.alice')).toBe('teamspace');

      await user.click(screen.getByRole('button', {name: 'Open saved query Theirs'}));
      expect(mockReadSaved).toHaveBeenCalledWith({bucket: 'shared-bucket', key: 'teamspace/saved_queries/Theirs.sql'});
      expect(await screen.findByRole('tab', {name: /Theirs/})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT shared;');

      // FR-010, asserted for a SHARED space separately: editing changes a buffer, never
      // the object.
      const writesBefore = mockWriteSaved.mock.calls.length;
      await user.clear(editor());
      await user.type(editor(), 'SELECT edited;');
      expect(mockWriteSaved.mock.calls.length).toBe(writesBefore);

      // Re-opening it carries the FILE's stored body, not the edited buffer.
      await user.click(screen.getByRole('button', {name: 'Saved queries'}));
      await user.click(await screen.findByRole('button', {name: 'Open saved query Theirs'}));
      expect(screen.getAllByRole('tab', {name: /Theirs/})).toHaveLength(2);
      expect(editor()).toHaveValue('SELECT shared;');
    });

    // ── SPEC-175: saving into a chosen space ──

    /** A shared space the user is an active member of, for the save-destination tests. */
    function withSharedSpace() {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]})
      );
      // The real key builder, so a destination test cannot pass against a key the store
      // would never produce.
      mockWriteSaved.mockImplementation(async ({space, name, sql}) =>
        ok({
          spaceId: space.id,
          bucket: space.bucket,
          key: savedQueryKey(space.rootPrefix, name),
          name: savedQueryName(savedQueryKey(space.rootPrefix, name)),
          updatedAt: '2026-07-01T10:00:00.000Z',
          size: sql.length
        })
      );
    }

    /** Opens Save, picks a destination if asked, types a name and submits. */
    async function saveAs(user: ReturnType<typeof renderWorkspace>['user'], name: string, spaceId?: string) {
      await user.click(screen.getByRole('button', {name: 'Save query'}));
      const dialog = screen.getByRole('dialog', {name: 'Save query'});
      if (spaceId) await user.selectOptions(within(dialog).getByLabelText('Space'), spaceId);
      await user.clear(within(dialog).getByLabelText('Name'));
      await user.type(within(dialog).getByLabelText('Name'), name);
      await user.click(within(dialog).getByRole('button', {name: 'Save'}));
    }

    it('writes into the CHOSEN shared space, links the tab there, and remembers it', async () => {
      // FR-001/FR-002: the folder marker is ensured for the space being written to — not
      // for the personal one — and the ONE space memory the load surface reads is updated,
      // so the next save and the next load both open where the user last was.
      seedSingle('SELECT r;');
      withSharedSpace();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await screen.findByRole('button', {name: 'Save query'});

      await saveAs(user, 'Quarterly', 'teamspace');

      await waitFor(() =>
        expect(ensureSavedQueriesFolder).toHaveBeenCalledWith(
          expect.objectContaining({id: 'teamspace', bucket: 'shared-bucket', rootPrefix: 'teamspace/'})
        )
      );
      expect(mockWriteSaved).toHaveBeenCalledWith(
        expect.objectContaining({
          space: expect.objectContaining({id: 'teamspace', bucket: 'shared-bucket'}),
          name: 'Quarterly',
          sql: 'SELECT r;',
          overwrite: false
        })
      );
      expect(await screen.findByRole('tab', {name: /Quarterly/})).toBeInTheDocument();
      expect(await screen.findByText(/Saved “Quarterly” to teamspace/)).toBeInTheDocument();
      await waitFor(() => expect(sessionStorage.getItem('s3portal.query.savedQuerySpace.alice')).toBe('teamspace'));
    });

    it('re-saves a linked tab in place: one write, overwrite, and NO second confirm', async () => {
      // FR-004. The prompt already named the file being replaced, so confirming again asks
      // about the thing just answered.
      seedTabs({
        version: 1,
        tabs: [
          {
            id: 'a',
            label: 'Monthly',
            sql: 'SELECT edited;',
            savedQuery: {
              spaceId: 'personal',
              bucket: 'user-bucket',
              key: 'alice/saved_queries/Monthly.sql',
              name: 'Monthly'
            }
          }
        ],
        activeTabId: 'a',
        nextQueryNumber: 2
      });
      withSharedSpace();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Save query'}));
      await user.click(within(screen.getByRole('dialog', {name: 'Save query'})).getByRole('button', {name: 'Save'}));

      await waitFor(() => expect(mockWriteSaved).toHaveBeenCalledTimes(1));
      expect(mockWriteSaved).toHaveBeenCalledWith(
        expect.objectContaining({name: 'Monthly', sql: 'SELECT edited;', overwrite: true})
      );
      expect(screen.queryByRole('alertdialog', {name: /confirm replace saved query/i})).not.toBeInTheDocument();
      expect(screen.getByRole('tab', {name: /Monthly/})).toBeInTheDocument();
    });

    it('refuses a statement over Athena’s length bound before starting anything, and says how to fix it', async () => {
      seedSingle(`SELECT '${'x'.repeat(262_144)}'`);
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(
        await screen.findByText(/This statement is too long to run — Athena takes at most 256 KB/)
      ).toBeInTheDocument();
      expect(mockRunQuery).not.toHaveBeenCalled();
    });

    it('re-runs a history entry in a NEW tab, leaving the one it was opened from as it was', async () => {
      seedSingle('SELECT draft_i_have_not_saved');
      mockGetHistory.mockResolvedValue(
        ok({
          version: 1,
          entries: [
            {
              queryExecutionId: 'old',
              sql: 'SELECT 42',
              database: 'alice',
              submittedAt: new Date().toISOString(),
              status: 'SUCCEEDED'
            }
          ]
        })
      );
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: /History/}));
      await user.click(await screen.findByRole('button', {name: /re-run this query/i}));

      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 42', username: 'alice'});
      expect(editor()).toHaveValue('SELECT 42');
      // The run belongs to the NEW tab — the id is passed explicitly because the switch to it has
      // not committed when the run is submitted, and without it the run lands in the draft's tab.
      expect(await screen.findByText('Succeeded')).toBeInTheDocument();
      // The first tab still holds the draft, which loading into the active tab used to replace,
      // and no run.
      await user.click(screen.getAllByRole('tab')[0]);
      expect(editor()).toHaveValue('SELECT draft_i_have_not_saved');
      expect(screen.queryByText('Succeeded')).not.toBeInTheDocument();
    });

    // --- table actions (driven through the REAL rail menu) ---

    it('View source files navigates for an in-space table and is disabled for an out-of-space one', async () => {
      const {user} = renderWorkspace();
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'View source files'}));
      // `space` is part of the assertion: without it the browser resolves the personal
      // space, which is right here only by accident and wrong for every shared table.
      expect(screen.getByLabelText('probe-location')).toHaveTextContent(
        '/files?space=personal&prefix=alice%2Fsales%2F'
      );

      await openTableMenu(user, 'foreign');
      expect(await screen.findByRole('menuitem', {name: 'View source files'})).toBeDisabled();
    });

    // The two halves of the guard are separately deletable, so each gets a fixture that
    // only IT refuses. `foreign` above is in the right bucket under someone else's prefix;
    // `stray` is under the right prefix in a bucket that is not this space's — reachable
    // because a user can write CREATE EXTERNAL TABLE ... LOCATION pointing anywhere.
    it('refuses a table whose LOCATION is in another bucket, even under the right prefix', async () => {
      const {user} = renderWorkspace();
      await openTableMenu(user, 'stray');
      expect(await screen.findByRole('menuitem', {name: 'View source files'})).toBeDisabled();
    });

    // The item this feedback was raised about: it was dead for every shared-space table,
    // because the old rule asked whether the key started with the signed-in USERNAME.
    it('View source files works for a shared-space table, and carries its space', async () => {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]})
      );
      vi.mocked(listTables).mockImplementation(async (database: string) =>
        database === 'teamspace'
          ? ok([{name: 'team_sales', location: 's3://shared-bucket/teamspace/sales/', columns: []}])
          : ok([salesTable])
      );
      const {user} = renderWorkspace();

      await user.click(await screen.findByRole('button', {name: /teamspace/}));
      await openTableMenu(user, 'team_sales');
      await user.click(await screen.findByRole('menuitem', {name: 'View source files'}));

      expect(screen.getByLabelText('probe-location')).toHaveTextContent(
        '/files?space=teamspace&prefix=teamspace%2Fsales%2F'
      );
    });

    it('View data opens a "{table}" tab and auto-runs a fully-qualified unbounded SELECT * (no LIMIT) [SPEC-105]', async () => {
      const {user} = renderWorkspace();
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'View data'}));

      expect(await screen.findByRole('tab', {name: /sales_2026/})).toBeInTheDocument();
      expect(editor()).toHaveValue('SELECT * FROM alice.sales_2026');
      expect(mockRunQuery).toHaveBeenCalledWith(expect.objectContaining({sql: 'SELECT * FROM alice.sales_2026'}));
      expect(mockRunQuery.mock.calls.at(-1)?.[0].sql).not.toMatch(/limit/i);
    });

    // The table builder accepts a reserved word as a name, and bare it is a keyword, not a table.
    it('View data quotes a table named with a reserved word, and only that part', async () => {
      vi.mocked(listTables).mockResolvedValue(ok([{...salesTable, name: 'order'}]));
      const {user} = renderWorkspace();

      await openTableMenu(user, 'order');
      await user.click(await screen.findByRole('menuitem', {name: 'View data'}));

      await waitFor(() =>
        expect(mockRunQuery).toHaveBeenCalledWith(expect.objectContaining({sql: 'SELECT * FROM alice."order"'}))
      );
    });

    it('Drop table confirms, runs DROP TABLE in the background (history + toast); a failure shows an error toast', async () => {
      const {user} = renderWorkspace();

      mockRunToCompletion.mockResolvedValueOnce(ok(succeeded('q-drop')));
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop table'}));
      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm drop table/i})).getByRole('button', {name: 'Drop table'})
      );

      expect(await screen.findByText('Dropped sales_2026')).toBeInTheDocument();
      // BACKTICKS: a DROP TABLE is DDL, which Athena parses with Hive — the mirror of the view
      // statements, which are Trino and take double quotes. The database is the identifier that
      // needs quoting: a space named before the plane took the catalog rule passed no format check.
      expect(mockRunToCompletion).toHaveBeenCalledWith(
        expect.objectContaining({sql: 'DROP TABLE `alice`.`sales_2026`'})
      );
      expect(mockAppend).toHaveBeenCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-drop'}));

      mockRunToCompletion.mockResolvedValueOnce(
        ok(succeeded('q-drop2', {state: 'FAILED', stateChangeReason: 'table locked'}))
      );
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop table'}));
      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm drop table/i})).getByRole('button', {name: 'Drop table'})
      );
      // SPEC-106: the toast shows friendly, mapped text — not the raw Athena reason.
      expect(await screen.findByText(/Couldn’t drop sales_2026/)).toBeInTheDocument();
      expect(screen.queryByText(/table locked/)).not.toBeInTheDocument();
    });

    it('Drop view double-quotes the view, which Athena parses with Trino', async () => {
      mockRunToCompletion.mockResolvedValueOnce(ok(succeeded('q-drop-view')));
      const {user} = renderWorkspace();
      await openTableMenu(user, 'revenue_view');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop view'}));

      await user.click(
        within(screen.getByRole('alertdialog', {name: /confirm drop view/i})).getByRole('button', {name: 'Drop view'})
      );

      expect(await screen.findByText('Dropped revenue_view')).toBeInTheDocument();
      expect(mockRunToCompletion).toHaveBeenCalledWith(
        expect.objectContaining({sql: 'DROP VIEW "alice"."revenue_view"'})
      );
    });

    it('Drop table in a shared space says the drop is everyone’s', async () => {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'teamspace', role: 'member', status: 'active'}]})
      );
      vi.mocked(listTables).mockImplementation(async (database: string) =>
        database === 'teamspace'
          ? ok([{name: 'team_sales', location: 's3://shared-bucket/teamspace/sales/', columns: []}])
          : ok([salesTable])
      );
      const {user} = renderWorkspace();

      await user.click(await screen.findByRole('button', {name: /teamspace/}));
      await openTableMenu(user, 'team_sales');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop table'}));

      expect(
        within(screen.getByRole('alertdialog', {name: /confirm drop table/i})).getByText(
          /from teamspace, for everyone in this shared space\./
        )
      ).toBeInTheDocument();
    });

    it('Drop table that outlasts the wait says it may still finish, never that it failed', async () => {
      const {user} = renderWorkspace();
      mockRunToCompletion.mockResolvedValueOnce({
        success: false,
        error: {message: 'Timed out waiting for the query', code: 'Timeout'}
      });
      await openTableMenu(user, 'sales_2026');
      await user.click(await screen.findByRole('menuitem', {name: 'Drop table'}));
      const dialog = screen.getByRole('alertdialog', {name: /confirm drop table/i});
      // The database is named, and the data claim hedges on the one kind of table whose drop deletes it.
      expect(within(dialog).getByText(/from alice\. A standard table’s data files in S3 are kept/)).toBeInTheDocument();
      await user.click(within(dialog).getByRole('button', {name: 'Drop table'}));

      expect(
        await screen.findByText(/stopped waiting on “sales_2026”, but Athena may still finish/)
      ).toBeInTheDocument();
      expect(screen.queryByText(/Couldn’t drop sales_2026/)).not.toBeInTheDocument();
    });

    it('Create view composes CREATE OR REPLACE VIEW (target db derived from the body), records history + success toast', async () => {
      seedSingle('SELECT region FROM alice.sales;');
      mockRunToCompletion.mockResolvedValue(ok(succeeded('q-view')));
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Create view'}));
      const dialog = screen.getByRole('dialog', {name: 'Create view'});
      await user.type(within(dialog).getByLabelText('View name'), 'region_view');
      await user.click(within(dialog).getByRole('button', {name: 'Create'}));

      expect(await screen.findByText('Saved view region_view')).toBeInTheDocument();
      expect(mockRunToCompletion).toHaveBeenCalledWith(
        expect.objectContaining({
          // Both identifiers are QUOTED, with the Trino escaper — Athena parses CREATE VIEW
          // with Trino, where double quotes are the identifier quote and a backtick is an
          // error. It matters because a shared space's name reaches the same builder, and one
          // named before the control plane took the catalog rule passed no format check.
          sql: 'CREATE OR REPLACE VIEW "alice"."region_view" AS SELECT region FROM alice.sales',
          database: 'alice',
          username: 'alice'
        })
      );
      expect(mockAppend).toHaveBeenCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-view'}));
      expect(editor()).toHaveValue('SELECT region FROM alice.sales;'); // editor keeps the user's SELECT
    });

    it('Create view wraps only the statement under the cursor, and takes its database from that one', async () => {
      // The other statement names another database: read whole, the buffer is refused as spanning
      // two, and the cursor sits in the FIRST so the lazy-editor default of the last cannot pass.
      seedSingle('SELECT region FROM alice.sales;\nSELECT id FROM bob.orders;');
      mockRunToCompletion.mockResolvedValue(ok(succeeded('q-view')));
      const {user} = renderWorkspace();
      const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;
      ta.setSelectionRange(3, 3);

      await user.click(screen.getByRole('button', {name: 'Create view'}));
      const dialog = screen.getByRole('dialog', {name: 'Create view'});
      await user.type(within(dialog).getByLabelText('View name'), 'region_view');
      await user.click(within(dialog).getByRole('button', {name: 'Create'}));

      expect(await screen.findByText('Saved view region_view')).toBeInTheDocument();
      expect(mockRunToCompletion).toHaveBeenCalledWith(
        expect.objectContaining({
          sql: 'CREATE OR REPLACE VIEW "alice"."region_view" AS SELECT region FROM alice.sales',
          database: 'alice'
        })
      );
    });

    it('refuses Create view on a selection holding several statements, and says why', async () => {
      seedSingle('SELECT region FROM alice.sales;\nSELECT id FROM alice.orders;');
      const {user} = renderWorkspace();
      const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;
      ta.setSelectionRange(0, ta.value.length);

      await user.click(screen.getByRole('button', {name: 'Create view'}));

      expect(
        await screen.findByText(
          'Create view works on one statement. Select just the one to save as a view, or put the cursor in it.'
        )
      ).toBeInTheDocument();
      expect(screen.queryByRole('dialog', {name: 'Create view'})).not.toBeInTheDocument();
    });

    // --- Save results… (real SaveResultsDialog + DestinationPicker) ---

    async function runToSucceeded(user: ReturnType<typeof renderWorkspace>['user']) {
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
    }
    async function saveInto(user: ReturnType<typeof renderWorkspace>['user'], filename: string) {
      await user.click(await screen.findByRole('button', {name: 'Save results…'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, filename);
      return dialog;
    }

    it('refuses Save results for a SHOW result, which is not a result set, and says why', async () => {
      seedSingle('SHOW TABLES IN alice');
      const {user} = renderWorkspace();
      await runToSucceeded(user);

      const save = await screen.findByRole('button', {name: 'Save results…'});
      expect(save).toHaveAttribute('aria-disabled', 'true');
      expect(save).toHaveAttribute('title', SAVE_RESULTS_STATEMENT_REFUSAL);
      await user.click(save);
      expect(screen.queryByRole('dialog', {name: 'Save results'})).not.toBeInTheDocument();
    });

    it('saves a succeeded result to the personal space (cross-checked copy + Files deep-link)', async () => {
      seedSingle('SELECT 1');
      mockCopyObject.mockResolvedValue(ok({destKey: 'alice/out.csv'}));
      const {user} = renderWorkspace();
      await runToSucceeded(user);

      const dialog = await saveInto(user, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      expect(mockCopyObject).toHaveBeenCalledWith({
        bucket: 'user-bucket',
        destBucket: 'user-bucket',
        sourceKey: 'alice/athenaresults/q-1.csv',
        destKey: 'alice/out.csv',
        username: 'alice',
        overwrite: false
      });
      await user.click(await screen.findByRole('button', {name: 'View in Files'}));
      expect(screen.getByLabelText('probe-location')).toHaveTextContent('/files?space=personal&prefix=alice%2F');
    });

    it('a destination collision prompts Overwrite, then copies with overwrite', async () => {
      seedSingle('SELECT 1');
      mockCopyObject
        .mockResolvedValueOnce(fail('exists', 'Collision'))
        .mockResolvedValueOnce(ok({destKey: 'alice/out.csv'}));
      const {user} = renderWorkspace();
      await runToSucceeded(user);

      const dialog = await saveInto(user, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      await user.click(
        within(await screen.findByRole('alertdialog', {name: /confirm overwrite/i})).getByRole('button', {
          name: 'Overwrite'
        })
      );
      expect(mockCopyObject).toHaveBeenLastCalledWith(expect.objectContaining({overwrite: true}));
      expect(await screen.findByText(/Saved to alice\/out\.csv/)).toBeInTheDocument();
    });

    // The dialog is unmounted while the overwrite question is up, so it came back at its
    // defaults: a stamped name, CSV and the space root. Parquet and a subfolder are chosen
    // because both differ from those defaults, and the second save's probe is the effect —
    // it names the key the user is about to write, which is where the folder shows.
    it('cancelling the overwrite question returns to the dialog with the name, format and folder kept', async () => {
      seedSingle('SELECT 1');
      mockListFiles.mockImplementation(async (_bucket, prefix) =>
        ok({
          files: [],
          folders: prefix === 'alice/' ? [{type: 'folder' as const, prefix: 'alice/reports/', name: 'reports'}] : [],
          isTruncated: false
        })
      );
      vi.mocked(objectExists).mockResolvedValue(ok(true));
      const {user} = renderWorkspace();
      await runToSucceeded(user);

      const dialog = await saveInto(user, 'out');
      await user.selectOptions(within(dialog).getByLabelText('Format'), 'parquet');
      await user.click(await within(dialog).findByRole('button', {name: /open folder reports/i}));
      await user.click(within(dialog).getByRole('button', {name: 'Convert and save'}));
      await user.click(
        within(await screen.findByRole('alertdialog', {name: /confirm overwrite/i})).getByRole('button', {
          name: 'Cancel'
        })
      );

      const reopened = await screen.findByRole('dialog', {name: 'Save results'});
      expect(within(reopened).getByLabelText('File name')).toHaveValue('out.parquet');
      expect(within(reopened).getByLabelText('Format')).toHaveValue('parquet');
      await user.click(within(reopened).getByRole('button', {name: 'Convert and save'}));
      await waitFor(() => expect(objectExists).toHaveBeenCalledTimes(2));
      expect(objectExists).toHaveBeenLastCalledWith({bucket: 'user-bucket', key: 'alice/reports/out.parquet'});
    });
  });

  describe('QueryWorkspace — multi-statement batches (SPEC-078)', () => {
    const THREE = 'SELECT 1; CREATE TABLE alice.t (id int); SELECT 2;';
    function seedScript(sql: string = THREE) {
      seedTabs({version: 1, tabs: [{id: 'a', label: 'Query 1', sql}], activeTabId: 'a', nextQueryNumber: 2});
    }

    it('runs a script sequentially and records one history entry per statement (FR-002/FR-003)', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      expect(await screen.findByText(/Script finished · 3 statements/)).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(3);
      expect(mockRunQuery.mock.calls.map((c) => c[0].sql)).toEqual([
        'SELECT 1',
        'CREATE TABLE alice.t (id int)',
        'SELECT 2'
      ]);
      expect(mockAppend).toHaveBeenCalledTimes(3);
      expect(mockAppend.mock.calls.map((c) => c[1].sql)).toEqual([
        'SELECT 1',
        'CREATE TABLE alice.t (id int)',
        'SELECT 2'
      ]);
      // Single-result scope → no per-statement result-tab strip.
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
    });

    it('stops at the first failed statement, names it, and reports the skipped remainder (FR-002/FR-004)', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      statusMap['q-2'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      // The position is named and the sentence is friendly; Athena's own words exist only inside
      // the closed Details beneath it, never in the sentence.
      expect(await screen.findByText(/Statement 2 of 3 failed\. There’s a syntax error/)).toBeInTheDocument();
      expect(screen.getByText(/Statement 3 did not run/)).toBeInTheDocument();
      const engineText = screen.getAllByText(/SYNTAX_ERROR/);
      expect(engineText).toHaveLength(1);
      expect(engineText[0].closest('details')).not.toHaveAttribute('open');
      expect(mockRunQuery).toHaveBeenCalledTimes(2);
      expect(mockAppend).toHaveBeenCalledTimes(2);
    });

    // The statement that never started leaves the one before it as the latest status, so
    // a bar reading the status alone called a failed script a success under its own banner.
    it('says Failed on the bar when a later statement fails to start, not the earlier one’s Succeeded', async () => {
      queueRuns('q-1');
      mockRunQuery.mockResolvedValueOnce(fail('Rate exceeded', 'ThrottlingException'));
      seedScript('SELECT 1; SELECT 2;');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      expect(await screen.findByText(/Statement 2 of 2 failed\. The service is busy/)).toBeInTheDocument();
      expect(screen.getByText('Failed')).toBeInTheDocument();
      expect(screen.queryByText('Succeeded')).not.toBeInTheDocument();
    });

    // While the next statement's history entry is being written, the run still names the statement
    // before it — so a Stop there cancelled a finished query and the started one ran on, billed.
    it('cancels the next statement when Stop lands while it is being recorded', async () => {
      queueRuns('q-1', 'q-2');
      statusMap['q-2'] = {state: 'RUNNING'};
      let landAppend = () => {};
      mockAppend
        .mockResolvedValueOnce(ok({version: 1, entries: []}))
        .mockReturnValueOnce(new Promise((resolve) => (landAppend = () => resolve(ok({version: 1, entries: []})))));
      seedScript('SELECT 1; SELECT 2;');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);
      await waitFor(() =>
        expect(mockAppend).toHaveBeenLastCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-2'}))
      );
      await user.click(screen.getByRole('button', {name: 'Stop the running query'}));
      await act(async () => landAppend());

      await waitFor(() => expect(mockStopQuery).toHaveBeenCalledWith('q-2'));
      expect(mockStopQuery.mock.calls).toEqual([['q-1'], ['q-2']]);
    });

    // Closing the tab drops its run, so nothing would ever watch — or stop — the statement that
    // had just started: it ran to the end, billed, for a tab that no longer exists.
    it('cancels the next statement when its tab is closed while it is being recorded', async () => {
      queueRuns('q-1', 'q-2');
      statusMap['q-2'] = {state: 'RUNNING'};
      let landAppend = () => {};
      mockAppend
        .mockResolvedValueOnce(ok({version: 1, entries: []}))
        .mockReturnValueOnce(new Promise((resolve) => (landAppend = () => resolve(ok({version: 1, entries: []})))));
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
          {id: 'b', label: 'Query 2', sql: 'SELECT 1; SELECT 2;'}
        ],
        activeTabId: 'b',
        nextQueryNumber: 3
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await runScriptSingle(user);
      await waitFor(() =>
        expect(mockAppend).toHaveBeenLastCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-2'}))
      );
      screen.getByRole('tab', {name: /Query 2/}).focus();
      await user.keyboard('{Delete}');
      const dialog = await screen.findByRole('alertdialog', {name: /confirm close tab/i});
      await user.click(within(dialog).getByRole('button', {name: 'Close tab'}));

      await act(async () => landAppend());

      await waitFor(() => expect(mockStopQuery).toHaveBeenCalledWith('q-2'));
      expect(mockStopQuery.mock.calls).toEqual([['q-2']]);
    });

    // Run and Stop are one control, so focus stays on it across the swap — and so a held Enter's
    // repeats land on Stop, which would cancel the query that same keypress started.
    it('keeps focus on the run control as it becomes Stop, and a held Enter does not stop the run', async () => {
      queueRuns('q-1');
      statusMap['q-1'] = {state: 'RUNNING'};
      seedScript('SELECT 1;');
      renderWorkspace();
      await screen.findByLabelText('SQL editor');
      screen.getByRole('button', {name: 'Run statement'}).focus();
      // Spaced like a real auto-repeat, so the repeats straddle the moment Run becomes Stop.
      const held = userEvent.setup({delay: 5});

      await held.keyboard('{Enter>12/}');

      expect(await screen.findByRole('button', {name: 'Stop the running query'})).toHaveFocus();
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(mockStopQuery).not.toHaveBeenCalled();
    });

    // The first statement is recorded before its run exists, so there is no run for the close to
    // drop yet: installed afterwards, it would carry the whole batch on for a tab nobody can see.
    it('cancels the first statement, and starts no other, when its tab is closed while it is being recorded', async () => {
      queueRuns('q-1', 'q-2');
      statusMap['q-1'] = {state: 'RUNNING'};
      let landAppend = () => {};
      mockAppend.mockReturnValueOnce(
        new Promise((resolve) => (landAppend = () => resolve(ok({version: 1, entries: []}))))
      );
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT keep;'},
          {id: 'b', label: 'Query 2', sql: 'SELECT 1; SELECT 2;'}
        ],
        activeTabId: 'b',
        nextQueryNumber: 3
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await runScriptSingle(user);
      await waitFor(() =>
        expect(mockAppend).toHaveBeenLastCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-1'}))
      );
      screen.getByRole('tab', {name: /Query 2/}).focus();
      await user.keyboard('{Delete}');
      const dialog = await screen.findByRole('alertdialog', {name: /confirm close tab/i});
      await user.click(within(dialog).getByRole('button', {name: 'Close tab'}));

      await act(async () => landAppend());

      await waitFor(() => expect(mockStopQuery).toHaveBeenCalledWith('q-1'));
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
    });

    it('Run Script (tab per statement) yields one result tab per result-producing statement, and a new run clears them (FR-007)', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);

      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      const resultTabs = within(strip).getAllByRole('tab');
      // The CREATE (statement 2) earns no tab; labels carry statement positions.
      expect(resultTabs.map((t) => t.textContent)).toEqual(['1 · SELECT 1', '3 · SELECT 2']);
      expect(resultTabs[1]).toHaveAttribute('aria-selected', 'true');
      await user.click(resultTabs[0]);
      expect(within(strip).getAllByRole('tab')[0]).toHaveAttribute('aria-selected', 'true');

      // A fresh run (with an in-flight last statement) clears the previous strip.
      queueRuns('q-4', 'q-5', 'q-6');
      statusMap['q-6'] = {state: 'RUNNING'};
      await runScriptTabs(user);
      await screen.findByRole('button', {name: /Stop/});
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
    });

    it('closing the shown result tab shows the one beside it, and the last tab cannot be closed', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
        ok({
          columns: [{name: 'region', type: 'string'}],
          rows: queryExecutionId === 'q-1' ? [['us-east'], ['eu-west']] : [['ap-south']]
        })
      );
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await runScriptTabs(user);
      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      expect(await screen.findByText(/\b1 rows?\b/)).toBeInTheDocument();

      await user.click(within(strip).getByTitle('Close 3 · SELECT 2'));

      const left = within(strip).getAllByRole('tab');
      expect(left.map((t) => t.textContent)).toEqual(['1 · SELECT 1']);
      expect(left[0]).toHaveAttribute('aria-selected', 'true');
      await waitFor(() => expect(screen.getByText(/\b2 rows\b/)).toBeInTheDocument());
      expect(within(strip).queryByTitle(/^Close /)).not.toBeInTheDocument();
    });

    it('closing a tab before the shown one keeps the shown one', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
        ok({
          columns: [{name: 'region', type: 'string'}],
          rows: queryExecutionId === 'q-1' ? [['us-east'], ['eu-west']] : [['ap-south']]
        })
      );
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await runScriptTabs(user);
      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      expect(await screen.findByText(/\b1 rows?\b/)).toBeInTheDocument();

      await user.click(within(strip).getByTitle('Close 1 · SELECT 1'));

      const left = within(strip).getAllByRole('tab');
      expect(left.map((t) => t.textContent)).toEqual(['3 · SELECT 2']);
      expect(left[0]).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByText(/\b1 rows?\b/)).toBeInTheDocument();
    });

    // The count follows the SELECTED statement, not the last one that ran. Each execution
    // returns a different number of rows, so reading the wrong one is a wrong number rather
    // than a coincidence — an equal-sized fixture would pass whichever was read.
    //
    // Scope, measured rather than assumed: this passes against the pre-change gate too, so
    // it does NOT prove the walk now opens earlier. What it pins is that flipping re-derives
    // at all, which is the half of the report that was already working and is easy to break
    // — the eventual value is assertable, the removal of the gap in between is not without a
    // timing assertion that would be flaky. The earlier opening is covered by the DDL test,
    // which asserts the gate itself.
    it('re-derives the total row count when you flip between result tabs', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
        ok({
          columns: [{name: 'region', type: 'string'}],
          rows: queryExecutionId === 'q-1' ? [['us-east'], ['eu-west']] : [['ap-south']]
        })
      );
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);

      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      // Statement 3 is auto-selected and returned one row.
      expect(await screen.findByText(/\b1 rows?\b/)).toBeInTheDocument();

      await user.click(within(strip).getAllByRole('tab')[0]);

      // Statement 1 returned two — the stat moved with the tab.
      await waitFor(() => expect(screen.getByText(/\b2 rows\b/)).toBeInTheDocument());
    });

    // The scanned/duration figures sit in the SAME sentence as the row count, so they
    // must move with it. They used to be read off the editor tab's status — one per
    // editor tab however many statements ran — which left statement 1's rows beside
    // statement 3's bytes with nothing distinguishing them.
    //
    // Every figure differs per execution, in both directions: an equal-valued fixture
    // agrees whichever status is read, and reading the batch default (2.0 KB / 800 ms)
    // would match neither statement.
    it('moves the scanned bytes and the duration with the row count when you flip result tabs', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      statusMap['q-1'] = {dataScannedBytes: 1024, engineExecutionTimeMillis: 250};
      statusMap['q-3'] = {dataScannedBytes: 8192, engineExecutionTimeMillis: 1750};
      mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
        ok({
          columns: [{name: 'region', type: 'string'}],
          rows: queryExecutionId === 'q-1' ? [['us-east'], ['eu-west']] : [['ap-south']]
        })
      );
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);

      // Statement 3 is auto-selected: its one row, its bytes, its duration. The plural is
      // left open — the bar says "1 rows" today, and pinning that here would make an
      // unrelated fix to `rowCountLabel` look like a regression in this one.
      const stats = () => screen.getByText(/scanned ·/);
      await waitFor(() => expect(stats()).toHaveTextContent(/1 rows? · 8\.0 KB scanned · 1\.8s/));

      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      await user.click(within(strip).getAllByRole('tab')[0]);

      // Statement 1: all three figures moved together.
      await waitFor(() => expect(stats()).toHaveTextContent('2 rows · 1.0 KB scanned · 250 ms'));
    });

    // The same pairing, in the scope that has no tab strip to flip. A trailing DDL earns
    // no result tab, so the grid keeps showing the SELECT while the editor tab's status
    // has moved on to the CREATE — the mismatch is static here rather than reachable by a
    // click, and the mobile surface runs this scope over a saved query's whole buffer.
    it('reports the displayed statement, not a trailing DDL, in the single-result scope', async () => {
      queueRuns('q-1', 'q-2');
      // The displayed statement is the LARGER of the two here, where the flip test has it
      // smaller — so neither test can be satisfied by a reducer over the batch.
      statusMap['q-1'] = {dataScannedBytes: 8192, engineExecutionTimeMillis: 1750};
      statusMap['q-2'] = {dataScannedBytes: 1024, engineExecutionTimeMillis: 250};
      mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
        ok({
          columns: [{name: 'region', type: 'string'}],
          rows: queryExecutionId === 'q-1' ? [['us-east'], ['eu-west']] : [['ap-south']]
        })
      );
      seedScript('SELECT 1; CREATE TABLE alice.t (id int);');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      await waitFor(() => expect(screen.getByText(/scanned ·/)).toHaveTextContent('2 rows · 8.0 KB scanned · 1.8s'));
    });

    // The REFUSAL half of the same swap, which the two tests above cannot see. A batch that
    // failed at statement 3 still displays statement 1's succeeded result tab, and the bar
    // keeps the batch's verdict rather than that tab's: the failure banner is dismissible, so
    // the indicator is the only terminal signal left on screen. Swapping unconditionally
    // prints "Succeeded" over a script that failed, and every other test here stays green.
    it('keeps the batch verdict when a later statement fails under a displayed result tab', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      statusMap['q-1'] = {dataScannedBytes: 1024, engineExecutionTimeMillis: 250};
      statusMap['q-3'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);

      // Statement 1 earned the only result tab, and the grid is showing it.
      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      expect(
        within(strip)
          .getAllByRole('tab')
          .map((t) => t.textContent)
      ).toEqual(['1 · SELECT 1']);
      expect(await screen.findByText('Failed')).toBeInTheDocument();
      // Not its figures, and not a stray "Succeeded" beside them.
      expect(screen.queryByText(/scanned ·/)).not.toBeInTheDocument();
      expect(screen.queryByText('Succeeded')).not.toBeInTheDocument();
    });

    it('saves the displayed result after a later statement failed, from the displayed execution', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      // q-3 fails but still carries an outputLocation of its own, so a Save wired to the
      // run's verdict rather than the displayed tab would copy q-3.csv and pass a
      // button-exists assertion. The sourceKey is what discriminates the two.
      statusMap['q-3'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);
      expect(await screen.findByText('Failed')).toBeInTheDocument();

      await user.click(await screen.findByRole('button', {name: 'Save results…'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({sourceKey: 'alice/athenaresults/q-1.csv', destKey: 'alice/out.csv'})
      );
    });

    /**
     * The Save affordance never appears. A plain `queryBy` passes on the render before the
     * results arrive, which is exactly when a broken gate still looks correct — measured: with
     * the SUCCEEDED gate deleted the button does appear, and a `queryBy` sitting here missed it.
     */
    async function expectSaveNeverAppears() {
      await expect(screen.findByRole('button', {name: 'Save results…'}, {timeout: 400})).rejects.toThrow(
        /Unable to find/
      );
    }

    // `soleStatementSucceeded` is the only thing keeping a lone failed statement out of
    // `displayExecutionId`, and it sits two files from the button it now gates. It is also the
    // client-side "read results only at SUCCEEDED" gate — `useQueryResults` checks the id alone.
    it('offers no Save when the only statement failed, so there is no earlier result', async () => {
      queueRuns('q-1');
      statusMap['q-1'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedSingle('SELECT nope');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      expect(await screen.findByText('Failed')).toBeInTheDocument();
      await expectSaveNeverAppears();
    });

    // The displayed tab ANSWERS for its own output object. A `??` fallthrough here would reach
    // past a tab with no output object to the failed statement's, minting a CSV from the wrong
    // execution — and every other fixture sets `outputLocation`, so nothing else can see it.
    it('offers no Save when the displayed result tab carries no output object', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      statusMap['q-1'] = {outputLocation: undefined};
      statusMap['q-3'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedScript();
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptTabs(user);
      expect(await screen.findByText('Failed')).toBeInTheDocument();
      await expectSaveNeverAppears();
    });

    it('Run Statement executes the selection, else the statement under the cursor (FR-006)', async () => {
      queueRuns('q-1', 'q-2');
      seedScript('SELECT 1;\nSELECT 2;');
      const {user} = renderWorkspace();
      const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;

      ta.setSelectionRange(0, 'SELECT 1'.length);
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(1));
      expect(mockRunQuery.mock.calls[0][0].sql).toBe('SELECT 1');
      await screen.findByText('Succeeded');
      // One statement selected is one result, shown alone, as it always was.
      expect(await screen.findByText('us-east')).toBeInTheDocument();
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();

      const cursor = ta.value.indexOf('SELECT 2') + 3;
      ta.setSelectionRange(cursor, cursor);
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));
      expect(mockRunQuery.mock.calls[1][0].sql).toBe('SELECT 2');
      await waitFor(() => expect(screen.getAllByText('Succeeded')).toHaveLength(1));
      expect(await screen.findByText('us-east')).toBeInTheDocument();
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
    });

    // Rows that differ per execution, so "the grid shows statement 2" is a claim about which
    // execution was read rather than about there being a grid at all.
    function rowsByExecution() {
      mockGetResults.mockImplementation(async ({queryExecutionId}: {queryExecutionId: string}) =>
        ok({columns: [{name: 'n', type: 'string'}], rows: [[`rows of ${queryExecutionId}`]]})
      );
    }

    it('gives each statement of a multi-statement selection its own result tab, showing the latest', async () => {
      queueRuns('q-1', 'q-2');
      rowsByExecution();
      seedScript('SELECT 1;\nSELECT 2;\nSELECT 3;');
      const {user} = renderWorkspace();
      const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;

      ta.setSelectionRange(0, 'SELECT 1;\nSELECT 2'.length);
      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      const strip = await screen.findByRole('tablist', {name: 'Result tabs'});
      expect(mockRunQuery.mock.calls.map(([call]) => call.sql)).toEqual(['SELECT 1', 'SELECT 2']);
      const resultTabs = within(strip).getAllByRole('tab');
      expect(resultTabs.map((tab) => tab.textContent)).toEqual(['1 · SELECT 1', '2 · SELECT 2']);
      expect(resultTabs[1]).toHaveAttribute('aria-selected', 'true');
      expect(await screen.findByText('rows of q-2')).toBeInTheDocument();

      await user.click(resultTabs[0]);
      expect(await screen.findByText('rows of q-1')).toBeInTheDocument();
      expect(screen.queryByText('rows of q-2')).not.toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Save results…'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));
      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({sourceKey: 'alice/athenaresults/q-1.csv', destKey: 'alice/out.csv'})
      );
    });

    it('stops a multi-statement selection at a failed first statement, as every scope does', async () => {
      queueRuns('q-1', 'q-2');
      statusMap['q-1'] = {state: 'FAILED', stateChangeReason: 'SYNTAX_ERROR: line 1'};
      seedScript('SELECT 1;\nSELECT 2;');
      const {user} = renderWorkspace();
      const ta = (await screen.findByLabelText('SQL editor')) as HTMLTextAreaElement;

      ta.setSelectionRange(0, ta.value.length);
      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(await screen.findByText(/Statement 1 of 2 failed\./)).toBeInTheDocument();
      expect(screen.getByText(/Statement 2 did not run/)).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('tablist', {name: 'Result tabs'})).not.toBeInTheDocument();
    });
  });

  describe('QueryWorkspace — a failed status poll', () => {
    const NOT_FOUND = 'That item no longer exists. Refresh and try again.';
    const UNREACHABLE = 'Can’t reach the server. Check your connection and try again.';

    /** Every status request for `id` fails — both the first and the hook's own retry. */
    function refuseStatus(id: string, code: string, message = `raw: execution ${id} is outside alice/`) {
      mockGetStatus.mockImplementation(async (queryExecutionId: string) =>
        queryExecutionId === id
          ? fail(message, code)
          : ok(succeeded(queryExecutionId, statusMap[queryExecutionId] ?? {}))
      );
    }
    const statusRequestsFor = (id: string) => mockGetStatus.mock.calls.filter(([requested]) => requested === id).length;

    it('ends the run and says why in the code’s wording, writing no verdict and stopping nothing', async () => {
      queueRuns('q-1');
      refuseStatus('q-1', 'NotFound');
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(await screen.findByText(NOT_FOUND)).toBeInTheDocument();
      expect(screen.queryByText(/is outside alice/)).not.toBeInTheDocument();
      expect(screen.queryByText('Running…')).not.toBeInTheDocument();
      expect(statusRequestsFor('q-1')).toBe(2);
      expect(mockUpdate).not.toHaveBeenCalled();
      expect(mockStopQuery).not.toHaveBeenCalled();
    });

    it('frees the tab, so Run starts a new execution', async () => {
      queueRuns('q-1', 'q-2');
      refuseStatus('q-1', 'NetworkUnavailable');
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText(UNREACHABLE);

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(await screen.findByText('Succeeded')).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(2);
    });

    it('stops a batch at the statement whose status cannot be read', async () => {
      queueRuns('q-1', 'q-2', 'q-3');
      refuseStatus('q-2', 'NotFound');
      seedTabs({
        version: 1,
        tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1; SELECT 2; SELECT 3;'}],
        activeTabId: 'a',
        nextQueryNumber: 2
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await runScriptSingle(user);

      expect(
        await screen.findByText(`Statement 2 of 3 failed. ${NOT_FOUND} Statement 3 did not run.`)
      ).toBeInTheDocument();
      expect(mockRunQuery).toHaveBeenCalledTimes(2);
    });

    it('keeps an earlier statement’s rows savable, beside a Failed verdict', async () => {
      queueRuns('q-1', 'q-2');
      refuseStatus('q-2', 'NotFound');
      seedTabs({
        version: 1,
        tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1; SELECT 2;'}],
        activeTabId: 'a',
        nextQueryNumber: 2
      });
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await runScriptTabs(user);
      expect(await screen.findByText('Failed')).toBeInTheDocument();

      await user.click(await screen.findByRole('button', {name: 'Save results…'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({sourceKey: 'alice/athenaresults/q-1.csv', destKey: 'alice/out.csv'})
      );
    });

    it('retries a failed status request once, and a run whose retry answers carries on', async () => {
      queueRuns('q-1');
      mockGetStatus.mockResolvedValueOnce(fail('fetch failed', 'NetworkUnavailable'));
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');

      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      expect(await screen.findByText('Succeeded')).toBeInTheDocument();
      expect(screen.queryByText('Query failed.')).not.toBeInTheDocument();
      expect(statusRequestsFor('q-1')).toBe(2);
    });

    it('asks nothing more once the run has settled, even when the network comes back', async () => {
      queueRuns('q-1');
      refuseStatus('q-1', 'NetworkUnavailable');
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText(UNREACHABLE);

      try {
        // A failed query is stale, so a reconnect refetches it unless the poll is disabled.
        await act(async () => {
          onlineManager.setOnline(false);
          onlineManager.setOnline(true);
          await new Promise((resolve) => setTimeout(resolve, 50));
        });
      } finally {
        onlineManager.setOnline(true);
      }

      expect(statusRequestsFor('q-1')).toBe(2);
      expect(screen.getByText(UNREACHABLE)).toBeInTheDocument();
    });
  });

  describe('QueryWorkspace — a query that outlives the ceiling', () => {
    const sentence = (id: string) =>
      `Data Quarry stopped waiting for this query after 30 minutes, so its results won’t appear here. When it finishes, they’re saved in your files under system_settings/athenaresults, in a file named after its query ID (${id}).`;

    /** Every status read for `id` finds it running; every other execution succeeds. */
    function keepRunning(id: string) {
      mockGetStatus.mockImplementation(async (queryExecutionId: string) =>
        queryExecutionId === id
          ? ok({queryExecutionId, state: 'RUNNING' as const})
          : ok(succeeded(queryExecutionId, statusMap[queryExecutionId] ?? {}))
      );
    }

    /**
     * Crosses the ceiling's mark in an `act` of its own, then advances one poll, whose read decides.
     * The mark is a state update, and React applies it only as the `act` around it exits.
     */
    async function outliveTheCeiling() {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });
    }

    const statusBar = () => screen.getAllByRole('status').find((el) => /Still running/.test(el.textContent ?? ''));

    it('settles with a warning that says where the results go, stops nothing, and frees the tab', async () => {
      await withFakeTimers(async () => {
        queueRuns('q-1', 'q-2');
        keepRunning('q-1');
        seedSingle('SELECT 1');
        const {user} = renderWorkspace();
        await screen.findByLabelText('SQL editor');
        await user.click(screen.getByRole('button', {name: 'Run statement'}));
        await screen.findByRole('button', {name: /Stop/});

        await outliveTheCeiling();

        const banner = (await screen.findByText(sentence('q-1'))).closest('[role="alert"]');
        expect(banner).toHaveTextContent('Still running');
        expect(banner).toHaveClass('bg-warning-soft');
        expect(screen.queryByText('Query failed.')).not.toBeInTheDocument();
        // Beside the banner, these say the run settled rather than that nothing happened.
        expect(screen.queryByText('Running…')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', {name: /Stop/})).not.toBeInTheDocument();
        expect(statusBar()).toBeDefined();
        expect(statusBar()).not.toHaveTextContent(/Failed|elapsed/);
        expect(mockStopQuery).not.toHaveBeenCalled();
        expect(mockUpdate).not.toHaveBeenCalled();

        await user.click(screen.getByRole('button', {name: 'Run statement'}));
        await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));
      });
    });

    it('gives a failed start after the verdict the failure’s own title and colour', async () => {
      await withFakeTimers(async () => {
        queueRuns('q-1');
        mockRunQuery.mockResolvedValueOnce(fail('fetch failed', 'NetworkUnavailable'));
        keepRunning('q-1');
        seedSingle('SELECT 1');
        const {user} = renderWorkspace();
        await screen.findByLabelText('SQL editor');
        await user.click(screen.getByRole('button', {name: 'Run statement'}));
        await screen.findByRole('button', {name: /Stop/});
        await outliveTheCeiling();
        await screen.findByText(sentence('q-1'));

        await user.click(screen.getByRole('button', {name: 'Run statement'}));

        const banner = (
          await screen.findByText('Can’t reach the server. Check your connection and try again.')
        ).closest('[role="alert"]');
        expect(banner).toHaveTextContent('Query failed.');
        expect(banner).toHaveClass('bg-danger-soft');
      });
    });

    it('stops a batch at the statement it stopped watching', async () => {
      await withFakeTimers(async () => {
        queueRuns('q-1', 'q-2', 'q-3');
        keepRunning('q-2');
        seedTabs({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1; SELECT 2; SELECT 3;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        });
        const {user} = renderWorkspace();
        await screen.findByLabelText('SQL editor');
        await runScriptSingle(user);
        await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));

        await outliveTheCeiling();

        expect(
          await screen.findByText(`Statement 2 of 3 is still running. ${sentence('q-2')} Statement 3 did not run.`)
        ).toBeInTheDocument();
        expect(mockRunQuery).toHaveBeenCalledTimes(2);
      });
    });

    it('keeps an earlier statement’s rows savable beside the Still running verdict', async () => {
      await withFakeTimers(async () => {
        queueRuns('q-1', 'q-2');
        keepRunning('q-2');
        seedTabs({
          version: 1,
          tabs: [{id: 'a', label: 'Query 1', sql: 'SELECT 1; SELECT 2;'}],
          activeTabId: 'a',
          nextQueryNumber: 2
        });
        const {user} = renderWorkspace();
        await screen.findByLabelText('SQL editor');
        await runScriptTabs(user);
        await waitFor(() => expect(mockRunQuery).toHaveBeenCalledTimes(2));
        await outliveTheCeiling();
        await screen.findByText(new RegExp(`Statement 2 of 2 is still running`));

        await user.click(await screen.findByRole('button', {name: 'Save results…'}));
        const dialog = await screen.findByRole('dialog', {name: 'Save results'});
        const nameInput = within(dialog).getByLabelText('File name');
        await user.clear(nameInput);
        await user.type(nameInput, 'out');
        await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

        await waitFor(() =>
          expect(mockCopyObject).toHaveBeenCalledWith(
            expect.objectContaining({sourceKey: 'alice/athenaresults/q-1.csv', destKey: 'alice/out.csv'})
          )
        );
      });
    });
  });

  describe('QueryWorkspace — a dismissed banner and a refused Stop', () => {
    const COLUMN_MISSING = 'A column in your query wasn’t found. Check the column names.';

    /** Runs `q-1` to a failure and closes its banner. */
    async function failAndDismiss(user: ReturnType<typeof renderWorkspace>['user']) {
      statusMap['q-1'] = {state: 'FAILED', stateChangeReason: 'COLUMN_NOT_FOUND: amont'};
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText(COLUMN_MISSING);
      await user.click(screen.getByRole('button', {name: 'Dismiss'}));
    }

    it('keeps a dismissed banner closed while the next run starts, then shows that run’s own failure', async () => {
      queueRuns('q-1', 'q-2');
      statusMap['q-2'] = {state: 'FAILED', stateChangeReason: 'TABLE_NOT_FOUND: Table alice.nope does not exist'};
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await failAndDismiss(user);
      let landAppend = () => {};
      mockAppend.mockReturnValueOnce(
        new Promise((resolve) => (landAppend = () => resolve(ok({version: 1, entries: []}))))
      );

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await waitFor(() =>
        expect(mockAppend).toHaveBeenLastCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-2'}))
      );

      expect(screen.queryByText('Query failed.')).not.toBeInTheDocument();
      landAppend();
      expect(
        await screen.findByText('That table wasn’t found. Check the name and that it includes its database.')
      ).toBeInTheDocument();
    });

    it('shows a start that fails after a dismissed banner, and its retry does not bring the dismissed one back', async () => {
      queueRuns('q-1');
      mockRunQuery
        .mockResolvedValueOnce(fail('raw: rate exceeded for alice', 'ThrottlingException'))
        .mockResolvedValueOnce(ok({queryExecutionId: 'q-3'}));
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await failAndDismiss(user);

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      expect(await screen.findByText('The service is busy. Wait a moment and try again.')).toBeInTheDocument();
      expect(screen.queryByText(/rate exceeded/)).not.toBeInTheDocument();

      // The failed start installed no run, so the dismissed failure is still the tab's.
      mockAppend.mockReturnValueOnce(new Promise(() => {}));
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await waitFor(() =>
        expect(mockAppend).toHaveBeenLastCalledWith('alice', expect.objectContaining({queryExecutionId: 'q-3'}))
      );
      expect(screen.queryByText(COLUMN_MISSING)).not.toBeInTheDocument();
    });

    it('says why a Stop was refused, in the code’s wording, and leaves the run going', async () => {
      queueRuns('q-1');
      statusMap['q-1'] = {state: 'RUNNING'};
      mockStopQuery.mockResolvedValueOnce(fail('raw: cannot cancel q-1', 'NetworkError'));
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      await user.click(await screen.findByRole('button', {name: 'Stop the running query'}));

      expect(
        await screen.findByText('Couldn’t stop the query. Can’t reach the server. Check your connection and try again.')
      ).toBeInTheDocument();
      expect(screen.queryByText(/cannot cancel/)).not.toBeInTheDocument();
      expect(mockStopQuery).toHaveBeenCalledWith('q-1');
      expect(screen.getByText('Running…')).toBeInTheDocument();
    });

    it('keeps a refused Stop’s toast when a View DDL started before it lands', async () => {
      queueRuns('q-1');
      statusMap['q-1'] = {state: 'RUNNING'};
      mockStopQuery.mockResolvedValueOnce(fail('raw: cannot cancel q-1', 'NetworkError'));
      let land = () => {};
      mockGetTableDdl.mockReturnValueOnce(
        new Promise((resolve) => (land = () => resolve(ok('CREATE EXTERNAL TABLE sales_2026 (region string)'))))
      );
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await openTableMenu(user, 'sales_2026');
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'View DDL'}));
      await user.click(await screen.findByRole('button', {name: 'Stop the running query'}));
      const refusal = 'Couldn’t stop the query. Can’t reach the server. Check your connection and try again.';
      await screen.findByText(refusal);

      await act(async () => land());

      expect(await screen.findByRole('tab', {name: /DDL: sales_2026/})).toBeInTheDocument();
      expect(screen.getByText(refusal)).toBeInTheDocument();
    });

    it('says nothing when a Stop goes through', async () => {
      queueRuns('q-1');
      statusMap['q-1'] = {state: 'RUNNING'};
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await screen.findByLabelText('SQL editor');
      await user.click(screen.getByRole('button', {name: 'Run statement'}));

      await user.click(await screen.findByRole('button', {name: 'Stop the running query'}));
      await waitFor(() => expect(mockStopQuery).toHaveBeenCalledWith('q-1'));
      await act(async () => {});

      expect(screen.queryByText(/Couldn’t stop/)).not.toBeInTheDocument();
    });
  });

  describe('QueryWorkspace — shared-space routing & save (SPEC-055/077)', () => {
    it('runs with no db/outputLocation, offers personal + shared save destinations, and links a shared save into Files', async () => {
      // Two shared spaces in one bucket, the other sorting first, so the link has to pick by folder.
      mockReadCache.mockResolvedValue(
        ok({
          version: 1,
          connections: [
            {name: 'analytics', role: 'member', status: 'active'},
            {name: 'salesdata', role: 'member', status: 'active'}
          ]
        })
      );
      seedSingle('SELECT 1');
      mockCopyObject.mockResolvedValue(ok({destKey: 'salesdata/out.csv'}));
      const {user} = renderWorkspace();
      await screen.findByRole('button', {name: 'sales_2026'}); // rail loaded

      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
      // The run carries neither a database context nor a shared outputLocation.
      expect(mockRunQuery).toHaveBeenCalledTimes(1);
      expect(mockRunQuery.mock.calls[0][0]).toEqual({sql: 'SELECT 1', username: 'alice'});
      expect(mockRunQuery.mock.calls[0][0]).not.toHaveProperty('outputLocation');

      await user.click(await screen.findByRole('button', {name: 'Save results…'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      const spaceSelect = within(dialog).getByLabelText('Save to');
      expect(within(spaceSelect).getByRole('option', {name: 'alice'})).toBeInTheDocument();
      expect(within(spaceSelect).getByRole('option', {name: 'salesdata'})).toBeInTheDocument();

      await user.selectOptions(spaceSelect, 'salesdata');
      const nameInput = within(dialog).getByLabelText('File name');
      await user.clear(nameInput);
      await user.type(nameInput, 'out');
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));

      // Cross-bucket copy from the personal results prefix into the shared space.
      expect(mockCopyObject).toHaveBeenCalledWith(
        expect.objectContaining({
          bucket: 'user-bucket',
          destBucket: 'shared-bucket',
          sourceKey: 'alice/athenaresults/q-1.csv',
          destKey: 'salesdata/out.csv',
          overwrite: false
        })
      );
      expect(await screen.findByText(/Saved to salesdata\/out\.csv/)).toBeInTheDocument();
      // `space` is part of the assertion: without it Files resolves the personal space and opens
      // it at its root, and with the wrong one it opens `analytics`, which shares the bucket.
      await user.click(screen.getByRole('button', {name: 'View in Files'}));
      expect(screen.getByLabelText('probe-location')).toHaveTextContent('/files?space=salesdata&prefix=salesdata%2F');
    });

    // The space half of a cancelled overwrite's restore, which the one-space test cannot see — the
    // selector renders nothing below two options — and the lifecycle's other half: a fresh open
    // forgets what a cancel restored.
    it('a cancelled overwrite reopens in the shared space and folder, and a fresh open forgets them', async () => {
      mockReadCache.mockResolvedValue(
        ok({version: 1, connections: [{name: 'salesdata', role: 'member', status: 'active'}]})
      );
      seedSingle('SELECT 1');
      mockListFiles.mockImplementation(async (_bucket, prefix) =>
        ok({
          files: [],
          folders:
            prefix === 'salesdata/' ? [{type: 'folder' as const, prefix: 'salesdata/reports/', name: 'reports'}] : [],
          isTruncated: false
        })
      );
      mockCopyObject.mockResolvedValue(fail('exists', 'Collision'));
      const {user} = renderWorkspace();
      await screen.findByRole('button', {name: 'sales_2026'});
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
      const cancelOverwrite = async () =>
        user.click(
          within(await screen.findByRole('alertdialog', {name: /confirm overwrite/i})).getByRole('button', {
            name: 'Cancel'
          })
        );

      await user.click(await screen.findByRole('button', {name: 'Save results…'}));
      const dialog = await screen.findByRole('dialog', {name: 'Save results'});
      await user.selectOptions(within(dialog).getByLabelText('Save to'), 'salesdata');
      await user.clear(within(dialog).getByLabelText('File name'));
      await user.type(within(dialog).getByLabelText('File name'), 'out');
      await user.click(await within(dialog).findByRole('button', {name: /open folder reports/i}));
      await user.click(within(dialog).getByRole('button', {name: 'Save here'}));
      await cancelOverwrite();

      const reopened = await screen.findByRole('dialog', {name: 'Save results'});
      expect(within(reopened).getByLabelText('Save to')).toHaveValue('salesdata');
      await user.click(within(reopened).getByRole('button', {name: 'Save here'}));
      expect(mockCopyObject).toHaveBeenLastCalledWith(
        expect.objectContaining({destBucket: 'shared-bucket', destKey: 'salesdata/reports/out.csv'})
      );

      await cancelOverwrite();
      const again = await screen.findByRole('dialog', {name: 'Save results'});
      await user.click(within(again).getByRole('button', {name: 'Cancel'}));
      await user.click(screen.getByRole('button', {name: 'Save results…'}));
      const fresh = await screen.findByRole('dialog', {name: 'Save results'});
      expect(within(fresh).getByLabelText('Save to')).toHaveValue('personal');
      expect((within(fresh).getByLabelText('File name') as HTMLInputElement).value).toMatch(/^query-results-/);
    });
  });

  // ── SPEC-145: refresh table ─────────────────────────────────────────────────

  describe('QueryWorkspace — refresh table (SPEC-145)', () => {
    const refreshDialog = () => screen.getByRole('alertdialog', {name: /confirm refresh table/i});

    beforeEach(() => {
      mockEnqueueRefresh.mockResolvedValue(ok(undefined));
    });

    it('enqueues a refresh from the rail menu and reports it as pending', async () => {
      const {user} = renderWorkspace();
      await user.click(await screen.findByRole('button', {name: 'Options for sales_2026'}));
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Refresh table'}));

      const dialog = refreshDialog();
      expect(within(dialog).getByText('alice.sales_2026')).toBeInTheDocument();
      expect(within(dialog).getByText('s3://user-bucket/alice/sales/')).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', {name: 'Refresh table'}));

      // The space is derived from the table's own location (FR-004).
      expect(mockEnqueueRefresh).toHaveBeenCalledWith({
        space: {kind: 'personal', bucket: 'user-bucket', prefix: 'alice/sales/', database: 'alice'},
        tableName: 'sales_2026'
      });
      expect(await screen.findByText(/Refreshing “alice\.sales_2026”/)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    });

    it('opens the link-borne dialog from a columns_removed notification link', async () => {
      const {user} = renderWorkspace('/query?refreshTable=alice.sales_2026&removed=legacy_id,Order%20ID');

      const dialog = await screen.findByRole('alertdialog', {name: /confirm refresh table/i});
      const named = within(dialog).getByRole('list', {name: /columns that would be removed/i});
      expect(within(named).getByText('legacy_id')).toBeInTheDocument();
      expect(within(named).getByText('Order ID')).toBeInTheDocument();

      // FR-003: confirm is gated on the opt-in in this state — since SPEC-186 FR-002 as an
      // `aria-disabled` refusal that says what it is waiting for, not a bare `disabled`.
      const confirm = within(dialog).getByRole('button', {name: 'Refresh table'});
      expect(confirm).toHaveAttribute('aria-disabled', 'true');
      await user.click(within(dialog).getByRole('checkbox', {name: /allow columns to be removed/i}));
      await user.click(confirm);

      expect(mockEnqueueRefresh).toHaveBeenCalledWith(expect.objectContaining({allowRemovals: true}));
    });
  });

  // ── SPEC-100: responsive workspace ──────────────────────────────────────────

  describe('QueryWorkspace — share table (SPEC-093)', () => {
    async function openShareDialog(user: ReturnType<typeof renderWorkspace>['user'], table = 'sales_2026') {
      await openTableMenu(user, table);
      await user.click(within(screen.getByRole('menu')).getByRole('menuitem', {name: 'Share table'}));
      return screen.getByRole('dialog', {name: `Share table ${table}`});
    }

    beforeEach(() => {
      mockEnqueueShare.mockResolvedValue(ok(undefined));
    });

    it('shares a table with two users from the rail menu and reports it as pending', async () => {
      const {user} = renderWorkspace();

      const dialog = await openShareDialog(user);
      // The DATABASE comes from the rail node, not from anywhere in the dialog (SPEC-077),
      // so it is worth seeing before the submit that carries it.
      expect(within(dialog).getByText('alice.sales_2026')).toBeInTheDocument();

      await user.type(within(dialog).getByLabelText('Usernames'), 'bob, cara');
      await user.click(within(dialog).getByRole('button', {name: 'Add'}));
      const chips = within(dialog).getByRole('list', {name: 'Recipients'});
      expect(within(chips).getByText('bob')).toBeInTheDocument();
      expect(within(chips).getByText('cara')).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', {name: 'Share'}));

      expect(mockEnqueueShare).toHaveBeenCalledWith({
        source: {database: 'alice', table: 'sales_2026'},
        tableName: 'sales_2026',
        recipients: [
          {kind: 'user', name: 'bob'},
          {kind: 'user', name: 'cara'}
        ]
      });
      expect(mockEnqueueShare).toHaveBeenCalledTimes(1);
      expect(await screen.findByText(/Sharing “alice\.sales_2026”/)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByRole('dialog', {name: /Share table/})).not.toBeInTheDocument());
    });
  });

  // ── SPEC-154 FR-005: results pagination, and the seam it shares ─────────────
  //
  // `'Next'` did not appear anywhere in this file, and the fixture could not enable it —
  // `rowsPage` hard-codes `nextToken: undefined`, so the pager was permanently disabled and
  // every path through it was unreachable. Coverage was hook state plus a prop spy, which is
  // exactly the split this spec exists to close.

  describe('QueryWorkspace — results pagination (SPEC-087)', () => {
    const page = (rows: string[][], nextToken?: string) => ({
      columns: [{name: 'region', type: 'string'}],
      rows,
      nextToken
    });

    /** Two server pages: page 1 carries a token, page 2 ends the walk. */
    function seedTwoPages() {
      mockGetResults.mockImplementation(async ({nextToken}: {nextToken?: string}) =>
        nextToken === 't-2' ? ok(page([['ap-south']])) : ok(page([['us-east'], ['eu-west']], 't-2'))
      );
    }

    async function runOnce(user: ReturnType<typeof renderWorkspace>['user']) {
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
    }

    it('says the results could not be read, rather than that the query returned no rows', async () => {
      mockGetResults.mockResolvedValue(fail('raw: results read refused for alice', 'NetworkError'));
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();

      await runOnce(user);

      expect(
        await screen.findByText('Can’t reach the server. Check your connection and try again.')
      ).toBeInTheDocument();
      expect(screen.queryByText('No rows returned.')).not.toBeInTheDocument();
      expect(screen.queryByText(/results read refused/)).not.toBeInTheDocument();
    });

    // A failed RE-read keeps the page it already has, so an empty result that loaded is still
    // an empty result — only a read that never loaded anything stands in for the answer. A DDL
    // statement's result is the hard case: it has no columns either.
    it('still says a loaded empty result returned no rows when a later re-read fails', async () => {
      mockGetResults.mockResolvedValue(ok({columns: [], rows: []}));
      seedSingle('SELECT 1');
      const {user, queryClient} = renderWorkspace();
      await runOnce(user);
      await screen.findByText('No rows returned.');
      mockGetResults.mockResolvedValue(fail('raw: results read refused for alice', 'NetworkError'));

      await act(async () => {
        await queryClient.refetchQueries({predicate: (q) => q.queryKey.includes('results')});
        // TanStack notifies observers on a later tick; the page must have re-rendered on the error.
        await new Promise((resolve) => setTimeout(resolve, 50));
      });

      expect(screen.getByText('No rows returned.')).toBeInTheDocument();
      expect(
        screen.queryByText('Can’t reach the server. Check your connection and try again.')
      ).not.toBeInTheDocument();
    });

    it('fetches page 2 with the NextToken and renders it', async () => {
      seedTwoPages();
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await runOnce(user);
      expect(await screen.findByText('us-east')).toBeInTheDocument();

      await user.click(screen.getByRole('button', {name: 'Next'}));

      expect(await screen.findByText('ap-south')).toBeInTheDocument();
      expect(screen.queryByText('us-east')).not.toBeInTheDocument();
      // The token is the whole mechanism — a Next that refetched page 1 would still "work"
      // visually on a fixture that returned the same rows twice.
      //
      // `maxRows` is load-bearing in this assertion, not decoration: with the suite's default
      // "Athena does not count" answer, `useResultRowCount` walks every page of the same
      // execution through this same mock, threading the token itself, so
      // `objectContaining({nextToken: 't-2'})` alone is satisfied by the row-count walker even if
      // the pager never threads anything. The walker uses ROW_COUNT_PAGE_SIZE; only the pager asks
      // for the display page size.
      expect(mockGetResults).toHaveBeenCalledWith({
        queryExecutionId: 'q-1',
        nextToken: 't-2',
        maxRows: DEFAULT_RESULTS_PAGE_SIZE
      });
    });

    // THE FIRST ARM of the row-count gate, which nothing else reaches. The count is opened by
    // the batch's verdict — a result tab exists — rather than by the first page's columns
    // arriving, and the only way to tell those apart is to keep that page in flight: under the
    // pre-change gate the count could not start at all while it hung. Its first request is the
    // ask for Athena's count, so that call is what the gate opening looks like.
    it('asks for the row count while the first page is still in flight', async () => {
      let displayPageStarted = false;
      mockGetResults.mockImplementation(async ({maxRows}: {maxRows?: number}) => {
        if (maxRows === ROW_COUNT_PAGE_SIZE) return ok(page([['us-east'], ['eu-west']]));
        displayPageStarted = true;
        return new Promise(() => {}) as never; // never settles
      });
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await runOnce(user);

      await waitFor(() => expect(mockGetRowCount).toHaveBeenCalledWith('q-1'));
      // The premise the assertion above rests on: the display page really was outstanding, so
      // the count cannot have been let through by columns that had already arrived.
      expect(displayPageStarted).toBe(true);
    });

    // THE SECOND ARM, which the first cannot cover. `isResultProducingSql` is a shape heuristic
    // over the SQL, so a statement it declines gets no result tab — and if Athena returns
    // columns for it anyway, the count worked before this change and has to keep working.
    // Same statement as the DDL test below; only the fixture differs, which is what makes both
    // arms mean something.
    it('still counts a statement the batch declined, when it returns columns anyway', async () => {
      mockGetResults.mockResolvedValue(ok(page([['us-east'], ['eu-west']])));
      seedSingle('CREATE TABLE t (a int)');
      const {user} = renderWorkspace();
      await runOnce(user);

      await waitFor(() => expect(mockGetRowCount).toHaveBeenCalledWith('q-1'));
    });

    // The paging-derived total is null until the last page has been loaded, so before this
    // the pager showed no total until you clicked Next to the very end — on a real result
    // that is every page of it. Athena's own count already knew the answer.
    it('shows the exact total in the pager on the FIRST page, without paging to the end', async () => {
      seedTwoPages();
      mockGetRowCount.mockResolvedValue(ok({rowCount: 3, pending: false}));
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();
      await runOnce(user);
      expect(await screen.findByText('us-east')).toBeInTheDocument();

      // 3 rows across both server pages, and we are still standing on page 1.
      expect(await screen.findByText(/Rows 1–2 of 3/)).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Next'})).toBeEnabled();
    });

    // DDL opens neither of the two gates, so nothing may be asked for it: not Athena's count,
    // and not the walk. Asserts the CALLS, not the absence of a number: the label is separately
    // gated on `hasResultSet`, so "no total on screen" is satisfied whether or not a request
    // went out.
    it('asks nothing and walks no pages for a statement that returns no rows', async () => {
      mockGetResults.mockResolvedValue(ok({columns: [], rows: []}));
      seedSingle('CREATE TABLE t (a int)');
      const {user} = renderWorkspace();
      await runOnce(user);

      await waitFor(() => expect(screen.getByText('Succeeded')).toBeInTheDocument());
      expect(mockGetRowCount).not.toHaveBeenCalled();
      expect(mockGetResults).not.toHaveBeenCalledWith(expect.objectContaining({maxRows: ROW_COUNT_PAGE_SIZE}));

      // The positive control, in the same test: a row-returning statement must ask. Without it,
      // a gate that never opened would make the negative above true for the wrong reason.
      cleanup();
      mockGetResults.mockResolvedValue(ok(page([['us-east']])));
      seedSingle('SELECT 1');
      const second = renderWorkspace();
      await runOnce(second.user);

      await waitFor(() => expect(mockGetRowCount).toHaveBeenCalledWith('q-1'));
    });

    // One total for the bar and the pager, and it never contradicts the grid. The count lands
    // after the first page, so each case waits for the cache to hold it: asserting on the first
    // render would read today's screen before the count arrives, and pass on unfixed code.
    it('shows the pager’s own total once it has the last page, over a disagreeing count', async () => {
      mockGetResults.mockResolvedValue(ok(page([['a'], ['b'], ['c']])));
      mockGetRowCount.mockResolvedValue(ok({rowCount: 5, pending: false}));
      seedSingle('SELECT 1');
      const {user, queryClient} = renderWorkspace();
      await runOnce(user);

      await waitFor(() => expect(queryClient.getQueryData(catalogKeys.rowCount('q-1'))).toBe(5));
      expect(await screen.findByText(/Rows 1–3 of 3/)).toBeInTheDocument();
      expect(screen.getByText(/3 rows ·/)).toBeInTheDocument();
      expect(screen.queryByText(/5 rows/)).not.toBeInTheDocument();
    });

    it.each([
      {count: 40, bar: /100\+ rows ·/, pager: /^Rows 1–100$/},
      // Equal to the rows loaded, with a token still present: an exactly-full page can carry one.
      {count: 100, bar: /100 rows ·/, pager: /^Rows 1–100 of 100$/},
      {count: 10_000_000, bar: /10,000,000 rows ·/, pager: /^Rows 1–100 of 10000000$/}
    ])('shows a count of $count only if it is at least the rows already loaded', async ({count, bar, pager}) => {
      const hundred = Array.from({length: 100}, (_, i) => [`r${i}`]);
      mockGetResults.mockImplementation(async ({maxRows}: {maxRows?: number}) =>
        maxRows === ROW_COUNT_PAGE_SIZE ? ok(page([])) : ok(page(hundred, 't-2'))
      );
      mockGetRowCount.mockResolvedValue(ok({rowCount: count, pending: false}));
      seedSingle('SELECT 1');
      const {user, queryClient} = renderWorkspace();
      await runOnce(user);

      await waitFor(() => expect(queryClient.getQueryData(catalogKeys.rowCount('q-1'))).toBe(count));
      expect(await screen.findByText(bar)).toBeInTheDocument();
      expect(screen.getByText(pager)).toBeInTheDocument();
    });

    // "100+" alone read as the whole answer to testers, who then assumed the total was unavailable.
    it('says the total is still being counted while Athena’s count is on its way', async () => {
      const hundred = Array.from({length: 100}, (_, i) => [`r${i}`]);
      mockGetResults.mockResolvedValue(ok(page(hundred, 't-2')));
      mockGetRowCount.mockImplementation(() => new Promise(() => {}) as never);
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();

      await runOnce(user);

      expect(await screen.findByText(/100\+ rows · counting… ·/)).toBeInTheDocument();
      expect(screen.getByText(/^Rows 1–100$/)).toBeInTheDocument();
    });

    it('stops saying it is counting once the pager holds the last page, whatever Athena’s count is doing', async () => {
      mockGetResults.mockResolvedValue(ok(page([['a'], ['b'], ['c']])));
      mockGetRowCount.mockImplementation(() => new Promise(() => {}) as never);
      seedSingle('SELECT 1');
      const {user} = renderWorkspace();

      await runOnce(user);

      expect(await screen.findByText(/3 rows ·/)).toBeInTheDocument();
      expect(screen.queryByText(/counting/)).not.toBeInTheDocument();
    });
  });

  // FR-005's neighbours: two settings that share the pagination seam — tested at hook level
  // and through a prop spy, never through a user path.

  describe('QueryWorkspace — result-view settings that survive a tab switch (SPEC-079/087)', () => {
    async function runOnce(user: ReturnType<typeof renderWorkspace>['user']) {
      await user.click(screen.getByRole('button', {name: 'Run statement'}));
      await screen.findByText('Succeeded');
    }

    it('keeps a column width across a switch away from the results tab and back', async () => {
      seedTabs({
        version: 1,
        tabs: [
          {id: 'a', label: 'Query 1', sql: 'SELECT 1'},
          {id: 'b', label: 'Query 2', sql: 'SELECT 2'}
        ],
        activeTabId: 'a',
        nextQueryNumber: 3
      });
      // A client with a REAL gcTime, deliberately, and the mechanism is worth stating precisely
      // because the obvious reading is wrong. It is NOT the table unmounting: `useQueryResults`
      // and `useColumnWidths` both live at the workspace level, above that boundary, exactly so
      // they survive. What happens is that switching tabs sends `displayExecutionId` to null, so
      // the results query KEY changes and `q-1` is left with no observer — which the harness's
      // `gcTime: 0` evicts instantly. Coming back re-fetches cold, `columns.length` is 0 for a
      // beat, and `useColumnWidths` re-seeds to defaults.
      //
      // Production sets no `gcTime` (lib/queryClient.ts), so TanStack's 5-minute default keeps
      // the pages cached and the dip never happens. Asserting the reset here would have pinned
      // the test client's behaviour as if it were the feature's. (The persistence is bounded by
      // that cache rather than by the session — see the delivery doc.)
      const {user, container} = renderWorkspace(undefined, {
        queryClient: new QueryClient({defaultOptions: {queries: {retry: false, staleTime: 0}}})
      });
      await runOnce(user);
      await screen.findByText('us-east');

      // Read through the <col> element, and this is the FR-009 exception rather than laziness:
      // the width has no accessible contract to assert — the separator exposes no
      // `aria-valuenow`, and the header's own style is not where the width lands.
      const regionWidth = () => (container.querySelectorAll('colgroup col')[1] as HTMLElement).style.width;
      const before = regionWidth();

      // The keyboard path is the accessible one and the only one jsdom can drive honestly:
      // ColumnResizeHandle is a role="separator" that nudges by COLUMN_RESIZE_STEP_PX.
      const handle = screen.getByRole('separator', {name: 'Resize column region'});
      handle.focus();
      await user.keyboard('{ArrowRight}{ArrowRight}');
      const widened = regionWidth();
      expect(widened).not.toBe(before);

      await user.click(screen.getByRole('tab', {name: /Query 2/}));
      await user.click(screen.getByRole('tab', {name: /Query 1/}));

      expect(regionWidth()).toBe(widened);
    });
  });
});

describe('QueryWorkspace.a11y', () => {
  // Integration a11y (react.md §21): render the REAL workspace — real SchemaBrowser
  // over the mocked glue boundary, the real tab strip/toolbar/results shell — and
  // check it under axe. Only the AWS service boundary + the heavy Monaco editor are
  // mocked. The QueryClient is pre-seeded so the schema rail shows real tables at
  // axe time rather than a transient loading state.

  // NOTE: the env stubs this section needs are set at the top of `queryWorkspaceSupport.tsx`,
  // which every workspace suite imports. A `vi.stubEnv` inside a describe body runs at
  // COLLECTION time and applies file-wide, so a second copy here would not be scoped anyway.

  /**
   * The real workspace inside seeded providers (schema tables warm in the cache).
   *
   * Bespoke tree, kept deliberately (SPEC-154 FR-007) — but no longer for the reason
   * that was written here. This case renders the tree itself now, so a
   * `renderWithProviders` result IS available; what the harness would also do is seed
   * the feature flags, and this check wants the registry's own defaults. The
   * QueryClient is still the harness's, so retry behaviour cannot drift.
   */
  function workspace(): ReactElement {
    const client = createTestQueryClient();
    client.setQueryData(connectionKeys.list('alice'), {version: 1, connections: []});
    client.setQueryData(catalogKeys.schema('alice'), {
      database: {name: 'alice'},
      tables: [{name: 'sales_2026', location: 's3://b/alice/sales/', columns: [{name: 'region', type: 'string'}]}]
    });
    client.setQueryData(queryKeys.history('alice'), {version: 1, entries: []});
    client.setQueryData(savedQueryKeys.list('personal'), {
      pages: [{queries: [], isTruncated: false}],
      pageParams: [undefined]
    });
    return (
      <AuthContext.Provider value={authValue()}>
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <ToastProvider>
              <QueryWorkspace />
            </ToastProvider>
          </MemoryRouter>
        </QueryClientProvider>
      </AuthContext.Provider>
    );
  }

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    // The suite-wide mocks above are bare `vi.fn()`; these cases need the boundary to
    // resolve so axe sees a populated workspace rather than a loading state.
    vi.mocked(getDatabase).mockResolvedValue({success: true, data: {name: 'alice'}});
    vi.mocked(listTables).mockResolvedValue({success: true, data: []});
    vi.mocked(getQueryHistory).mockResolvedValue({success: true, data: {version: 1, entries: []}});
    vi.mocked(listSavedQueries).mockResolvedValue({
      success: true,
      data: {queries: [], isTruncated: false}
    });
    vi.mocked(ensureSavedQueriesFolder).mockResolvedValue({success: true, data: undefined});
    vi.mocked(readSharedConnectionsCache).mockResolvedValue({
      success: true,
      data: {version: 1, connections: []}
    });
  });

  describe('QueryWorkspace accessibility (SPEC-045 FR-003)', () => {
    it('has no axe violations with the schema rail populated', async () => {
      const {container} = render(workspace());
      // Check the DRIVEN container, and assert the divider is in it first: axe
      // over a tree the separator never reached would pass by its absence.
      expect(await screen.findByRole('separator', {name: 'Resize the editor and results'})).toBeInTheDocument();
      await expectContainerHasNoA11yViolations(container, ROUTE_AXE_OPTIONS);
    });
  });
});
