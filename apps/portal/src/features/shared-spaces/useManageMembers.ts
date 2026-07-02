import {useCallback, useState} from 'react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import type {ServiceResult} from '../../types/service.types';

/**
 * Owner member management: enqueues `add_members` / `remove_members` onto the
 * shared-space pipeline, which authorizes the caller as owner, validates usernames,
 * and updates the owner's cache projection (visible after a Refresh-connections).
 * Only enqueues + tracks in-flight state — holds no optimistic member list.
 */
export function useManageMembers(username: string | null) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (
      action: 'add_members' | 'remove_members',
      space: string,
      members: string[]
    ): Promise<ServiceResult<{requestId: string}>> => {
      if (!username) {
        return {success: false, error: {message: 'Not signed in'}};
      }
      if (members.length === 0) {
        return {success: false, error: {message: 'No members specified'}};
      }
      setBusy(true);
      const result = await enqueueSharedSpaceRequest({
        action,
        actor: username,
        space,
        payload: {members}
      });
      setBusy(false);
      return result;
    },
    [username]
  );

  const addMembers = useCallback((space: string, members: string[]) => submit('add_members', space, members), [submit]);

  const removeMembers = useCallback(
    (space: string, members: string[]) => submit('remove_members', space, members),
    [submit]
  );

  return {addMembers, removeMembers, busy};
}
