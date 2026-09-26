import {useEffect, useEffectEvent, useRef, useState} from 'react';
import {exceedsAthenaQueryLimit} from '../../lib/athenaLimit';
import {toUserText} from '../../lib/errorMessages';
import {parseViewLine} from '../../lib/savedViewLine';
import {useConnections} from '../connections/useConnections';
import {useSpaceLinkPending} from '../connections/useSpaceLinkPending';
import {readSavedQuery} from '../saved-queries/savedQueries.service';
import {spaceDatabase} from './exploreSources';
import {readSavedView, SAVED_VIEW_REFUSALS, stripForSharedFolder} from './savedView';
import type {ToastApi} from '../../components/toastContext';
import type {QuerySpace} from '../catalog/catalog.types';
import type {SavedQuery} from '../saved-queries/savedQueries.types';
import type {ExplorationSource} from './dataExplorer.types';
import type {SavedView} from './savedView';
import type {OpenExplorationOpts} from './useExplorationTabs';

/** A file that did not reopen: what the dialog says, and the SQL **Open in Query** hands over. */
export type SavedViewRefusal = {name: string; message: string; sql: string};

type Pending = {query: SavedQuery; fileSpace: QuerySpace; view: SavedView; sql: string};

/**
 * The tab a settled open asks for.
 *
 * @param done - The file, the space it was listed from, and its view.
 * @param space - The space the view's database resolved to.
 * @returns The source and how to open it: whole and linked from the personal folder; held,
 *   stripped and unlinked from a shared one.
 */
function openRequest(
  done: Pending,
  space: QuerySpace,
  personalBucket: string | undefined
): {source: ExplorationSource; opts: OpenExplorationOpts} {
  // By BUCKET rather than by space id: a shared space's id is its name, and nothing reserves the
  // name `personal`. A missing personal space leaves nothing trusted.
  const shared = personalBucket === undefined || done.fileSpace.bucket !== personalBucket;
  const stripped = shared ? stripForSharedFolder(done.view.presentation) : null;
  const presentation = {
    ...(stripped?.presentation ?? done.view.presentation),
    valuePanelOpen: false,
    recordRowIndex: 0
  };
  const {query} = done;
  return {
    source: {kind: 'table', spaceId: space.id, database: done.view.source.database, table: done.view.source.table},
    opts: {
      seed: {query: done.view.query, presentation},
      ...(stripped
        ? {awaitingRun: {space: done.fileSpace.label, leftOut: stripped.leftOut}}
        : {savedQuery: {spaceId: query.spaceId, bucket: query.bucket, key: query.key, name: query.name}})
    }
  };
}

type Params = {
  username: string;
  /** The spaces the table picker offers, personal first — already view-gated. */
  spaces: QuerySpace[];
  /** Opens a tab the way every other open does, returning null at the tab cap. */
  openTab: (source: ExplorationSource, opts: OpenExplorationOpts) => string | null;
  toast: ToastApi;
};

/**
 * Reopens a saved query as a Data Explorer view, or says why it will not.
 *
 * The file is read, its view line parsed and its payload read strictly; the table's space is then
 * found by DATABASE among the spaces the picker offers, never from anything else the file names.
 * A space the list lacks is refused only after a read of the connections list that settles after
 * the open, as a deep link's is — a space joined a moment ago must not read as no access.
 *
 * Where the FILE came from decides how much of it is trusted. From the user's personal folder,
 * which only they can write, the view restores whole, runs, and stays linked to its file. From a
 * shared space's folder, which any member can write, it is held until the user runs it, loses its
 * link columns and pattern rules, and is not linked, so a save cannot silently replace the
 * author's version.
 *
 * @param params - The user, the picker's spaces, how to open a tab, and where a read failure goes.
 * @returns The file being opened, a refusal to show, and the gestures over both.
 */
export function useOpenSavedView({username, spaces, openTab, toast}: Params) {
  const [openingKey, setOpeningKey] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [refusal, setRefusal] = useState<SavedViewRefusal | null>(null);
  const {listReadsSettled, rereadList} = useConnections(username || null);

  const database = pending?.view.source.database ?? null;
  const space = database === null ? null : (spaces.find((s) => spaceDatabase(s, username) === database) ?? null);
  const waiting = useSpaceLinkPending({
    username: username || null,
    space: database,
    missing: pending !== null && space === null,
    listReadsSettled,
    rereadList
  });

  // The open settles once the space is known either way. Settled DURING RENDER — the "adjust state
  // when a value changes" pattern, and guarded, because settling clears `pending` — since what it
  // waits on is a read of the connections list, which arrives on its own schedule.
  const [toOpen, setToOpen] = useState<{source: ExplorationSource; opts: OpenExplorationOpts} | null>(null);
  // Never in the render that first sees a pending open: the wait re-arms by setting its own state
  // during that render, so its answer there is the previous request's, and a refusal read from it
  // would refuse a space whose list read has not even been asked for.
  const [armed, setArmed] = useState<Pending | null>(null);
  if (armed !== pending) setArmed(pending);
  if (pending && armed === pending && !waiting) {
    setPending(null);
    setOpeningKey(null);
    if (space) setToOpen(openRequest(pending, space, spaces.find((s) => s.id === 'personal')?.bucket));
    else
      setRefusal({name: pending.query.name, message: SAVED_VIEW_REFUSALS.noAccess(database ?? ''), sql: pending.sql});
  }

  // Opening a tab is not idempotent, so it happens once per request, after the render that made it.
  const opened = useRef<object | null>(null);
  const openNow = useEffectEvent((request: {source: ExplorationSource; opts: OpenExplorationOpts}) => {
    openTab(request.source, request.opts);
  });
  useEffect(() => {
    if (!toOpen || opened.current === toOpen) return;
    opened.current = toOpen;
    openNow(toOpen);
  }, [toOpen]);

  const openFile = async (query: SavedQuery, fileSpace: QuerySpace) => {
    setOpeningKey(query.key);
    const read = await readSavedQuery({bucket: query.bucket, key: query.key});
    if (!read.success) {
      setOpeningKey(null);
      toast.push({variant: 'danger', message: toUserText(read.error)});
      return;
    }
    const parsed = parseViewLine(read.data);
    const refuse = (message: string) => {
      setOpeningKey(null);
      setRefusal({name: query.name, message, sql: parsed.sql});
    };
    // This build never writes a file Athena would not run, so a larger one was written by hand,
    // and its size alone — tens of thousands of Colors rules — is enough to stall the page.
    if (exceedsAthenaQueryLimit(read.data)) return refuse(SAVED_VIEW_REFUSALS.tooLarge(query.name));
    if (parsed.kind === 'none') return refuse(SAVED_VIEW_REFUSALS.none(query.name));
    if (parsed.kind === 'edited') return refuse(SAVED_VIEW_REFUSALS.edited(query.name));
    if (parsed.kind === 'newer') return refuse(SAVED_VIEW_REFUSALS.newer(query.name));
    const view = parsed.kind === 'ok' ? readSavedView(parsed.payload) : null;
    if (!view) return refuse(SAVED_VIEW_REFUSALS.unreadable(query.name));
    setPending({query, fileSpace, view, sql: parsed.sql});
  };

  return {
    openingKey,
    refusal,
    dismissRefusal: () => setRefusal(null),
    openFile: (query: SavedQuery, fileSpace: QuerySpace) => void openFile(query, fileSpace)
  };
}
