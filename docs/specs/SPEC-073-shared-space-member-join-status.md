# Spec: Shared-Space Member Join Status (Pending / Active)

**ID:** SPEC-073
**Status:** Completed
**Last Updated:** 2026-07-03
**Depends On:** SPEC-053 (add/remove members + owner-readable member projection), SPEC-056 (membership-slot principal tag), SPEC-062 (control-plane verb Lambdas + `shared-space-common` layer), SPEC-051/050 (FIFO SQS → EventBridge Pipe → Step Function control plane)

> **Origin:** UI feedback (2026-06-30). The Manage-members surface should distinguish a member who has
> been *invited* (added by the owner, a valid user, but who has not yet picked up the space) from one who
> has actually *joined* (signed in since being added, so their scoped credentials now carry the membership
> tag). Today the system tracks no such distinction — `members` is a plain `string[]` and every added user
> is provisioned immediately and treated as equally active. Adding the distinction needs a new **join
> signal**, which is why this is its own spec rather than a UI tweak.

## Overview

When an owner adds members to a shared space, the control plane validates each username, assigns a
membership slot, writes the member's own cache entry, and appends the name to the owner's member
projection — all server-side and immediate (SPEC-053). But the new member's *credentials* only gain the
membership principal tag on their **next sign-in** (SPEC-056 ABAC), so until they sign in they cannot
actually open the space. From the owner's side this is invisible: every name in the list looks the same.

This spec adds a per-member **join status** so the Manage-members UI can show a **Pending** chip for an
invited-but-not-yet-joined member and an **Active** chip for one who has signed in and picked up the space —
mirroring the connection-level status chips on the Shared connections page. It gives owners an accurate
picture of who can actually use the space, and a clear signal that an invitee still needs to sign in.

## Scope

### In Scope

- A per-member `status: 'pending' | 'active'` field in the owner-readable member projection
  (`{owner}/user_settings/shared-connections.json`) and in the `Connection.members` shape the browser reads.
- `add-members` marks each newly-added member **`pending`** (already-active members are left unchanged;
  re-adding never demotes an active member back to pending).
- A **join acknowledgement** path: the first time a member's authenticated browser session successfully
  resolves a shared space it belongs to, it enqueues a control-plane `acknowledge_membership` request; the
  control plane flips that member's status to **`active`** in the owner's projection (idempotent).
- `ManageMembersDrawer` renders a **Pending** / **Active** status chip per member, reusing the
  `StatusBadge` pattern from the Shared connections page (dot + text, never color-only).
- A **Refresh** control in `ManageMembersDrawer` so the owner can manually re-pull member state (a
  pending → active flip lands asynchronously, after the member signs in and the ack processes), reusing the
  `RefreshConnectionsButton` pattern from the Shared connections page.
- The owner's card meta line may surface a pending count (e.g. "3 members · 1 pending") — optional polish.

### Out of Scope

- A Cognito **post-authentication trigger** as the join signal (see *Alternatives Considered*); the
  browser-ack approach is chosen to avoid a new auth-path Lambda. Revisit only if the browser ack proves
  unreliable.
- Notifying the owner when a member joins (could be a later notifications producer; not required here).
- Changing who can manage members, membership limits, or any IAM/access behavior — join status is
  **display + bookkeeping only**; access is already granted at add time (SPEC-053/056).
- Retroactively classifying members added before this ships — they are treated as `active` (back-compat;
  see FR-005).

---

## Functional Requirements

### FR-001: Per-member status in the projection

#### Description:
The owner-readable member projection stores each member with a join status. The browser data layer
(`useConnections`) surfaces it on `Connection.members`.

#### Acceptance Criteria:
- [ ] The projection persists members as `{ username: string; status: 'pending' | 'active' }` (or an
      equivalent shape that carries status per member) at `{owner}/user_settings/shared-connections.json`.
- [ ] `Connection.members` exposes the status to the UI (shape decided in Data Model below).
- [ ] A projection written before this spec (plain `string[]`) is read without error.

### FR-002: New members are added as Pending

#### Description:
`add-members` (SPEC-062 verb Lambda) marks each successfully-added, not-already-a-member user `pending`.

#### Acceptance Criteria:
- [ ] A user newly added by the owner appears with `status: 'pending'`.
- [ ] Re-adding a user who is already `active` does not demote them to `pending` (idempotent).
- [ ] `ignoredUnknown` / `skippedAtLimit` users are not written to the projection (unchanged behavior).

### FR-003: Join acknowledgement flips Pending → Active

#### Description:
The first time a member's authenticated browser resolves a shared space they belong to, the browser
enqueues an `acknowledge_membership` control-plane request; the control plane sets that member's status to
`active` in the **owner's** projection.

#### Acceptance Criteria:
- [ ] On resolving a usable shared connection where the signed-in user is a `member` (not owner), the
      browser enqueues exactly one `acknowledge_membership` request per space per session (deduped).
- [ ] The control plane verifies the actor (Cognito ID token → username, server-side) is actually a member
      of the space before flipping status (no spoofing a different user's status).
- [ ] Setting an already-`active` member to active is a no-op (idempotent, no spurious projection write).
- [ ] The owner sees the member as `active` after a Refresh once the ack has processed.

### FR-004: Manage-members UI shows the chip

#### Description:
`ManageMembersDrawer` renders a Pending/Active status chip per member row.

#### Acceptance Criteria:
- [ ] Each non-owner member row shows a chip: **Pending** (warning tone) or **Active** (success tone).
- [ ] The chip carries a text label (never color/dot only) — WCAG AA, matching the Shared connections
      `StatusBadge`.
- [ ] The owner row is unaffected (still shows the "Owner" pill).

### FR-006: Manual refresh of member state

#### Description:
A pending → active flip is asynchronous (it lands only after the member signs in and the ack processes), so
the owner needs a way to re-pull member state without leaving the drawer. `ManageMembersDrawer` gets a
**Refresh** control that re-reads the authoritative projection on demand, reusing the
`RefreshConnectionsButton` pattern (and the same `useConnections` refresh seam) from the Shared connections
page.

#### Acceptance Criteria:
- [ ] The drawer shows a Refresh control; activating it re-reads member state from the authoritative
      projection (forcing a credential refresh + cache re-read, as the Connections page Refresh does).
- [ ] A member who has acknowledged since the drawer opened flips from **Pending** to **Active** after a
      Refresh, with no full-page reload.
- [ ] The control shows a busy/disabled state while refreshing and is keyboard-operable + labelled (a11y).
- [ ] Refresh never mutates membership — it only re-reads (no add/remove side effects).

### FR-005: Backward compatibility

#### Description:
Members recorded before this spec ships (plain strings) must not break and must not all appear stuck as
Pending.

#### Acceptance Criteria:
- [ ] A legacy `members: string[]` entry is interpreted as all-`active` (they predate the pending concept).
- [ ] No migration job is required; the first projection write after this ships upgrades the shape.

---

## Data Model

```ts
// apps/portal/src/features/shared-spaces/sharedSpaces.types.ts
export type MemberStatus = 'pending' | 'active';

export type Member = {
  username: string;
  status: MemberStatus;
};

// SharedConnectionEntry.members widens from string[] to (string | Member)[] on read,
// normalized to Member[] by the read service (a bare string → {username, status:'active'}
// for FR-005 back-compat). query.types Connection.members follows the same Member[] shape.
```

```
# control-plane request (FIFO SQS body), mirrors the existing verb contract
{ "action": "acknowledge_membership", "actor": "<from ID token>", "space": "<space name>" }
```

---

## API / Interface Contract

- **Lambda:** new verb `shared-space-acknowledge-membership/` (single-task, uses the `shared-space-common`
  layer; reuses `validate-authorize` membership check). Wire into the Step Function `Choice(action)` map
  alongside the existing verbs (SPEC-062). Keeps the single shared `orchestrator` role.
- **add-members:** set status `pending` for newly-added users in `cache.write_owner_projection`.
- **Browser:** `features/shared-spaces` gains an `acknowledgeMembership(space)` enqueue (reusing the
  SPEC-051 SQS send seam) called from the file-space resolution path (`useFileSpace`) once per session per
  space for member-role connections.

## Environment Variables

None new (reuses the existing control-plane queue URL already configured for shared-space mutations).

## File & Folder Structure

```
lambdas/
└── shared-space-acknowledge-membership/
    ├── acknowledge_membership.py
    └── test_acknowledge_membership.py
apps/portal/src/features/shared-spaces/
├── sharedSpaces.types.ts        # MemberStatus, Member; widen members shape
├── sharedSpaces.service.ts      # normalize legacy string[] → Member[] on read
├── useAcknowledgeMembership.ts  # enqueue ack (once per session per space)
└── ManageMembersDrawer.tsx      # render Pending/Active chip + Refresh control per member
```

## Implementation Phases

### Phase 1: Data model + back-compat read
- Add `MemberStatus` / `Member`; widen `members` shape on `SharedConnectionEntry` and `Connection`.
- Normalize legacy `string[]` → `Member[]` (all `active`) in the read service; update tests.

### Phase 2: Control plane (Lambdas + Step Function)
- `add-members` writes new members as `pending`; never demotes an active member.
- New `acknowledge-membership` verb; wire into the Step Function `Choice(action)`; deploy-role / layer
  plumbing per the repo's Lambda code/infra split (`lambdas/info/best-practices/lambdas/lambdas.md`).

### Phase 3: Browser ack + UI
- `useAcknowledgeMembership` enqueue, called once per session per member-role space from `useFileSpace`.
- `ManageMembersDrawer` Pending/Active chip (reuse `StatusBadge` pattern) + a Refresh control (reuse
  `RefreshConnectionsButton` + the `useConnections` refresh seam, FR-006); optional owner-card pending count.

## Alternatives Considered

- **Cognito post-authentication trigger** records each sign-in and a reconciler marks the member active.
  More robust (server-side, no browser dependency) but adds an auth-path Lambda and a reconciliation step;
  deferred in favor of the browser ack, which reuses the existing control plane. Revisit if the browser ack
  proves unreliable (e.g. a member who only ever uses the Query workspace and never resolves the file space).
