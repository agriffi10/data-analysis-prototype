# Spec: Notifications UI (Header Button + Slide-out Panel)

**ID:** SPEC-060
**Status:** Draft
**Last Updated:** 2026-06-22
**Depends On:** SPEC-059 (notifications data layer: `useNotifications`), SPEC-028 (`IconButton`/`Badge`), SPEC-036 (`Drawer`), SPEC-038/042 (`Pager` + client-side pagination pattern), SPEC-044/049 (`Toast`)

> **Third of the notifications arc (058 → 059 → 060).** This spec is **UI only** — it adds the header
> notifications **bell button** (left of the username) with an **unread indicator**, a right **slide-out
> Drawer** listing notifications with a per-row unread marker, **8/page Prev/Next pagination**, and the
> **mark-read / mark-all-read / delete / delete-all** controls wired to the SPEC-059 hook. It reuses the
> existing `Drawer`, `Pager`, `IconButton`, `Toast`, and `ConfirmDialog` primitives; it adds no services,
> no IAM, no infra. All mutations are optimistic via `useNotifications` (the write is the SPEC-058 pipeline).

## Overview

Surface notifications in the authenticated shell. A bell button sits in the header user-zone, immediately to
the left of the username, carrying a small indicator when there are unread notifications. The read is
prefetched on app load (SPEC-059 FR-005) so the indicator is correct and the first open is instant. Clicking
the bell opens a right slide-out panel that lists the user's notifications newest-first, 8 per page with
Prev/Next; unread rows carry a visual marker (the same accent-dot language as the active query tab). From the
panel the user can mark a single notification read, mark all read, delete one, or delete all — each action
updates the view instantly (optimistic) and is applied asynchronously by the write pipeline. Destructive
actions (delete, delete all) confirm first; failures surface a toast and roll back.

## Scope

### In Scope

- **Header bell button** in `Header.tsx`, placed **left of `{user.username}`** in the authenticated
  user-zone; an `IconButton` (bell icon) with an aria-label that includes the unread count; an **unread
  indicator** (accent dot / small `Badge`) shown when `hasUnread`.
- **Notifications slide-out** — a right `Drawer` (reuse SPEC-036), titled "Notifications", opened from the
  bell, closed via the Drawer's close button / Escape / backdrop.
- **Notification list + per-row unread marker** — newest-first; each row shows the message, a relative
  timestamp (reuse `formatRelativeTime`), and an **unread marker** (accent dot, mirroring the active
  query-tab indicator); read rows are visually de-emphasized.
- **Pagination** — client-side **8/page Prev/Next** over the full in-memory list using the shared `Pager`
  (mirrors SPEC-042 history: `"1–8 of N"`, newest-first, reset-to-first-page on open / on list change).
- **Per-row actions** — **mark read** (on an unread row) and **delete** (with confirm).
- **Bulk actions** — **Mark all read** and **Delete all** (with confirm) in the Drawer header/footer;
  disabled when empty / when nothing is unread (mark-all).
- **States** — empty ("You're all caught up"), loading, and error states in the panel (match history/saved-
  queries panel conventions).
- **Optimistic feedback** — actions update the list + indicator instantly via `useNotifications`; a failed
  enqueue rolls back and shows a danger `Toast`.
- **Accessibility** — the panel and indicator follow the SPEC-045 axe baseline; the unread indicator is not
  color-only (aria-label / visually-hidden text conveys unread state + count); co-located `*.a11y.test.tsx`.
- **Design pass** — the panel + bell get a design treatment consistent with the drawer family
  (`docs/design/` + design-system.md), before/at implementation (as other UI specs did).

### Out of Scope

- The read service, enqueue helpers, hook, SQS client, types (all **SPEC-059**); the write pipeline + IAM
  (all **SPEC-058**).
- Creating notifications from the UI (`create` is trusted-producer-only — SPEC-058 FR-006).
- Realtime/push updates or auto-poll while the panel is open — the panel reflects the prefetched read +
  manual `refresh()` + post-action reconcile from SPEC-059. (A Refresh control is allowed, reusing the
  history Refresh pattern, but live push is out of scope.)
- Per-notification deep-links / actions beyond read/delete (notifications are plain messages this arc).

---

## Functional Requirements

### FR-001: Header bell button + unread indicator

#### Description:

A bell control in the header user-zone, left of the username, signaling unread state.

#### Acceptance Criteria:

- [ ] In `Header.tsx`, the authenticated user-zone renders an `IconButton` (bell) **before** the
  `{user.username}` span (order: bell → username → avatar → Sign out).
- [ ] When `hasUnread` (SPEC-059), an **indicator** (accent dot or count `Badge`) is shown on/by the bell;
  when there are no unread, no indicator.
- [ ] The button's accessible name conveys state, e.g. `"Notifications, 3 unread"` / `"Notifications, none
  unread"` (the indicator is **not** color-only — FR-007).
- [ ] The bell is only rendered when `status === 'authenticated'`; it uses the prefetched read so the
  indicator is correct on first paint (SPEC-059 FR-005).

### FR-002: Open/close the slide-out panel

#### Acceptance Criteria:

- [ ] Clicking the bell opens a right `Drawer` (SPEC-036) titled "Notifications"; clicking again / the
  Drawer close button / Escape / backdrop closes it.
- [ ] Opening the panel resets the pager to the **first (newest) page** (FR-004); focus moves into the
  panel (Drawer focus-trap) and returns to the bell on close.
- [ ] The panel coexists with other drawers (history/saved-queries) without conflict (one drawer concern at
  a time is acceptable; document if they can stack).

### FR-003: Notification list + per-row unread marker

#### Acceptance Criteria:

- [ ] Rows render newest-first: message text, relative timestamp (`formatRelativeTime`), and an **unread
  marker** (accent dot, same visual language as the active query tab) on unread rows; read rows are
  de-emphasized (no marker).
- [ ] Each unread row has a **Mark read** affordance; each row has a **Delete** affordance (icon button with
  aria-label). Read rows show no Mark-read control.
- [ ] Long messages wrap/truncate gracefully; the row is keyboard-operable and screen-reader-labeled.

### FR-004: Pagination (8/page, Prev/Next)

#### Acceptance Criteria:

- [ ] The list is paginated **client-side, 8 per page**, using the shared `Pager` (Prev / `"X–Y of N"` /
  Next), newest-first — mirroring SPEC-042 history pagination.
- [ ] Prev is disabled on the first page; Next on the last; the range label is accurate; an empty list shows
  the empty state (no pager).
- [ ] The page resets to the first page when the panel opens and when the list identity changes (after a
  delete/delete-all/reconcile), without stranding the user on an out-of-range page.

### FR-005: Per-item actions (mark read, delete)

#### Acceptance Criteria:

- [ ] **Mark read** on an unread row calls `useNotifications.markRead(id)`: the row's marker clears
  instantly (optimistic) and `unreadCount`/indicator update; on enqueue failure it rolls back + danger
  `Toast`.
- [ ] **Delete** on a row opens a `ConfirmDialog` (SPEC-026 pattern); confirming calls `remove(id)`: the row
  disappears instantly (optimistic), pager range updates; on failure it rolls back + danger `Toast`.
- [ ] Actions are non-blocking (the panel stays usable); an in-flight action does not double-fire on rapid
  clicks.

### FR-006: Bulk actions (mark all read, delete all)

#### Acceptance Criteria:

- [ ] **Mark all read** calls `markAllRead()`: all markers clear + indicator clears instantly; disabled when
  `unreadCount === 0`.
- [ ] **Delete all** opens a `ConfirmDialog` (danger, irreversible line); confirming calls `removeAll()`:
  list empties → empty state, indicator clears; disabled when the list is empty.
- [ ] Both reflect optimistic update + rollback-on-failure (danger `Toast`), consistent with FR-005.

### FR-007: Accessibility + states

#### Acceptance Criteria:

- [ ] Empty ("You're all caught up"), loading, and error states render in the panel (match history/saved-
  queries conventions); the error state offers a retry/`refresh()`.
- [ ] The unread indicator conveys state non-visually (aria-label / visually-hidden text with the count); the
  panel passes the SPEC-045 axe baseline (`*.a11y.test.tsx` for the panel + the header bell).
- [ ] All interactive controls are keyboard reachable and labeled; the Drawer's focus-trap + Escape behavior
  is preserved (nested ConfirmDialog yields Escape correctly — `Drawer.closeOnEscape`).

---

## Data Model

No new types — consumes `Notification` + `useNotifications` from SPEC-059. UI-local state only:

```ts
// NotificationsDrawer.tsx (local)
const PAGE_SIZE = 8;                 // FR-004 (mirrors SPEC-042's history page constant)
const [pageIndex, setPageIndex] = useState(0);
const [confirming, setConfirming] = useState<{ kind: 'one'; id: string } | { kind: 'all' } | null>(null);
```

## API / Interface Contract

Component surface (presentational; the workspace/shell owns the hook, mirroring the history/saved-queries
split):

```tsx
// NotificationsBell.tsx — header control
type NotificationsBellProps = {
  hasUnread: boolean;
  unreadCount: number;
  onOpen: () => void;
};

// NotificationsDrawer.tsx — the slide-out
type NotificationsDrawerProps = {
  open: boolean;
  onClose: () => void;
  notifications: Notification[];
  isLoading: boolean;
  isError: boolean;
  onRefresh: () => void;
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onDelete: (id: string) => void;
  onDeleteAll: () => void;
};
```

## Environment Variables

None (the queue URL var is introduced in SPEC-059).

## File & Folder Structure

```
apps/portal/src/
├── components/
│   └── icons.tsx                              # + BellIcon (shared inline SVG, no icon lib)
├── features/
│   └── notifications/
│       ├── NotificationsBell.tsx              # header bell + indicator (FR-001)
│       ├── NotificationsBell.test.tsx
│       ├── NotificationsDrawer.tsx            # slide-out: list + pager + bulk actions (FR-002/004/006/007)
│       ├── NotificationsDrawer.test.tsx
│       ├── NotificationRow.tsx                # one row: marker + message + time + actions (FR-003/005)
│       ├── NotificationRow.test.tsx
│       ├── NotificationsDrawer.a11y.test.tsx  # SPEC-045 axe baseline (FR-007)
│       └── index.ts                           # barrel adds the UI exports
└── components/Header.tsx                       # mount the bell + own open state + the hook (FR-001/002)
```

## Implementation Phases

### Phase 1: Bell + indicator + open/close

- `BellIcon`; `NotificationsBell`; mount in `Header.tsx` left of the username, wire `useNotifications`
  (read + `hasUnread`/`unreadCount`) and the Drawer open state; empty Drawer shell opens/closes
  (FR-001/002). a11y for the bell.

#### Checkpoint

Bell appears left of the username; the indicator shows only when there are unread (seed via the SPEC-059
hook/mock); clicking opens/closes the panel; bell aria-name reflects the count; `NotificationsBell.test.tsx`
+ a11y green.

### Phase 2: List + pagination + per-row marker

- `NotificationRow` (marker, time, mark-read/delete affordances); `NotificationsDrawer` list + `Pager`
  8/page + empty/loading/error states; reset-to-first-page on open / list change (FR-003/004/007).

#### Checkpoint

Panel lists notifications newest-first, 8/page with working Prev/Next + accurate range; unread rows show the
marker; empty/loading/error states render; tests green incl. `NotificationsDrawer.a11y.test.tsx`.

### Phase 3: Actions (optimistic + confirm + toast)

- Wire mark-read / delete (confirm) / mark-all-read / delete-all (confirm) to the hook mutations; optimistic
  update + rollback + danger `Toast` on failure; disabled-state rules (FR-005/006).

#### Checkpoint

Each action updates the list + indicator instantly; delete / delete-all confirm first; a simulated enqueue
failure rolls back and shows a toast; mark-all disabled with zero unread, delete-all disabled when empty.
All notifications-feature tests green; `npm run lint`/`test`/`build -w apps/portal` clean.

## Open Questions

- [ ] **Indicator style:** a plain accent **dot** (presence only) or a **count Badge** on the bell? Default:
  dot for presence + the count in the aria-label; revisit if product wants a numeric badge.
- [ ] **Refresh control in the panel:** include a Refresh button (reuse the SPEC-046 history pattern) so the
  user can pull writer-applied changes without reload? Default: yes, small Refresh in the panel header.
- [ ] **Drawer stacking:** can the notifications panel open while the query history/saved-queries drawer is
  open, or is one-drawer-at-a-time enforced? Confirm during the design pass.
- [ ] **Read-on-open:** should opening the panel auto-mark-all-read, or only explicit actions? Default:
  **no** auto-read — the user explicitly marks read (preserves the unread inbox model).
