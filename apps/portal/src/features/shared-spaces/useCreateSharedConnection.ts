import {useCallback, useState} from 'react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import type {ServiceResult} from '../../types/service.types';
import type {SharedConnectionEntry} from './sharedSpaces.types';

/**
 * Create-shared-connection flow: enqueue a `create` request and, on a successful
 * enqueue, hold an optimistic local pending entry (provisioning) for immediate
 * feedback. Authoritative active/failed state arrives via the pipeline-written
 * per-user cache — this hook only tracks the in-memory pending list; it never writes S3.
 *
 * A pending entry's only job is covering the gap until the pipeline writes, so it is dropped
 * the first time the cache lists its name. Kept past that, it outlives the space: once the
 * space is deleted, or a failed create is dismissed, the cache stops listing the name and the
 * entry would come back as a phantom "Provisioning" row.
 *
 * @param username - The signed-in user, or null.
 * @param cachedNames - The shared-space names the per-user cache lists right now.
 */
export function useCreateSharedConnection(username: string | null, cachedNames: ReadonlySet<string>) {
  const [pending, setPending] = useState<SharedConnectionEntry[]>([]);
  const [busy, setBusy] = useState(false);

  // Render-phase "adjust state on change" (react.md §3): the guard is false once pruned.
  if (pending.some((p) => cachedNames.has(p.name))) {
    setPending(pending.filter((p) => !cachedNames.has(p.name)));
  }

  const create = useCallback(
    async (name: string): Promise<ServiceResult<{requestId: string}>> => {
      if (!username) {
        return {success: false, error: {message: 'Not signed in', code: 'NotAuthenticated'}};
      }
      setBusy(true);
      const result = await enqueueSharedSpaceRequest({
        action: 'create',
        actor: username,
        space: name,
        payload: {}
      });
      setBusy(false);
      if (result.success) {
        setPending((prev) => [...prev, {name, role: 'owner', status: 'provisioning'}]);
      }
      return result;
    },
    [username]
  );

  return {create, busy, pending};
}
