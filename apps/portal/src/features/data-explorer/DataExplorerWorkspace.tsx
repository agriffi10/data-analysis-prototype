import {useEffect, useEffectEvent, useMemo, useRef, useState} from 'react';
import {useLocation, useNavigate} from 'react-router';
import {useQueryClient} from '@tanstack/react-query';
import {LoadingState} from '../../components/LoadingState';
import {useToast} from '../../components/toastContext';
import {useAuth} from '../auth';
import {useFeature} from '../feature-flags';
import {useQuerySpaces} from '../catalog/useQuerySpaces';
import {useSaveResults} from '../catalog/useSaveResults';
import {useRunDdl} from '../catalog/useRunDdl';
import {isQueryStillRunning} from '../catalog/useQueryExecution';
import {buildCreateViewSql} from '../catalog/createView';
import {CreateViewDialog} from '../catalog/CreateViewDialog';
import {useSavedQuerySpace} from '../saved-queries/useSavedQuerySpace';
import {buildOpenSqlHandoff, readExploreSqlHandoff} from '../../lib/routeHandoff';
import {EXPLORATION_TABPANEL_ID, EXPLORATION_TABS_MAX} from './dataExplorer.constants';
import {ColumnValuesProvider} from './ColumnValuesProvider';
import {CostIndicator} from './CostIndicator';
import {ExplorationLimitDialog} from './ExplorationLimitDialog';
import {ExplorationResultsRegion, NOTHING_TO_EXPORT} from './ExplorationResultsRegion';
import {ExportExplorationDialog} from './ExportExplorationDialog';
import {ExplorationTabStrip} from './ExplorationTabStrip';
import {SaveExplorationDialog} from './SaveExplorationDialog';
import {OpenSavedViewDrawer} from './OpenSavedViewDrawer';
import {SavedViewRefusal} from './SavedViewRefusal';
import {useOpenSavedView} from './useOpenSavedView';
import {SourcePicker} from './SourcePicker';
import {useExploration} from './useExploration';
import {useExplorationQuery} from './useExplorationQuery';
import {useExplorationTabs} from './useExplorationTabs';
import type {OpenExplorationOpts} from './useExplorationTabs';
import {useExploreDeepLink} from './useExploreDeepLink';
import {evictSqlSource} from './useExplorationEviction';
import {useSourceColumns} from './useSourceColumns';
import {emptyExplorationPresentation} from './exploration';
import {tabBytesScanned} from './explorationTabs';
import type {ExploreTarget} from './exploreSources';
import type {Exploration, ExplorationSource} from './dataExplorer.types';

const EMPTY_PRESENTATION = emptyExplorationPresentation();

/** Why *Create view…* is refused on a tab whose source is a statement rather than a table. */
export const SQL_SOURCE_VIEW_REFUSAL =
  'A view is created in one database, and SQL opened from a query or a saved file can read from several. Open a table to create a view from it.';

/**
 * The Data Explorer's shell: the source picker, the tab strip, and one
 * exploration's rows.
 *
 * The engine is the — this mounts it. The results table below is explicitly a
 * placeholder the real grid replaces.
 *
 * **A denied deep link renders the refusal ALONE**, with no picker and no active
 * exploration: the page must ask nothing of Glue or Athena about a space this user cannot
 * reach, or the route becomes an existence oracle for someone else's catalog.
 */
export function DataExplorerWorkspace() {
  const {user} = useAuth();
  const username = user?.username ?? '';

  // FILTERED AT THE VIEW, never in `useQuerySpaces` and never in a service (the space selector's
  // precedent): the hook answers "which spaces can this user reach", which is a question
  // about access, and a flag is presentation.
  const sharedEnabled = useFeature('sharedWorkspaces');
  // The saved-query store is hidden with Query off, so the saved views it holds are too.
  const queryEnabled = useFeature('query');
  const allSpaces = useQuerySpaces();
  const spaces = useMemo(
    () => (sharedEnabled ? allSpaces : allSpaces.filter((space) => space.id === 'personal')),
    [sharedEnabled, allSpaces]
  );

  const tabs = useExplorationTabs(username);
  const [picking, setPicking] = useState(false);
  // Closing the last tab unmounts the strip that held focus; the picker takes its place and
  // takes the focus with it.
  const [pickerTakesFocus, setPickerTakesFocus] = useState(false);
  const [browsingSaved, setBrowsingSaved] = useState(false);
  const [limitReached, setLimitReached] = useState(false);
  // Which tab, and the statement on screen, both taken at the gesture rather than read live
  // while the dialog is up. The dialog is modal, so nothing can change the active tab behind
  // it today — capturing is what keeps that a property of THIS code rather than of `Modal`.
  const [saving, setSaving] = useState<{tabId: string; sql: string; exploration: Exploration} | null>(null);
  // The statement the view will wrap and the database it lands in, both CAPTURED at the
  // gesture rather than read live while the dialog is up — the same reason `saving` is.
  const [creatingView, setCreatingView] = useState<{sql: string; database: string} | null>(null);
  const queryControls = useExplorationQuery(tabs, tabs.activeTabId);

  // The ONE memory of "the space I am working in", shared with the Query workspace's save and
  // load surfaces — same hook, same key. The list is the view-gated one above.
  const savedSpace = useSavedQuerySpace(username || null, spaces);

  const {resolution, clear} = useExploreDeepLink(spaces, username, sharedEnabled);
  const denied = resolution.status === 'denied';

  // A statement handed over from a Query result rides in router state until the effect below
  // opens it. Until then the tab restored from the session stays unrun: it is about to be
  // switched away from, and running it would bill a statement nobody sees.
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const handoffPending = readExploreSqlHandoff(location.state) !== null;

  // NOT `denied ? null : …`, which was measured wrong: `denied` is false during the
  // `loading` window, so a restored tab started a real `StartQueryExecution` for a page that
  // then rendered nothing but a refusal. An unsettled link runs nothing at all — the same
  // rule the early return below applies to Glue, applied to the bill.
  //
  // A SUSPENDED description is held back for the same reason and by the same means: a
  // history step onto a statement that already failed must not re-run it,
  // and "runs nothing" is expressed here, by passing nothing to run.
  const linkUnsettled = resolution.status === 'loading' || denied;
  const exploration = useExploration(
    linkUnsettled || handoffPending || queryControls.suspended ? null : (tabs.activeTab?.exploration ?? null),
    tabs.activeTab?.id,
    // A tab reopened from a shared space's saved view shows its statement and waits to be asked.
    {hold: Boolean(tabs.activeTab?.awaitingRun)}
  );
  // Gated by the same rule, for the same reason one layer down: a denied link must ask
  // Glue nothing at all, and this hook reads a database.
  const schemaColumns = useSourceColumns(
    linkUnsettled ? null : (tabs.activeTab?.exploration.source ?? null),
    tabs.activeTab?.sqlSourceColumns
  );

  // Export. The Query workspace's own save path, mounted here — it copies
  // the EXECUTION's results object, so what leaves is every row the statement returned
  // rather than the page in the grid, and the copy is server-side (zero executions).
  //
  // The destinations are the view-gated `spaces`, not an unfiltered list: this control is a
  // WRITE target, so a colleague's space must leave it with `sharedWorkspaces` off.
  const toast = useToast();
  // No history to append to on this surface — the Query workspace owns that store, and a
  // Data Explorer view is not a statement the user typed there. The write is a no-op that
  // resolves, which `useRunDdl` treats as best-effort anyway.
  const ddl = useRunDdl({username, appendEntry: async () => undefined, toast});

  // Held here rather than read from the region at submit time, because the dialog outlives the
  // gesture: the list is what the grid showed WHEN export was chosen, and a column hidden while
  // the dialog is open must not change the file it is about to write.
  const [exportColumns, setExportColumns] = useState<number[] | null>(null);
  const saveResults = useSaveResults({
    spaces,
    username,
    // The one thing that decides whether export is available at all: Athena reports it only
    // on a SUCCEEDED execution, so "nothing has finished running" and "there is nothing to
    // export" are the same fact rather than two that could drift apart.
    outputLocation: exploration.outputLocation,
    executionId: exploration.queryExecutionId,
    // The linked saved query's name when the tab has one — the same default the Query
    // workspace uses, and the closest thing an exploration has to a name the user chose.
    linkedSavedName: tabs.activeTab?.savedQuery?.name,
    columnIndexes: exportColumns,
    toast
  });

  // Every way a tab opens — the picker, a link, a hand-off — goes through here. `openTab` is the
  // authority on the cap and says so by returning null, and every caller raises the same dialog
  // rather than pre-checking a count that may already be stale.
  const openExplorationTab = (source: ExplorationSource, opts?: OpenExplorationOpts): string | null => {
    const id = tabs.openTab(source, opts);
    if (id === null) setLimitReached(true);
    else {
      setPicking(false);
      setBrowsingSaved(false);
      setPickerTakesFocus(false);
    }
    return id;
  };
  const savedView = useOpenSavedView({username, spaces, openTab: openExplorationTab, toast});
  const openSource = (target: ExploreTarget) => {
    openExplorationTab({kind: 'table', spaceId: target.spaceId, database: target.database, table: target.table});
  };

  // A resolved link opens ONCE. The parameters are then dropped (replacing the history
  // entry), so a reload restores the session's tabs instead of stacking another copy of the
  // linked table on top of them.
  const openedLink = useRef<string | null>(null);
  const openResolvedLink = useEffectEvent((target: ExploreTarget) => {
    openSource(target);
    clear();
  });
  useEffect(() => {
    if (resolution.status !== 'ready') return;
    const {target} = resolution;
    const key = `${target.spaceId}/${target.database}/${target.table}`;
    if (openedLink.current === key) return;
    openedLink.current = key;
    openResolvedLink(target);
  }, [resolution]);

  // A hand-off opens ONCE, keyed by the history entry it arrived on: `StrictMode` runs this effect
  // twice on mount, and the replace below lands a render later. The entry is replaced with no
  // state whether or not a tab opened, as a deep link drops its parameters either way, so neither
  // a reload nor Back raises the tab-limit dialog again.
  //
  // A hand-off always RE-RUNS the statement: once its tab exists, every cached execution over
  // that body is dropped — see `evictSqlSource` for why, and why only that body's.
  const consumedHandoff = useRef<string | null>(null);
  const acceptHandoff = useEffectEvent((handoff: {body: string; label: string}) => {
    if (openExplorationTab({kind: 'sql', body: handoff.body, label: handoff.label}) !== null) {
      evictSqlSource(queryClient, handoff.body);
    }
    navigate({pathname: location.pathname, search: location.search, hash: location.hash}, {replace: true, state: null});
  });
  useEffect(() => {
    // An unsettled or refused link opens nothing, by the rule the page applies to Glue and Athena.
    // A link about to open goes first: its `clear()` keeps this state, and replacing the entry here
    // in the same flush would put back the parameters it just dropped.
    if (resolution.status !== 'none') return;
    if (consumedHandoff.current === location.key) return;
    const handoff = readExploreSqlHandoff(location.state);
    if (!handoff) return;
    consumedHandoff.current = location.key;
    // The history entry is outside React and delivers the hand-off once; opening its tab, or
    // refusing one at the cap, is state that event has to set — as the deep link's effect above
    // does, which the rule's analysis happens not to trace.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    acceptHandoff(handoff);
  }, [location.key, location.state, resolution.status]);

  // What THIS apply cost, decided at the one moment the answer is knowable: an execution
  // the tab's ledger already holds is one it has already run and already been billed for,
  // so this gesture scanned nothing.
  //
  // Read during render rather than in the effect below, and that ordering is the whole
  // point — `recordScan` puts the id in the ledger, after which every execution looks
  // known and every apply would report itself a cache hit.
  const [lastApply, setLastApply] = useState<{key: string; bytesScanned: number; fromCache: boolean} | null>(null);
  const costKey =
    tabs.activeTab && exploration.queryExecutionId && exploration.cost
      ? `${tabs.activeTab.id}:${exploration.queryExecutionId}`
      : null;
  if (costKey !== null && lastApply?.key !== costKey && tabs.activeTab && exploration.cost) {
    const known = tabs.activeTab.scannedByExecution[exploration.queryExecutionId as string];
    setLastApply({key: costKey, bytesScanned: known ?? exploration.cost.bytesScanned, fromCache: known !== undefined});
  }
  // Keyed by tab, and read back by tab: a tab whose own run has not reported yet shows no
  // per-apply figure, rather than the one the previous tab left behind.
  const shownApply = tabs.activeTab && lastApply?.key.startsWith(`${tabs.activeTab.id}:`) ? lastApply : null;

  // The tab's cost ledger, keyed by execution id upstream — recording the same execution
  // twice changes nothing, which is what makes a cache hit free by construction.
  const recordActiveScan = useEffectEvent((tabId: string, executionId: string, bytesScanned: number) =>
    tabs.recordScan(tabId, executionId, bytesScanned)
  );
  const activeTabId = tabs.activeTab?.id;
  const {queryExecutionId, cost} = exploration;
  useEffect(() => {
    if (!activeTabId || !queryExecutionId || !cost) return;
    recordActiveScan(activeTabId, queryExecutionId, cost.bytesScanned);
  }, [activeTabId, queryExecutionId, cost]);

  // A statement that failed is remembered so history never walks back into it unasked
  // In memory and per tab — see `useExplorationQuery`. A statement the browser stopped watching
  // did not fail, and going back to it starts a new watch, which looks again.
  const noteFailedStatement = useEffectEvent((sql: string) => queryControls.noteFailure(sql));
  useEffect(() => {
    if (exploration.error != null && !isQueryStillRunning(exploration.error) && exploration.sql !== null) {
      noteFailedStatement(exploration.sql);
    }
  }, [exploration.error, exploration.sql]);

  // THE PICKER MUST NOT MOUNT WHILE A LINK IS STILL RESOLVING. It reads a database on
  // mount, so an optimistic render would issue that read for the personal space and then
  // swap to the refusal a tick later — which still answers "does this run against Glue",
  // just about the wrong space. `FeatureRoute` holds the same line one layer up.
  if (resolution.status === 'loading') return <LoadingState />;

  if (denied) {
    return (
      <section
        aria-label="Data Explorer"
        className="mx-auto flex max-w-lg flex-col gap-3 p-8 text-center">
        <h2 className="text-lg font-semibold text-text">You don’t have access to that space</h2>
        <p className="text-sm leading-relaxed text-text-2">
          This link points at a space you’re not a member of. If you think that’s wrong, ask its owner to add you.
        </p>
      </section>
    );
  }

  const showPicker = picking || tabs.tabs.length === 0;
  const ledgerOf = (tabId: string) => tabs.tabs.find((tab) => tab.id === tabId)?.scannedByExecution;
  const totalOf = (tabId: string) => {
    const tab = tabs.tabs.find((candidate) => candidate.id === tabId);
    return tab ? tabBytesScanned(tab) : 0;
  };
  // A stable object while there is no active tab: the geometry resolver memoises on it,
  // and a fresh literal every render would recompute the whole column layout for nothing.
  const presentation = tabs.activeTab?.exploration.presentation ?? EMPTY_PRESENTATION;

  return (
    // Capped to the viewport below the h-14 header from tablet up, as the Query workspace is, so
    // the grid scrolls inside its own box and the SQL above it and the panels beside it stay in
    // view. Phones keep the page's own scroll: a bounded box would squeeze the stacked grid.
    // The values listings live ABOVE the source picker: New tab unmounts the tab panel, and a
    // listing still running must keep its watch so its scan reaches the tab that asked.
    <ColumnValuesProvider
      activeTabId={tabs.activeTab?.id ?? null}
      ledgerOf={ledgerOf}
      recordScan={tabs.recordScan}
      totalOf={totalOf}>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col tablet:h-[calc(100dvh-3.5rem)] tablet:overflow-hidden">
        {tabs.tabs.length > 0 && (
          <ExplorationTabStrip
            tabs={tabs.tabs}
            activeTabId={tabs.activeTabId}
            onSelect={(id) => {
              setPicking(false);
              tabs.setActiveTab(id);
            }}
            // Closing is not itself an execution. What CAN follow one is the neighbour that
            // slides into view: if it has run this session its statement is cached, but a tab
            // restored from `sessionStorage` and never opened has not, and showing an
            // exploration is running it.
            onClose={(id) => {
              if (tabs.tabs.length === 1) setPickerTakesFocus(true);
              tabs.closeTab(id);
            }}
            // A state read is honest for ONE human click — the picker's choice still goes
            // through `openTab`, which is the authority and refuses on its own synchronous
            // count. What this buys is the refusal arriving at the gesture that
            // asked for it, rather than one table-click later.
            onNew={() => (tabs.tabs.length >= EXPLORATION_TABS_MAX ? setLimitReached(true) : setPicking(true))}
            panelShown={!showPicker}
          />
        )}

        {showPicker ? (
          <SourcePicker
            spaces={spaces}
            username={username}
            onChoose={openSource}
            onCancel={tabs.tabs.length > 0 ? () => setPicking(false) : undefined}
            onOpenSaved={queryEnabled ? () => setBrowsingSaved(true) : undefined}
            takeFocus={pickerTakesFocus}
          />
        ) : (
          // The region each tab controls. `aria-controls` on a tab has to name something, or
          // the relationship the tablist announces does not exist.
          <div
            id={EXPLORATION_TABPANEL_ID}
            role="tabpanel"
            aria-label={tabs.activeTab?.label ?? 'Exploration'}
            className="flex min-h-0 flex-1 flex-col">
            <ExplorationResultsRegion
              tabId={tabs.activeTabId}
              source={tabs.activeTab?.exploration.source ?? null}
              // The statement that RAN, so the disclosure shows the string
              // handed to StartQueryExecution rather than a second rendering of it.
              sql={exploration.sql}
              queryExecutionId={exploration.queryExecutionId}
              // Load-bearing: the region reads results only at SUCCEEDED. Reading them
              // earlier is a 400 from Athena that surfaces as the generic error message.
              state={exploration.state}
              isPending={exploration.isPending}
              error={exploration.error}
              schemaColumns={schemaColumns}
              presentation={presentation}
              // Presentation changes land the same way every other exploration edit does —
              // through the tab — so geometry survives paging and tab switches, and is
              // persisted with the tab it belongs to.
              onPresentationChange={(update) =>
                tabs.updateActiveExploration((e) => ({...e, presentation: update(e.presentation)}))
              }
              queryControls={queryControls}
              held={tabs.activeTab?.awaitingRun ?? null}
              onRun={() => tabs.activeTab && tabs.releaseHold(tabs.activeTab.id)}
              onSaveQuery={() => {
                if (tabs.activeTab && exploration.sql !== null) {
                  setSaving({tabId: tabs.activeTab.id, sql: exploration.sql, exploration: tabs.activeTab.exploration});
                }
              }}
              // A copy of the statement goes to Query in router state, never the URL, and this tab is
              // left exactly as it was: nothing comes back from the edit made there.
              onOpenInQuery={(sql) => {
                if (tabs.activeTab) {
                  navigate('/query', {state: buildOpenSqlHandoff({sql, label: tabs.activeTab.label})});
                }
              }}
              onCreateView={() => {
                const source = tabs.activeTab?.exploration.source;
                if (exploration.sql !== null && source?.kind === 'table') {
                  setCreatingView({sql: exploration.sql, database: source.database});
                }
              }}
              // A statement source reads whatever its body names, so there is no single database to
              // create the view IN. Without this the control would be offered and do nothing.
              createViewRefusal={
                tabs.activeTab && tabs.activeTab.exploration.source.kind !== 'table' ? SQL_SOURCE_VIEW_REFUSAL : null
              }
              onExport={(columnIndexes) => {
                setExportColumns(columnIndexes);
                saveResults.openDialog();
              }}
              // Judged HERE, on the results location, because that object is what export
              // copies — a grid full of rows says nothing about whether Athena has finished
              // writing the CSV, and a failed apply leaves the LAST GOOD execution's rows on
              // screen while this field has already moved on.
              exportRefusal={exploration.outputLocation ? null : NOTHING_TO_EXPORT}
              onSourceColumns={tabs.setTabSourceColumns}
            />
            <CostIndicator
              bytesScanned={shownApply?.bytesScanned ?? null}
              fromCache={shownApply?.fromCache ?? false}
              totalBytes={tabs.activeTabBytesScanned}
            />
          </div>
        )}

        {creatingView && (
          <CreateViewDialog
            busy={ddl.busy}
            targetDatabase={creatingView.database}
            onCreate={(name) =>
              ddl.run({
                sql: buildCreateViewSql(creatingView.database, name, creatingView.sql),
                database: creatingView.database,
                // The view is the only thing that changed, so the exploration it was built FROM
                // is not evicted and does not re-run.
                table: name,
                describe: {success: `Saved view ${name}`, failure: `Couldn\u2019t create view ${name}.`},
                onSettled: () => setCreatingView(null)
              })
            }
            onCancel={() => setCreatingView(null)}
          />
        )}

        {/* Mounting IS the open state — see the dialog's own note. */}
        {saving && (
          <SaveExplorationDialog
            sql={saving.sql}
            exploration={saving.exploration}
            spaces={spaces}
            defaultSpace={savedSpace.space}
            link={tabs.tabs.find((tab) => tab.id === saving.tabId)?.savedQuery}
            onSaved={(query) => {
              tabs.setTabSavedQuery(saving.tabId, {
                spaceId: query.spaceId,
                bucket: query.bucket,
                key: query.key,
                name: query.name
              });
              // ONE memory of "the space I am working in", written on every success — the
              // same rule the Query workspace settles, and the same storage key.
              savedSpace.selectSpace(query.spaceId);
              setSaving(null);
            }}
            onClose={() => setSaving(null)}
          />
        )}

        <ExportExplorationDialog saveResults={saveResults} />

        {browsingSaved && (
          <OpenSavedViewDrawer
            spaces={spaces}
            space={savedSpace.space}
            onSelectSpace={savedSpace.selectSpace}
            openingKey={savedView.openingKey}
            onOpen={savedView.openFile}
            onClose={() => setBrowsingSaved(false)}
          />
        )}

        {savedView.refusal && (
          <SavedViewRefusal
            refusal={savedView.refusal}
            onClose={savedView.dismissRefusal}
            onOpenInQuery={() => {
              const {sql, name} = savedView.refusal ?? {sql: '', name: ''};
              navigate('/query', {state: buildOpenSqlHandoff({sql, label: name})});
            }}
          />
        )}

        {limitReached && <ExplorationLimitDialog onDismiss={() => setLimitReached(false)} />}
      </div>
    </ColumnValuesProvider>
  );
}
