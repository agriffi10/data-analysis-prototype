// Shared types for the connections domain — the databases a signed-in user can target.

import type {
  FailedAction,
  Member,
  SharedConnectionRole,
  SharedConnectionStatus
} from '../shared-spaces/sharedSpaces.types';

export type ConnectionKind = 'personal' | 'shared';

/**
 * A database the signed-in user can target: the personal database
 * (`database = username`) or a shared space, both fed through the same
 * `useConnections` seam.
 */
export type Connection = {
  /** 'personal' for the user's own DB; the shared-space name for shared. */
  id: string;
  /** Display name (the database name for personal; the shared-space name). */
  label: string;
  /** Glue database name targeted by queries. */
  database: string;
  kind: ConnectionKind;
  /** Surfaced from the per-user cache for shared connections only. */
  status?: SharedConnectionStatus;
  role?: SharedConnectionRole;
  /** Failure reason (present when status === 'failed'). */
  reason?: string;
  /** Which verb failed, so the row offers the retry that matches it. */
  failedAction?: FailedAction;
  /** Owner-readable member roster + join status (present only on a connection the user owns); drives the Manage-members drawer. */
  members?: Member[];
  /** Creation date (ISO). Absent on older cache entries. */
  createdAt?: string;
  /** Owner username; present on member connections (owner connections derive the count from `members`). */
  owner?: string;
};

/**
 * A connection is targetable (queryable/browsable) only when it's the
 * personal DB or an `active` shared space; provisioning/failed/leaving shared
 * entries are shown but disabled.
 */
export function isConnectionUsable(c: Connection): boolean {
  return c.kind === 'personal' || c.status === 'active';
}
