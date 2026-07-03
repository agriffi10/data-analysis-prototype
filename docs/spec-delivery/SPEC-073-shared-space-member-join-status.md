# Completed Spec — SPEC-073: Shared-Space Member Join Status (Pending / Active)

## What was completed?

The Manage-members surface now distinguishes an **invited** member (added by the owner, a
valid user, but who hasn't signed in since being added) from one who has actually **joined**
(signed in, so their scoped credentials carry the membership tag). Each member in the
owner-readable projection carries a `pending`/`active` join status, surfaced as a status chip.
Shipped in **two PRs** (control plane, then browser/UI) per the infra-first split.

### PR 1 — control plane (Lambdas + infra)

- **Status model:** membership stays `members: string[]` in the registry (source of truth);
  join status is tracked out-of-band as `acknowledged: string[]`. `cache.write_owner_projection`
  now emits `members: [{username, status}]` — a member is `active` if they're the owner or in
  `acknowledged`, else `pending`. **Back-compat (FR-005):** `registry.effective_acknowledged`
  reads a legacy record (no `acknowledged` field) as all-non-owner-members-active; no migration.
- **add-members (FR-002):** new users are added but NOT to `acknowledged` → they project as
  `pending`; re-adding an already-active member never demotes. **remove/leave** prune the
  `acknowledged` set so a later re-add restarts at pending.
- **New `acknowledge-membership` verb** (`lambdas/shared-space-acknowledge-membership/`): flips
  a member pending → active by recording them in `acknowledged` + rewriting the owner projection.
  Idempotent (already-active = no write); member-only, owner-exempt, authorized in
  `validate-authorize` like `leave` (`config.VALID_ACTIONS` + an `auth.authorize` branch).
- **Infra:** verb added to the `shared_space_functions` map (auto-provisions
  function/log-group/ARN/invoke grant via the existing `for_each`), a `Choice(action)` branch +
  `AcknowledgeMembership` Task state in the orchestrator, and the `deploy-lambdas` CI matrix.
  **No new deploy-role IAM** — the new function/log-group match the existing `*-shared-space-*`
  wildcards; no new resource type.

### PR 2 — browser data layer + UI

- **Types/service:** `MemberStatus`/`Member` added; `SharedConnectionEntry.members` and
  `Connection.members` widen from `string[]` to `Member[]`; `SharedSpaceAction` gains
  `acknowledge_membership`. The read service normalizes on parse — a legacy bare string →
  `{username, status:'active'}` (FR-005), a well-formed object passes through, malformed dropped.
- **`useAcknowledgeMembership`** (`features/shared-spaces/`): fired from `FilesPage` (the
  file-space resolution path); when the active space is an `active` shared connection where the
  user is a `member` (not owner), enqueues exactly one `acknowledge_membership` per space per
  browser session (sessionStorage dedup, set before the async send).
- **`ManageMembersDrawer` (FR-004/FR-006):** a Pending (warning) / Active (success) chip per
  member row — dot + **text label** (never color-only, WCAG AA), mirroring the Connections
  `StatusBadge`; a **Refresh** control reusing `RefreshConnectionsButton` + the `useConnections`
  refresh seam. `ConnectionsPage` now tracks the managed space by **name** and re-derives the
  drawer's row from the live `rows`, so a Refresh that lands a pending→active flip updates the
  open drawer without reopening. Owner-card meta line gains a `· N pending` count.

## What changed from earlier specs?

- The SPEC-053 owner projection member shape changed from `string[]` to `[{username, status}]`
  (registry membership handling is unchanged — status is a separate `acknowledged` list).
- The shared-space control plane gained its seventh verb; the single shared `orchestrator` role
  is unchanged (SPEC-062 FR-005 decision holds).
- No change to who can manage members, membership limits, or any IAM/access behavior — join
  status is display + bookkeeping only; access is still granted at add time (SPEC-053/056).

## Verification

`pytest lambdas/` = **228 passed** (new `test_acknowledge_membership.py` + updated projection-
shape assertions across create/add/remove/leave/common); `ruff check lambdas/` clean;
`tofu validate` clean; state-machine template renders valid JSON (11 states). SPA:
`vitest run` = **865 passed** (new service-normalization + `useAcknowledgeMembership` +
drawer chip/Refresh tests), `tsc --noEmit` clean, `prettier --check` clean, production build
clean. A fresh-context review of PR 1 confirmed FR-001/002/003/005 correct with no material
defects. The Manage drawer is Cognito-gated (not reachable in the dev-unauth preview); its
rendering is covered by unit tests, and PR 1's control plane deployed green to AWS before PR 2.
