import {useCallback, useMemo, useRef, useState} from 'react';
import {EXPLORER_FILTER_HISTORY_MAX} from './dataExplorer.constants';
import {emptyExplorationQuery} from './exploration';
import {isEmptyQuery, sameQuery} from './explorationQueryOps';
import {renderExplorationSql} from './renderExplorationSql';
import type {ExplorationQuery, ExplorationTab} from './dataExplorer.types';
import type {UseExplorationTabsResult} from './useExplorationTabs';

export type UseExplorationQueryResult = {
  /** The description that is running (or would run) — the tab's own. */
  query: ExplorationQuery;
  /** Applies changes to the description. THIS is what mints an execution. */
  apply: (next: Partial<ExplorationQuery>) => void;
  /** Clears every filter, the expression, every sort and the grouping in ONE apply. */
  clearAll: () => void;
  /** Null when there is something to clear, else why the control is unavailable. */
  clearAllRefusal: string | null;
  /** What the clear-all control is called — it names the grouping when there is one. */
  clearAllLabel: string;
  canGoBack: boolean;
  canGoForward: boolean;
  back: () => void;
  forward: () => void;
  /**
   * A restored description whose SQL has already failed, held back from running.
   *
   * True only after a history step, never after an apply — an apply IS the user asking for
   * it again.
   */
  suspended: boolean;
  /** Runs the suspended description after all. */
  retry: () => void;
  /** Records that a statement failed, so history never walks back into it unasked. */
  noteFailure: (sql: string) => void;
};

const NOTHING_TO_CLEAR = 'There are no filters, expressions, sorts or grouping to clear.';

/**
 * The two names the clear-all control goes by.
 *
 * The label changes because the ACTION does: with a grouping in force, pressing it also
 * un-groups the result, and a control that says "filters" while removing a grouping is
 * lying about what the click will do.
 */
export const CLEAR_ALL_LABEL = 'Remove all filters and sorts';
export const CLEAR_ALL_WITH_GROUPING_LABEL = 'Remove all filters, sorts and grouping';

function cap(entries: ExplorationQuery[]): ExplorationQuery[] {
  return entries.length > EXPLORER_FILTER_HISTORY_MAX
    ? entries.slice(entries.length - EXPLORER_FILTER_HISTORY_MAX)
    : entries;
}

/**
 * The one door through which a tab's query description changes.
 *
 * Every gesture that renders SQL — a header menu, a cell filter, the filter builder, the
 * settings dialog, Remove all — lands here, which is what makes "one apply is one
 * execution" a property of the feature rather than of each surface: the description is
 * written once, `useExploration` re-renders one statement, and the cache decides whether
 * that costs anything.
 *
 * **It takes the tabs result rather than reading one of its own** (a deviation from the
 * spec's `useExplorationQuery(tabId)`). The tabs hook owns `sessionStorage`, and a second
 * instance of it would be a second copy of that state — two writers to one key, diverging
 * on the first edit. The tab id still names WHICH tab, because the history entry and the
 * description it belongs to have to be written in one update.
 *
 * @param tabs - The tabs state, from `useExplorationTabs`.
 * @param tabId - The tab whose description this edits; '' when there is no tab.
 * @returns The description and every operation over it.
 */
export function useExplorationQuery(tabs: UseExplorationTabsResult, tabId: string): UseExplorationQueryResult {
  const {updateTab} = tabs;
  const tab = tabs.tabs.find((t) => t.id === tabId) ?? null;
  const query = tab?.exploration.query ?? emptyExplorationQuery();
  const history = tab?.history ?? {past: [], future: []};

  // Statements this session has seen fail, per tab. In memory and never persisted: it is
  // an aid to history navigation, and a failure that only ever happened in a previous
  // session should not stop this one from trying.
  const failedSql = useRef(new Map<string, Set<string>>());

  // Suspension belongs to the tab that was suspended, and the hook is shared by all of them —
  // so it is held per tab id. A single flag had to be cleared on every switch (held, it
  // suspended the NEXT tab too), and clearing it meant a round trip back to the suspended tab
  // ran the known-failed statement without being asked.
  const [suspendedTabs, setSuspendedTabs] = useState<ReadonlySet<string>>(() => new Set());
  const suspended = suspendedTabs.has(tabId);
  const setSuspended = useCallback((id: string, value: boolean) => {
    setSuspendedTabs((prev) => {
      if (prev.has(id) === value) return prev;
      const next = new Set(prev);
      if (value) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const noteFailure = useCallback(
    (sql: string) => {
      const known = failedSql.current.get(tabId) ?? new Set<string>();
      known.add(sql);
      failedSql.current.set(tabId, known);
    },
    [tabId]
  );

  // "Run it anyway" also forgets what this tab has seen fail. Otherwise a transient
  // failure — throttling, an expired credential — that succeeds on the retry goes on
  // suspending every later history step onto that description for the rest of the session.
  // A statement that fails again is re-recorded by `noteFailure` on the spot.
  const retry = useCallback(() => {
    failedSql.current.delete(tabId);
    setSuspended(tabId, false);
  }, [setSuspended, tabId]);

  // Whether restoring this description would re-run a statement that already failed. The
  // render is attempted rather than assumed: a description that cannot render at all is
  // not a known failure, and its refusal is the ordinary error path.
  const wouldReplayFailure = useCallback((next: ExplorationQuery, source: ExplorationTab | null): boolean => {
    if (!source) return false;
    const known = failedSql.current.get(source.id);
    if (!known || known.size === 0) return false;
    try {
      return known.has(renderExplorationSql(source.exploration.source, next));
    } catch {
      return false;
    }
  }, []);

  const apply = useCallback(
    (next: Partial<ExplorationQuery>) => {
      if (!tab) return;
      setSuspended(tab.id, false);
      // The proposed description is built INSIDE the updater, from the tab as the updater
      // finds it — not from this render's copy. Two applies batched into one commit would
      // otherwise both merge onto the same stale description: the first change would be
      // lost, and the history entry pushed by the second would equal the description it
      // replaced, so Back would appear to do nothing once.
      updateTab(tab.id, (t) => {
        const proposed = {...t.exploration.query, ...next};
        // An apply that changes nothing is not history — it would fill Back with duplicates
        // of one description, and it renders the same SQL either way.
        if (sameQuery(proposed, t.exploration.query)) return t;
        const changed: ExplorationTab = {
          ...t,
          exploration: {...t.exploration, query: proposed},
          // A new branch discards the forward entries, as every undo stack does: they
          // describe a future that no longer follows from where the user now is.
          history: {past: cap([...t.history.past, t.exploration.query]), future: []}
        };
        // A held tab's hold ends here too: changing its query is the user asking for a run.
        // Dropped, not blanked, because a blank reads back as held.
        delete changed.awaitingRun;
        return changed;
      });
    },
    [setSuspended, tab, updateTab]
  );

  const clearAll = useCallback(() => {
    if (isEmptyQuery(query)) return;
    // Grouping goes too, superseding the preservation — and
    // the control SAYS so, because a label naming only filters silently un-grouping a view would
    // be the change nobody asked for that the earlier decision was protecting against.
    apply(emptyExplorationQuery());
  }, [apply, query]);

  const step = useCallback(
    (direction: 'back' | 'forward') => {
      if (!tab) return;
      const from = direction === 'back' ? tab.history.past : tab.history.future;
      const restored = from[from.length - 1];
      if (!restored) return;
      setSuspended(tab.id, wouldReplayFailure(restored, tab));
      updateTab(tab.id, (t) => {
        const source = direction === 'back' ? t.history.past : t.history.future;
        const target = source[source.length - 1];
        if (!target) return t;
        const rest = source.slice(0, -1);
        const other = direction === 'back' ? t.history.future : t.history.past;
        // The description being left becomes the other side's newest entry, so a Back
        // followed by a Forward is a round trip rather than a loss.
        const moved = cap([...other, t.exploration.query]);
        return {
          ...t,
          exploration: {...t.exploration, query: target},
          history: direction === 'back' ? {past: rest, future: moved} : {past: moved, future: rest}
        };
      });
    },
    [setSuspended, tab, updateTab, wouldReplayFailure]
  );

  const back = useCallback(() => step('back'), [step]);
  const forward = useCallback(() => step('forward'), [step]);

  return useMemo(
    () => ({
      query,
      apply,
      clearAll,
      clearAllRefusal: isEmptyQuery(query) ? NOTHING_TO_CLEAR : null,
      clearAllLabel: query.grouping ? CLEAR_ALL_WITH_GROUPING_LABEL : CLEAR_ALL_LABEL,
      canGoBack: history.past.length > 0,
      canGoForward: history.future.length > 0,
      back,
      forward,
      suspended,
      retry,
      noteFailure
    }),
    [apply, back, clearAll, forward, history.future.length, history.past.length, noteFailure, query, retry, suspended]
  );
}
