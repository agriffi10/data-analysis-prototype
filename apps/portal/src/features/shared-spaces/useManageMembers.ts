import { useCallback, useState } from 'react';
import { enqueueSharedSpaceRequest } from './sharedSpaces.service';
import type { ServiceResult } from '../../types/service.types';

// SPEC-053: owner member management. Enqueues `add_members` / `remove_members`
// requests onto the shared-space pipeline (the browser never touches
// Cognito/Glue/LF/S3 directly). The pipeline authorizes the caller as the owner,
// validates each username against the User Pool, and updates slots/registry/cache;
// the result lands in the owner's cache projection, visible after a
// Refresh-connections (SPEC-052). This hook only enqueues + tracks the in-flight
// state — it holds no optimistic member list (member-list-only feedback, per the
// SPEC-053 design decision; ignored/at-limit counts arrive via the notifications
// arc later).
export function useManageMembers(username: string | null) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (
      action: 'add_members' | 'remove_members',
      space: string,
      members: string[]
    ): Promise<ServiceResult<{ requestId: string }>> => {
      if (!username) {
        return { success: false, error: { message: 'Not signed in' } };
      }
      if (members.length === 0) {
        return { success: false, error: { message: 'No members specified' } };
      }
      setBusy(true);
      const result = await enqueueSharedSpaceRequest({
        action,
        actor: username,
        space,
        payload: { members },
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

  return { addMembers, removeMembers, busy };
}
