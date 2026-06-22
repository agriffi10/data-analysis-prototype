# Spec: Notifications Data Layer (Read Service + Hook)

**ID:** SPEC-059
**Status:** Draft
**Last Updated:** 2026-06-22
**Depends On:** SPEC-058 (notifications write pipeline + queue + contract), SPEC-034 (S3 client + `withCredentialRetry` + per-user `user_settings` JSON precedent), SPEC-015 (TanStack Query foundation)

> **Second of the notifications arc (058 → 059 → 060).** This spec is the **browser data layer**: a
> read-only `notifications.service.ts` that **reads** `{username}/user_settings/notifications.json`, the
> **enqueue helpers** that `SendMessage` to the SPEC-058 queue for the four user-actions, and a
> `useNotifications` hook (TanStack Query read + optimistic mutations + unread count). **No UI** (SPEC-060
> builds the drawer + header button). The browser **never writes** the JSON — mutations are SQS messages
> the SPEC-058 writer applies; the hook updates the cache **optimistically** because the write is
> eventually consistent.

## Overview

Expose notifications to the React app as a clean, typed data layer that the UI (SPEC-060) consumes without
knowing about S3 or SQS. Reads come straight from the user's `notifications.json` via the existing scoped
S3 client; the array is the full inbox (capped writer-side to `NOTIFICATIONS_MAX`), so pagination and
filtering happen in the UI over the in-memory list. Mutations (mark read, mark all read, delete, delete
all) are **not** direct writes — each enqueues a message on the SPEC-058 queue and the hook reflects the
change optimistically, reconciling on the next read. The hook also derives the **unread count / has-unread**
flag the header indicator needs, and supports a lightweight **prefetch on app load** so the indicator is
correct and the first drawer open is instant.

## Scope

### In Scope

- **`notifications.service.ts`** (returns `ServiceResult<T>`, never throws):
  - `getNotifications(username)` — `GetObject` + parse `notifications.json`; missing (404) or
    corrupt JSON → **empty array** (not an error); validates/normalizes each row to `Notification`.
  - `enqueueNotificationAction(input)` — `SendMessage` to the SPEC-058 queue for the four **user** actions
    (`markRead` | `markAllRead` | `delete` | `deleteAll`), attaching the caller's Cognito **ID token** per
    the SPEC-058 contract (FR-005). Returns `ServiceResult<void>` (enqueue success ≠ applied).
- **`useNotifications(username | null)` hook** — TanStack Query read (keyed per user), exposing the list,
  `unreadCount`, `hasUnread`, `isLoading`/`isError`, a `refresh()`, and the four mutations
  (`markRead`/`markAllRead`/`remove`/`removeAll`) that **enqueue + optimistically update the cache**, with
  rollback on enqueue failure and a delayed background refetch to reconcile the eventually-consistent write.
- **Types** in `notifications.types.ts` — `Notification`, `NotificationAction`, the enqueue input shape;
  shared with SPEC-060 and matching the SPEC-058 wire contract exactly.
- **SQS client** in `src/lib/` (instantiated there, never in components/hooks), built from the same scoped
  Identity-Pool credentials as the S3/Athena/Glue clients (`getSessionCredentials`), with the same
  `withCredentialRetry` wrapper on send.
- **New dependency** `@aws-sdk/client-sqs` (modular v3) — recorded in CLAUDE.md Tech Stack at
  implementation (per the "don't add deps without noting them" rule).
- **Env var** `VITE_NOTIFICATIONS_QUEUE_URL` (the SPEC-058 queue URL output), documented in
  `apps/portal/.env.example`.

### Out of Scope

- **All UI** — header bell, unread dot, slide-out drawer, pagination controls, action buttons, toasts —
  **SPEC-060**.
- **Client-side pagination** — the service returns the whole array; paging 8/page is a SPEC-060 UI concern
  (mirrors history's client-side `Pager`).
- **Writing `notifications.json`** — never from the browser (SPEC-058 writer owns all writes).
- **Creating notifications** — `create` is a trusted-producer action (SPEC-058 FR-006); the data layer
  exposes only the four user-actions unless the FR-006 open question reopens it.
- Realtime/push delivery (WebSocket/poll-for-new) — reads are on-demand + prefetch-on-load only; a polling
  cadence (if wanted) is a follow-up.

---

## Functional Requirements

### FR-001: Read service

#### Description:

Read the user's notifications document into a typed, sorted list.

#### Acceptance Criteria:

- [ ] `getNotifications(username)` issues a `GetObject` for
  `{username}/user_settings/notifications.json` through the scoped S3 client (`withCredentialRetry`).
- [ ] A **404 / NoSuchKey** resolves to `{ success: true, data: [] }` — a user with no notifications is
  the normal empty state, not an error.
- [ ] **Corrupt/unparseable** JSON (or a non-array root) resolves to `{ success: true, data: [] }`
  (defensive — the writer owns the format; the reader never throws), and is logged.
- [ ] Each row is normalized to `Notification` (`id`, `message`, `read`, `timestamp`); rows are returned
  **newest-first** by `timestamp` (the writer already stores newest-first; the reader re-sorts to be
  resilient).
- [ ] Any other S3 error returns `{ success: false, error: { message, code? } }` (never throws).

### FR-002: Enqueue service (user actions)

#### Description:

Send a user-action message to the SPEC-058 queue, bound to the caller's identity.

#### Acceptance Criteria:

- [ ] `enqueueNotificationAction({ action, id?, idToken })` sends one `SendMessage` to
  `VITE_NOTIFICATIONS_QUEUE_URL` with a body matching the SPEC-058 contract for
  `markRead` | `markAllRead` | `delete` | `deleteAll`.
- [ ] The message **always** carries the current user's Cognito **ID token** (obtained from the auth layer)
  and **never** a client-asserted `username` — the writer derives the user from the token (SPEC-058 FR-005).
- [ ] `markRead` and `delete` include the target `id`; `markAllRead`/`deleteAll` omit it. Calling
  `markRead`/`delete` without an `id` returns a validation error (no send).
- [ ] Returns `ServiceResult<void>`; success means **enqueued**, explicitly **not** "applied" (the doc is
  updated asynchronously by the writer). A `SendMessage` failure returns a typed error.

### FR-003: `useNotifications` hook — read + derived state

#### Description:

A single hook the UI consumes for the list and the indicator.

#### Acceptance Criteria:

- [ ] `useNotifications(username | null)` reads via `useQuery` keyed `notificationsKeys.list(username)`;
  disabled when `username` is null (unauthenticated).
- [ ] Exposes `notifications: Notification[]`, `unreadCount: number`, `hasUnread: boolean`
  (`unreadCount > 0`), `isLoading`, `isError`, and `refresh()` (manual re-read; mirrors history's Refresh).
- [ ] Respects the app `queryClient` defaults (staleTime 30s); the indicator reflects the cached read
  without forcing a network call on every render.

### FR-004: `useNotifications` hook — optimistic mutations

#### Description:

Mutations enqueue and update the cache immediately, reconciling later.

#### Acceptance Criteria:

- [ ] `markRead(id)` / `markAllRead()` / `remove(id)` / `removeAll()` each call
  `enqueueNotificationAction` and **optimistically** mutate the cached list (set `read`, or drop the
  item(s)) so the UI + indicator update instantly.
- [ ] On **enqueue failure**, the optimistic change is **rolled back** and the error is surfaced (the UI
  shows a toast in SPEC-060).
- [ ] After a successful enqueue, the hook schedules a **delayed background refetch** (e.g. invalidate after
  a short delay) to reconcile the cache with the writer's eventual result; a reconciliation that differs
  from the optimistic state wins (writer is source of truth).
- [ ] Concurrent optimistic mutations compose (e.g. mark-all-read then delete-one) without resurrecting
  removed items on reconcile.

### FR-005: Prefetch on app load

#### Description:

Make the indicator correct and the first drawer-open instant.

#### Acceptance Criteria:

- [ ] On authenticated app load, the notifications read is **prefetched** once (e.g.
  `queryClient.prefetchQuery` / an enabled query high in the authenticated shell) so the header indicator
  is accurate before the user interacts and the first drawer render has data (SPEC-058/-060 "most recent 8
  on page load" — the read returns the full capped array; the UI shows the first page of 8).
- [ ] Prefetch failure degrades gracefully (no indicator / no crash); it never blocks the shell from
  rendering.

### FR-006: Wiring + dependency

#### Acceptance Criteria:

- [ ] `@aws-sdk/client-sqs` is added (modular v3) and recorded in CLAUDE.md Tech Stack; the SQS client is
  instantiated in `src/lib/` (e.g. `lib/sqsClient.ts`) from `getSessionCredentials`, never in a component.
- [ ] `VITE_NOTIFICATIONS_QUEUE_URL` is documented in `apps/portal/.env.example` with a description.
- [ ] All new symbols get one-line rows in `docs/component-inventory.md` at completion.

---

## Data Model

```ts
// apps/portal/src/features/notifications/notifications.types.ts

export type Notification = {
  id: string;          // server-assigned (SPEC-058 writer)
  message: string;
  read: boolean;
  timestamp: string;   // ISO-8601 (writer clock)
};

// The four browser-originated actions (create is trusted-producer-only — SPEC-058 FR-006).
export type NotificationAction = 'markRead' | 'markAllRead' | 'delete' | 'deleteAll';

export type EnqueueNotificationInput = {
  action: NotificationAction;
  id?: string;        // required for markRead | delete
  // idToken is attached by the service from the auth layer, not passed by callers of the hook
};

export type NotificationsStore = Notification[];   // the on-S3 document shape (array root)
```

## API / Interface Contract

```ts
// notifications.service.ts — all return ServiceResult<T>, never throw
getNotifications(username: string): Promise<ServiceResult<Notification[]>>;
enqueueNotificationAction(
  input: EnqueueNotificationInput & { idToken: string },
): Promise<ServiceResult<void>>;

// useNotifications.ts
function useNotifications(username: string | null): {
  notifications: Notification[];
  unreadCount: number;
  hasUnread: boolean;
  isLoading: boolean;
  isError: boolean;
  refresh: () => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  remove: (id: string) => void;
  removeAll: () => void;
};

// Example (SPEC-060 consumes this):
const { notifications, hasUnread, markAllRead } = useNotifications(user?.username ?? null);
```

```ts
// notificationsKeys.ts — never hand-build key arrays
export const notificationsKeys = {
  all: ['notifications'] as const,
  list: (username: string) => ['notifications', username] as const,
};
```

## Environment Variables

Add to `apps/portal/.env.example`:

```
VITE_NOTIFICATIONS_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account-id>/<notifications-queue>  # SPEC-058 output; target for user-action SendMessage
```

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   └── sqsClient.ts                         # getSqsClient(forceRefresh?) — scoped creds, ServiceResult<SQSClient>
├── features/
│   └── notifications/
│       ├── index.ts                          # barrel (service + hook + types + keys)
│       ├── notifications.service.ts
│       ├── notifications.service.test.ts
│       ├── useNotifications.ts
│       ├── useNotifications.test.ts
│       ├── notificationsKeys.ts
│       └── notifications.types.ts
```

## Implementation Phases

### Phase 1: Read service + SQS client + types

- `notifications.types.ts` + `notificationsKeys.ts`; `lib/sqsClient.ts`; `getNotifications` (FR-001) with
  unit tests (404 → empty, corrupt → empty, happy path sorts newest-first, S3 error → error);
  `enqueueNotificationAction` (FR-002) with tests (id-required validation, token attached, send failure).
  Add `@aws-sdk/client-sqs` + the env var (FR-006).

#### Checkpoint

`npm run test -w apps/portal` green for `notifications.service.test.ts`; `getNotifications` returns `[]` for
a missing/corrupt object and a sorted list for a valid one; `enqueueNotificationAction` builds a
contract-correct body with the ID token and rejects `markRead`/`delete` with no id.

### Phase 2: Hook (read + derived state + optimistic mutations + prefetch)

- `useNotifications` (FR-003/004/005); tests for `unreadCount`/`hasUnread`, optimistic update + rollback on
  enqueue failure, delayed reconcile, and prefetch-on-load behavior (mocked query client). Component-inventory
  rows (FR-006).

#### Checkpoint

`useNotifications.test.ts` green: marking read/deleting updates the list + `unreadCount` instantly, rolls
back on a simulated send failure, and reconciles to the writer's value on the delayed refetch. No UI yet.

## Open Questions

- [ ] **Reconcile timing:** what delay before the post-enqueue background refetch (writer latency)? Start
  with a single delayed invalidate (~2–3s) + the manual `refresh()`; tune if the eventual-consistency
  window feels laggy. (A short poll-until-changed is a possible upgrade — out of scope now.)
- [ ] **ID token source:** confirm the auth layer exposes the current Cognito **ID token**
  (`fetchAuthSession` / Amplify) for `enqueueNotificationAction`; if only the access token is readily
  available, align with SPEC-058 FR-005 on which token the writer verifies.
- [ ] Should `getNotifications` cap/trim client-side too, or fully trust the writer's `NOTIFICATIONS_MAX`
  cap? Default: trust the writer; the UI paginates the full array.
