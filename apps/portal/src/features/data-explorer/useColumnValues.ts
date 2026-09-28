import {useContext, useEffect, useMemo, useState, useSyncExternalStore} from 'react';
import {explorationSourceScope} from './explorerKeys';
import {exceedsAthenaQueryLimit, ExplorationStatementTooLong, renderColumnValuesSql} from './renderExplorationSql';
import {ColumnValuesContext, keyOf} from './columnValuesStore';
import type {ColumnValueCount, ExplorationSource, ValuesNarrowing} from './dataExplorer.types';

/** A column's values listing, as a picker shows it. */
export type ColumnValuesListing =
  | {status: 'pending'}
  /** `tryAgain` is null where trying again would fail the same way, as a statement too long to run. */
  | {status: 'error'; error: unknown; tryAgain: (() => void) | null}
  | {
      status: 'ready';
      entries: ColumnValueCount[];
      /** How many values the column has under the narrowing, of which `entries` holds the most common. */
      valueCount: number;
      truncated: boolean;
      bytesScanned: number;
      /** The asking tab had already run this listing, so opening it scanned nothing. */
      fromCache: boolean;
    };

/** What a picker asks to have listed. */
export type ColumnValuesRequest = {source: ExplorationSource; narrowing: ValuesNarrowing; column: string};

/**
 * Asks the workspace's provider for one column's values listing, and follows it.
 *
 * **Calling this is the billed gesture.** The listing starts when the calling component mounts —
 * or is found already cached, which costs nothing — so a surface must mount its caller only on
 * an explicit user action. Two callers with the same request share one listing. The tab is the
 * one active when the caller mounted, and the listing is billed to it even if the user has moved
 * to another tab by the time it settles.
 *
 * @param request - The source, what narrows the listing, and the column.
 * @returns The listing, and the asking tab's running total for its cost line.
 */
export function useColumnValues(request: ColumnValuesRequest): {listing: ColumnValuesListing; totalBytes: number} {
  const context = useContext(ColumnValuesContext);
  if (!context) throw new Error('useColumnValues needs a ColumnValuesProvider above it.');
  const {store, request: ask, retryExecution, totalOf} = context;
  const [tabId] = useState(() => context.activeTabId ?? '');
  const registry = useSyncExternalStore(store.subscribe, store.get);

  const {source, narrowing, column} = request;
  const [scopeKind, scopeFirst, scopeSecond] = explorationSourceScope(source);
  const rendered = useMemo((): {sql: string} | {error: unknown} => {
    try {
      const sql = renderColumnValuesSql(source, narrowing, column);
      return exceedsAthenaQueryLimit(sql) ? {error: new ExplorationStatementTooLong()} : {sql};
    } catch (error) {
      return {error};
    }
  }, [source, narrowing, column]);
  const sql = 'sql' in rendered ? rendered.sql : null;

  useEffect(() => {
    if (sql !== null && tabId !== '') ask(tabId, [scopeKind, scopeFirst, scopeSecond], sql);
  }, [ask, tabId, scopeKind, scopeFirst, scopeSecond, sql]);

  const listing = ((): ColumnValuesListing => {
    if ('error' in rendered) return {status: 'error', error: rendered.error, tryAgain: null};
    const key = registry.keys[keyOf(tabId, rendered.sql)];
    const again = () => ask(tabId, [scopeKind, scopeFirst, scopeSecond], rendered.sql);
    if (!key || key.status === 'starting') return {status: 'pending'};
    if (key.status === 'error') return {status: 'error', error: key.error, tryAgain: again};
    const execution = registry.executions[key.executionId];
    if (!execution || execution.status === 'watching' || execution.status === 'reading') return {status: 'pending'};
    if (execution.status === 'error') {
      const failed = execution.terminal !== null && execution.terminal.state !== 'SUCCEEDED';
      return {
        status: 'error',
        error: execution.error,
        tryAgain: failed ? again : () => retryExecution(key.executionId)
      };
    }
    return {
      status: 'ready',
      entries: execution.entries,
      valueCount: execution.valueCount,
      truncated: execution.valueCount > execution.entries.length,
      bytesScanned: execution.terminal?.dataScannedBytes ?? 0,
      fromCache: key.fromCache
    };
  })();

  return {listing, totalBytes: tabId === '' ? 0 : totalOf(tabId)};
}
