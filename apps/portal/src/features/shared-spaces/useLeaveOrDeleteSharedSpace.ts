import {useCallback, useState} from 'react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import type {ServiceResult} from '../../types/service.types';

// SPEC-054 + `forget`: the terminal lifecycle actions. A member `leave` revokes only
// the caller's own access; an owner `delete` cascades the whole space away; `forget`
// durably clears a failed/phantom entry from the caller's own list (cache-only, or a
// teardown of the caller's own failed create — never a healthy active space). All are
// pipeline requests (the browser never touches Cognito/Glue/LF/S3 directly) that the
// provisioner authorizes server-side (`leave`: member-not-owner; `delete`: owner-only;
// `forget`: self-scoped) and apply after a Refresh-connections (SPEC-052). This hook
// only enqueues + tracks the in-flight state; the optimistic pending status lives in
// the Connections screen (mirrors useManageMembers / useCreateSharedConnection).
export function useLeaveOrDeleteSharedSpace(username: string | null) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (action: 'leave' | 'delete' | 'forget', space: string): Promise<ServiceResult<{requestId: string}>> => {
      if (!username) {
        return {success: false, error: {message: 'Not signed in'}};
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
