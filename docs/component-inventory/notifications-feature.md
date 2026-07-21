# Notifications feature (`apps/portal/src/features/notifications/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `getNotifications(username)` | `notifications.service.ts` | Read-only `GetObject` of `{username}/user_settings/notifications.json`; forgiving parse (missing/corrupt/non-array → empty, drops malformed rows, coerces `read`), returns rows newest-first; `ServiceResult<Notification[]>`, never throws (SPEC-059). |
| `enqueueNotificationAction(input)` | `notifications.service.ts` | Enqueue one user-action (`markRead`/`markAllRead`) onto the SPEC-058 FIFO queue (`MessageGroupId` = username, body carries the verified ID token, never a body username); `ServiceResult<void>` (enqueued ≠ applied), never throws. The browser's only notifications write (SPEC-059). |
| `useNotifications(username, options?)` | `useNotifications.ts` | `{notifications, unreadCount, hasUnread, isLoading, isError, refresh, markRead, markAllRead}` — TanStack read + optimistic mark-read mutations (rollback + delayed reconcile) + a 60s self-limiting poll (suspends while unread); `options.onMutationError` for the SPEC-060 toast (SPEC-059). |
| `prefetchNotifications(queryClient, username)` | `useNotifications.ts` | One-shot graceful prefetch of the inbox read for first-paint indicator accuracy; no-op when signed out, never throws (wired in `ProtectedLayout`, SPEC-059). |
| `notificationsKeys` | `notificationsKeys.ts` | TanStack query-key factory (`all`, `list(username)`) for the notifications read (SPEC-059). |
| `Notification`, `NotificationAction`, `EnqueueNotificationInput`, `NotificationsStore` | `notifications.types.ts` | Inbox row + the two browser action names + enqueue input + the on-S3 array shape; match the SPEC-058 wire contract (SPEC-059). |

| `NotificationsBell` | `NotificationsBell.tsx` | Header bell **link** (react-router `NavLink` → `/notifications`) with a presence-only accent dot when `hasUnread`; count carried in the aria-label (never color-only); `aria-current` on route (SPEC-060). |
| `NotificationsPage` | `NotificationsPage.tsx` | Routed page (via `routes/NotificationsPage.tsx` wrapper): newest-first list, 10/page `Pager`, Mark-all-read + Refresh, empty/loading/error states, optimistic actions + danger `Toast`; owns `useNotifications` + its document title (SPEC-060). |
| `isSafeInAppPath(link)` | `notificationLink.ts` | Open-redirect guard for a notification's optional `link`: accepts a single-slash in-app path only, rejecting schemes, protocol-relative `//host` and backslash-authority `/\host`. The row falls back to plain text when it returns false (SPEC-113 FR-008). |
| `NotificationRow` | `NotificationRow.tsx` | One notification row — unread accent dot + sr-only "Unread:", message, `formatRelativeTime`, Mark-read on unread rows (read rows de-emphasized, no control); no delete (SPEC-060). |
| `BellIcon` | `components/icons.tsx` | Shared inline bell SVG for the notifications header link (SPEC-060). |
| `buildSqlCompletions`, `createSqlCompletionProvider`, `DatabaseSchema` | `features/query/sqlCompletions.ts` | Pure, Monaco-free builder mapping `DatabaseSchema[]` (per-DB tables) → completion descriptors: **fully-qualified** `database.table` for tables/views, bare de-duped columns with type detail; plus the Monaco provider factory reading a live `schemaRef`. Feeds multi-database autocomplete (SPEC-065/077). |
| `deriveViewTargetDatabase(body)`, `schemaChangingDatabase(sql)` | `features/query/query.sql.ts` | Pure SQL heuristics: the single database of a view body's fully-qualified base tables (error when ambiguous/none), and the target DB of a schema-changing DDL statement — both used now that there's no active database (SPEC-077). |
| `splitSqlStatements(buffer)`, `resolveRunStatements(buffer, stmts, sel, cursor)`, `isResultProducingSql(sql)`, `statementHint(sql)` | `features/query/query.sql.ts` | Pure multi-statement helpers (SPEC-078): split a buffer into `ParsedStatement[]` (string/comment/backtick-aware, source offsets); resolve Run Statement's scope (selection → cursor statement → sole); classify row-returning statements; short label for result tabs. |
| `ResultTabs` | `features/query/ResultTabs.tsx` | Result-tab strip for a "tab per statement" script run (SPEC-078): WAI-ARIA tablist (roving tabindex, Arrow/Home/End), one labeled tab per `ResultTab`, controlled `activeIndex`/`onSelect`. |
| `useResultsPageSize(username)`, `clampPageSize(n)` | `features/query/useResultsPageSize.ts` | Workspace-global "Rows per page" value (default 100, clamped 1–1000), per-user sessionStorage persistence (defensive read, degrade-safe); `clampPageSize` is the pure validator (null for non-integers) (SPEC-087). |
| `ResultsPageSizeControl` | `features/query/ResultsPageSizeControl.tsx` | Labeled "Rows per page" integer input for the results header: commit on blur/Enter (never per keystroke), Escape abandons the draft, invalid input reverts / out-of-range clamps, `disabled` renders non-interactive but visible (SPEC-087). |

