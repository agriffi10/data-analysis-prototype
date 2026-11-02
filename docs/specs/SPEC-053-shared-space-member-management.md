---
type: Spec
id: SPEC-053
title: "Shared-Space Member Management (Owner)"
description: "Lets a shared connection's owner add and remove members by username, singly or in bulk, from a Manage members drawer, with server-side owner authorization, username validation, and silent skipping of unknown users."
spec_status: Completed
depends_on: [SPEC-050, SPEC-056, SPEC-051, SPEC-052, SPEC-036, SPEC-026, SPEC-028, SPEC-044]
arc: shared-connections
arc_order: 5
---

**Dependency notes:** SPEC-050 (Step Function, registry storage, orchestrator role perms incl. `AdminGetUser`/`ListUsers`/`AdminUpdateUserAttributes`), SPEC-056 (request contract, membership slots, actor binding/validate), SPEC-051 (create + cache/registry shapes), SPEC-052 (Connections tab — hosts the **Manage** entry point + roles/status), SPEC-036 (right slide-over `Drawer` pattern), SPEC-026 (dialog), SPEC-028 (Button/Input), SPEC-044 (`Toast`)
> **Reference:** `docs/shared-spaces-architecture.md` (§2 validate-then-grant; §3 membership tag; §4 registry as
> source of truth). Owner-only; all mutations go through the pipeline and are authorized server-side.

## Overview

Let the **owner** of a shared connection manage who has access. From a **Manage members** slide-out **drawer** (a
right slide-over opened by the **Manage** action on the Connections tab, SPEC-052, reusing the SPEC-036 `Drawer`) the
owner adds users by **username** — one at a time or in **bulk** (a list) — and removes them. Adds and removes are **requests**
enqueued to the pipeline; the Step Function authorizes the caller as the owner (against the registry), validates
each submitted username against the **Cognito User Pool**, **silently ignores unknowns**, and for each valid user
updates the registry membership list, assigns/clears that user's membership **slot** (`custom:shared_space_k`), and
updates that user's per-user cache. A non-owner can never manage members (the request fails server-side). All access
is to the **same** shared objects/tables — adding a member grants access, it never copies data.

## Scope

### In Scope

- A **Manage members** drawer (right slide-over, SPEC-036 `Drawer`; owner only), opened from the **Manage** action on
  the Connections tab (SPEC-052): shows current members (from the registry, via a read path), with **Add members** and
  **Remove** actions
- **Add members** — a single username or a **bulk** list (comma/space/newline-separated); enqueues an `add_members`
  request; **invalid/unknown usernames are ignored** (validated against the User Pool by the pipeline) and never
  appear in the member list
- **Remove members** — single or bulk; enqueues a `remove_members` request; removing a user revokes their slot + DB
  access + cache entry (the objects/tables remain — shared, not owned by the member)
- **Owner-only enforcement, server-side:** the Step Function verifies `registry[space].owner == actor`; a non-owner
  request **fails** with no effect (the UI also hides manage controls for non-owners, but the pipeline is the real
  gate)
- **Pipeline behavior** (provisioner `add_members` / `remove_members`): owner-auth; per username validate against the
  User Pool (`AdminGetUser`/`ListUsers`) → drop unknowns; for each valid add: registry `members += user`, assign the
  user's next free slot, LF is already granted to the shared role (no per-user LF needed — the slot tag is the gate),
  update the user's cache (`role:'member'`, `status:'active'`); for each remove: registry `members -= user`, clear the
  user's matching slot, remove the user's cache entry; **idempotent** (already-member add / already-absent remove are
  no-ops)
- **Slot-full on a target:** if an added user already holds 10 memberships, that user is **skipped with a recorded
  reason** (surfaced back) and the rest still process
- **Pending + result feedback:** adds/removes show pending and resolve on Refresh-connections (SPEC-052); the
  requester sees a summary (added N, ignored M unknown, skipped K at-limit)

### Out of Scope

- **Leaving** (member self-service) and **deleting** a space — SPEC-054
- **Self-add/remove of the owner** — the owner is implicitly a member and cannot be removed via this screen (owner
  changes ownership/deletes via SPEC-054); the owner cannot remove themselves here
- **Roles beyond owner/member** (no co-owners / granular permissions) — single owner model
- **Bulk file/table operations** — membership only; data is shared in place
- Real-time effect — a newly-added member gains access on **their** next token refresh (Refresh-connections,
  SPEC-052/§3)

---

## Functional Requirements

### FR-001: Manage-members drawer (owner)

#### Acceptance Criteria:

- [ ] For a connection the user **owns**, the **Manage** action on the Connections tab (SPEC-052) opens a right
  slide-over **drawer** (SPEC-036 `Drawer`: 440px, scrim, Escape/scrim/close-button dismiss, `role="dialog"`) that
  lists current members (usernames, owner marked) with **Add members** and per-member **Remove**; the **Manage**
  action / drawer is **absent for a non-owner**
- [ ] The member list is read from the **registry** (a read path the owner is permitted — owners may read their
  space's registry object; document the read grant) or from a pipeline-maintained owner-readable projection; a read
  error shows a Banner, not a crash

### FR-002: Add members (single + bulk) → request

#### Acceptance Criteria:

- [ ] **Add members** accepts a single username or a **bulk** list (split on commas/whitespace/newlines, de-duplicated,
  trimmed, lowercased to the username rule); client-side it drops obviously-malformed tokens (don't match the
  identifier rule) before sending, but **final validity is the pipeline's call**
- [ ] On submit it enqueues one `add_members` request `{ action:'add_members', actor, space, payload:{ members:[…] } }`
  (SPEC-050 contract); the browser makes no direct Glue/Cognito/LF/S3 call
- [ ] The UI shows a pending state and, on resolution (via Refresh), a summary: **added**, **ignored (unknown user)**,
  **skipped (at membership limit)** counts

### FR-003: Remove members (single + bulk) → request

#### Acceptance Criteria:

- [ ] **Remove** (single or multi-select/bulk) enqueues a `remove_members` request; removing revokes the target's
  access (slot cleared, cache entry removed) but **never deletes shared objects/tables**
- [ ] Removing the **owner** is not offered; attempting it (e.g. via a crafted request) fails server-side
- [ ] Idempotent: removing a non-member is a no-op success

### FR-004: Pipeline — owner auth + per-user validate + apply

#### Acceptance Criteria:

- [ ] The provisioner authorizes `actor == registry[space].owner`; a non-owner request **fails** with reason
  "not the owner" and **no** side effects (the real enforcement, independent of the UI)
- [ ] Each submitted username is validated against the **Cognito User Pool** (`AdminGetUser`/`ListUsers`); **unknown
  users are silently dropped** (not added, no error) per the user decision
- [ ] For each valid **add**: registry `members += user` (idempotent), assign the user's next free
  `custom:shared_space_k = space` slot (skip with a recorded "at limit" reason if none free), write the user's cache
  entry (`role:'member'`, `status:'active'`); the LF grant on the shared DB is to the **shared role** (already in
  place from SPEC-051) so no per-user LF grant is needed — the slot tag is the gate
- [ ] For each valid **remove**: registry `members -= user`, clear the user's matching slot
  (`AdminUpdateUserAttributes` empty), remove the user's cache entry
- [ ] The request records a terminal summary (added/ignored/skipped) and is **idempotent** on replay

### FR-005: Tests + lint

#### Acceptance Criteria:

- [ ] App: `npm run test` + `npm run lint` pass — manage screen is owner-only; add (single + bulk) parses/dedupes and
  enqueues one well-formed request; remove enqueues correctly and never offers the owner; summary renders
  added/ignored/skipped; no direct AWS mutation from the browser
- [ ] Pipeline (Python): non-owner request fails with no effect; unknown usernames dropped silently; valid add assigns
  a slot + registry + cache (and skips an at-limit target with a reason); remove clears slot + registry + cache and
  leaves objects/tables intact; replay idempotency — in `lambdas/shared-space-provisioner/` tests + the e2e doc

---

## Data Model

```jsonc
// add_members / remove_members request payload (SPEC-050 contract)
{ "action": "add_members", "actor": "alice", "space": "salesdata",
  "payload": { "members": ["bob", "cara", "typo_user"] } }

// Terminal request summary (recorded; surfaced to the requester)
{ "added": ["bob","cara"], "ignoredUnknown": ["typo_user"], "skippedAtLimit": [] }
```

Registry `members[]` and per-user `shared-connections.json` entries are the SPEC-050/051 shapes (unchanged).

## File & Folder Structure

```
apps/portal/src/features/shared-spaces/
├── ManageMembersDrawer.tsx          ← NEW: right slide-over (SPEC-036 Drawer) — member list + Add/Remove (owner only)
├── ManageMembersDrawer.test.tsx
├── AddMembersDialog.tsx             ← NEW: single + bulk input (parse/dedupe/validate-shape)
├── AddMembersDialog.test.tsx
├── useManageMembers.ts              ← enqueue add/remove + pending + summary
└── sharedSpaces.service.ts          ← + member read path (registry projection) if owner-readable

lambdas/shared-space-provisioner/
└── shared_space_provisioner.py      ← + add_members / remove_members (owner-auth, validate, apply)
```

## Implementation Phases

### Phase 1: Screen + add/remove requests

- `ManageMembersDrawer` (owner-only right slide-over, member list); `AddMembersDialog` (single + bulk parse);
  `useManageMembers` (enqueue add/remove, pending, summary) (FR-001–FR-003, FR-005 app)

#### Checkpoint

`npm run dev` as an owner: **Manage** on the Connections tab opens the members drawer listing members; Add (single + a
bulk paste) enqueues one well-formed `add_members` request; Remove enqueues `remove_members` and never targets the
owner; a non-owner has no Manage action/drawer. App tests/lint pass.

### Phase 2: Pipeline add/remove

- Provisioner `add_members`/`remove_members`: owner-auth, User-Pool validation (drop unknowns), slot assign/clear +
  registry + cache, at-limit skip, idempotency, summary (FR-004, FR-005 pipeline)

#### Checkpoint

A real Add grants a valid user (their slot/cache/registry update; after **their** token refresh they can query the
shared DB), silently ignores an unknown username, and skips an at-limit user with a reason; Remove revokes access and
leaves shared data intact; a non-owner request fails with no effect. e2e doc updated.

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** "valid user" = **exists in the Cognito User Pool**; unknowns are
  silently ignored and never appear in the member list (`shared-spaces-architecture.md` §9).
- [x] **Resolved (2026-06-21):** owner-only management is enforced **server-side** (registry owner-check); the UI
  gating is convenience, not the security boundary.
- [x] **Resolved (2026-06-21):** adding a member **grants access to the shared objects/tables in place** (single
  copy) — never a per-member copy.
- [x] **Resolved (2026-06-21, default):** the owner can **read** their space's registry member list (an
  owner-scoped read path) to render the screen; if a direct owner read is undesirable, the pipeline maintains an
  owner-readable members projection instead. Confirm which during design.
