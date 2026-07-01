// Shared-spaces types (SPEC-051). The per-user cache shape mirrors what the
// pipeline writes to {username}/user_settings/shared-connections.json (SPEC-056);
// SPEC-052 reads/renders it. SPEC-051 only emits a LOCAL (in-memory) pending entry.

export type SharedConnectionRole = 'owner' | 'member';
export type SharedConnectionStatus = 'provisioning' | 'active' | 'failed' | 'leaving' | 'deleting';

// One entry in the per-user cache (and the local optimistic pending list).
export type SharedConnectionEntry = {
  name: string; // == S3 prefix == Glue DB
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  reason?: string; // present when status === 'failed'
  // SPEC-053 owner-readable projection: the pipeline writes the current member
  // list into the OWNER's entry (only) so the Manage drawer can render it without
  // reading the admin-bucket registry. Absent on member entries.
  members?: string[];
  // Card meta line: when the space was created (ISO 8601, immutable) — stamped on
  // every member's entry. `owner` is the space owner's username, written on member
  // entries (members never get the full `members` list). Both absent on older cache
  // entries written before this projection landed.
  createdAt?: string;
  owner?: string;
};

export type SharedConnectionsCache = {
  version: 1;
  connections: SharedConnectionEntry[];
};

// Shared-space request actions (SPEC-056 contract). SPEC-051 sends only `create`;
// the rest land in SPEC-053/054. `forget` = durable "clear this entry from my list".
export type SharedSpaceAction = 'create' | 'add_members' | 'remove_members' | 'leave' | 'delete' | 'forget';

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
