# Notifications feature (`apps/portal/src/features/notifications/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `NotificationPayload` / `NotificationConflict` | `notifications.types.ts` | The optional structured field a trusted producer attaches beside the message — `requestId` always, plus what re-submitting a refused file operation needs. Owned by the WRITER's wire contract, not by the producing feature: a row must never import from the feature its producer belongs to. |
| `getNotifications(username)` | `notifications.service.ts` | Read-only `GetObject` of `{username}/user_settings/notifications.json`; forgiving parse (missing/corrupt/non-array → empty, drops malformed rows, coerces `read`), returns rows newest-first; `ServiceResult<Notification[]>`, never throws (SPEC-059). |
| `enqueueNotificationAction(input)` | `notifications.service.ts` | Enqueue one user-action (`markRead`/`markAllRead`) onto the SPEC-058 FIFO queue (`MessageGroupId` = username, body carries the verified ID token, never a body username); `ServiceResult<void>` (enqueued ≠ applied), never throws. The browser's only notifications write (SPEC-059). |
| `useNotifications(username, options?)` | `useNotifications.ts` | `{notifications, unreadCount, hasUnread, isLoading, isError, refresh, markRead, markAllRead}` — TanStack read + optimistic mark-read mutations (rollback + delayed reconcile) + a 60s self-limiting poll (suspends while unread); `options.onMutationError` for the SPEC-060 toast (SPEC-059). |
| `prefetchNotifications(queryClient, username)` | `useNotifications.ts` | One-shot graceful prefetch of the inbox read for first-paint indicator accuracy; no-op when signed out, never throws (wired in `ProtectedLayout`, SPEC-059). |
| `notificationsKeys` | `notificationsKeys.ts` | TanStack query-key factory (`all`, `list(username)`) for the notifications read (SPEC-059). |
| `Notification`, `NotificationAction`, `EnqueueNotificationInput`, `NotificationsStore` | `notifications.types.ts` | Inbox row + the two browser action names + enqueue input + the on-S3 array shape; match the SPEC-058 wire contract (SPEC-059). |
| `NotificationsBell` | `NotificationsBell.tsx` | Header bell **link** (react-router `NavLink` → `/notifications`) with a presence-only accent dot when `hasUnread`; count carried in the aria-label (never color-only); `aria-current` on route (SPEC-060). |
| `NotificationsPage` | `NotificationsPage.tsx` | Routed page (via `routes/NotificationsPage.tsx` wrapper): newest-first list, 10/page `Pager`, Mark-all-read + Refresh, empty/loading/error states, optimistic actions + danger `Toast`; owns `useNotifications` + its document title (SPEC-060). |
| `isSafeInAppPath(link)` | `notificationLink.ts` | Open-redirect guard for a notification's optional `link`: accepts a single-slash in-app path only, rejecting schemes, protocol-relative `//host` and backslash-authority `/\host`. The row falls back to plain text when it returns false (SPEC-113 FR-008). |
| `reviewHref(base, requestId)` | `notificationLink.ts` | The href of a row's own action control: the row's already-gated destination with `requestId` added via `URLSearchParams`, falling back to `/files`. Never picks a `?`/`&` by hand — the base ordinarily already carries `?space=`, which is where a hand-rolled separator produces a URL no gate has seen. |
| `NotificationRow` | `NotificationRow.tsx` | One notification row — unread accent dot + sr-only "Unread:", message, `formatRelativeTime`, Mark-read on unread rows (read rows de-emphasized, no control); no delete (SPEC-060). A payload carrying conflicts adds a **Review conflicts** `Link` as a **sibling** of the message anchor (never nested — `nested-interactive`), gated by `files` and registered in `GATED_SURFACES`. |
| `BellIcon` | `components/icons.tsx` | Shared inline bell SVG for the notifications header link (SPEC-060). |

