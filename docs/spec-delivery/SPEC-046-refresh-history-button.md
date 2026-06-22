# Completed Spec — SPEC-046: Refresh History Button

## What was completed?

- The Query History drawer header gains a **Refresh** icon button (`aria-label="Refresh history"`),
  placed in the SPEC-036 `Drawer` `headerAccessory` slot. Activating it re-reads the user's
  `query-history.json` from S3 on demand.
- `useQueryHistory` exposes two new fields: **`refresh()`** (= `invalidateQueries(queryKeys.history(username))`,
  which refetches the active observer and resolves once the refetch settles) and **`isRefreshing`**
  (`query.isRefetching` — true for a manual/background refetch, not the initial load).
- **In-flight:** the button is disabled + its icon spins while `isRefreshing`, so it can't be
  re-triggered. **On success:** the pager snaps back to the **newest page** (page 1), matching the
  SPEC-042 open/append behavior.
- **Non-destructive error (FR-003):** a failed refetch keeps the last-loaded entries (TanStack retains
  data on refetch error); the panel now renders the read-error `Banner` **above** the retained list
  rather than replacing it. A corrupt/missing store still reads as an empty store (SPEC-034), never an
  error.

## What changed from earlier specs?

- **SPEC-034 `useQueryHistory`** (`UseQueryHistoryResult`) += `refresh` / `isRefreshing`; the history
  storage schema and service functions are unchanged.
- **SPEC-036 `QueryHistoryPanel`** body restructured so an error and a populated list can render
  together (previously error replaced the list). Manual-only — no polling, no schema/IAM change.

## Verification

`npm run lint`, `npm run build`, and `npm run test` (**557 pass**, +7: hook refresh/refetch-key/
non-destructive-error in `useQueryHistory.test.tsx`, and panel click-triggers-refresh / disabled-in-flight /
reset-to-newest / error-keeps-list in `QueryHistoryPanel.test.tsx`) all green locally. Live `/query`
browser checkpoint deferred to deploy (needs an authenticated Cognito + Athena/Glue session not
reproducible in local preview). No new dependency, no IAM/infra change.
