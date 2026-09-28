import {beforeEach, describe, expect, it, vi} from 'vitest';
import {act, waitFor} from '@testing-library/react';
import {renderHookWithProviders, createTestQueryClient} from '../../test/renderWithProviders';
import {useExploration} from './useExploration';
import {useQueryResults} from '../catalog/useQueryResults';
import {getQueryStatus, runQuery, getQueryResults} from '../catalog/athena.service';
import {newExploration} from './exploration';
import {toUserText} from '../../lib/errorMessages';
import {explorerKeys, explorationSourceScope} from './explorerKeys';
import type {Exploration, ExplorationSource} from './dataExplorer.types';
import type {QueryState} from '../catalog/catalog.types';
import {MAX_POLL_DURATION_MS, POLL_INTERVAL_MS} from '../catalog/catalog.constants';

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

describe('a failing start is not retried', () => {
  it('issues ONE runQuery even under a client that retries by default', async () => {
    // The one behaviour this port deliberately changes, and it needs a client that would retry —
    // the shared test harness sets `retry: false` globally, so against it the hook's own option
    // is invisible and deleting the line leaves every other test in this file green.
    //
    // What it is protecting: starting a query is billed and stateful, and it inherited the app
    // default of `retry: 1` because it looked like a read. A failing apply issued two
    // `StartQueryExecution` calls about a second apart — two executions for one gesture.
    const {QueryClient} = await import('@tanstack/react-query');
    const retrying = new QueryClient({
      // `retryDelay: 0` so the retry, if one happens, lands INSIDE `waitFor`'s window. Left at
      // TanStack's ~1s first delay it ties RTL's 1s timeout, and which assertion reports the
      // failure is a coin-flip on a slower machine — the count is the one this test is named for.
      defaultOptions: {
        queries: {retry: 1, retryDelay: 0, staleTime: 0, gcTime: 0},
        mutations: {retry: false}
      }
    });
    vi.mocked(runQuery).mockResolvedValue(fail('Athena refused', 'InvalidRequest'));

    const {result} = renderHookWithProviders(() => useExploration(newExploration(TABLE)), {
      queryClient: retrying
    });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(runQuery).toHaveBeenCalledTimes(1);
  });
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
      presentation: {
        hiddenColumns: ['qty'],
        columnOrder: ['status'],
        pinnedColumns: ['id'],
        columnWidths: {id: 240},
        valuePanelOpen: true,
        // SPEC-184's half of the same claim: colours, striping, the type tint and a
        // transformer are presentation too, so none of them may reach the renderer.
        formatting: {
          rules: [{id: 'r1', column: 'status', operator: '=', value: 'ok', background: 'danger-soft'}],
          colourByType: true,
          stripeColumns: ['id'],
          transformers: {id: {kind: 'url', template: 'https://example.com/${value}'}}
        }
      }
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
    expect(
      client.getQueryData(explorerKeys.execution(explorationSourceScope(TABLE), first.result.current.sql as string))
    ).toBe('exec-1');

    first.unmount();
    expect(
      client.getQueryData(explorerKeys.execution(explorationSourceScope(TABLE), 'SELECT *\nFROM "alice"."orders"'))
    ).toBeUndefined();

    vi.mocked(getQueryStatus).mockResolvedValue(status({bytes: 10}));
    const second = renderHookWithProviders(() => useExploration(exploration), {queryClient: client});
    await waitFor(() => expect(second.result.current.queryExecutionId).toBe('exec-2'));
    expect(runQuery).toHaveBeenCalledTimes(2);
  });

  it('does not re-run a FAILED statement when only presentation changes while it is shown', async () => {
    // A column resize reports on every pointermove, and each one is a fresh exploration
    // object. If that identity reached the eviction's dependencies, every move would evict the
    // live entry and start the statement again — a burst of executions for one drag.
    vi.mocked(getQueryStatus).mockResolvedValue(status({state: 'FAILED', bytes: 0}));
    const base = newExploration(TABLE);
    const {result, rerender} = renderHookWithProviders(
      ({exploration}: {exploration: Exploration}) => useExploration(exploration),
      {initialProps: {exploration: base}}
    );
    await waitFor(() => expect(result.current.state).toBe('FAILED'));

    for (const width of [120, 140, 160]) {
      rerender({exploration: {...base, presentation: {...base.presentation, columnWidths: {id: width}}}});
    }
    await waitFor(() => expect(result.current.state).toBe('FAILED'));

    expect(runQuery).toHaveBeenCalledTimes(1);
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

describe('useExploration — a statement that outlives the watch’s ceiling', () => {
  it('reports the verdict as its error and stops being pending', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(getQueryStatus).mockResolvedValue(status({state: 'RUNNING'}));
      const {result} = renderHookWithProviders(() => useExploration(newExploration(TABLE)));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
      });
      expect(result.current.isPending).toBe(true);

      // The ceiling's mark in an act of its own, then the one poll whose read decides.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(MAX_POLL_DURATION_MS);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS + 10);
      });

      expect(result.current.error).toMatchObject({code: 'QueryStillRunning', params: {queryExecutionId: 'exec-1'}});
      expect(result.current.state).toBe('RUNNING');
      expect(result.current.isPending).toBe(false);
    } finally {
      vi.useRealTimers();
    }
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
        grouping: {
          columns: ['status'],
          aggregates: [{fn: 'COUNT', column: '*'}],
          duplicatesOnly: false,
          showPercentage: false
        },
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
        grouping: {
          columns: ['status'],
          aggregates: [{fn: 'COUNT', column: '*'}],
          duplicatesOnly: false,
          showPercentage: false
        },
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

describe('useExploration — a statement Athena would refuse for its length (SPEC-238 FR-005)', () => {
  // One `in` filter big enough to push the statement past the limit, built from values
  // long enough that a thousand of them would not have done it — which is the reason the
  // byte check exists beside the value cap rather than instead of it.
  const longList = Array.from({length: 400}, (_, i) => `${'v'.repeat(700)}${i}`);

  const withList = (values: string[]): Exploration => {
    const base = newExploration(TABLE);
    return {...base, query: {...base.query, filters: [{column: 'brnd_name', operator: 'in', values}]}};
  };

  it('starts NOTHING, reports the sentence, and has no statement to show or save', async () => {
    const {result} = renderHookWithProviders(() => useExploration(withList(longList)));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    // The claim that costs money if it is wrong.
    expect(runQuery).not.toHaveBeenCalled();
    // `sql: null` is what makes *Generated SQL* show its no-statement sentence and
    // *Save as query* refuse, rather than handing over a file Athena will not run.
    expect(result.current.sql).toBeNull();
    expect(toUserText(result.current.error)).toBe(
      'This query is too long to run. Use fewer conditions, or fewer or shorter filter values.'
    );
  });

  it('starts one execution once the long filter is gone, so the refusal is about the LENGTH', async () => {
    const {result} = renderHookWithProviders(() => useExploration(withList(['Abilify'])));

    await waitFor(() => expect(result.current.queryExecutionId).toBe('exec-1'));
    expect(runQuery).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
  });
});
