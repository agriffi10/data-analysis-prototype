import {useCallback} from 'react';
import {useAuth} from '../auth';
import {linkFlags} from './linkFlags';
import {useFeatureSet} from './useFeatureSet';

/**
 * Whether an in-app link leads somewhere this user can currently see.
 *
 * **How a link into ANOTHER feature asks.** A control that navigates across features gates on
 * its destination rather than its own screen: every flag the destination route needs, and shared
 * workspaces when the link names a shared space (see {@link linkFlags}). Asking `useFeature` for
 * one hand-picked flag is how links kept shipping into pages that had been switched off.
 *
 * `false` while the flags are loading, like {@link useFeature}.
 *
 * @returns A predicate over in-app links, stable while the flags and the viewer are.
 *
 * @example
 * const canFollow = useCanFollowLink();
 * {canFollow(href) && <Button onClick={() => navigate(href)}>Open folder</Button>}
 */
export function useCanFollowLink(): (link: string) => boolean {
  const {isEnabled} = useFeatureSet();
  const {user} = useAuth();
  const username = user?.username ?? null;
  return useCallback((link: string) => linkFlags(link, username).every(isEnabled), [isEnabled, username]);
}
