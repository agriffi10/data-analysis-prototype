import {beforeEach, describe, expect, it, vi} from 'vitest';
import {waitFor} from '@testing-library/react';
import {renderHookWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {useExploration} from './useExploration';
import {useQueryResults} from '../catalog/useQueryResults';
import {getQueryStatus, runQuery, getQueryResults} from '../catalog/athena.service';
import {newExploration} from './exploration';
import {explorerKeys} from './explorerKeys';
import type {Exploration, ExplorationSource} from './dataExplorer.types';
import type {QueryState} from '../catalog/catalog.types';

vi.mock('../catalog/athena.service', async (importOriginal) => ({
  // `isTerminalState` stays REAL: it decides when polling stops, and a stub would decide
  // the pending/settled boundary this suite is asserting.
  ...(await importOriginal<typeof import('../catalog/athena.service')>()),
  runQuery: vi.fn(),
  getQueryStatus: vi.fn(),
  getQueryResults: vi.fn()
}));

const TABLE: ExplorationSource = {kind: 'table', spaceId: 'personal', database: 'alice', table: 'orders'};

const ok = <T>(data: T) => ({success: true as const, data});
const fail = (message: string, code?: string) => ({
  success: false as const,
  error: {message, ...(code ? {code} : {})}
});

function status(over: {state?: QueryState; bytes?: number; millis?: number} = {}) {
  return ok({
    queryExecutionId: 'exec-1',
    state: over.state ?? ('SUCCEEDED' as QueryState),
    ...(over.bytes === undefined ? {} : {dataScannedBytes: over.bytes}),
    ...(over.millis === undefined ? {} : {engineExecutionTimeMillis: over.millis})
  });
}

const withFilter = (base: Exploration, value: string): Exploration => ({
  ...base,
  query: {...base.query, filters: [{column: 'status', operator: '=', value}]}
});

beforeEach(() => {
  vi.clearAllMocks();
  let n = 0;
  vi.mocked(runQuery).mockImplementation(async () => {
    n += 1;
    return ok({queryExecutionId: `exec-${n}`});
  });
  vi.mocked(getQueryStatus).mockResolvedValue(status({bytes: 1024, millis: 250}));
});

describe('useExploration — one execution per distinct rendered SQL (FR-006)', () => {
  it('renders the SQL and starts exactly one execution', async () => {
    const exploration = newExploration(TABLE);
    const {result} = renderHookWithProviders(() => useExploration(exploration));

    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));
    expect(result.current.sql).toBe('SELECT *\nFROM "alice"."orders"');
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(vi.mocked(runQuery).mock.calls[0][0]).toMatchObject({
      sql: 'SELECT *\nFROM "alice"."orders"',
      username: 'alice'
    });
  });

  it('applying a sort then removing it issues exactly ONE StartQueryExecution', async () => {
    // The cache key is the rendered SQL, so a round trip back to an identical description
    // is a cache hit rather than a second bill. This is the feature's cost control.
    const base = newExploration(TABLE);
    const sorted: Exploration = {
      ...base,
      query: {...base.query, ordering: [{column: 'qty', direction: 'asc', priority: 0}]}
    };
    // No `setQueryDefaults` here: the hook must set its OWN `gcTime`, because the harness's
    // client (like production's) would otherwise collect the detached entry and turn the
    // return trip into a second execution.
    const client = createTestQueryClient();

    const {result, rerender} = renderHookWithProviders(
      ({exploration}: {exploration: Exploration}) => useExploration(exploration),
      {initialProps: {exploration: base}, queryClient: client}
    );
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));

    rerender({exploration: sorted});
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-2'));

    rerender({exploration: base});
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));

    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('does not re-run when only PRESENTATION changes (FR-003 AC1)', async () => {
    // Hiding, reordering, pinning or resizing a column must cost nothing. Counted at the
    // AWS boundary, because that is where a bill would appear.
    const base = newExploration(TABLE);
    const dressed: Exploration = {
      ...base,
      presentation: {hiddenColumns: ['qty'], columnOrder: ['status'], pinnedColumns: ['id'], columnWidths: {id: 240}}
    };
    const {result, rerender} = renderHookWithProviders(
      ({exploration}: {exploration: Exploration}) => useExploration(exploration),
      {initialProps: {exploration: base}}
    );
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));

    rerender({exploration: dressed});
    await waitFor(() => expect(result.current.sql).toBe('SELECT *\nFROM "alice"."orders"'));

    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(result.current.queryExecutionId).toBe('exec-1');
  });

  it('paging through the results issues NO StartQueryExecution at all (FR-006 AC3)', async () => {
    // Paging is `GetQueryResults`' NextToken walk within one execution — it scans no extra
    // bytes, which is why Prev/Next never bills and only filter/order/grouping do. Driven
    // through SPEC-176's `useQueryResults` unmodified; this spec adds no second pager.
    vi.mocked(getQueryResults)
      .mockResolvedValueOnce(ok({columns: [{name: 'id', type: 'varchar'}], rows: [['1'], ['2']], nextToken: 'page-2'}))
      .mockResolvedValue(ok({columns: [{name: 'id', type: 'varchar'}], rows: [['3']]}));

    const exploration = newExploration(TABLE);
    const {result} = renderHookWithProviders(() => {
      const run = useExploration(exploration);
      return {run, results: useQueryResults(run.queryExecutionId, 2)};
    });

    await waitFor(() => expect(result.current.results.rows.length).toBe(2));
    expect(runQuery).toHaveBeenCalledTimes(1);

    result.current.results.goNext();
    await waitFor(() => expect(result.current.results.rows).toEqual([['3']]));
    result.current.results.goPrev();
    await waitFor(() => expect(result.current.results.rows.length).toBe(2));

    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('does not cache a FAILED start as a success — the same description retries', async () => {
    vi.mocked(runQuery).mockResolvedValueOnce(fail('Athena said no', 'InvalidRequest'));
    const exploration = newExploration(TABLE);
    const client = createTestQueryClient();

    const first = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(first.result.current.error).toBeTruthy());
    expect(first.result.current.queryExecutionId).toBeNull();
    first.unmount();

    // The retry is the first SUCCESSFUL start, so it takes the counter's first id — what
    // matters is that a second call happened at all rather than the failure being served
    // from cache.
    const second = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(second.result.current.queryExecutionId).toBe('exec-1'));
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('evicts a FAILED execution on the way OUT, so returning to it retries', async () => {
    // FR-006 AC4. The eviction is deliberately on unmount / statement change, never while
    // mounted: evicting on FAILED with an observer attached refetches immediately, which
    // is start -> FAILED -> evict -> start, a BILLING LOOP on any permanently-bad query.
    vi.mocked(getQueryStatus).mockResolvedValue(status({state: 'FAILED', bytes: 0}));
    const exploration = newExploration(TABLE);
    const client = createTestQueryClient();

    const first = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(first.result.current.state).toBe('FAILED'));
    expect(runQuery).toHaveBeenCalledTimes(1);
    // Still cached while mounted — the user sees the failure and pays for it once.
    expect(client.getQueryData(explorerKeys.execution(first.result.current.sql as string))).toBe('exec-1');

    first.unmount();
    expect(client.getQueryData(explorerKeys.execution('SELECT *\nFROM "alice"."orders"'))).toBeUndefined();

    vi.mocked(getQueryStatus).mockResolvedValue(status({bytes: 10}));
    const second = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(second.result.current.queryExecutionId).toBe('exec-2'));
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('keeps a SUCCEEDED execution cached across an unmount — only failures are evicted', async () => {
    // The pair that makes the eviction meaningful: an unconditional one would make every
    // remount a fresh bill, and the failure test above would still pass.
    const exploration = newExploration(TABLE);
    const client = createTestQueryClient();

    const first = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(first.result.current.state).toBe('SUCCEEDED'));
    first.unmount();

    const second = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(second.result.current.queryExecutionId).toBe('exec-1'));
    expect(runQuery).toHaveBeenCalledTimes(1);
  });

  it('starts nothing at all for a null exploration', async () => {
    const {result} = renderHookWithProviders(() => useExploration(null));
    expect(result.current.sql).toBeNull();
    expect(result.current.isPending).toBe(false);
    await waitFor(() => expect(runQuery).not.toHaveBeenCalled());
  });
});

describe('useExploration — cost accounting (FR-007)', () => {
  it('exposes bytes scanned and engine time from the execution status', async () => {
    const {result} = renderHookWithProviders(() => useExploration(newExploration(TABLE)));
    await waitFor(() => expect(result.current.cost).toEqual({bytesScanned: 1024, engineMillis: 250}));
  });

  it('contributes ZERO, not NaN, when an execution fails before reporting statistics', async () => {
    // A NaN here propagates silently into the tab's cumulative total and renders as
    // "NaN B" long after the failed run is forgotten.
    vi.mocked(getQueryStatus).mockResolvedValue(status({state: 'FAILED'}));
    const {result} = renderHookWithProviders(() => useExploration(newExploration(TABLE)));

    await waitFor(() => expect(result.current.state).toBe('FAILED'));
    expect(result.current.cost).toEqual({bytesScanned: 0, engineMillis: 0});
    expect(Number.isNaN(result.current.cost?.bytesScanned)).toBe(false);
  });
});

describe('useExploration — a description that cannot render (FR-002)', () => {
  it('surfaces the refusal as an error and starts NO query', async () => {
    const base = newExploration(TABLE);
    const impossible: Exploration = {
      ...base,
      query: {
        ...base.query,
        grouping: {columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]},
        ordering: [{column: 'placed_at', direction: 'asc', priority: 0}]
      }
    };
    const {result} = renderHookWithProviders(() => useExploration(impossible));

    expect(result.current.sql).toBeNull();
    expect(result.current.error).toBeInstanceOf(Error);
    await waitFor(() => expect(runQuery).not.toHaveBeenCalled());
  });

  it('recovers once the description becomes renderable again', async () => {
    // Starts from a description that genuinely CANNOT render, or the recovery is never
    // exercised and the assertion passes over its own title.
    const base = newExploration(TABLE);
    const impossible: Exploration = {
      ...base,
      query: {
        ...base.query,
        grouping: {columns: ['status'], aggregates: [{fn: 'COUNT', column: '*'}]},
        ordering: [{column: 'placed_at', direction: 'asc', priority: 0}]
      }
    };
    const {result, rerender} = renderHookWithProviders(
      ({exploration}: {exploration: Exploration}) => useExploration(exploration),
      {initialProps: {exploration: impossible}}
    );
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.sql).toBeNull();

    rerender({exploration: withFilter(base, "O'Brien")});
    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));
    expect(result.current.sql).toContain("'O''Brien'");
    expect(result.current.error).toBeNull();
  });
});
