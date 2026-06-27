# Spec: Create Shared Connection

**ID:** SPEC-051
**Status:** Completed
**Last Updated:** 2026-06-27
**Depends On:** SPEC-050 (shared bucket, request queue, Step Function, registry storage, orchestrator role), SPEC-056 (request contract, membership slots, portal `sqs:SendMessage`, actor binding/validate), SPEC-033 (catalog-safe identifier rule; Glue DB + LF grant pattern), SPEC-047 (`useConnections` seam), SPEC-026 (dialog pattern), SPEC-028 (Button/Input), SPEC-044 (`Toast`)

> **Reference:** `docs/shared-spaces-architecture.md` (§2 pipeline, §3 enforcement, §4 registry, §6 async UX).
> This spec delivers the **create** action end-to-end: the browser enqueues a `create` request; the Step
> Function validates uniqueness, provisions the prefix + Glue DB + registry entry, grants the creator a
> membership slot, and writes the per-user cache so the new connection appears (pending → active).

## Overview

Let any authenticated user create a shared connection by name. The user opens a **New shared connection**
dialog, enters a name (validated to the catalog-safe identifier rule, since the name becomes both the S3 prefix
and the Glue database), and submits. The browser places a single `create` message on the SQS queue (its only
privilege). The Step Function then **validates** the name is globally unique (conditional registry write),
**creates** the `dat-prod-shared-space/{name}/` prefix (+ marker) and the Glue database `{name}`, **grants** the
creator membership (a `shared_space_k` slot + LF grant on the DB), and **writes** a per-user cache entry. Because
provisioning is asynchronous, the new connection shows immediately in a **provisioning…** pending state and flips
to **active** once the pipeline finishes (surfaced via SPEC-052's list + Refresh-connections).

## Scope

### In Scope

- A **New shared connection** entry point + **dialog** (SPEC-026 pattern): a name `Input` validated to
  `^[a-z][a-z0-9_]{2,62}$` (SPEC-033 rule, referenced from the shared constant), inline errors, **Create**/**Cancel**
- **Enqueue** a `create` request (Data Model from SPEC-050 FR-004) via `sqs:SendMessage` from the browser using the
  signed-in session — the **only** AWS call the browser makes for this; a thin `sharedSpaces.service.ts` wraps it
- **Optimistic pending entry:** on successful enqueue, the user sees the connection in a **provisioning…** state
  (a success Toast "Creating {name}…" + a local pending record) until the pipeline completes
- **Step Function `create` path** (provisioner Lambda logic, extending the SPEC-050 skeleton): **validate** name is
  catalog-safe + **globally unique** (conditional `PutObject If-None-Match:*` on the registry object — a collision
  fails); **create** the shared prefix + `DO_NOT_DELETE.txt` marker + Glue database `{name}`; **grant** the creator
  the next free membership slot (`AdminUpdateUserAttributes` on `custom:shared_space_k`) + an LF `GrantPermissions`
  on the DB (mirrors SPEC-033) + `DATA_LOCATION_ACCESS` on the shared location; **write** the registry
  (`owner`, `members:[creator]`, `status:active`) and the creator's per-user cache entry
- **Failure handling:** name collision / slot-full / any step failure terminates in the registry `failed` status
  with a reason; the user's pending entry flips to **failed** with that reason (surfaced by SPEC-052)
- **Idempotency:** a replayed `create` (same `requestId`) does not double-provision (tolerate already-exists, as
  SPEC-033)

### Out of Scope

- **Listing / selector rendering / Refresh-connections** of shared connections — SPEC-052 (this spec only writes
  the cache entry + emits a local pending state; the rich list/refresh is 052)
- **Member management** (SPEC-053), **leave/delete** (SPEC-054), **results routing** (SPEC-055)
- The **infrastructure** itself (bucket, queue, state machine, IAM, slots) — SPEC-050
- **Slot allocation across many memberships** edge policy beyond "next free slot; if none free (already in 10),
  fail with a clear reason" (the cap is `MAX_SHARED_MEMBERSHIPS`, SPEC-050)

---

## Functional Requirements

### FR-001: New-connection dialog + validation

#### Acceptance Criteria:

- [ ] A **New shared connection** control opens a dialog (SPEC-026) with a name `Input`; **Create** is disabled
  until the name matches `^[a-z][a-z0-9_]{2,62}$` (SPEC-033 rule from the shared constant — no regex duplication)
- [ ] Inline error copy states the rule on an invalid name; Cancel/Escape closes with no request sent
- [ ] The dialog explains the name is **permanent** (no rename) and **globally unique** (so a later collision is
  expected UX, not a surprise)

### FR-002: Enqueue the create request

#### Acceptance Criteria:

- [ ] On **Create**, `sharedSpaces.service.ts` sends one SQS message `{ schemaVersion, requestId: uuid,
  action:'create', actor: username, space: name, payload:{} }` (SPEC-050 contract) using the signed-in session;
  it returns `ServiceResult` and never throws
- [ ] The browser performs **no** other AWS call (no Glue/LF/S3/Cognito) — creation is entirely the pipeline's job
- [ ] On enqueue failure (network/permission) an error Toast shows and no pending entry is created

### FR-003: Pending feedback

#### Acceptance Criteria:

- [ ] On successful enqueue, a success Toast ("Creating {name}…") shows and the connection appears in a
  **provisioning…** pending state (a local pending record keyed by `requestId`/name) so the user has immediate
  feedback before the pipeline completes
- [ ] The pending state resolves to **active** (connection usable) or **failed** (with reason) once the user
  refreshes connections (SPEC-052) — this spec defines the pending/failed entry shape; SPEC-052 renders/refreshes it

### FR-004: Step Function — validate

#### Acceptance Criteria:

- [ ] The provisioner validates the name is catalog-safe and **globally unique** by attempting a conditional
  create of `shared-spaces/{name}.json` (`If-None-Match:*`); an existing object → **fail** with reason
  "name already taken" and **no** other side effects
- [ ] It confirms a free membership slot exists for the creator (≤ `MAX_SHARED_MEMBERSHIPS` after adding); none free
  → **fail** with reason "membership limit reached"

### FR-005: Step Function — create + grant + cache

#### Acceptance Criteria:

- [ ] On valid input the provisioner: creates `dat-prod-shared-space/{name}/DO_NOT_DELETE.txt`; `glue:CreateDatabase`
  `{name}` (tolerate `AlreadyExists`); LF `GrantPermissions` to the **shared portal role** on the DB (`DESCRIBE`/
  `CREATE_TABLE`/`ALTER`/`DROP` on the DB; `SELECT`/`INSERT`/`DESCRIBE`/`ALTER`/`DROP` on its tables — mirrors
  SPEC-033) + `DATA_LOCATION_ACCESS` on `dat-prod-shared-space/{name}/`
- [ ] It assigns the creator the next free slot: `AdminUpdateUserAttributes` sets `custom:shared_space_k = name`
- [ ] It writes the registry object (`owner:creator`, `members:[creator]`, `status:active`, `createdAt`,
  `lastRequestId`) and the creator's per-user cache entry `{username}/user_settings/shared-connections.json`
  (entry: `{ name, role:'owner', status:'active' }`)
- [ ] Every step is **idempotent** (replay-safe) and the handler records a terminal `active` (success) or `failed`
  (with reason) status; a mid-way failure leaves the registry `failed` and does not leave the creator half-granted
  without a recorded reason (best-effort cleanup or clear failure record — documented)

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] App: `npm run test` + `npm run lint` pass — dialog validation accepts/rejects per the rule; Create enqueues
  exactly one well-formed `create` message and makes no other AWS call; enqueue failure shows an error Toast and
  no pending entry; success shows the pending entry + Toast
- [ ] Pipeline (Lambda unit tests, Python): unique-name pass + collision fail (conditional put); create+grant+cache
  happy path; slot-full failure; replay idempotency; failure path records a reason and avoids a half-provisioned
  state — covered in `lambdas/shared-space-provisioner/` tests and the `docs/testing/shared-spaces-e2e.md` flow

---

## Data Model

```ts
// apps/portal/src/features/shared-spaces/sharedSpaces.types.ts
export type SharedConnectionRole = 'owner' | 'member';
export type SharedConnectionStatus = 'provisioning' | 'active' | 'failed' | 'leaving';

export type SharedConnectionEntry = {     // per-user cache entry (shared-connections.json)
  name: string;                            // == prefix == Glue DB
  role: SharedConnectionRole;
  status: SharedConnectionStatus;
  reason?: string;                         // present when status === 'failed'
};

export type SharedConnectionsCache = { version: 1; connections: SharedConnectionEntry[] };
```

```ts
// sharedSpaces.service.ts — browser side: enqueue only
enqueueSharedSpaceRequest(msg: SharedSpaceRequest): Promise<ServiceResult<{ requestId: string }>>;
// SharedSpaceRequest matches SPEC-050 FR-004 (schemaVersion, requestId, action, actor, space, payload)
```

## File & Folder Structure

```
apps/portal/src/features/shared-spaces/
├── index.ts
├── sharedSpaces.types.ts        ← entry/cache/request types (FR-…)
├── sharedSpaces.service.ts      ← enqueueSharedSpaceRequest (SQS SendMessage) + cache read helper
├── sharedSpaces.service.test.ts
├── CreateSharedConnectionDialog.tsx
├── CreateSharedConnectionDialog.test.tsx
└── useCreateSharedConnection.ts ← enqueue + optimistic pending + Toast

lambdas/shared-space-provisioner/
├── shared_space_provisioner.py  ← + create action (validate/create/grant/cache)
└── test_shared_space_provisioner.py
```

## Implementation Phases

### Phase 1: Browser create flow (enqueue + pending)

- Types + `sharedSpaces.service.ts` (SQS enqueue); `CreateSharedConnectionDialog` + `useCreateSharedConnection`
  (validate, enqueue, optimistic pending, Toast) (FR-001–FR-003, FR-006 app)

#### Checkpoint

`npm run dev`: New shared connection → valid name enqueues one `create` message (assert no other AWS call) and
shows a provisioning pending state + Toast; invalid names blocked; enqueue failure → error Toast. App tests/lint pass.

### Phase 2: Step Function create path

- Provisioner `create` action: validate (unique + slot), create (prefix+marker+DB), grant (LF + slot), cache write,
  idempotency + failure recording (FR-004, FR-005, FR-006 pipeline)

#### Checkpoint

A real Create drives the pipeline: registry object + Glue DB + creator slot/grant + per-user cache `active` entry
appear; a duplicate name fails with "name already taken"; replay doesn't double-provision; after a token refresh
the creator can query `database/{name}` and read/write `dat-prod-shared-space/{name}/*`. `docs/testing/shared-spaces-e2e.md` updated.

## Implementation Decisions (in-session, 2026-06-26)

- **Minimal Connections tab now** (user decision): SPEC-051 introduces the third
  top-level Connections tab (`PrimaryNav` + lazy `/connections` route +
  `ConnectionsPage` shell) hosting the New-connection control + the optimistic local
  pending list. SPEC-052 enriches it (full personal+shared list, Refresh, selector).
- **ID token in the message body** (`idToken`), verified by the Lambda → trusted
  actor (SPEC-056); the body `actor` is advisory. `getIdToken()` added to
  `awsCredentials`. New dep `@aws-sdk/client-sqs`; new `VITE_SHARED_SPACE_QUEUE_URL`.
- **FIFO send:** constant `MessageGroupId = "shared-space"` (serial intake, SPEC-050)
  + `MessageDeduplicationId = requestId`.
- **Optimistic pending is LOCAL/in-memory** (FR-003) — the browser never writes the
  cache. The pipeline writes the per-user cache (active/failed); SPEC-052 reads it.
- **DATA_LOCATION_ACCESS = a single Terraform grant** on the whole registered shared
  bucket (`shared-spaces/lakeformation.tf`, mirrors analytics' user-space grant), not
  a per-create Lambda grant. The Lambda's create verb issues only the per-DB LF grant
  (DB + tables to the portal role, mirroring SPEC-033). Per-space isolation is the IAM
  membership tag, not LF.
- **Orchestrator per-user cache write:** the orchestrator writes
  `{username}/user_settings/shared-connections.json` in the **user-space** bucket, so
  it gains `s3:Get/PutObject` on that path **and** is added to the user-space
  bucket-policy Deny-exclusion list (else the resource-policy Deny overrides its
  identity allow). The intended privileged cross-user write.
- **No new deploy-role IAM / no new resource types** — all edits use grants the deploy
  role already holds (PutRolePolicy on `*-shared-space-*`, PutBucketPolicy,
  UpdateFunctionConfiguration, lakeformation:GrantPermissions). No IAM-first PR needed.

## Open Questions

- [x] **Resolved (2026-06-21):** the name is the catalog-safe identifier (SPEC-033) and is **permanent + globally
  unique** (conditional registry write enforces uniqueness — `shared-spaces-architecture.md` §4).
- [x] **Resolved (2026-06-21):** creation is **fully pipeline-side**; the browser only `sqs:SendMessage` (§2/§3).
- [x] **Resolved (2026-06-21, default):** a `create` when the creator already holds 10 memberships **fails** with
  "membership limit reached" (no auto-eviction). Flag if creation should be exempt from the cap (it can't be — the
  creator needs a slot to access their own space).
