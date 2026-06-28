# Completed Spec — SPEC-060: Notifications UI (Header Bell Link + Notifications Page)

The UI layer of the notifications arc (058 → 059 → **060** → 061): the header bell link + a routed `/notifications` page consuming the SPEC-059 hook. UI only — no services, no IAM, no infra. Delivered in one app PR.

## What was completed?

- **Header bell link + unread indicator (FR-001):** `NotificationsBell` — a react-router `NavLink` to `/notifications` (a link, not a drawer toggle), mounted in `Header.tsx` **left of the username** (bell → username → avatar → Sign out), authenticated-only. A **presence-only accent dot** when `hasUnread` (no numeric badge); the count rides in the accessible name (`"Notifications, 3 unread"` / `"…none unread"`) so it's never color-only; `aria-current` + styling on `/notifications`. The Header owns `useNotifications(authenticated ? username : null)` — mounting it in the always-present shell **activates the SPEC-059 60s poll + prefetched read**, so the indicator is correct on first paint and refreshes without navigation.
- **`/notifications` route + page (FR-002):** registered under `ProtectedLayout` (redirects to sign-in when unauthenticated like the other protected routes). `routes/NotificationsPage.tsx` is a thin default-export wrapper over the feature view `features/notifications/NotificationsPage.tsx`, which owns its own `useNotifications` + `usePageTitle` (title shows the unread count when present). Eager-imported (the SQS client is already in the main bundle via the header bell, so lazy-loading would save nothing). Navigating does not auto-mark anything read.
- **List + per-row marker (FR-003):** `NotificationRow` renders newest-first — accent dot + sr-only "Unread:" on unread rows, message (wraps), `formatRelativeTime`, and a **Mark read** affordance; read rows are de-emphasized with no marker/control. The list root is `<main id="main">` (skip-link target + landmark).
- **Pagination (FR-004):** client-side **10/page** via the shared `Pager` (`"1–10 of N"`, newest-first), Prev/Next disabled at ends, clamp-on-shrink + snap-to-newest when the list grows (mirrors SPEC-042 history).
- **Actions (FR-005):** per-row `markRead` + header `Mark all read` (disabled at `unreadCount === 0`) wired to the hook's optimistic mutations — markers/indicator clear instantly; a failed enqueue rolls back and raises a **danger `Toast`** (via the hook's `onMutationError`). Optimistic read-flip removes the control so rapid clicks can't double-fire. **No delete anywhere.**
- **States + a11y (FR-006):** empty ("You're all caught up"), loading, and error (Banner + "Try again" → `refresh()`) states; Refresh control (SPEC-046 IconButton + spin). New `BellIcon` in `components/icons.tsx`. axe baseline tests for the page + the bell; the unread state is conveyed non-visually.

## What changed from earlier specs?

- **`Header.tsx`** now mounts the bell + `useNotifications` (its `RootLayout.test` gains a `QueryClientProvider` + a stubbed read). **`App.tsx`** registers the `/notifications` route. **`components/icons.tsx`** gains `BellIcon`. Reused cross-feature: `Toast` + `formatRelativeTime` imported from `features/query` (the established precedent — shared-spaces already imports `Toast`). **No IAM/infra change**; the live poll the bell activates uses the SPEC-059 data layer over the SPEC-058 queue.

## Decisions made in-session

- **No separate design-HTML artifact** — the page matches the existing page/container + design-system patterns (as SPEC-052/057 shipped), rather than authoring a new `docs/design/` mock.
- **Page resets to the first page only when the list grows** (new notification) + clamp-on-shrink — not on every 60s poll/refetch — so a reader paging through history isn't yanked back to page 1 each minute.
- **Bell owns the hook; the page owns a second instance** — both share the TanStack read cache (so a page mark-read updates the header dot instantly), while only the page wires `onMutationError` → Toast.

## Verification

`format:check` / `lint` / `build` (tsc + vite) / `test` all green — **743 tests** (20 new: bell link/aria-name/aria-current; row marker/sr-only/mark-read; page loading/empty/error+retry/10-per-page/range-label/mark-read/mark-all/disabled/rollback-toast; page + bell axe baselines). Browser verification was not run: the page is authenticated-only (needs a Cognito session + AWS), which the local preview can't exercise; behavior is covered by the unit + a11y suite. Frontend-only; nothing to deploy beyond the app bundle.
