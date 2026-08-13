import {useEffect, useMemo, useRef, useState} from 'react';
import {LoadingState} from '../../components/LoadingState';
import {useAuth} from '../auth';
import {useFeature} from '../feature-flags';
import {useQuerySpaces} from '../catalog/useQuerySpaces';
import {formatBytes} from '../../lib/format';
import {EXPLORATION_TABPANEL_ID, EXPLORATION_TABS_MAX} from './dataExplorer.constants';
import {ExplorationLimitDialog} from './ExplorationLimitDialog';
import {ExplorationResultsRegion} from './ExplorationResultsRegion';
import {ExplorationTabStrip} from './ExplorationTabStrip';
import {SourcePicker} from './SourcePicker';
import {useExploration} from './useExploration';
import {useExplorationTabs} from './useExplorationTabs';
import {useExploreDeepLink} from './useExploreDeepLink';
import {useSourceColumns} from './useSourceColumns';
import {emptyExplorationPresentation} from './exploration';
import type {ExploreTarget} from './exploreSources';

const EMPTY_PRESENTATION = emptyExplorationPresentation();

/**
 * The Data Explorer's shell (SPEC-179): the source picker, the tab strip, and one
 * exploration's rows.
 *
 * The engine is SPEC-178's — this mounts it. The results table below is explicitly a
 * placeholder that SPEC-180 replaces with the real grid.
 *
 * **A denied deep link renders the refusal ALONE**, with no picker and no active
 * exploration: the page must ask nothing of Glue or Athena about a space this user cannot
 * reach, or the route becomes an existence oracle for someone else's catalog (SPEC-113).
 */
export function DataExplorerWorkspace() {
  const {user} = useAuth();
  const username = user?.username ?? '';

  // FILTERED AT THE VIEW, never in `useQuerySpaces` and never in a service (SPEC-174's
  // precedent): the hook answers "which spaces can this user reach", which is a question
  // about access, and a flag is presentation.
  const sharedEnabled = useFeature('sharedWorkspaces');
  const allSpaces = useQuerySpaces();
  const spaces = useMemo(
    () => (sharedEnabled ? allSpaces : allSpaces.filter((space) => space.id === 'personal')),
    [sharedEnabled, allSpaces]
  );

  const tabs = useExplorationTabs(username);
  const [picking, setPicking] = useState(false);
  const [limitReached, setLimitReached] = useState(false);

  const {resolution, clear} = useExploreDeepLink(spaces, username, sharedEnabled);
  const denied = resolution.status === 'denied';

  // NOT `denied ? null : …`, which was measured wrong: `denied` is false during the
  // `loading` window, so a restored tab started a real `StartQueryExecution` for a page that
  // then rendered nothing but a refusal. An unsettled link runs nothing at all — the same
  // rule the early return below applies to Glue, applied to the bill.
  const linkUnsettled = resolution.status === 'loading' || denied;
  const exploration = useExploration(linkUnsettled ? null : (tabs.activeTab?.exploration ?? null));
  // Gated by the same rule, for the same reason one layer down: a denied link must ask
  // Glue nothing at all, and this hook reads a database.
  const schemaColumns = useSourceColumns(linkUnsettled ? null : (tabs.activeTab?.exploration.source ?? null));

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

  // The tab's cost ledger, keyed by execution id upstream — recording the same execution
  // twice changes nothing, which is what makes a cache hit free by construction.
  useEffect(() => {
    const tabId = tabs.activeTab?.id;
    if (!tabId || !exploration.queryExecutionId || !exploration.cost) return;
    tabs.recordScan(tabId, exploration.queryExecutionId, exploration.cost.bytesScanned);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `tabs` is re-created each render; recordScan is idempotent per execution id.
  }, [tabs.activeTab?.id, exploration.queryExecutionId, exploration.cost]);

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
          // count (SPEC-178). What this buys is the refusal arriving at the gesture that
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
            queryExecutionId={exploration.queryExecutionId}
            isPending={exploration.isPending}
            error={exploration.error}
            schemaColumns={schemaColumns}
            presentation={presentation}
            // Presentation changes land the same way every other exploration edit does —
            // through the tab — so geometry survives paging and tab switches, and is
            // persisted with the tab it belongs to (FR-001 AC7).
            onPresentationChange={(update) =>
              tabs.updateActiveExploration((e) => ({...e, presentation: update(e.presentation)}))
            }
          />
          <p className="flex-none border-t border-border px-3 py-1.5 text-xs text-text-3">
            {formatBytes(tabs.activeTabBytesScanned)} scanned by this exploration
          </p>
        </div>
      )}

      {limitReached && <ExplorationLimitDialog onDismiss={() => setLimitReached(false)} />}
    </div>
  );
}
