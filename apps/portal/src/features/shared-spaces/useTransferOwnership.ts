import {useCallback, useState} from 'react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import type {ServiceResult} from '../../types/service.types';

/**
 * Hand a shared space to one of its existing members: enqueues `transfer_ownership` onto the
 * shared-space pipeline, which authorizes the caller as owner, checks the target is a member,
 * and rewrites the registry. Only enqueues + tracks in-flight state — the drawer never flips
 * the roles optimistically, because the request can be refused after it is accepted.
 */
export function useTransferOwnership(username: string | null) {
  const [busy, setBusy] = useState(false);

  const transfer = useCallback(
    async (space: string, newOwner: string): Promise<ServiceResult<{requestId: string}>> => {
      if (!username) {
        return {success: false, error: {message: 'Not signed in', code: 'NotAuthenticated'}};
      }
      if (!newOwner) {
        return {success: false, error: {message: 'No new owner specified', code: 'InvalidRequest'}};
      }
      setBusy(true);
      const result = await enqueueSharedSpaceRequest({
        action: 'transfer_ownership',
        actor: username,
        space,
        payload: {newOwner}
      });
      setBusy(false);
      return result;
    },
    [username]
  );

  return {transfer, busy};
}
