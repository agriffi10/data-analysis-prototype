import {useRef, useState, type ReactNode} from 'react';
import {useToast} from '../../components/toastContext';
import {MobileSurfaceContext, QueryRunsContext} from './queryRunsContext';
import type {MobileHomeTab, MobileQueryView, MobileRun} from './query.types';
import {useQueryHistoryWriters} from './useQueryHistory';
import {useQueryRunsEngine} from './useQueryRunsEngine';

/**
 * Holds the Query workspace's runs at the signed-in shell, so they outlive the Query page.
 *
 * The page unmounts on every nav-tab click; held there, a run's results were gone on the way
 * back and an in-flight batch lost its poller, so it never advanced and its history never
 * settled. Here the pollers keep running while the user is elsewhere. The mobile surface's state
 * sits beside the runs, since it identifies its own run by a token. Nothing is persisted, and
 * nothing is fetched until the workspace starts a run.
 *
 * @example
 * <QueryRunsProvider username={username}>
 *   <Outlet />
 * </QueryRunsProvider>
 */
export function QueryRunsProvider({username, children}: {username: string; children: ReactNode}) {
  const toast = useToast();
  const {appendEntry, updateEntry} = useQueryHistoryWriters(username || null);
  const {pollers, ...engine} = useQueryRunsEngine({username, appendEntry, updateEntry, toast});
  const [view, setView] = useState<MobileQueryView>({kind: 'home'});
  const [homeTab, setHomeTab] = useState<MobileHomeTab>('saved');
  const [run, setRun] = useState<MobileRun | null>(null);
  const tokenRef = useRef(0);
  return (
    <QueryRunsContext.Provider value={engine}>
      <MobileSurfaceContext.Provider value={{view, setView, homeTab, setHomeTab, run, setRun, tokenRef}}>
        {pollers}
        {children}
      </MobileSurfaceContext.Provider>
    </QueryRunsContext.Provider>
  );
}
