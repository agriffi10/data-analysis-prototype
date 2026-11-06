import {useState} from 'react';
import {splitSqlStatements} from './query.sql';
import {useMobileSurfaceStore} from './queryRunsContext';
import type {MobileHomeTab, MobileQueryView, MobileRun, MobileSavedRef} from './query.types';
import type {TabRun} from './useQueryRunsEngine';
import type {UseTabRunsResult} from './useTabRuns';

export type UseMobileQuerySurfaceResult = {
  view: MobileQueryView;
  /** Which list the mobile home is showing; kept beside the view so Back returns to it. */
  homeTab: MobileHomeTab;
  setHomeTab: (tab: MobileHomeTab) => void;
  /** Non-null only while a submit this surface made is still the tab's installed run. */
  run: MobileRun | null;
  /** The view may adopt the active tab's status and results. */
  ownsRun: boolean;
  /** Submitted, but the run has not appeared in the tab yet. */
  pending: boolean;
  /** The submit never started; the error is this surface's, not the tab's. */
  failedToStart: boolean;
  /**
   * Run SQL through the same path the editor uses, then show the results view. `savedQuery` is
   * the saved query being run, if it is one; the tab's own link is never the mobile run's.
   */
  runSql: (sql: string, title: string, savedQuery?: MobileSavedRef) => void;
  /** Show SQL read-only, without running it. */
  viewSql: (sql: string, title: string, savedQuery?: MobileSavedRef) => void;
  back: () => void;
  /** Forgets a failed submit, so its error stops being rendered. */
  clearRun: () => void;
};

type Params = {
  isMobile: boolean;
  activeTabId: string;
  runs: Record<string, TabRun>;
  submitBatch: UseTabRunsResult['submitBatch'];
};

/**
 * The below-`tablet` query surface: a browse-first home over saved
 * queries and history, and a read-only results view. There is no editor here,
 * so a run started from this surface is tracked by a token rather than by the
 * tab's editor buffer.
 *
 * The view adopts a tab's status and results ONLY while its token is the
 * installed run's — SQL text is not a run identity (the same text can name an
 * older execution), and a submit is not installed synchronously, so an ungated
 * view shows a previous query's outcome under the current query's title.
 * `phase` is reported by the submit itself rather than inferred: a residual
 * "no run and no error" reading turns into a permanent phantom once the error
 * is dismissed.
 *
 * Its state lives at the signed-in shell with the runs it tracks, so leaving the Query page and
 * coming back finds the view on its own run, and a token is never issued twice in a session: one
 * counted afresh on each visit matched the previous visit's run.
 */
export function useMobileQuerySurface({isMobile, activeTabId, runs, submitBatch}: Params): UseMobileQuerySurfaceResult {
  const {view, setView, homeTab, setHomeTab, run, setRun, tokenRef} = useMobileSurfaceStore();

  // Crossing up out of mobile hands the tab back to the editor, so this surface's
  // run bookkeeping must not survive to be matched against a later, unrelated
  // desktop run. Render-phase state adjustment (the React "derive state on change"
  // pattern), as elsewhere in this feature — not an Effect.
  const [prevIsMobile, setPrevIsMobile] = useState(isMobile);
  if (isMobile !== prevIsMobile) {
    setPrevIsMobile(isMobile);
    if (!isMobile) {
      setRun(null);
      setView({kind: 'home'});
    }
  }

  // Run a saved/history entry from the mobile home through
  // the SAME run path the editor uses, then show the results view.
  // The tab's SQL is deliberately NOT set here: submitBatch takes the statements
  // explicitly, and writing the editor buffer would overwrite (and persist over)
  // a draft the user left on a wider screen.
  const runSql = (sql: string, title: string, savedQuery?: MobileSavedRef) => {
    const token = tokenRef.current + 1;
    const tabId = activeTabId;
    // Navigate only if the submit is actually accepted, so a refused tap never
    // strands the user on a page for a query that isn't running.
    const started = submitBatch(splitSqlStatements(sql), 'script-single', tabId, {
      token,
      onOutcome: (ok, error) =>
        setRun((cur) => (cur?.token === token ? {...cur, phase: ok ? 'started' : 'failed', error} : cur)),
      savedQuery
    });
    if (!started) return;
    tokenRef.current = token;
    setRun({token, tabId, phase: 'submitting'});
    setView({kind: 'results', sql, title, savedQuery});
  };

  const viewSql = (sql: string, title: string, savedQuery?: MobileSavedRef) => {
    setRun(null);
    // Carried so the view's own Run records the saved query, as a run from its card does.
    setView({kind: 'results', sql, title, savedQuery});
  };

  const back = () => {
    setRun(null);
    setView({kind: 'home'});
  };

  // The view owns a run only while ITS submit is the one installed in the tab it
  // submitted into — the tab can change under the view, and a later run replaces
  // the entry.
  const runTab = run ? runs[run.tabId] : undefined;
  const ownsRun = run !== null && run.tabId === activeTabId && runTab?.token === run.token;

  return {
    view,
    homeTab,
    setHomeTab,
    run,
    ownsRun,
    pending: run?.phase === 'submitting' && !ownsRun,
    failedToStart: run?.phase === 'failed',
    runSql,
    viewSql,
    back,
    clearRun: () => setRun(null)
  };
}
