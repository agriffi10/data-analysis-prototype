import {vi} from 'vitest';
import {screen} from '@testing-library/react';
import {useLocation} from 'react-router';
import {renderWithProviders} from './renderWithProviders';
import type {TestRoute} from './renderWithProviders';
import {authenticated} from './authFixtures';
import {useNavRailContent} from '../components/navRailContext';
import {
  getQueryResults,
  getQueryRowCount,
  getQueryStatus,
  getTableDdl,
  runQuery,
  runStatementToCompletion,
  stopQuery
} from '../features/catalog/athena.service';
import {getDatabase, listTables} from '../features/catalog/glue.service';
import {appendQueryHistory, getQueryHistory, updateQueryHistoryEntry} from '../features/query/queryHistory.service';
import {
  deleteSavedQuery,
  ensureSavedQueriesFolder,
  listSavedQueries,
  readSavedQuery,
  writeSavedQuery
} from '../features/saved-queries/savedQueries.service';
import {readSharedConnectionsCache} from '../features/shared-spaces/sharedSpaces.service';
import {copyObject, listFiles} from '../features/file-browser/fileBrowser.service';
import {enqueueTableRefresh} from '../features/table-builder/tableBuild.service';
import {enqueueTableShare} from '../features/table-share/tableShare.service';
import {QueryWorkspace} from '../features/query/QueryWorkspace';
import {QUERY_TABS_STORAGE_PREFIX} from '../features/query/query.constants';
import type {QueryClient} from '@tanstack/react-query';
import type {QueryTabsState} from '../features/query/query.types';
import type {QueryState, QueryStatus} from '../features/catalog/catalog.types';

/*
 * Shared setup for the query workspace suites — the mocked service spies, the fixtures, the
 * seeds and the render. A suite that imports this must still declare the `vi.mock` calls for
 * the eight service modules and the editor stub: mocks are per test file and cannot be shared.
 */

// Integration style (react.md §21): render the REAL QueryWorkspace tree — real
// hooks (useQueryTabs/useConnections/useSchema/useQueryExecution/useQueryResults/
// useQueryHistory/useSavedQueries/useResultsPageSize/useResultRowCount/…) and real
// child components (SchemaBrowser/DatabaseNode/TableActionsMenu/QueryTabStrip/
// QueryStatusBar/QueryResultsTable/SaveResultsDialog/DestinationPicker/dialogs/
// drawers) — mocking ONLY the AWS service boundary. Pure helpers in
// query.service (parseS3Url/isTerminalState) and query.sql stay real via
// importActual so the real hooks and split/resolve logic behave normally.

// The Monaco editor is heavy/global (its own SqlEditor.test covers it) — stub the
// lazy wrapper with a textarea that still drives value/onChange and forwards the
// selection handle so statement-resolution tests can position a cursor.
// This is the sanctioned §21 heavy-child exception: Monaco needs a real DOM editor
// and workers, which jsdom has neither of.
//
// The stub used to type only `{value, onChange}`, so
// the three run-scope props were silently discarded and deleting one at the call
// site changed nothing any test could see. It now accepts them and exposes each as a
// button, which keeps the stub honest about the contract it stands in for — the
// keybindings themselves stay SqlEditor.test's subject, not this file's.

// copyObject = Save-results copy; listFiles = the SaveResultsDialog's real
// DestinationPicker folder listing.

export const mockRunQuery = vi.mocked(runQuery);
export const mockStopQuery = vi.mocked(stopQuery);
export const mockGetTableDdl = vi.mocked(getTableDdl);
export const mockRunToCompletion = vi.mocked(runStatementToCompletion);
export const mockGetStatus = vi.mocked(getQueryStatus);
export const mockGetResults = vi.mocked(getQueryResults);
export const mockGetRowCount = vi.mocked(getQueryRowCount);
export const mockListTables = vi.mocked(listTables);
export const mockGetHistory = vi.mocked(getQueryHistory);
export const mockAppend = vi.mocked(appendQueryHistory);
export const mockUpdate = vi.mocked(updateQueryHistoryEntry);
export const mockListSaved = vi.mocked(listSavedQueries);
export const mockReadSaved = vi.mocked(readSavedQuery);
export const mockWriteSaved = vi.mocked(writeSavedQuery);
export const mockDeleteSaved = vi.mocked(deleteSavedQuery);
export const mockReadCache = vi.mocked(readSharedConnectionsCache);
export const mockCopyObject = vi.mocked(copyObject);
export const mockListFiles = vi.mocked(listFiles);
export const mockEnqueueRefresh = vi.mocked(enqueueTableRefresh);
export const mockEnqueueShare = vi.mocked(enqueueTableShare);

// SaveResultsDialog and the space resolver read these at render/module time. Still load-bearing:
// removing the user-space stub fails 18 of the tests below.
vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-bucket');
vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-bucket');

export const ok = <T,>(data: T) => ({success: true as const, data});
export const fail = (message: string, code?: string) => ({
  success: false as const,
  error: {message, ...(code ? {code} : {})}
});

// ── Builders ────────────────────────────────────────────────────────────────
/** One `.sql` object in a space's `saved_queries/` folder. */
export const savedFile = (
  name: string,
  over: {spaceId?: string; bucket?: string; size?: number; updatedAt?: string} = {}
) => ({
  spaceId: over.spaceId ?? 'personal',
  bucket: over.bucket ?? 'user-bucket',
  key: `alice/saved_queries/${name}.sql`,
  name,
  updatedAt: over.updatedAt ?? '2026-07-01T10:00:00.000Z',
  size: over.size ?? 24
});
export const savedListing = (...names: string[]) => ok({queries: names.map((n) => savedFile(n)), isTruncated: false});
// The bucket in a LOCATION is load-bearing now, not scenery: View source files checks that
// the table's bucket IS the browsed space's, so this fixture names the stubbed one.
export const salesTable = {
  name: 'sales_2026',
  location: 's3://user-bucket/alice/sales/',
  columns: [{name: 'region', type: 'string'}]
};
/** Right bucket, someone else's prefix — fails the prefix half alone. */
export const foreignTable = {name: 'foreign', location: 's3://user-bucket/bob/x/', columns: []};
/**
 * Right prefix for its own space, WRONG bucket — fails the bucket half alone.
 *
 * Its own fixture because the two halves are separately deletable: a table that fails both
 * leaves the bucket check untested, since the prefix check already refused it.
 */
export const strayBucketTable = {name: 'stray', location: 's3://other-bucket/alice/stray/', columns: []};
export const viewObj = {name: 'revenue_view', tableType: 'VIRTUAL_VIEW', columns: []};

/**
 * Per-execution status overrides consulted by the getQueryStatus mock (live). Any field
 * of the status may be overridden, so a case can give two executions in one batch
 * DIFFERENT scanned/duration figures — equal ones agree whichever execution is read.
 *
 * `exactOptionalPropertyTypes` is off, so an explicit `undefined` here type-checks and
 * BLANKS the default below rather than leaving it. Omit a field to keep its default.
 */
export type StatusOverride = Partial<Omit<QueryStatus, 'queryExecutionId'>>;
export const statusMap: Record<string, StatusOverride> = {};
export const succeeded = (id: string, over: StatusOverride = {}) => ({
  queryExecutionId: id,
  state: 'SUCCEEDED' as QueryState,
  dataScannedBytes: 2048,
  engineExecutionTimeMillis: 800,
  outputLocation: `s3://user-bucket/alice/athenaresults/${id}.csv`,
  ...over
});

export const rowsPage = {
  columns: [{name: 'region', type: 'string'}],
  rows: [['us-east'], ['eu-west']],
  nextToken: undefined
};

export function seedTabs(state: QueryTabsState) {
  sessionStorage.setItem(`${QUERY_TABS_STORAGE_PREFIX}alice`, JSON.stringify(state));
}
export function seedSingle(sql: string) {
  seedTabs({version: 1, tabs: [{id: 'a', label: 'Query 1', sql}], activeTabId: 'a', nextQueryNumber: 2});
}

/** runQuery returns a distinct execution id per statement in a batch. */
export function queueRuns(...ids: string[]) {
  mockRunQuery.mockReset();
  for (const id of ids) mockRunQuery.mockResolvedValueOnce(ok({queryExecutionId: id}));
}

/** Renders whatever the page registered for the mobile nav drawer. */
export function NavRailProbe() {
  return <div aria-label="mobile nav rail">{useNavRailContent()}</div>;
}

/** A probe that surfaces the router location so navigation is observable without
 *  mocking react-router (everything stays real). */
export function LocationProbe() {
  const loc = useLocation();
  return <span aria-label="probe-location">{`${loc.pathname}${loc.search}`}</span>;
}

/**
 * The workspace as alice sees it, with a location probe beside it.
 *
 * `route` takes history state for a hand-off from another feature. A test of that hand-off also
 * passes `strictMode` and `browserRouter`: StrictMode's doubled effect is the hazard the receiver
 * guards against, and the entry it replaces is readable only on jsdom's own history.
 */
export function renderWorkspace(
  route?: TestRoute,
  options: {queryClient?: QueryClient; strictMode?: boolean; browserRouter?: boolean} = {}
) {
  return renderWithProviders(
    <>
      <QueryWorkspace />
      <LocationProbe />
    </>,
    {auth: authenticated('alice'), route, ...options}
  );
}

export const editor = () => screen.getByLabelText('SQL editor') as HTMLTextAreaElement;

/** The suite-wide boundary: every mocked service answering as an empty, healthy workspace. Call from `beforeEach`. */
export function installWorkspaceMocks() {
  vi.clearAllMocks();
  sessionStorage.clear();
  localStorage.clear();
  for (const key of Object.keys(statusMap)) delete statusMap[key];

  mockReadCache.mockResolvedValue(ok({version: 1, connections: []}));
  mockGetDatabase();
  mockListTables.mockResolvedValue(ok([salesTable, foreignTable, strayBucketTable, viewObj]));
  mockGetHistory.mockResolvedValue(ok({version: 1, entries: []}));
  mockListSaved.mockResolvedValue(ok({queries: [], isTruncated: false}));
  mockAppend.mockResolvedValue(ok({version: 1, entries: []}));
  mockUpdate.mockResolvedValue(ok({version: 1, entries: []}));
  mockWriteSaved.mockImplementation(async ({space, name, sql}) =>
    ok(savedFile(name, {spaceId: space.id, bucket: space.bucket, size: sql.length}))
  );
  mockReadSaved.mockResolvedValue(ok('SELECT 1;'));
  mockDeleteSaved.mockResolvedValue(ok(undefined));
  vi.mocked(ensureSavedQueriesFolder).mockResolvedValue(ok(undefined));
  mockRunQuery.mockResolvedValue(ok({queryExecutionId: 'q-1'}));
  mockStopQuery.mockResolvedValue(ok(undefined));
  mockGetStatus.mockImplementation(async (id: string) => ok(succeeded(id, statusMap[id] ?? {})));
  mockGetResults.mockResolvedValue(ok(rowsPage));
  // "Athena does not count this" — the suites' walk assertions keep their subject; a case about
  // Athena's own count answers a number itself.
  mockGetRowCount.mockResolvedValue(ok({rowCount: null, pending: false}));
  mockRunToCompletion.mockResolvedValue(ok(succeeded('q-run')));
  mockGetTableDdl.mockResolvedValue(ok('CREATE EXTERNAL TABLE ...'));
  mockCopyObject.mockResolvedValue(ok({destKey: 'alice/out.csv'}));
  mockListFiles.mockResolvedValue(ok({files: [], folders: [], isTruncated: false}));

  window.innerWidth = 1024;
}

/** Undo a case's viewport change. Call from `afterEach`. */
export function resetViewport() {
  window.innerWidth = 1024;
}

// getDatabase varies rarely — a helper so tests can override.
export function mockGetDatabase() {
  vi.mocked(getDatabase).mockImplementation(async (name: string) => ok({name}));
}

// Open the "More run options" split dropdown and pick a whole-script scope.
export async function runScriptSingle(user: ReturnType<typeof renderWorkspace>['user']) {
  await user.click(screen.getByRole('button', {name: 'More run options'}));
  await user.click(await screen.findByRole('menuitem', {name: 'Run Query Tab'}));
}
export async function runScriptTabs(user: ReturnType<typeof renderWorkspace>['user']) {
  await user.click(screen.getByRole('button', {name: 'More run options'}));
  await user.click(await screen.findByRole('menuitem', {name: 'Run Multiple Queries'}));
}

// Open a rail table's kebab menu (the rail auto-expands the personal db).
export async function openTableMenu(user: ReturnType<typeof renderWorkspace>['user'], table: string) {
  await user.click(await screen.findByRole('button', {name: `Options for ${table}`}));
}
