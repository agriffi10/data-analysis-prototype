---
type: Spec
id: SPEC-075
title: "Read-Only Member Roster for Shared-Connection Members"
description: "Lets every member of a shared connection see a read-only roster of all members, with the owner tagged and listed first and no add or remove controls, reversing the earlier owner-only visibility."
spec_status: Completed
depends_on: [SPEC-053, SPEC-056, SPEC-062, SPEC-073]
---

**Dependency notes:** SPEC-053 (owner member management), SPEC-056 (access model + registry), SPEC-062 (decomposed control plane), SPEC-073 (per-member join status)
> **Implementation note (2026-07-03).** This spec's Data Model says the roster is `members: string[]`, written
> before SPEC-073 shipped per-member join status. SPEC-073 changed the owner projection (and the frontend
> `SharedConnectionEntry.members`) to `Member[]` (`{username, status}`). So the member roster is implemented as
> the **same `Member[]` projection the owner sees** — members see each person's Active/Pending chip too (user-
> confirmed) — reusing `cache._member_projection` and a shared `MembersList` component. `write_roster_to_all`
> takes `acknowledged` so it can compute status. Acknowledge-membership still updates only the owner projection
> (fan-out is scoped to add/remove/leave per FR-002), so a peer's status in a member's roster is refreshed on the
> next membership change — eventually consistent, as the spec intends.

## Overview

Today only the **owner** of a shared connection can see who belongs to it — the
owner's cache entry carries a `members[]` roster (rendered in the owner-only
Manage members drawer), while a member's cache entry carries only the owner's
name. SPEC-053 deliberately withheld the roster from members "for privacy". Per
user feedback (2026-06-30) that decision is being reversed: **every member of a
shared connection should be able to see a read-only roster of all members**,
presented like the owner's Manage members pane — the owner denoted with a tag and
always listed first — but with no add/remove affordances. This makes shared
connections legible to the people using them ("who else can see this data?")
without granting members any management power.

## Scope

### In Scope

- Populate the full member roster into **every member's** per-user cache entry
  (`{username}/user_settings/shared-connections.json`), not just the owner's.
- Fan out roster updates to all remaining members whenever membership changes
  (add / remove / leave), so each member's cache stays current.
- A **read-only** members view available to members from the Connections page
  (owner tagged + listed first, alphabetical thereafter), reusing the owner
  drawer's presentation.
- Reuse of the existing `SharedConnectionEntry.members` field (already optional on
  the frontend type) — now populated for member entries too.
- Tests: control-plane (common layer + verb Lambdas) and frontend (component +
  a11y).

### Out of Scope

- Any member management power for non-owners (add/remove/rename/delete stay
  owner-only — SPEC-053/054 unchanged).
- Changing the authoritative registry shape (it already holds `members[]`).
- Per-verb IAM roles or new IAM grants — the shared `orchestrator` role already
  has `s3:PutObject` on every user's cache key (`*/user_settings/shared-connections.json`).
- New notifications (SPEC-061 lifecycle events unchanged).
- Real-time roster updates — the roster is eventually-consistent, refreshed on the
  existing Connections refresh / poll, same as the owner's view today.
- Roles beyond `owner` / `member`.

---

## Functional Requirements

### FR-001: Member cache entries carry the full roster

#### Description:

The `shared-space-common` cache layer must write the full member roster into a
member's cache entry, mirroring the owner projection. Add a helper that writes a
member entry including `members: string[]` (the same roster the owner gets), the
`owner` name, `status`, and `createdAt`.

#### Acceptance Criteria:

- [ ] `write_member_entry(...)` (or a successor helper) writes `members` (full
      roster, order not significant) in addition to the existing `owner`,
      `role: 'member'`, `status`, `createdAt` fields.
- [ ] The write remains a compare-and-swap upsert by `name` (unchanged concurrency
      semantics; ETag retry preserved).
- [ ] The owner projection (`write_owner_projection`) is unchanged.

### FR-002: Membership changes fan out the roster to all remaining members

#### Description:

When the membership of a space changes, every **remaining** member's cache entry
must be updated with the new roster — not just the owner's (as today). This
applies to `add_members`, `remove_members`, and `leave`. Provide a single common
helper (e.g. `write_roster_to_all(members, name, owner, created_at)`) that writes
the owner projection and each member entry so the three verbs share one code path.

#### Acceptance Criteria:

- [ ] **add-members:** after adding, every current member (existing + newly added)
      and the owner have a cache entry reflecting the new full roster.
- [ ] **remove-members:** removed members' entries are deleted (unchanged); every
      **remaining** member and the owner reflect the reduced roster.
- [ ] **leave:** the leaving member's entry is deleted (unchanged); every remaining
      member and the owner reflect the reduced roster.
- [ ] **create-space:** the creator's owner entry has `members: [creator]`
      (unchanged); no member fan-out needed (no other members yet).
- [ ] **delete-space:** all entries removed (unchanged).
- [ ] Each per-user write is independently CAS-safe; a failure writing one
      member's cache does not abort the others (best-effort fan-out, logged), and
      the verb still reports success for the registry mutation.
- [ ] Fan-out is bounded by the membership cap (≤ the slot limit, currently 10),
      so a change writes at most ~N member caches.

### FR-003: Members can open a read-only roster from the Connections page

#### Description:

On the Connections page, an **active member** card exposes a "View members" action
that opens a read-only roster: all members listed, the owner denoted with an
"Owner" tag and always first, the rest alphabetical. No add/remove/Manage
controls are shown to members.

#### Acceptance Criteria:

- [ ] A member (role `member`, status `active`) sees a "View members" affordance on
      the connection card; an owner continues to see "Manage" (unchanged).
- [ ] The roster view lists every member; the owner is tagged and appears first,
      others alphabetical.
- [ ] The member roster view has **no** add-member input and **no** per-member
      remove buttons (read-only).
- [ ] If the member's cache entry predates this spec and has no `members` (legacy
      entry), the view shows a non-blocking "not available yet — refresh after the
      next membership change" message (reuse the SPEC-053 `unavailable` pattern);
      it never crashes.
- [ ] The owner's Manage members drawer is unchanged (still read-write).

### FR-004: Backfill of existing member entries

#### Description:

Existing member cache entries written before this spec lack `members`. Rather than
a bespoke migration job, the next membership change on a space heals all members'
entries via FR-002's fan-out. Legacy entries render the FR-003 "not available yet"
state until then.

#### Acceptance Criteria:

- [ ] No standalone migration Lambda/job is introduced.
- [ ] After any add/remove/leave on a space, every remaining member's entry has
      `members` populated.
- [ ] A legacy member entry (no `members`) renders the read-only view's
      "not available yet" state without error.

---

## Data Model

```ts
// apps/portal/src/features/shared-spaces/sharedSpaces.types.ts (existing — no shape change)
// `members` is already optional; this spec populates it for member entries too.
export type SharedConnectionEntry = {
  name: string;
  role: 'owner' | 'member';
  status: 'provisioning' | 'active' | 'failed' | 'leaving' | 'deleting';
  reason?: string;
  members?: string[]; // OWNER always; MEMBER now too (SPEC-075). Absent on legacy member entries.
  createdAt?: string;
  owner?: string; // MEMBER entries: the owner's username.
};
```

```python
# lambdas/shared-space-common/cache.py — helpers
def write_member_entry(member, name, owner, members, created_at=None): ...  # + members
def write_roster_to_all(members, name, owner, created_at=None):
    """Write the owner projection + every member entry with the full roster."""
    ...
```

The authoritative roster is `registry["members"]`, already loaded by
`validate-authorize` and passed to each verb — no new registry read is needed.

---

## API / Interface Contract

No new browser-facing service is required: members already read their cache via
`readSharedConnectionsCache()` / `useConnections`. The new data (`members` on
member entries) flows through the existing read path. The frontend adds a
presentational read-only roster component (extracted from / shared with
`ManageMembersDrawer`).

## File & Folder Structure

```
lambdas/
├── shared-space-common/
│   └── cache.py                      # + members on member entries, write_roster_to_all
├── shared-space-add-members/add_members.py    # fan out roster to all members
├── shared-space-remove-members/remove_members.py  # fan out to remaining members
└── shared-space-leave/leave.py       # fan out to remaining members

apps/portal/src/features/shared-spaces/
├── MembersList.tsx                   # shared presentational roster (owner tagged + first)
├── MembersList.test.tsx
├── MemberRosterDrawer.tsx            # read-only view for members (reuses MembersList)
├── MemberRosterDrawer.test.tsx
├── ManageMembersDrawer.tsx           # refactored to reuse MembersList (owner: read-write)
└── ConnectionsPage.tsx               # "View members" on active member cards
```

## Implementation Phases

### Phase 1: Control-plane roster fan-out

- Extend `cache.write_member_entry` to include `members`; add `write_roster_to_all`.
- Update `add_members`, `remove_members`, `leave` to fan out the roster to all
  (remaining) members + owner via the shared helper; keep best-effort + CAS.
- Common-layer + verb unit tests (roster present for members; removed/leaving
  entries deleted; best-effort on single-write failure).

### Phase 2: Read-only member roster UI

- Extract a shared `MembersList` presentational component (owner tagged + first,
  alphabetical); refactor `ManageMembersDrawer` to use it (behavior unchanged).
- Add `MemberRosterDrawer` (read-only) + a "View members" action on active member
  cards in `ConnectionsPage`.
- Handle the legacy "no members / not available yet" state.
- Component + a11y tests (WCAG AA: focus trap, labelling — reuse Drawer primitive).

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory row (MembersList), and the
  one-line Key Decisions update noting SPEC-053's member-privacy stance is
  reversed (members now see a read-only roster).
