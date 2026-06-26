import { useCallback, useState } from 'react';
import { enqueueSharedSpaceRequest } from './sharedSpaces.service';
import type { ServiceResult } from '../../types/service.types';
import type { SharedConnectionEntry } from './sharedSpaces.types';

// Create-shared-connection flow (SPEC-051): enqueue a `create` request and, on a
// successful enqueue, hold an optimistic LOCAL pending entry (provisioning…) so the
// user gets immediate feedback. The authoritative active/failed state arrives when
// SPEC-052 reads the per-user cache the pipeline writes — this hook only tracks the
// in-memory pending list; it never writes S3.
export function useCreateSharedConnection(username: string | null) {
  const [pending, setPending] = useState<SharedConnectionEntry[]>([]);
  const [busy, setBusy] = useState(false);

  const create = useCallback(
    async (name: string): Promise<ServiceResult<{ requestId: string }>> => {
      if (!username) {
        return { success: false, error: { message: 'Not signed in' } };
      }
      setBusy(true);
      const result = await enqueueSharedSpaceRequest({
        action: 'create',
        actor: username,
        space: name,
        payload: {},
      });
      setBusy(false);
      if (result.success) {
        setPending((prev) => [
          ...prev,
          { name, role: 'owner', status: 'provisioning' },
        ]);
      }
      return result;
    },
    [username],
  );

  return { create, busy, pending };
}
