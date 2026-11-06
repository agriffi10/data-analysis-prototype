import {useEffect, useEffectEvent} from 'react';
import {useQueryRuns, type QueryRunsContextValue} from './queryRunsContext';
import type {RunOwner} from './useQueryRunsEngine';
import type {ParsedStatement, QueryTab, RunScope} from './query.types';

export type UseTabRunsResult = Omit<QueryRunsContextValue, 'submitBatch' | 'handleStop'> & {
  /**
   * Starts a batch in `tabId` (defaults to the active tab). Returns whether the submit began. `link`
   * is the saved query the run records in history, for a tab opened in the same event: the tab
   * list this hook was rendered with does not hold that tab yet, so its link cannot be read there.
   */
  submitBatch: (
    statements: ParsedStatement[],
    scope: RunScope,
    tabId?: string,
    owner?: RunOwner,
    link?: {key: string; name: string}
  ) => boolean;
  /** Cancels the active tab's in-flight statement and halts the remainder; a refused cancel is toasted. */
  handleStop: () => void;
};

/**
 * The shell's run engine, bound to the workspace's active tab and open tabs.
 *
 * An explicit `tabId` lets a just-opened tab (View data) run into itself before the active-tab
 * change has committed. A run from a tab linked to a saved query records that query in history,
 * read off the tab at submit time, since the whole link lives there.
 *
 * On mount it drops any run whose tab is no longer open, as closing the tab would. The tabs come
 * back from session storage with the same ids, so this bites when that storage failed and the
 * workspace came back with new ones: a run left behind would go on polling and starting
 * statements with no tab to show or stop it.
 *
 * @param params - The active tab's id and the open tabs.
 * @returns The run state and its operations, with the active tab as the default target.
 *
 * @example
 * const {runs, submitBatch, handleStop} = useTabRuns({activeTabId, tabs: tabs.tabs});
 */
export function useTabRuns({activeTabId, tabs}: {activeTabId: string; tabs: QueryTab[]}): UseTabRunsResult {
  const engine = useQueryRuns();
  const dropOrphanedRuns = useEffectEvent(() => {
    const open = new Set(tabs.map((t) => t.id));
    for (const id of Object.keys(engine.runs)) if (!open.has(id)) engine.dropRunState(id);
  });
  useEffect(() => {
    dropOrphanedRuns();
  }, []);
  return {
    ...engine,
    submitBatch: (statements, scope, tabId = activeTabId, owner, link) =>
      engine.submitBatch(
        statements,
        scope,
        tabId,
        owner,
        owner ? undefined : (link ?? tabs.find((t) => t.id === tabId)?.savedQuery)
      ),
    handleStop: () => engine.handleStop(activeTabId)
  };
}
