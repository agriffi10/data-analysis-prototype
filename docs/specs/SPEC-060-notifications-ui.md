---
type: Spec
id: SPEC-060
title: "Notifications UI (Header Bell Link + Notifications Page)"
description: "Adds a header bell link with an unread indicator and a Notifications page listing the user's notifications newest first, 10 per page, where users can mark one or all as read."
spec_status: Completed
depends_on: [SPEC-059, SPEC-008, SPEC-028, SPEC-038, SPEC-042, SPEC-044, SPEC-049, SPEC-031]
arc: notifications
arc_order: 3
---

**Dependency notes:** SPEC-059 (notifications data layer: `useNotifications`), SPEC-008 (auth-gated layout + react-router routes), SPEC-028 (`IconButton`/`Badge`), SPEC-038/042 (`Pager` + client-side pagination pattern), SPEC-044/049 (`Toast`), SPEC-031 (document title management)
> **Third of the notifications arc (058 → 059 → 060 → 061).** This spec is **UI only** — it makes the
> header notifications **bell a link** (left of the username, with an **unread indicator**) to a brand-new
> **`/notifications` page** inside the authenticated dashboard. The page lists notifications newest-first
> with a per-row unread marker, **10/page Prev/Next pagination**, and **mark-read / mark-all-read** controls
> wired to the SPEC-059 hook. The bell's indicator is kept fresh by the SPEC-059 **60-second background
> poll**. There is **no slide-out drawer and no delete** — notifications are only ever marked read. It
> reuses `IconButton`/`Badge`/`Pager`/`Toast`; it adds no services, no IAM, no infra.

## Overview

Surface notifications in the authenticated shell as a first-class page. A bell sits in the header user-zone,
immediately to the left of the username, carrying a small indicator when there are unread notifications; the
indicator is driven by the SPEC-059 read + its 60-second background poll, so it stays current even while the
user sits on another page. The bell is a **link** — clicking it navigates to a dedicated `/notifications`
page (it is **not** a slide-out panel, and it is **not** added to the main tab bar of Files | Query |
Connections). The page lists the user's notifications newest-first, 10 per page with Prev/Next; unread rows
carry a visual marker (the same accent-dot language as the active query tab). From the page the user can mark
a single notification read or mark all read — each action updates the view instantly (optimistic) and is
applied asynchronously by the SPEC-058 write pipeline. Notifications are never deleted.

## Scope

### In Scope

- **Header bell link** in `Header.tsx`, placed **left of `{user.username}`** in the authenticated user-zone;
  an `IconButton`-styled **link** (react-router `Link`/`NavLink` to `/notifications`, bell icon) with an
  aria-label that includes the unread count; an **unread indicator** — a plain **accent dot** (presence only;
  **not** a numeric `Badge` in v1), with the count carried in the aria-label — shown when `hasUnread`.
  Active-route styling when on `/notifications`.
- **`/notifications` route + `NotificationsPage`** — a new authenticated route (under the SPEC-008
  auth-gated layout) rendering a page-level route component (`default` export per convention) that owns the
  `useNotifications(username)` hook. Sets the document title (SPEC-031).
- **Notification list + per-row unread marker** — newest-first; each row shows the message, a relative
  timestamp (reuse `formatRelativeTime`), and an **unread marker** (accent dot, mirroring the active
  query-tab indicator); read rows are visually de-emphasized.
- **Pagination** — client-side **10/page Prev/Next** over the full in-memory list using the shared `Pager`
  (mirrors SPEC-042 history: `"1–10 of N"`, newest-first, reset-to-first-page on list change).
- **Per-row action** — **Mark read** (on an unread row).
- **Bulk action** — **Mark all read** in the page header; disabled when nothing is unread.
- **Refresh** — a Refresh control (reuse the SPEC-046 history pattern) to pull writer-applied changes on
  demand, in addition to the SPEC-059 background poll.
- **States** — empty ("You're all caught up"), loading, and error states on the page (match
  history/saved-queries panel conventions; error offers a retry/`refresh()`).
- **Optimistic feedback** — actions update the list + indicator instantly via `useNotifications`; a failed
  enqueue rolls back and shows a danger `Toast`.
- **Accessibility** — the page and indicator follow the SPEC-045 axe baseline; the unread indicator is not
  color-only (aria-label / visually-hidden text conveys unread state + count); co-located `*.a11y.test.tsx`.
- **Design pass** — the page + bell get a design treatment consistent with the existing pages
  (`docs/design/` + design-system.md), before/at implementation (as other UI specs did).

### Out of Scope

- The read service, enqueue helpers, hook, SQS client, types, and the background poll itself (all
  **SPEC-059**); the write pipeline + IAM (all **SPEC-058**); the shared-workspace producer (**SPEC-061**).
- **Deleting notifications** — there is no delete / delete-all anywhere in the UI (notifications are only
  marked read).
- **A slide-out drawer** — superseded; notifications live on a full routed page now.
- **Adding Notifications to the main tab bar** — the page is reached via the header bell link only (product
  decision, 2026-06-27).
- Creating notifications from the UI (`create` is trusted-producer-only — SPEC-058).
- Realtime/push updates beyond the SPEC-059 60-second poll + manual `refresh()` + post-action reconcile.
- Per-notification deep-links / actions beyond mark-read (notifications are plain messages this arc).

---

## Functional Requirements

### FR-001: Header bell link + unread indicator

#### Description:

A bell control in the header user-zone, left of the username, that links to the notifications page and
signals unread state.

#### Acceptance Criteria:

- [ ] In `Header.tsx`, the authenticated user-zone renders a bell **link** (react-router) to
  `/notifications`, positioned **before** the `{user.username}` span (order: bell → username → avatar →
  Sign out).
- [ ] When `hasUnread` (SPEC-059), an **accent-dot indicator** (presence only — no numeric count rendered)
  is shown on/by the bell; when there are no unread, no indicator.
- [ ] The link's accessible name conveys state, e.g. `"Notifications, 3 unread"` / `"Notifications, none
  unread"` (the indicator is **not** color-only — FR-006).
- [ ] The bell is only rendered when `status === 'authenticated'`; it uses the prefetched + polled read
  (SPEC-059 FR-005/FR-006) so the indicator is correct on first paint and refreshes ~every 60s without a
  navigation.
- [ ] The bell shows an active/current state (e.g. `aria-current="page"` + styling) when the user is on
  `/notifications`.

### FR-002: `/notifications` route + page

#### Description:

A dedicated authenticated page that hosts the notifications list.

#### Acceptance Criteria:

- [ ] A `/notifications` route is registered under the authenticated layout (SPEC-008); visiting it
  unauthenticated redirects to sign-in like the other protected routes.
- [ ] `NotificationsPage` owns `useNotifications(user.username)` and renders the list, the Mark-all-read +
  Refresh controls, the pager, and the empty/loading/error states.
- [ ] The page sets a document title (SPEC-031), e.g. `"Notifications"` (with the unread count if present).
- [ ] Navigating to the page does **not** auto-mark anything read (preserves the unread inbox model;
  FR-005).

### FR-003: Notification list + per-row unread marker

#### Acceptance Criteria:

- [ ] Rows render newest-first: message text, relative timestamp (`formatRelativeTime`), and an **unread
  marker** (accent dot, same visual language as the active query tab) on unread rows; read rows are
  de-emphasized (no marker).
- [ ] Each unread row has a **Mark read** affordance; read rows show no Mark-read control.
- [ ] Long messages wrap/truncate gracefully; the row is keyboard-operable and screen-reader-labeled.

### FR-004: Pagination (10/page, Prev/Next)

#### Acceptance Criteria:

- [ ] The list is paginated **client-side, 10 per page**, using the shared `Pager` (Prev / `"X–Y of N"` /
  Next), newest-first — mirroring SPEC-042 history pagination.
- [ ] Prev is disabled on the first page; Next on the last; the range label is accurate; an empty list shows
  the empty state (no pager).
- [ ] The page resets to the first page when the list identity changes (after mark-all-read / poll /
  reconcile) without stranding the user on an out-of-range page.

### FR-005: Per-item + bulk actions (mark read, mark all read)

#### Acceptance Criteria:

- [ ] **Mark read** on an unread row calls `useNotifications.markRead(id)`: the row's marker clears
  instantly (optimistic) and `unreadCount`/the header indicator update; on enqueue failure it rolls back +
  danger `Toast`.
- [ ] **Mark all read** calls `markAllRead()`: all markers clear + the indicator clears instantly; the
  control is **disabled when `unreadCount === 0`**; on failure it rolls back + danger `Toast`.
- [ ] Actions are non-blocking (the page stays usable); an in-flight action does not double-fire on rapid
  clicks.
- [ ] There is **no delete / delete-all** control anywhere on the page.

### FR-006: Accessibility + states

#### Acceptance Criteria:

- [ ] Empty ("You're all caught up"), loading, and error states render on the page (match
  history/saved-queries conventions); the error state offers a retry/`refresh()`.
- [ ] The unread indicator conveys state non-visually (aria-label / visually-hidden text with the count); the
  page passes the SPEC-045 axe baseline (`*.a11y.test.tsx` for the page + the header bell).
- [ ] All interactive controls are keyboard reachable and labeled.

---

## Data Model

No new types — consumes `Notification` + `useNotifications` from SPEC-059. UI-local state only:

```ts
// NotificationsPage.tsx (local)
const PAGE_SIZE = 10;                // FR-004 (mirrors SPEC-042's history page constant, sized to 10)
const [pageIndex, setPageIndex] = useState(0);
```

## API / Interface Contract

```tsx
// NotificationsBell.tsx — header control (a styled react-router link)
type NotificationsBellProps = {
  hasUnread: boolean;
  unreadCount: number;
  // renders <Link to="/notifications" …>; no onOpen — navigation replaces the drawer toggle
};

// NotificationsPage.tsx — default-exported route component; owns useNotifications.
// (No props — reads user from auth context, like other page components.)
export default function NotificationsPage(): JSX.Element;

// NotificationRow.tsx — one row
type NotificationRowProps = {
  notification: Notification;
  onMarkRead: (id: string) => void;
};
```

## Environment Variables

None (the queue URL var is introduced in SPEC-059).

## File & Folder Structure

```
apps/portal/src/
├── components/
│   ├── icons.tsx                              # + BellIcon (shared inline SVG, no icon lib)
│   └── Header.tsx                             # mount the bell link + the unread indicator (FR-001)
├── features/
│   └── notifications/
│       ├── NotificationsBell.tsx              # header bell link + indicator (FR-001)
│       ├── NotificationsBell.test.tsx
│       ├── NotificationsPage.tsx              # routed page: list + pager + mark-all + refresh (FR-002/004/005/006)
│       ├── NotificationsPage.test.tsx
│       ├── NotificationRow.tsx                # one row: marker + message + time + mark-read (FR-003/005)
│       ├── NotificationRow.test.tsx
│       ├── NotificationsPage.a11y.test.tsx    # SPEC-045 axe baseline (FR-006)
│       └── index.ts                           # barrel adds the UI exports
└── (router config)                            # register the /notifications route under the auth-gated layout (FR-002)
```

## Implementation Phases

### Phase 1: Bell link + indicator + route shell

- `BellIcon`; `NotificationsBell` (react-router link + indicator); mount in `Header.tsx` left of the
  username, wire `useNotifications` (`hasUnread`/`unreadCount`); register the `/notifications` route under
  the auth-gated layout with a `NotificationsPage` shell that sets the document title (FR-001/002). a11y for
  the bell.

### Phase 2: List + pagination + per-row marker

- `NotificationRow` (marker, time, mark-read affordance); `NotificationsPage` list + `Pager` 10/page +
  empty/loading/error + Refresh; reset-to-first-page on list change (FR-003/004/006).

### Phase 3: Actions (optimistic + toast)

- Wire mark-read (per row) + mark-all-read (page header) to the hook mutations; optimistic update + rollback
  + danger `Toast` on failure; mark-all disabled with zero unread (FR-005).
