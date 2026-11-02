---
type: Spec
id: SPEC-054
title: "Leave & Delete a Shared Space"
description: "Lets members leave a shared connection and owners delete one, with delete cascading to the files, tables, Glue database, every member's access slot, and the registry entry, while owners cannot leave."
spec_status: Completed
depends_on: [SPEC-050, SPEC-056, SPEC-051, SPEC-052, SPEC-053, SPEC-026, SPEC-044]
arc: shared-connections
arc_order: 6
---

**Dependency notes:** SPEC-050 (Step Function, registry storage, orchestrator Glue/LF/S3/Cognito perms), SPEC-056 (request contract, membership slots, actor binding/validate), SPEC-051 (create + registry/cache shapes), SPEC-052 (connections screen + status), SPEC-053 (member model), SPEC-026 (confirm dialog), SPEC-044 (`Toast`)
> **Reference:** `docs/shared-spaces-architecture.md` (§2 pipeline, §3 slot revoke, §4 registry, §5 data layout).
> Two terminal lifecycle actions: a **member leaves** (revokes only their own access); an **owner deletes** (cascades
> away the whole space). Both go through the pipeline and are authorized server-side.

## Overview

Give members a way out and owners a way to tear down. A **member** can **leave** a shared connection: a request
revokes their membership slot, removes them from the registry, and drops their per-user cache entry — the shared
objects and tables are untouched (everyone else keeps access). An **owner** can **delete** the space: a confirmed,
irreversible request that cascades — delete all files under `dat-prod-shared-space/{name}/`, drop all tables and the
Glue database `{name}`, revoke **every** member's slot + cache entry, and remove the registry object. The owner
cannot "leave" (they must delete); a non-owner cannot delete. Both actions are async (pending → resolved on
Refresh-connections, SPEC-052) and idempotent.

## Scope

### In Scope

- **Leave (member):** a confirm dialog → enqueue a `leave` request; the pipeline removes `actor` from the registry,
  clears the actor's `custom:shared_space_k` slot, and removes the actor's cache entry. **No data is deleted.** The
  **owner cannot leave** (the action is hidden for owners and rejected server-side)
- **Delete (owner):** an **irreversible** confirm (type-to-confirm the name, given the cascade) → enqueue a `delete`
  request; the pipeline cascades: delete every object under `dat-prod-shared-space/{name}/` (recursive, incl. the
  marker and all `athenaresults/`), drop all tables + the Glue database `{name}`, revoke the slot + cache entry for
  **every** member, and delete the registry object. **Owner-only**, enforced server-side
- **Confirmations** matching the destructiveness: leave = simple confirm; delete = irreversible alertdialog with a
  type-the-name guard (SPEC-026 pattern; the file-delete + drop-table precedent, SPEC-018/044)
- **Pending + cleanup UX:** the connection shows `leaving`/`deleting` then disappears from the user's list on
  Refresh; if the active tab targeted that connection, it falls back to personal (SPEC-052 FR-003)
- **Pipeline behavior** (provisioner `leave` / `delete`): authorize (`leave`: `actor ∈ members ∧ actor != owner`;
  `delete`: `actor == owner`); apply the revoke/cascade idempotently; record a terminal status; partial-failure
  handling for the recursive delete (report which steps succeeded; never leave the registry claiming `active` after
  a successful teardown)

### Out of Scope

- **Transferring ownership** (no owner handoff in v1 — deleting is the owner's exit) — note as future
- **Per-member data cleanup on leave** (leaving touches no objects; the member's prior contributions stay in the
  shared space — it's shared, not owned)
- **Soft-delete / recovery** of a deleted space (versioning is off — architecture Known Constraints; delete is
  permanent)
- **Member management** (add/remove others) — SPEC-053
- Real-time effect — revocation takes effect on the affected user's next token refresh (Refresh-connections, §3)

---

## Functional Requirements

### FR-001: Leave (member) — confirm + request

#### Acceptance Criteria:

- [ ] For a connection where the user is a **member** (not owner), a **Leave** action opens a confirm dialog
  ("Leave {name}? You'll lose access to its files and tables. They are not deleted."); confirming enqueues a `leave`
  request `{ action:'leave', actor, space }`
- [ ] **Leave is not offered to the owner** (the screen shows Delete instead); a crafted `leave` from the owner is
  rejected server-side
- [ ] The browser makes no direct Glue/LF/S3/Cognito call; the connection shows a `leaving` pending state and is gone
  on the next Refresh-connections

### FR-002: Delete (owner) — irreversible confirm + request

#### Acceptance Criteria:

- [ ] For a connection the user **owns**, a **Delete** action opens an **irreversible** alertdialog (SPEC-026,
  danger) that names the cascade (all files, all tables, the database, all members' access) and requires
  **typing the space name** to enable the destructive button
- [ ] Confirming enqueues a `delete` request `{ action:'delete', actor, space }`; the connection shows a `deleting`
  pending state
- [ ] Delete is **not offered to non-owners**; a crafted `delete` from a non-owner is rejected server-side

### FR-003: Pipeline — leave

#### Acceptance Criteria:

- [ ] The provisioner authorizes `actor ∈ registry[space].members ∧ actor != registry[space].owner`; otherwise
  **fail** with reason and no effect
- [ ] It removes `actor` from `members`, clears the actor's matching `custom:shared_space_k` slot, and removes the
  actor's per-user cache entry; the shared prefix, tables, DB, and other members are **untouched**
- [ ] Idempotent: a `leave` from a non-member is a no-op success

### FR-004: Pipeline — delete (cascade)

#### Acceptance Criteria:

- [ ] The provisioner authorizes `actor == registry[space].owner`; otherwise **fail** with reason and no effect
- [ ] It cascades: **recursively delete** all objects under `dat-prod-shared-space/{name}/` (paginated, incl. the
  marker + every `athenaresults/{user}/`); **drop all tables** then `glue:DeleteDatabase {name}` (+ revoke the LF
  grant / data-location access); **clear the slot + remove the cache entry for every member** in `members`; then
  **delete the registry object** `shared-spaces/{name}.json`
- [ ] The cascade is **idempotent** and tolerant of partial prior progress (re-running completes it); ordering ensures
  the registry object is removed **last**, so a failure mid-cascade leaves a `deleting`/`failed` status (recoverable
  by re-running), never a dangling `active` registry pointing at half-deleted resources
- [ ] After success, the name is **free to reuse** (a future `create` of the same name passes the uniqueness check)

### FR-005: Post-action UX

#### Acceptance Criteria:

- [ ] After a successful leave/delete + Refresh-connections, the connection disappears from the user's list; any tab
  that targeted it falls back to the personal connection with a non-blocking notice (SPEC-052 FR-003)
- [ ] A `failed` leave/delete surfaces its reason on the connections screen with a Retry affordance (re-enqueues)

### FR-006: Tests + lint

#### Acceptance Criteria:

- [ ] App: `npm run test` + `npm run lint` pass — Leave shown only to members (confirm → one `leave` request); Delete
  shown only to owners (type-to-confirm → one `delete` request); no direct AWS mutation; pending → fallback on Refresh
- [ ] Pipeline (Python): leave authorizes member-not-owner, clears slot/registry/cache, leaves data intact, idempotent;
  delete authorizes owner, cascades files+tables+DB+all-members+registry in the safe order, idempotent/partial-safe,
  frees the name; non-owner delete + owner leave both fail with no effect — in `lambdas/shared-space-provisioner/`
  tests + `docs/testing/e2e.md`

---

## Data Model

```jsonc
// leave / delete requests (SPEC-050 contract; no payload needed)
{ "action": "leave",  "actor": "bob",   "space": "salesdata" }
{ "action": "delete", "actor": "alice", "space": "salesdata" }
```

No new persisted types — mutates the SPEC-050/051 registry + per-user caches + Cognito slots.

## File & Folder Structure

```
apps/portal/src/features/shared-spaces/
├── LeaveSharedSpaceDialog.tsx       ← NEW: member confirm
├── DeleteSharedSpaceDialog.tsx      ← NEW: owner irreversible (type-the-name) confirm
├── *.test.tsx
├── useLeaveOrDeleteSharedSpace.ts   ← enqueue leave/delete + pending + Toast
└── (SharedConnectionsScreen wiring) ← Leave (member) / Delete (owner) per-row actions (SPEC-052)

lambdas/shared-space-provisioner/
└── shared_space_provisioner.py      ← + leave / delete (cascade, safe ordering, idempotent)
```

## Implementation Phases

### Phase 1: Leave/Delete UI + requests

- Confirm dialogs (leave simple; delete irreversible type-the-name); `useLeaveOrDeleteSharedSpace` (enqueue + pending +
  Toast); wire role-gated actions into the SPEC-052 screen (FR-001, FR-002, FR-005, FR-006 app)

#### Checkpoint

`npm run dev`: a member sees Leave (confirm → one `leave` request); an owner sees Delete (type-the-name → one
`delete` request); neither is shown the other's action; after Refresh the connection is gone and a targeting tab
falls back to personal. App tests/lint pass.

### Phase 2: Pipeline leave + delete cascade

- Provisioner `leave` (member-not-owner revoke) and `delete` (owner cascade in safe order); idempotency + partial-safe
  + name freed (FR-003, FR-004, FR-006 pipeline)

#### Checkpoint

A real Leave revokes only that member (data + others intact); a real Delete removes all files, tables, the DB, every
member's access, and the registry object (name reusable afterward); re-running a partially-failed delete completes it;
owner-leave and non-owner-delete both fail with no effect. e2e doc updated.

## Open Questions

- [x] **Resolved (2026-06-21):** the **owner cannot leave** — they **delete** (no ownership transfer in v1; noted as
  future).
- [x] **Resolved (2026-06-21):** delete is a **cascade** (files + tables + DB + all members + registry), irreversible
  (versioning off), with the registry object removed **last** for partial-safety.
- [x] **Resolved (2026-06-21):** leaving deletes **no** data (shared, single copy); the member just loses access.
- [x] **Resolved (2026-06-21, default):** delete requires **typing the space name** to confirm (matches the cascade's
  severity; stronger than a plain confirm). Flag if a plain confirm is preferred.
