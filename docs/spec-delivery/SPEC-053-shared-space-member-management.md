# Completed Spec — SPEC-053: Shared-Space Member Management (Owner)

The owner-side member management for shared connections: a Manage drawer to add/remove members, backed by two new pipeline verbs. Owner-only, enforced server-side. Delivered in two PRs (app → pipeline) + completion ritual.

## What was completed?

- **Owner-readable member projection (design decision):** the pipeline writes the current member list into the **owner's own** per-user cache entry (`members: string[]`); the drawer renders it via `useConnections` — **no admin-bucket registry read, no new IAM**. (The alternative — granting the portal role read on the admin-bucket registry — would have leaked every space's membership to every user.) Surfaced through `SharedConnectionEntry` + `Connection`.
- **App (Phase 1, [#117]):** `ManageMembersDrawer` (SPEC-036 `Drawer`, owner-only) — member list (owner marked, never removable), per-member **Remove** (SPEC-026 confirm), **Add members**; opened from a **Manage** action on active connections the user owns in `ConnectionsPage`. `AddMembersDialog` + `parseMemberInput` (`memberInput.ts`): single or bulk input (comma/space/newline), trimmed/lowercased/de-duped, malformed dropped, existing-members excluded. `useManageMembers` enqueues `add_members`/`remove_members` (`payload.members`) — the browser makes no direct AWS call. Add/remove show a pending toast and resolve on Refresh-connections.
- **Pipeline (Phase 2, [#118]):** provisioner `add_members` — per username validate against the User Pool (`AdminGetUser`; unknown → silently ignored), assign the next free `custom:shared_space_k` slot (none free → skipped "at limit"), write the member's cache entry (`role:member`, `active`), append to the registry. `remove_members` — clear the matching slot (empty), drop the member's cache entry, remove from the registry. Both do a registry members **RMW** (preserving owner/createdAt — not the create-only `_finalize`) and refresh the owner projection; `create` now seeds `members:[owner]`. Owner never added/removed; idempotent on replay; shared Glue DB/objects left intact.

Design decisions (asked + recorded): (1) member-list read = **owner cache projection**, not registry read; (2) feedback is **member-list-only** now — the added/ignored/at-limit summary is computed by the pipeline (returned/logged) but **not** surfaced in the UI; that lands with the notifications arc (058→060).

## What changed from earlier specs?

- **SPEC-051/052 cache shape:** `SharedConnectionEntry`/`Connection` gain optional `members[]` (owner-only projection); `useConnections` carries it through. **SPEC-052 `ConnectionsPage`:** gains the owner **Manage** action + drawer. **Provisioner (SPEC-056/051):** `add_members`/`remove_members` verbs implemented (were authorize-only stubs); `create` seeds the owner projection. **No IAM/infra change** — the orchestrator already had `AdminGetUser`/`AdminUpdateUserAttributes`/`ListUsers` and cross-user cache write (SPEC-050/056).

## Verification

`npm run lint` / `build` / `test` green — app tests cover parse/dedupe, owner-only Manage gating, drawer add/remove + confirm, single well-formed request, no direct AWS call. **23 provisioner tests** (script + CI ruff/pytest): add (slot+registry+member-cache+owner-projection), unknown-ignored, at-limit-skip, idempotent-existing, never-add-owner; remove (clear+registry+cache+projection, data intact), idempotent-non-member, never-remove-owner; handler owner-runs-verb + non-owner fails with no effect. e2e doc gains a SPEC-053 section (live checks). Frontend deploys with the app bundle; the Lambda deploys via `deploy-lambdas.yml`.
