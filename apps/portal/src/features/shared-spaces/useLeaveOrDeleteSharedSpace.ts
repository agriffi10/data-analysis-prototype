import {useCallback, useState} from 'react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import type {ServiceResult} from '../../types/service.types';

/**
 * Terminal shared-space lifecycle actions. `leave` revokes only the caller's own
 * access; `delete` (owner-only) ends everyone's access and keeps the space's contents; `forget` durably
 * clears a failed/phantom entry from the caller's own list — never a healthy active
 * space. All are pipeline requests authorized server-side; results apply after a
 * Refresh-connections. This hook only enqueues + tracks in-flight state; optimistic
 * pending status lives in the Connections screen.
 */
export function useLeaveOrDeleteSharedSpace(username: string | null) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (action: 'leave' | 'delete' | 'forget', space: string): Promise<ServiceResult<{requestId: string}>> => {
      if (!username) {
        return {success: false, error: {message: 'Not signed in', code: 'NotAuthenticated'}};
      }
      setBusy(true);
      const result = await enqueueSharedSpaceRequest({action, actor: username, space});
      setBusy(false);
      return result;
    },
    [username]
  );

  const leave = useCallback((space: string) => submit('leave', space), [submit]);
  const remove = useCallback((space: string) => submit('delete', space), [submit]);
  const forget = useCallback((space: string) => submit('forget', space), [submit]);

  return {leave, remove, forget, busy};
}
