import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor} from '@testing-library/react';
import {
  editor,
  installWorkspaceMocks,
  mockRunQuery,
  renderWorkspace,
  resetViewport,
  seedSingle,
  seedTabs
} from '../../test/queryWorkspaceSupport';
import {buildOpenSqlHandoff} from '../../lib/routeHandoff';
import {Link} from '../../lib/navigation';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {traverse} from '../../test/nextNavigation';
import {QueryRunsProvider} from './QueryRunsProvider';
import {QueryWorkspace} from './QueryWorkspace';
import {QUERY_TABS_MAX, QUERY_TABS_STORAGE_PREFIX} from './query.constants';
import type {QueryTabsState} from './query.types';

// The Query half of *Open in Query*: a statement from the Data Explorer's Generated SQL arrives as
// router state and opens ONE new tab, unrun, and nothing is left in history for a reload or Back
// to open again. Rendered under `StrictMode` as the placed root, as the app is — its doubled
// effect is the hazard — on jsdom's own history, where the replaced entry can be read.
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

// Leading spaces, a blank line and a trailing space: "equals exactly" has to mean exactly.
const SQL = '  SELECT *\nFROM "alice"."orders"\n\nWHERE "state" = \'NY\' ';
const HANDOFF = {pathname: '/query', state: buildOpenSqlHandoff({sql: SQL, label: 'orders'})};

function seedFullStrip() {
  seedTabs({
    version: 1,
    tabs: Array.from({length: QUERY_TABS_MAX}, (_, i) => ({id: `t${i}`, label: `Query ${i + 1}`, sql: ''})),
    activeTabId: 't0',
    nextQueryNumber: QUERY_TABS_MAX + 1
  });
}

function persistedTabs(): QueryTabsState {
  return JSON.parse(sessionStorage.getItem(`${QUERY_TABS_STORAGE_PREFIX}alice`) ?? '{}') as QueryTabsState;
}

function render(route: Parameters<typeof renderWorkspace>[0]) {
  return renderWorkspace(route, {strictMode: true});
}

/** The phone's read-only SQL view, found by its exact text so whitespace counts. */
function shownStatement() {
  return screen.getByText((_content, element) => element?.tagName === 'PRE' && element.textContent === SQL);
}

describe('a statement handed over from the Data Explorer', () => {
  beforeEach(installWorkspaceMocks);
  afterEach(resetViewport);

  it('opens one new tab holding it exactly, runs nothing, and clears the hand-off from history', async () => {
    seedSingle('SELECT 1;');

    const {location} = render(HANDOFF);

    expect(await screen.findByRole('tab', {name: /orders/})).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    // The editor is lazy, so it is waited for; its text is compared whole.
    await screen.findByLabelText('SQL editor');
    expect(editor().value).toBe(SQL);
    await waitFor(() => expect(location().state).toEqual(null));
    expect(window.location.pathname).toBe('/query');
    expect(mockRunQuery).not.toHaveBeenCalled();
  });

  it('raises the tab limit at the cap, opens nothing, and still clears the hand-off', async () => {
    seedFullStrip();

    const {location} = render(HANDOFF);

    expect(await screen.findByRole('alertdialog', {name: /query tab limit reached/i})).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(QUERY_TABS_MAX);
    expect(screen.queryByRole('tab', {name: /orders/})).toBeNull();
    await waitFor(() => expect(location().state).toEqual(null));
  });

  it('ignores state it did not build, and leaves the entry alone', async () => {
    seedSingle('SELECT 1;');
    const malformed = {openSql: {sql: 1}};

    const {location} = render({pathname: '/query', state: malformed});

    expect(await screen.findByRole('tab', {name: /Query 1/})).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(1);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(location().state).toEqual(malformed);
  });

  it('shows the statement read-only on a phone, and opens its tab for a wider screen', async () => {
    window.innerWidth = 390;
    seedSingle('SELECT 1;');

    render(HANDOFF);

    expect(await screen.findByRole('heading', {name: 'orders'})).toBeInTheDocument();
    expect(shownStatement()).toBeInTheDocument();
    await waitFor(() => expect(persistedTabs().tabs.map((tab) => tab.label)).toEqual(['Query 1', 'orders']));
    const opened = persistedTabs().tabs[1];
    expect(persistedTabs().activeTabId).toBe(opened.id);
    expect(opened.sql).toBe(SQL);
    expect(mockRunQuery).not.toHaveBeenCalled();
  });

  it('still shows the statement on a phone at the cap, and raises no dialog a phone cannot act on', async () => {
    window.innerWidth = 390;
    seedFullStrip();

    const {location} = render(HANDOFF);

    expect(await screen.findByRole('heading', {name: 'orders'})).toBeInTheDocument();
    expect(shownStatement()).toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(persistedTabs().tabs).toHaveLength(QUERY_TABS_MAX);
    await waitFor(() => expect(location().state).toEqual(null));
  });
});

describe('a hand-off already read', () => {
  beforeEach(installWorkspaceMocks);
  afterEach(resetViewport);

  // The seam never writes a hand-off to history, so nothing a traversal or a reload restores can
  // carry one; the receiver's replace is belt and braces. Measured on both routers while authoring.
  it('opens nothing on Back and then Forward to its entry, and nothing on a reload', async () => {
    seedSingle('SELECT 1;');
    const workspace = (
      <>
        <QueryRunsProvider username="alice">
          <QueryWorkspace />
        </QueryRunsProvider>
        <Link to="/files">Away</Link>
      </>
    );
    const view = renderWithProviders(workspace, {
      route: HANDOFF,
      path: '/query',
      routes: {'/files': <p>Files</p>},
      auth: authenticated('alice'),
      strictMode: true
    });
    expect(await screen.findByRole('tab', {name: /orders/})).toBeInTheDocument();
    await waitFor(() => expect(view.location().state).toEqual(null));

    await view.user.click(screen.getByRole('link', {name: 'Away'}));
    await screen.findByText('Files');
    await traverse(-1);
    await traverse(1);
    await traverse(-1);

    await screen.findByRole('tab', {name: /orders/});
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(view.location().pathname).toBe('/query');
    expect(view.location().state).toBeUndefined();

    view.unmount();
    renderWorkspace('/query', {strictMode: true});
    expect(await screen.findByRole('tab', {name: /orders/})).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(2);
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });
});
