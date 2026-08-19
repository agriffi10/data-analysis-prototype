import {beforeEach, describe, expect, it, vi} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {useExploration} from './useExploration';
import {useExplorationEviction, evictExplorations} from './useExplorationEviction';
import {invalidateSchema} from '../catalog/useSchema';
import {getQueryStatus, runQuery} from '../catalog/athena.service';
import {newExploration} from './exploration';
import {explorerKeys, explorationSourceScope} from './explorerKeys';
import type {ExplorationSource} from './dataExplorer.types';

vi.mock('../catalog/athena.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn()
}));

const ORDERS: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};
const OTHER_DB: ExplorationSource = {kind: 'table', spaceId: 'teamspace', database: 'teamspace', table: 'orders'};
const SAVED: ExplorationSource = {kind: 'sql', body: 'SELECT 1', label: 'monthly.sql'};

const ok = <T>(data: T) => ({success: true as const, data});

beforeEach(() => {
  vi.clearAllMocks();
  let started = 0;
  vi.mocked(runQuery).mockImplementation(async () => ok({queryExecutionId: `exec-${(started += 1)}`}) as never);
  vi.mocked(getQueryStatus).mockResolvedValue(
    ok({
      queryExecutionId: 'exec-1',
      state: 'SUCCEEDED' as const,
      dataScannedBytes: 10,
      engineExecutionTimeMillis: 5,
      stateChangeReason: undefined
    })
  );
});

/**
 * A table dropped and rebuilt under the same name renders BYTE-IDENTICAL SQL. Under
 * `staleTime: Infinity, gcTime: Infinity` that is a cache hit, so the Explorer answered from
 * the pre-rebuild execution — the old rows — for the rest of the session. These pin the
 * eviction that closes it, and the scoping that keeps it from being a blanket cache purge.
 */
describe('exploration cache eviction', () => {
  async function seed(source: ExplorationSource, executionId: string) {
    const client = createTestQueryClient();
    vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: executionId}));
    const exploration = newExploration(source);
    const {result, unmount} = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(result.current.queryExecutionId).toBe(executionId));
    const sql = result.current.sql as string;
    // Unmount so nothing is observing: an eviction with an observer attached refetches
    // immediately, which is a different behaviour and not the one under test.
    unmount();
    return {client, sql};
  }

  it('drops an unobserved table execution when its own database changes', async () => {
    const {client, sql} = await seed(ORDERS, 'exec-1');
    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(ORDERS), sql))).toBe('exec-1');

    evictExplorations(client, 'alice');

    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(ORDERS), sql))).toBeUndefined();
  });

  // THE LOAD-BEARING HALF FOR THE COMMONEST CASE. `resetQueries` clears an entry rather than
  // removing it, so an unobserved one stays in the cache with no data. Under
  // `staleTime: Infinity` that could plausibly sit empty forever and never re-run — it does
  // not, because staleTime governs refetching data that EXISTS. Asserted rather than reasoned
  // about: if this were wrong, the fix would be broken for every tab not currently on screen,
  // which is most of them.
  it('re-runs an unobserved exploration the next time it is opened', async () => {
    const {client, sql} = await seed(ORDERS, 'exec-1');
    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(ORDERS), sql))).toBe('exec-1');

    evictExplorations(client, 'alice', 'orders');
    // `seed` pins the mock to one id; the rebuild's execution is a different one.
    vi.mocked(runQuery).mockResolvedValue(ok({queryExecutionId: 'exec-after-rebuild'}));

    const reopened = renderHookWithProviders(() => useExploration(newExploration(ORDERS)), {queryClient: client});
    await waitFor(() => expect(reopened.result.current.queryExecutionId).toBe('exec-after-rebuild'));
  });

  it('leaves a table execution in a DIFFERENT database alone', async () => {
    const {client, sql} = await seed(OTHER_DB, 'exec-2');

    evictExplorations(client, 'alice');

    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(OTHER_DB), sql))).toBe('exec-2');
  });

  // A saved query's body is arbitrary SQL over any number of databases and this app has no
  // parser, so it is evicted whichever database moved. Over-eviction on purpose: the
  // alternative is a saved query that keeps showing rows a rebuilt table no longer holds.
  it('drops a saved-query execution whichever database changed', async () => {
    const {client, sql} = await seed(SAVED, 'exec-3');
    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(SAVED), sql))).toBe('exec-3');

    evictExplorations(client, 'a_database_it_may_or_may_not_read');

    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(SAVED), sql))).toBeUndefined();
  });

  // The point of the subscriber: no `invalidateSchema` caller had to be told about it, and
  // the next one will not have to be either.
  it('fires off an ordinary invalidateSchema, with no call of its own', async () => {
    const {client, sql} = await seed(ORDERS, 'exec-1');
    renderHookWithProviders(() => useExplorationEviction(), {queryClient: client});

    await invalidateSchema(client, 'alice');

    await waitFor(() =>
      expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(ORDERS), sql))).toBeUndefined()
    );
  });

  // THE POINT OF THE WHOLE FIX: a stale execution must not be served AT ALL — not until the
  // user changes a filter, not until they come back to the tab. Removing an observed query
  // makes TanStack refetch it immediately, so the tab in front of the user re-runs and shows
  // the rebuilt table's rows. That second execution is the price, and it is why the eviction is
  // scoped as narrowly as the signal allows rather than being made timid.
  it('re-runs a MOUNTED exploration of the table that changed', async () => {
    const client = createTestQueryClient();
    const exploration = newExploration(ORDERS);
    const {result} = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));

    evictExplorations(client, 'alice', 'orders');

    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-2'));
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  // The narrowing that makes the above affordable. Creating a view beside an exploration
  // changes the catalog and changes none of its rows; re-running it would be a bill for
  // nothing, every time.
  it('leaves a mounted exploration of a DIFFERENT table alone', async () => {
    const client = createTestQueryClient();
    const exploration = newExploration(ORDERS);
    const {result} = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));

    evictExplorations(client, 'alice', 'monthly_revenue_view');

    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(result.current.queryExecutionId).toBe('exec-1');
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  // A change that names no table claims anything in the database may have moved — an arbitrary
  // DDL statement the user typed, or the rail's own refresh button. Both are cases where
  // re-reading everything is what was asked for.
  it('re-runs a mounted exploration when the change names no table', async () => {
    const client = createTestQueryClient();
    const exploration = newExploration(ORDERS);
    const {result} = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));

    evictExplorations(client, 'alice');

    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-2'));
  });

  // The registration is module-level state, so an unmounted shell that kept listening would
  // evict into a client nobody is using and hold it alive with it.
  it('stops listening when the shell unmounts', async () => {
    const {client, sql} = await seed(ORDERS, 'exec-1');
    const shell = renderHookWithProviders(() => useExplorationEviction(), {queryClient: client});
    shell.unmount();

    await invalidateSchema(client, 'alice');

    expect(client.getQueryData(explorerKeys.execution(explorationSourceScope(ORDERS), sql))).toBe('exec-1');
  });
});
