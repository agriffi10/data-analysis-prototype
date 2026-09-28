import {vi} from 'vitest';
import {getQueryResults, getQueryStatus, runQuery} from '../catalog/athena.service';
import {getDatabase, listTables} from '../catalog/glue.service';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {EXPLORATION_TABS_STORAGE_PREFIX} from './dataExplorer.constants';
import {newExploration} from './exploration';
import type {QueryState} from '../catalog/catalog.types';
import type {AwaitingRun, ColumnFilter, ExplorationTab, ExplorationTabsState, Grouping} from './dataExplorer.types';

/**
 * The Athena stand-in the values-listing suites share.
 *
 * The files that use it declare their own `vi.mock` of the three service modules — a mock is
 * hoisted per test file — and this installs the behaviour: an execution per `runQuery`, each
 * remembered by its SQL, so a listing and an exploration answer differently, and a listing's
 * status can be held RUNNING behind a gate until a test releases it.
 */

export const ok = <T>(data: T) => ({success: true as const, data});

export const COLUMNS = [
  {name: 'brnd_name', type: 'varchar'},
  {name: 'qty', type: 'bigint'},
  {name: 'ship_date', type: 'date'},
  {name: 'active', type: 'boolean'}
];

export const ROWS = [
  ['Abilify', '10', '2024-01-01', 'true'],
  [null, '2', '2024-01-02', 'false'],
  ['', '3', '2024-01-03', 'true']
];

/** What a listing scans, apart from what an exploration scans, so a total says which ran. */
export const LISTING_BYTES = 4096;
export const EXPLORATION_BYTES = 2048;

/** `[value, row_count, value_count]`, as the listing statement returns them. */
export const LISTING_ROWS: (string | null)[][] = [
  ['Abilify', '40', '3'],
  ['', '3', '3'],
  [null, '2', '3']
];

export const USERNAME = 'alice';

/** Whether a statement is a values listing rather than an exploration. */
export const isListing = (sql: string) => sql.includes(' AS "value", COUNT(*) AS "row_count"');

type Deferred = {promise: Promise<void>; release: () => void};

/** A gate a listing's status waits behind, so a test can close the dialog while it runs. */
export function gate(): Deferred {
  let release = () => {};
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return {promise, release};
}

export type AthenaStandIn = {
  sqlOf: Map<string, string>;
  /** The rows a listing returns, by its SQL; the default is `LISTING_ROWS`. */
  listingRows: (sql: string) => (string | null)[][];
  /** The state a listing settles in. */
  listingState: QueryState;
  /** When set, every listing's status read waits for it. */
  listingGate: Deferred | null;
  /** Fails this many listing result reads before they succeed. */
  failedListingReads: number;
};

/**
 * Installs the stand-in on the mocked services and seeds the catalog calls the workspace makes.
 *
 * @returns The stand-in, whose fields a test changes to steer what Athena answers.
 */
export function installAthena(): AthenaStandIn {
  const athena: AthenaStandIn = {
    sqlOf: new Map(),
    listingRows: () => LISTING_ROWS,
    listingState: 'SUCCEEDED',
    listingGate: null,
    failedListingReads: 0
  };
  vi.stubEnv('VITE_S3_USER_SPACE_BUCKET', 'user-space');
  vi.stubEnv('VITE_S3_SHARED_SPACE_BUCKET', 'shared-space');
  vi.mocked(readSharedConnectionsCache).mockResolvedValue(ok({version: 1, connections: []}) as never);
  vi.mocked(getDatabase).mockResolvedValue(ok({name: USERNAME}) as never);
  vi.mocked(listTables).mockResolvedValue(ok([{name: 'orders', tableType: 'EXTERNAL_TABLE', columns: []}]) as never);

  let seq = 0;
  vi.mocked(runQuery).mockImplementation((async ({sql}: {sql: string}) => {
    seq += 1;
    const queryExecutionId = `exec-${seq}`;
    athena.sqlOf.set(queryExecutionId, sql);
    return ok({queryExecutionId});
  }) as never);
  vi.mocked(getQueryStatus).mockImplementation((async (queryExecutionId: string) => {
    const listing = isListing(athena.sqlOf.get(queryExecutionId) ?? '');
    if (listing && athena.listingGate) await athena.listingGate.promise;
    const state = listing ? athena.listingState : 'SUCCEEDED';
    return ok({
      queryExecutionId,
      state,
      stateChangeReason: state === 'FAILED' ? 'SYNTAX_ERROR: line 1:8: mismatched input' : undefined,
      dataScannedBytes: listing ? LISTING_BYTES : EXPLORATION_BYTES,
      engineExecutionTimeMillis: 120
    });
  }) as never);
  vi.mocked(getQueryResults).mockImplementation((async ({queryExecutionId}: {queryExecutionId: string}) => {
    const sql = athena.sqlOf.get(queryExecutionId) ?? '';
    if (!isListing(sql)) return ok({columns: COLUMNS, rows: ROWS});
    if (athena.failedListingReads > 0) {
      athena.failedListingReads -= 1;
      return {success: false, error: {message: 'Service unavailable', code: 'ServiceUnavailable'}};
    }
    return ok({
      columns: [
        {name: 'value', type: 'varchar'},
        {name: 'row_count', type: 'bigint'},
        {name: 'value_count', type: 'bigint'}
      ],
      rows: athena.listingRows(sql)
    });
  }) as never);
  return athena;
}

/** Every listing statement started so far, in order. */
export function listingStarts(): string[] {
  return vi
    .mocked(runQuery)
    .mock.calls.map(([call]) => (call as {sql: string}).sql)
    .filter(isListing);
}

/** Every exploration statement started so far, in order. */
export function explorationStarts(): string[] {
  return vi
    .mocked(runQuery)
    .mock.calls.map(([call]) => (call as {sql: string}).sql)
    .filter((sql) => !isListing(sql));
}

type SeededTab = {
  id: string;
  filters?: ColumnFilter[];
  grouping?: Grouping | null;
  awaitingRun?: AwaitingRun;
};

/**
 * Stores tabs over `alice.orders` for the workspace to restore.
 *
 * @param tabs - Each tab's id and the parts of its query that differ from an empty one.
 * @param activeTabId - Which tab is in front; the first when omitted.
 */
export function seedTabs(tabs: SeededTab[], activeTabId = tabs[0].id): void {
  const state: ExplorationTabsState = {
    version: 1,
    tabs: tabs.map(({id, filters = [], grouping = null, awaitingRun}) => {
      const created = newExploration({kind: 'table', spaceId: 'personal', database: USERNAME, table: 'orders'}, id);
      const tab: ExplorationTab = {
        id,
        label: `orders ${id}`,
        exploration: {...created, query: {...created.query, filters, grouping}},
        scannedByExecution: {},
        history: {past: [], future: []}
      };
      return awaitingRun ? {...tab, awaitingRun} : tab;
    }),
    activeTabId
  };
  sessionStorage.setItem(`${EXPLORATION_TABS_STORAGE_PREFIX}${USERNAME}`, JSON.stringify(state));
}

/**
 * A tab as the workspace last stored it, ledger and history included.
 *
 * @param id - The tab's id.
 * @returns The stored tab.
 */
export function storedTab(id: string): ExplorationTab {
  const raw = sessionStorage.getItem(`${EXPLORATION_TABS_STORAGE_PREFIX}${USERNAME}`) ?? '{"tabs":[]}';
  const tab = (JSON.parse(raw) as ExplorationTabsState).tabs.find((candidate) => candidate.id === id);
  if (!tab) throw new Error(`No stored tab ${id}.`);
  return tab;
}

/**
 * The execution ids of the listings a tab has been billed for.
 *
 * @param id - The tab's id.
 * @returns Each listing execution in the tab's ledger with the bytes it was billed.
 */
export function billedListings(id: string): Record<string, number> {
  return Object.fromEntries(
    Object.entries(storedTab(id).scannedByExecution).filter(([executionId]) => isListing(sqlById(executionId)))
  );
}

function sqlById(executionId: string): string {
  const index = Number(executionId.replace('exec-', '')) - 1;
  const call = vi.mocked(runQuery).mock.calls[index];
  return call ? (call[0] as {sql: string}).sql : '';
}
