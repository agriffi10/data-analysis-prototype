# Completed Spec — SPEC-059: Notifications Data Layer (Read Service + Hook)

The browser data layer of the notifications arc (058 → **059** → 060 → 061): a typed, read-only service + a TanStack hook the SPEC-060 UI consumes without knowing about S3 or SQS. The browser **only reads** `notifications.json` and **enqueues** the two user-actions; the SPEC-058 writer Lambda owns every write. No visible UI. Delivered in one app PR (frontend-only — the queue + IAM shipped in SPEC-058).

## What was completed?

- **`notifications.service.ts` (FR-001/002):**
  - `getNotifications(username)` — `GetObject` of `{username}/user_settings/notifications.json` via the scoped S3 client + `withCredentialRetry`; 404 (new user) → `[]`, corrupt/non-array → `[]` (logged), drops malformed rows, coerces `read`, returns **newest-first**; any other S3 error → typed failure. Mirrors `queryHistory.service`.
  - `enqueueNotificationAction({action, username, id?})` — one `SendMessage` to `VITE_NOTIFICATIONS_QUEUE_URL`; body = `{action, idToken, id?}` (the verified ID token attached via `getIdToken`; **never** a body username — the writer derives the user from the token, anti-spoof per SPEC-058 FR-005), `MessageGroupId` = username (per-user FIFO ordering), fresh `MessageDeduplicationId`. `markRead` without an `id` → validation error (no send). `ServiceResult<void>` (enqueued ≠ applied).
- **`useNotifications(username, options?)` (FR-003/004/006):** TanStack read keyed per user (disabled when signed out), exposing `notifications`/`unreadCount`/`hasUnread`/`isLoading`/`isError`/`refresh` + `markRead`/`markAllRead`. Mutations enqueue and update the cache **optimistically** (cancel → snapshot → functional `setQueryData` so concurrent mark-one + mark-all compose), **roll back** on enqueue failure (surfacing the message via `options.onMutationError` for the SPEC-060 toast), and schedule a **delayed reconcile** invalidate (~2.5s) so the writer's eventual result wins. The read runs a **60s `refetchInterval`** that is a **function of cached data** — it returns `false` once `unreadCount > 0` (self-limiting: the bell already shows unread) and resumes after the set is marked read / a refresh / reload; `refetchOnWindowFocus` re-checks on tab return; the default `refetchIntervalInBackground:false` keeps a hidden tab from polling.
- **Prefetch-on-load (FR-005):** `prefetchNotifications(queryClient, username)` (graceful — never throws, no-op when signed out) wired into an effect in `ProtectedLayout` so the SPEC-060 indicator is accurate on first paint.
- **Types/keys (FR-007):** `Notification`, `NotificationAction`, `EnqueueNotificationInput`, `NotificationsStore` in `notifications.types.ts` (match the SPEC-058 wire contract); `notificationsKeys` factory. `lib/sqsClient.ts` reused as-is. `@aws-sdk/client-sqs` already a dep (SPEC-051) + already in CLAUDE.md Tech Stack. `VITE_NOTIFICATIONS_QUEUE_URL` documented in `.env.example`. Barrel `index.ts`; component-inventory rows added.

## What changed from earlier specs?

- **`ProtectedLayout`** now consumes the `QueryClient` and fires the notifications prefetch on authenticated mount (its test gains a `QueryClientProvider` wrapper + a stubbed prefetch). No other component touched (the bell + page are SPEC-060). **No IAM/infra change** — reuses the SPEC-058 queue, the SPEC-056 portal-role `sqs:SendMessage` grant, and the existing user-scoped S3 read.

## Decisions made in-session (reversible/technical)

- **The service fetches the ID token internally** (via `getIdToken`) rather than the hook passing it — matches the `sharedSpaces.service` precedent and the spec's own data-model note (the API-contract snippet's `& {idToken}` param was the looser reading).
- **Prefetch lives in `ProtectedLayout`; the live poll activates when SPEC-060 mounts the hook** in the header bell — keeping 059 strictly a data layer with no visible UI. The hook's poll/optimistic/reconcile behavior is fully unit-tested with mocked timers now.

## Verification

`npm run format:check` / `lint` / `build` (tsc + vite) / `test` all green — **723 tests** (28 new: service 404/corrupt/non-array/sort/coerce/drop/error + enqueue body/group-id/no-username/id-required/unconfigured/token-fail/send-fail; hook unread derivation, optimistic markRead/markAllRead, rollback + `onMutationError`, compose, delayed reconcile, 60s poll + suspend-when-unread, prefetch seed/no-op/graceful; `ProtectedLayout` prefetch-on-auth). Frontend-only; nothing to deploy beyond the app bundle.
