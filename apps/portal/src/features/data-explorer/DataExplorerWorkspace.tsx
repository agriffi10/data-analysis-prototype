import {useEffect, useMemo, useRef, useState} from 'react';
import {LoadingState} from '../../components/LoadingState';
import {useToast} from '../../components/toastContext';
import {useAuth} from '../auth';
import {useFeature} from '../feature-flags';
import {useQuerySpaces} from '../catalog/useQuerySpaces';
import {useSaveResults} from '../catalog/useSaveResults';
import {useRunDdl} from '../catalog/useRunDdl';
import {buildCreateViewSql} from '../catalog/createView';
import {CreateViewDialog} from '../catalog/CreateViewDialog';
import {
  CreateTableDialog,
  CreateTableFromSpaceDialog,
  suggestedNameFor,
  useCreateTableFromSpace
} from '../table-builder';
import {useSavedQuerySpace} from '../saved-queries/useSavedQuerySpace';
import {EXPLORATION_TABPANEL_ID, EXPLORATION_TABS_MAX} from './dataExplorer.constants';
import {CostIndicator} from './CostIndicator';
import {ExplorationLimitDialog} from './ExplorationLimitDialog';
import {ExplorationResultsRegion, NOTHING_TO_EXPORT} from './ExplorationResultsRegion';
import {ExportExplorationDialog} from './ExportExplorationDialog';
import {ExplorationTabStrip} from './ExplorationTabStrip';
import {SaveExplorationDialog} from './SaveExplorationDialog';
import {SourcePicker} from './SourcePicker';
import {useExploration} from './useExploration';
import {useExplorationQuery} from './useExplorationQuery';
import {useExplorationTabs} from './useExplorationTabs';
import {useExploreDeepLink} from './useExploreDeepLink';
import {useSourceColumns} from './useSourceColumns';
import {emptyExplorationPresentation} from './exploration';
import type {ExploreTarget} from './exploreSources';

const EMPTY_PRESENTATION = emptyExplorationPresentation();

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
  // Building a table is a Query capability wearing a Data Explorer control, the mirror of
  // `Save as query` — so it follows the flag that owns the capability, not the screen.
  const queryEnabled = useFeature('query');
  const allSpaces = useQuerySpaces();
  const spaces = useMemo(
    () => (sharedEnabled ? allSpaces : allSpaces.filter((space) => space.id === 'personal')),
    [sharedEnabled, allSpaces]
  );

  const tabs = useExplorationTabs(username);
  const [picking, setPicking] = useState(false);
  const [limitReached, setLimitReached] = useState(false);
  // Which tab, and the statement on screen, both taken at the gesture rather than read live
  // while the dialog is up. The dialog is modal, so nothing can change the active tab behind
  // it today — capturing is what keeps that a property of THIS code rather than of `Modal`.
  const [saving, setSaving] = useState<{tabId: string; sql: string} | null>(null);
  // The statement the view will wrap and the database it lands in, both CAPTURED at the
  // gesture rather than read live while the dialog is up — the same reason `saving` is.
  const [creatingView, setCreatingView] = useState<{sql: string; database: string} | null>(null);
  const createTable = useCreateTableFromSpace();
  // Derived from `spaces`, which the `sharedWorkspaces` filter has ALREADY been through —
  // never rebuilt from the connections, which would hand back what the flag just removed.
  const buildableSpaces = useMemo(
    () =>
      spaces.map((space) => ({
        id: space.id,
        label: space.label,
        bucket: space.bucket,
        rootPrefix: space.rootPrefix,
        kind: (space.id === 'personal' ? 'personal' : 'shared') as 'personal' | 'shared'
      })),
    [spaces]
  );
  const queryControls = useExplorationQuery(tabs, tabs.activeTabId);

  // The ONE memory of "the space I am working in", shared with the Query workspace's save and
  // load surfaces — same hook, same key. The list is the view-gated one above.
  const savedSpace = useSavedQuerySpace(username || null, spaces);

  const {resolution, clear} = useExploreDeepLink(spaces, username, sharedEnabled);
  const denied = resolution.status === 'denied';

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
    linkUnsettled || queryControls.suspended ? null : (tabs.activeTab?.exploration ?? null)
  );
  // Gated by the same rule, for the same reason one layer down: a denied link must ask
  // Glue nothing at all, and this hook reads a database.
  const schemaColumns = useSourceColumns(linkUnsettled ? null : (tabs.activeTab?.exploration.source ?? null));

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

  const saveResults = useSaveResults({
    spaces,
    username,
    // The one thing that decides whether export is available at all: Athena reports it only
    // on a SUCCEEDED execution, so "nothing has finished running" and "there is nothing to
    // export" are the same fact rather than two that could drift apart.
    outputLocation: exploration.outputLocation,
    // The linked saved query's name when the tab has one — the same default the Query
    // workspace uses, and the closest thing an exploration has to a name the user chose.
    linkedSavedName: tabs.activeTab?.savedQuery?.name,
    toast
  });

  const openSource = (target: ExploreTarget) => {
    const id = tabs.openTab({kind: 'table', spaceId: target.spaceId, database: target.database, table: target.table});
    // `openTab` is the authority on the cap and says so by returning null — every caller
    // raises the same dialog rather than pre-checking a count that may already be stale.
    if (id === null) setLimitReached(true);
    else setPicking(false);
  };

  // A resolved link opens ONCE. The parameters are then dropped (replacing the history
  // entry), so a reload restores the session's tabs instead of stacking another copy of the
  // linked table on top of them.
  const openedLink = useRef<string | null>(null);
  useEffect(() => {
    if (resolution.status !== 'ready') return;
    const {target} = resolution;
    const key = `${target.spaceId}/${target.database}/${target.table}`;
    if (openedLink.current === key) return;
    openedLink.current = key;
    openSource(target);
    clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- openSource/clear are re-created each render; the ref is the guard.
  }, [resolution]);

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

  // The tab's cost ledger, keyed by execution id upstream — recording the same execution
  // twice changes nothing, which is what makes a cache hit free by construction.
  useEffect(() => {
    const tab = tabs.activeTab;
    if (!tab || !exploration.queryExecutionId || !exploration.cost) return;
    tabs.recordScan(tab.id, exploration.queryExecutionId, exploration.cost.bytesScanned);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `tabs` is re-created each render; recordScan is idempotent per execution id.
  }, [tabs.activeTab?.id, exploration.queryExecutionId, exploration.cost]);

  // A statement that failed is remembered so history never walks back into it unasked
  // In memory and per tab — see `useExplorationQuery`.
  useEffect(() => {
    if (exploration.error != null && exploration.sql !== null) queryControls.noteFailure(exploration.sql);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `queryControls` is re-created each render; noteFailure is idempotent per statement.
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
  // A stable object while there is no active tab: the geometry resolver memoises on it,
  // and a fresh literal every render would recompute the whole column layout for nothing.
  const presentation = tabs.activeTab?.exploration.presentation ?? EMPTY_PRESENTATION;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
          onClose={tabs.closeTab}
          // A state read is honest for ONE human click — the picker's choice still goes
          // through `openTab`, which is the authority and refuses on its own synchronous
          // count. What this buys is the refusal arriving at the gesture that
          // asked for it, rather than one table-click later.
          onNew={() => (tabs.tabs.length >= EXPLORATION_TABS_MAX ? setLimitReached(true) : setPicking(true))}
        />
      )}

      {showPicker ? (
        <SourcePicker
          spaces={spaces}
          username={username}
          onChoose={openSource}
          onCancel={tabs.tabs.length > 0 ? () => setPicking(false) : undefined}
          // Follows the `query` flag, like `Save as query`: building a table is a Query
          // capability, and with the flag off there is no workspace to use the result in.
          onCreateTable={queryEnabled ? createTable.start : undefined}
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
            onSaveQuery={() => {
              if (tabs.activeTab && exploration.sql !== null) {
                setSaving({tabId: tabs.activeTab.id, sql: exploration.sql});
              }
            }}
            onCreateView={() => {
              const source = tabs.activeTab?.exploration.source;
              if (exploration.sql !== null && source?.kind === 'table') {
                setCreatingView({sql: exploration.sql, database: source.database});
              }
            }}
            // A saved-query source reads whatever its body names, so there is no single database
            // to create the view IN. No such source ships today; without this the control would
            // be offered and silently do nothing the moment one does.
            createViewRefusal={
              tabs.activeTab && tabs.activeTab.exploration.source.kind !== 'table'
                ? 'A view is created in one database, and a saved query can read from several. Open a table to create a view from it.'
                : null
            }
            onExport={saveResults.openDialog}
            // Judged HERE, on the results location, because that object is what export
            // copies — a grid full of rows says nothing about whether Athena has finished
            // writing the CSV, and a failed apply leaves the LAST GOOD execution's rows on
            // screen while this field has already moved on.
            exportRefusal={exploration.outputLocation ? null : NOTHING_TO_EXPORT}
          />
          <CostIndicator
            bytesScanned={lastApply?.bytesScanned ?? null}
            fromCache={lastApply?.fromCache ?? false}
            totalBytes={tabs.activeTabBytesScanned}
          />
        </div>
      )}

      {createTable.step === 'folder' && (
        <CreateTableFromSpaceDialog
          spaces={buildableSpaces}
          onChoose={createTable.chooseFolder}
          onCancel={createTable.cancel}
        />
      )}
      {createTable.step === 'name' && createTable.folder && (
        // The SAME dialog the Files toolbar raises — only the folder reached it differently.
        <CreateTableDialog
          folderName={suggestedNameFor(createTable.folder)}
          folderPath={createTable.folder.prefix}
          busy={createTable.busy}
          submitError={createTable.error ?? undefined}
          onSubmit={createTable.submit}
          onCancel={createTable.cancel}
        />
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
              describe: {success: `Created view ${name}`, failure: `Couldn\u2019t create view ${name}.`},
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

      {limitReached && <ExplorationLimitDialog onDismiss={() => setLimitReached(false)} />}
    </div>
  );
}
