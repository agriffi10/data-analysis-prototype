# Spec: Notifications Data Layer (Read Service + Hook)

**ID:** SPEC-059
**Status:** Completed
**Last Updated:** 2026-06-27
**Depends On:** SPEC-058 (notifications write pipeline + queue + contract), SPEC-034 (S3 client + `withCredentialRetry` + per-user `user_settings` JSON precedent), SPEC-015 (TanStack Query foundation)

> **Second of the notifications arc (058 → 059 → 060 → 061).** This spec is the **browser data layer**: a
> read-only `notifications.service.ts` that **reads** `{username}/user_settings/notifications.json`, the
> **enqueue helpers** that `SendMessage` to the SPEC-058 queue for the two user-actions
> (`markRead`/`markAllRead`), and a `useNotifications` hook (TanStack Query read + a **60-second background
> poll** that keeps the unread count/indicator fresh + optimistic mark-read mutations). **No UI** (SPEC-060
> builds the header bell link + notifications page). The browser **never writes** the JSON — mutations are
> SQS messages the SPEC-058 writer applies; the hook updates the cache **optimistically** because the write
> is eventually consistent. There is **no delete** — the only mutations are mark-read / mark-all-read.

## Overview

Expose notifications to the React app as a clean, typed data layer that the UI (SPEC-060) consumes without
knowing about S3 or SQS. Reads come straight from the user's `notifications.json` via the existing scoped
S3 client; the array is the full inbox (capped writer-side to `NOTIFICATIONS_MAX`), so pagination
happens in the UI (10/page) over the in-memory list. Mutations (mark read, mark all read)
are **not** direct writes — each enqueues a message on the SPEC-058 queue and the hook reflects the
change optimistically, reconciling on the next read. The hook derives the **unread count / has-unread**
flag the header indicator needs, supports a lightweight **prefetch on app load** so the indicator is
correct on first paint, and runs a **60-second background poll** so the bell icon picks up newly delivered
notifications without a manual refresh or navigation. The poll is **self-limiting**: it runs only while there
are no unread notifications and **suspends once unread is showing** (the indicator already reflects it),
resuming after the user marks the set read or reloads.

## Scope

### In Scope

- **`notifications.service.ts`** (returns `ServiceResult<T>`, never throws):
  - `getNotifications(username)` — `GetObject` + parse `notifications.json`; missing (404) or
    corrupt JSON → **empty array** (not an error); validates/normalizes each row to `Notification`.
  - `enqueueNotificationAction(input)` — `SendMessage` to the SPEC-058 queue for the two **user** actions
    (`markRead` | `markAllRead`), attaching the caller's Cognito **ID token** per
    the SPEC-058 contract (FR-005). Returns `ServiceResult<void>` (enqueue success ≠ applied).
- **`useNotifications(username | null)` hook** — TanStack Query read (keyed per user), exposing the list,
  `unreadCount`, `hasUnread`, `isLoading`/`isError`, a `refresh()`, and the two mutations
  (`markRead`/`markAllRead`) that **enqueue + optimistically update the cache**, with
  rollback on enqueue failure and a delayed background refetch to reconcile the eventually-consistent write.
- **Background poll (self-limiting)** — the read query runs on a **60-second `refetchInterval`** (also
  `refetchOnWindowFocus`) while the user is authenticated **and has no unread**; it **suspends once
  `unreadCount > 0`** (the indicator already conveys it) and resumes after the set is marked read or the page
  reloads, so the bell reflects newly delivered notifications within ~1 minute without needless polling
  (FR-006).
- **Types** in `notifications.types.ts` — `Notification`, `NotificationAction` (`'markRead' | 'markAllRead'`),
  the enqueue input shape; shared with SPEC-060 and matching the SPEC-058 wire contract exactly.
- **SQS client** in `src/lib/` (instantiated there, never in components/hooks), built from the same scoped
  Identity-Pool credentials as the S3/Athena/Glue clients (`getSessionCredentials`), with the same
  `withCredentialRetry` wrapper on send.
- **New dependency** `@aws-sdk/client-sqs` (modular v3) — recorded in CLAUDE.md Tech Stack at
  implementation (per the "don't add deps without noting them" rule).
- **Env var** `VITE_NOTIFICATIONS_QUEUE_URL` (the SPEC-058 queue URL output), documented in
  `apps/portal/.env.example`.

### Out of Scope

- **All UI** — header bell link, unread dot, notifications page, pagination controls, action buttons, toasts —
  **SPEC-060**.
- **Client-side pagination** — the service returns the whole array; paging 10/page is a SPEC-060 UI concern
  (mirrors history's client-side `Pager`).
- **Writing `notifications.json`** — never from the browser (SPEC-058 writer owns all writes).
- **Creating notifications** — `create` is a trusted-producer action (SPEC-058 FR-005/-006; the first
  producer is the shared-workspace control plane, SPEC-061); the data layer exposes only the two
  user-actions.
- **Deleting notifications** — there is no `delete`/`deleteAll`; the inbox only grows (writer-capped) and the
  user can only mark items read.
- Realtime/push delivery (WebSocket/server-push) — freshness is the 60-second poll + prefetch-on-load +
  manual `refresh()`; true push is a follow-up.

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
  `markRead` | `markAllRead`.
- [ ] The queue is **FIFO**, so the send sets **`MessageGroupId` = the current user's username** (so the
  user's actions serialize behind any system `create`s for them — SPEC-058 FR-001) plus a
  `MessageDeduplicationId` (e.g. a uuid, or rely on content-based dedup) to collapse accidental double-sends.
- [ ] The message **always** carries the current user's Cognito **ID token** — obtained via Amplify
  `fetchAuthSession()` (`tokens.idToken`), aligning with the token the SPEC-058 writer verifies — and
  **never** a client-asserted `username`; the writer derives the user from the token (SPEC-058 FR-005).
  (The `MessageGroupId` is only for ordering; the writer still trusts the token, not the group id.)
- [ ] `markRead` includes the target `id`; `markAllRead` omits it. Calling
  `markRead` without an `id` returns a validation error (no send).
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
- [ ] Respects the app `queryClient` defaults (staleTime 30s); between polls the indicator reflects the
  cached read without forcing a network call on every render.

### FR-004: `useNotifications` hook — optimistic mutations

#### Description:

Mutations enqueue and update the cache immediately, reconciling later.

#### Acceptance Criteria:

- [ ] `markRead(id)` / `markAllRead()` each call
  `enqueueNotificationAction` and **optimistically** mutate the cached list (set `read` on the item / on all)
  so the UI + indicator update instantly.
- [ ] On **enqueue failure**, the optimistic change is **rolled back** and the error is surfaced (the UI
  shows a toast in SPEC-060).
- [ ] After a successful enqueue, the hook schedules a **delayed background refetch** (invalidate **~2–3s**
  after enqueue, a tunable constant, to allow for writer latency) to reconcile the cache with the writer's
  eventual result; a reconciliation that differs from the optimistic state wins (writer is source of truth).
- [ ] Concurrent optimistic mutations compose (e.g. mark-one-read then mark-all-read) without losing the
  read state on reconcile.

### FR-005: Prefetch on app load

#### Description:

Make the indicator correct on first paint and the first page-visit instant.

#### Acceptance Criteria:

- [ ] On authenticated app load, the notifications read is **prefetched** once (e.g.
  `queryClient.prefetchQuery` / an enabled query high in the authenticated shell) so the header indicator
  is accurate before the user interacts and the first notifications-page render has data (the read returns
  the full capped array; the UI shows the first page of 10).
- [ ] Prefetch failure degrades gracefully (no indicator / no crash); it never blocks the shell from
  rendering.

### FR-006: Background poll (unread indicator freshness)

#### Description:

Keep the bell's unread indicator current as new notifications are delivered, without a navigation or
manual refresh — but stop polling once the indicator already shows unread, since further polling can't
change what the UI is telling the user.

#### Acceptance Criteria:

- [ ] While authenticated **and `unreadCount === 0`**, the notifications query runs on a **60-second
  `refetchInterval`** (configurable constant) so a newly delivered notification flips `hasUnread` within
  ~1 minute; the poll is disabled when `username` is null (signed out).
- [ ] **Poll suspends while unread (`hasUnread`):** once a poll (or any read) finds `unreadCount > 0`, the
  `refetchInterval` **stops** — the bell already reflects "you have unread", so there's nothing new to
  surface by polling. (Implementation: `refetchInterval` is a function of the cached data that returns
  `false` when `unreadCount > 0`.)
- [ ] **Poll resumes** when the unread state clears — i.e. after the user **marks the current set read**
  (`markRead`/`markAllRead` bring `unreadCount` back to 0) or on a **manual `refresh()` / page reload** — at
  which point the 60-second cadence restarts (and will suspend again on the next unread).
- [ ] `refetchOnWindowFocus` still runs (so returning to the tab re-checks once, regardless of poll state);
  the `refetchInterval` is additionally **paused while the tab is hidden** (`document.visibilityState !==
  'visible'`) and resumes on focus, so a backgrounded tab does not poll.
- [ ] A failed poll does not surface an error to the user or clear the existing indicator — it retains the
  last good state and tries again on the next interval (while still subject to the suspend-when-unread rule).
- [ ] The poll updates only the cached read (and therefore the count/indicator); it does **not** auto-mark
  anything read or otherwise mutate the inbox.

### FR-007: Wiring + dependency

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

// The two browser-originated actions (create is trusted-producer-only — SPEC-058 FR-005; no delete).
export type NotificationAction = 'markRead' | 'markAllRead';

export type EnqueueNotificationInput = {
  action: NotificationAction;
  id?: string;        // required for markRead
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
VITE_NOTIFICATIONS_QUEUE_URL=https://sqs.<region>.amazonaws.com/<account-id>/<notifications-queue>.fifo  # SPEC-058 output (FIFO); target for user-action SendMessage (set MessageGroupId = username)
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
  Add `@aws-sdk/client-sqs` + the env var (FR-007).

### Phase 2: Hook (read + derived state + optimistic mutations + poll + prefetch)

- `useNotifications` (FR-003/004/005/006); tests for `unreadCount`/`hasUnread`, optimistic update + rollback
  on enqueue failure, delayed reconcile, the 60s `refetchInterval` poll + its **suspend-when-unread /
  resume-after-read** rule (mocked timers), and prefetch-on-load behavior (mocked query client).
  Component-inventory rows (FR-007).
