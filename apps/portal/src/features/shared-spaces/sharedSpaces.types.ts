// Shared-spaces types (SPEC-051). The per-user cache shape mirrors what the
// pipeline writes to {username}/user_settings/shared-connections.json (SPEC-056);
// SPEC-052 reads/renders it. SPEC-051 only emits a LOCAL (in-memory) pending entry.

export type SharedConnectionRole = 'owner' | 'member';
export type SharedConnectionStatus = 'provisioning' | 'active' | 'failed' | 'leaving';

// One entry in the per-user cache (and the local optimistic pending list).
export type SharedConnectionEntry = {
  name: string; // == S3 prefix == Glue DB
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  reason?: string; // present when status === 'failed'
};

export type SharedConnectionsCache = {
  version: 1;
  connections: SharedConnectionEntry[];
};

// Shared-space request actions (SPEC-056 contract). SPEC-051 sends only `create`;
// the rest land in SPEC-053/054.
export type SharedSpaceAction =
  | 'create'
  | 'add_members'
  | 'remove_members'
  | 'leave'
  | 'delete';

// The SQS message body (SPEC-056 FR-004). `actor` is advisory — the Lambda derives
// the trusted actor from the verified `idToken` (cognito:username), never the body.
export type SharedSpaceRequest = {
  schemaVersion: 1;
  requestId: string;
  action: SharedSpaceAction;
  actor: string;
  space: string;
  payload: Record<string, unknown>;
  idToken: string;
};
