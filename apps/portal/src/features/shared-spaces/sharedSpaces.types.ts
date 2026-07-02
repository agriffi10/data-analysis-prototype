// Shared-spaces types. The per-user cache shape mirrors what the provisioning
// pipeline writes to {username}/user_settings/shared-connections.json.

export type SharedConnectionRole = 'owner' | 'member';
export type SharedConnectionStatus = 'provisioning' | 'active' | 'failed' | 'leaving' | 'deleting';

/** One entry in the per-user cache (and the local optimistic pending list). */
export type SharedConnectionEntry = {
  /** Space name == S3 prefix == Glue DB. */
  name: string;
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  /** Present when status === 'failed'. */
  reason?: string;
  /**
   * Owner-readable projection: the pipeline writes the current member list into the
   * OWNER's entry only, so the Manage drawer can render it without reading the
   * admin-bucket registry. Absent on member entries.
   */
  members?: string[];
  /** When the space was created (ISO 8601, immutable); absent on older cache entries. */
  createdAt?: string;
  /** The space owner's username, written on member entries only; absent on older cache entries. */
  owner?: string;
};

export type SharedConnectionsCache = {
  version: 1;
  connections: SharedConnectionEntry[];
};

/** Shared-space request actions. `forget` = durable "clear this entry from my list". */
export type SharedSpaceAction = 'create' | 'add_members' | 'remove_members' | 'leave' | 'delete' | 'forget';

/**
 * The SQS message body. `actor` is advisory — the Lambda derives the trusted actor
 * from the verified `idToken` (cognito:username), never the body.
 */
export type SharedSpaceRequest = {
  schemaVersion: 1;
  requestId: string;
  action: SharedSpaceAction;
  actor: string;
  space: string;
  payload: Record<string, unknown>;
  idToken: string;
};
