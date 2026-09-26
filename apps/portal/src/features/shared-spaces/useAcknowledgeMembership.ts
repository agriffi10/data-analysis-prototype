import {useEffect, useRef} from 'react';
import {enqueueSharedSpaceRequest} from './sharedSpaces.service';
import type {Connection} from '../connections/connection.types';

// Once-per-session-per-space dedup lives in sessionStorage so a re-render (or React
// StrictMode's double-effect) can't enqueue twice, and a new tab/session re-acks.
function ackKey(username: string, space: string): string {
  return `s3portal.ackMembership.${username}.${space}`;
}

/** Whether this session has acked the space. Storage that cannot be read answers no. */
function wasAcked(key: string): boolean {
  try {
    return sessionStorage.getItem(key) !== null;
  } catch {
    return false;
  }
}

/** Records the ack for this session. Storage that refuses the write is left alone. */
function recordAck(key: string): void {
  try {
    sessionStorage.setItem(key, '1');
  } catch {
    // Disabled or full storage; the in-hook record still dedupes this page.
  }
}

/**
 * Join-status acknowledgement. The first time a member's
 * authenticated session resolves a shared space they belong to, enqueue one
 * `acknowledge_membership` request so the control plane flips them Pending → Active in
 * the owner's projection. Best-effort and idempotent server-side: fired only for an
 * `active` shared connection where the signed-in user is a `member` (never the owner),
 * and deduped to exactly one enqueue per space per browser session.
 *
 * Every storage access is guarded, as everywhere in the app: a quota or security error thrown
 * from this effect would take the Files page down through its error boundary. Where storage
 * cannot be used, a record held by the hook keeps the dedup to one enqueue per page.
 *
 * Called from the file-space resolution path (`FilesPage`) with the active space id.
 */
export function useAcknowledgeMembership(
  username: string | null,
  connections: Connection[],
  activeSpaceId: string
): void {
  const ackedHere = useRef(new Set<string>());

  useEffect(() => {
    if (!username || activeSpaceId === 'personal') return;
    const conn = connections.find((c) => c.id === activeSpaceId);
    if (!conn || conn.kind !== 'shared' || conn.role !== 'member' || conn.status !== 'active') return;

    const key = ackKey(username, conn.id);
    if (ackedHere.current.has(key) || wasAcked(key)) return;
    // Mark done BEFORE the async send so concurrent renders can't double-enqueue; a
    // failed send simply retries next session (best-effort bookkeeping, not critical).
    ackedHere.current.add(key);
    recordAck(key);
    void enqueueSharedSpaceRequest({action: 'acknowledge_membership', actor: username, space: conn.id});
  }, [username, connections, activeSpaceId]);
}
