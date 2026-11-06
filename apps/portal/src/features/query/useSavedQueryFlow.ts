import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {useQuerySpaces} from '../catalog/useQuerySpaces';
import {useSavedQueries} from '../saved-queries/useSavedQueries';
import {useSavedQuerySpace} from '../saved-queries/useSavedQuerySpace';
import {ensureSavedQueriesFolder, readSavedQuery} from '../saved-queries/savedQueries.service';
import {useSaveQuery} from '../saved-queries/useSaveQuery';
import {logBackgroundFailure, toUserText} from '../../lib/errorMessages';
import {sameSql} from './query.sql';
import {QUERY_TABS_MAX} from './query.constants';
import type {useQueryTabs} from './useQueryTabs';
import type {useToast} from '../../components/toastContext';
import type {QuerySpace} from '../catalog/catalog.types';
import type {SavedQuery} from '../saved-queries/savedQueries.types';

type UseSavedQueryFlowParams = {
  username: string;
  /** With shared workspaces hidden, only the personal space is offered as a destination. */
  sharedSpacesEnabled: boolean;
  tabs: ReturnType<typeof useQueryTabs>;
  toast: ReturnType<typeof useToast>;
  /** Move focus into the editor after a save or an open. */
  focusEditor: () => void;
  /** The tab cap was hit: show the limit dialog. */
  onTabLimit: () => void;
  /** A saved query was opened into a tab: the caller closes its drawer. */
  onOpened: () => void;
};

export type UseSavedQueryFlowResult = {
  /** The view-gated destination list every space selector on the page shares. */
  savedSpaces: QuerySpace[];
  savedSpace: ReturnType<typeof useSavedQuerySpace>;
  saved: ReturnType<typeof useSavedQueries>;
  /** Linked tabs whose buffer differs from the file they were opened from. */
  dirtyTabIds: Set<string>;
  saveQuery: ReturnType<typeof useSaveQuery>;
  /**
   * Open a saved query into a new linked tab — exactly one GetObject, and only here. `afterOpen`
   * is handed the new tab's id and SQL once the tab exists, which is how Open and run runs it.
   */
  openSaved: (query: SavedQuery, afterOpen?: (tabId: string, sql: string) => void) => void;
  /** Read a saved query's body and hand it on, for surfaces that show no SQL until asked. */
  withSavedSql: (query: SavedQuery, use: (sql: string, title: string) => void) => void;
  /** Delete the file and unlink any open tab pointing at it. */
  deleteSaved: (query: SavedQuery) => void;
};

/**
 * Everything the query workspace does with `.sql` files in a space's `saved_queries/`
 * folder: which space is current, the listing, the folder marker, the dirty markers,
 * the save dialog, and opening or deleting a file.
 *
 * WHICH space is one piece of state, shared by loading and saving — the personal space
 * plus every active shared space, and the memory a successful save updates. Gated at the
 * VIEW: with shared workspaces hidden, offering a colleague's space would name spaces the
 * rest of the app has just stopped showing; `useQuerySpaces` still resolves them, because
 * a flag may not touch a service, and a remembered shared space falls through the "not in
 * the list" path to personal.
 *
 * A linked tab is dirty when its editor SQL differs from the file it was opened from. A
 * `.sql` object carries no body until it is READ, so the comparison is against what this
 * session last saw — the body fetched on open, or the buffer written on save. A tab restored
 * after a reload has no snapshot and shows no marker until it is opened or saved again; the
 * alternative was a GetObject per linked tab on every mount.
 *
 * @example
 * const savedFlow = useSavedQueryFlow({username, sharedSpacesEnabled, tabs, toast, focusEditor, onTabLimit, onOpened});
 */
export function useSavedQueryFlow({
  username,
  sharedSpacesEnabled,
  tabs,
  toast,
  focusEditor,
  onTabLimit,
  onOpened
}: UseSavedQueryFlowParams): UseSavedQueryFlowResult {
  const allSpaces = useQuerySpaces();
  const personalSpace: QuerySpace | null = allSpaces[0] ?? null;
  const savedSpaces = useMemo(
    () => (sharedSpacesEnabled ? allSpaces : allSpaces.slice(0, 1)),
    [sharedSpacesEnabled, allSpaces]
  );
  const savedSpace = useSavedQuerySpace(username || null, savedSpaces);
  const saved = useSavedQueries(savedSpace.space);

  // Hold the folder open, once per space per session. Best effort — a failure is logged
  // and the workspace renders regardless, because saving a query creates the prefix on
  // its own. The `.catch` is what makes "best effort" true of a REJECTION and not just of
  // a failed `ServiceResult`: a `.then`-only chain turns a breach of the never-throws
  // contract into an unhandled rejection.
  useEffect(() => {
    if (!personalSpace) return;
    void ensureSavedQueriesFolder(personalSpace)
      .then((result) => {
        if (!result.success) logBackgroundFailure('saved-queries-folder', result.error);
      })
      .catch((error: unknown) => logBackgroundFailure('saved-queries-folder', error));
  }, [personalSpace]);

  const [savedSnapshots, setSavedSnapshots] = useState<ReadonlyMap<string, string>>(() => new Map());
  const rememberSavedSql = useCallback(
    (key: string, sql: string) => setSavedSnapshots((prev) => new Map(prev).set(key, sql)),
    []
  );
  const dirtyTabIds = useMemo(
    () =>
      new Set(
        tabs.tabs
          .filter((tab) => {
            const snapshot = tab.savedQuery ? savedSnapshots.get(tab.savedQuery.key) : undefined;
            return snapshot !== undefined && !sameSql(snapshot, tab.sql);
          })
          .map((tab) => tab.id)
      ),
    [tabs.tabs, savedSnapshots]
  );

  const {activeTab} = tabs;
  // Every save asks — for a name AND a destination, a linked tab's included, pre-filled
  // and selected — because a user about to overwrite a file should be told which file, in
  // which space, before it happens. The whole path lives in the hook; this supplies the
  // destinations and takes the result.
  const saveQuery = useSaveQuery({
    spaces: savedSpaces,
    defaultSpace: savedSpace.space,
    // The hook takes the two fields it reads, not the tab that happens to carry them —
    // the Data Explorer has no `QueryTab` to hand it.
    payload: {sql: activeTab.sql, link: activeTab.savedQuery},
    toast,
    onSaved: (query, sql) => {
      // The buffer just written IS the file's content, so the dirty marker clears
      // without a read-back.
      rememberSavedSql(query.key, sql);
      tabs.setActiveTabMeta({
        label: query.name,
        savedQuery: {spaceId: query.spaceId, bucket: query.bucket, key: query.key, name: query.name}
      });
      // ONE memory of "the space I am working in" — the next save and the next load
      // both open where the user last was, rather than two memories that disagree.
      savedSpace.selectSpace(query.spaceId);
      saved.refresh();
      focusEditor();
    }
  });

  // The row that asked for a body stays on screen until the read lands, so a second click
  // there — a double-click — would open a second tab, and through Open and run start a second
  // billed query. One read per file at a time.
  const openingKeys = useRef(new Set<string>());
  // The read can land after the user has left the page. Its tab would open into a store nothing
  // persists any more, while Open and run would start a billed query in that tab on the shell's
  // engine — a run no tab comes back to show.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const openSaved = (query: SavedQuery, afterOpen?: (tabId: string, sql: string) => void) => {
    if (openingKeys.current.has(query.key)) return;
    // The cap is checked BEFORE the fetch. Reading a body only to discard it and raise
    // the limit dialog spends a GetObject on a tab that was never going to open.
    if (tabs.tabs.length >= QUERY_TABS_MAX) {
      onTabLimit();
      return;
    }
    openingKeys.current.add(query.key);
    void (async () => {
      try {
        const body = await readSavedQuery({bucket: query.bucket, key: query.key});
        if (!mounted.current) return;
        if (!body.success) {
          // The drawer stays open and no tab is opened: the user asked for this file, and
          // an empty tab labelled with its name would be a worse answer than the message.
          toast.push({variant: 'danger', message: toUserText(body.error)});
          return;
        }
        const id = tabs.openTab({
          // The label is the FILE's name from the store's own function, so a tab and a
          // list row can never disagree about what a file is called.
          label: query.name,
          sql: body.data,
          savedQuery: {spaceId: query.spaceId, bucket: query.bucket, key: query.key, name: query.name}
        });
        if (id === null) {
          onTabLimit();
          return;
        }
        rememberSavedSql(query.key, body.data);
        onOpened();
        focusEditor();
        afterOpen?.(id, body.data);
      } finally {
        openingKeys.current.delete(query.key);
      }
    })();
  };

  // The mobile Saved list has no SQL to hand its Run/View until the file is read, so the
  // fetch happens here — one GetObject, on the card the user actually chose, and never
  // merely because the list is on screen.
  const withSavedSql = (query: SavedQuery, use: (sql: string, title: string) => void) => {
    void (async () => {
      const body = await readSavedQuery({bucket: query.bucket, key: query.key});
      if (!body.success) {
        toast.push({variant: 'danger', message: toUserText(body.error)});
        return;
      }
      use(body.data, query.name);
    })();
  };

  // The tab keeps its SQL; a later Save creates a new file. Unlinked only once the file is gone:
  // a refused delete leaves it in place, and the tab still saves over it.
  const deleteSaved = (query: SavedQuery) => {
    saved
      .remove(query)
      .then(() => tabs.unlinkSavedQuery(query.key))
      .catch((e) => {
        toast.push({variant: 'danger', message: `Couldn’t delete the query. ${toUserText(e)}`});
      });
  };

  return {savedSpaces, savedSpace, saved, dirtyTabIds, saveQuery, openSaved, withSavedSql, deleteSaved};
}
