# Completed Spec — SPEC-075: Read-Only Member Roster for Shared-Connection Members

## What was completed?

Every member of a shared connection can now see a **read-only roster of all members** (owner tagged + first,
others alphabetical, each with a join-status chip) — reversing SPEC-053's member-privacy stance. No management
power is granted to non-owners.

**Control plane** (`shared-space-common/cache.py` + verbs):
- `write_member_entry(...)` now writes the full `{username, status}` roster (via the existing
  `_member_projection`), plus `owner`/`createdAt`.
- New `write_roster_to_all(members, name, owner, acknowledged, created_at)` — writes the owner projection + every
  member's entry with the current roster; **best-effort per member** (one cache write failing is logged, never
  aborts the rest; the registry mutation already committed).
- `add-members`, `remove-members`, `leave` fan out via `write_roster_to_all` (replacing their lone owner-
  projection write). `create` / `acknowledge-membership` unchanged. Removed/leaving entries still deleted.

**Frontend** (`features/shared-spaces/`):
- Extracted a shared `MembersList` (owner tagged + first, alphabetical, status chip; optional `onRemove` →
  read-write). `ManageMembersDrawer` refactored to use it (behavior unchanged).
- New read-only `MemberRosterDrawer` (reuses `MembersList`, Refresh, legacy "not available yet" note).
- `ConnectionsPage`: a **View members** action on active member cards opens the roster (NAME-tracked like
  Manage, so a Refresh keeps the open drawer in sync).

**Deliberate deviations:** the roster is `Member[]` (with status), not the spec's `string[]` — SPEC-073 shipped
join status after 075 was authored, so the roster matches the owner's `Member[]` projection (user-confirmed;
see the spec header note). Backfill is fan-out-on-next-change (FR-004) — no migration job; legacy entries show
the "not available yet" note until then.

**Docs sweep (process step 6):** updated the Help & guides "See who has access and their status" guide — the
member list is now reached via **Manage** (owner) or **View members** (member), not owner-only.

## What changed from earlier specs?

`cache.write_member_entry` signature gained `members` + `acknowledged` (only internal callers). `ManageMembersDrawer`
now delegates its list rendering to `MembersList` (the local `Avatar`/`MemberStatusBadge` moved there). No IAM/infra
change — the orchestrator role already has `s3:PutObject` on every user's cache key.

## Verification

Python: common layer + add/remove/leave verb tests updated/added (roster fan-out to existing + remaining members,
best-effort on a single-member failure) — all shared-space verb suites green. Frontend: `format:check`, `tsc`,
ESLint, `build` clean; full Vitest **892 passed** (+11: `MembersList`, `MemberRosterDrawer` incl. axe, ConnectionsPage
View-members + legacy-note). Live browser deferred (the Connections roster is Cognito-gated on real shared-space
membership — same limitation as SPEC-052/053/073), covered by component + a11y + integration tests instead.
