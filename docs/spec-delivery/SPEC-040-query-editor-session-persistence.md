# Completed Spec — SPEC-040: Query Editor Session Persistence + Clear Button

## What was completed?

- The query editor's **un-run SQL now survives tab switches (Files↔Query remount) and page reloads**
  within the browser session, and a **Clear** control empties it in one click.
- `queryDraft.ts` — typed `sessionStorage` wrapper: `readQueryDraft` / `writeQueryDraft` /
  `clearQueryDraft`, keyed per-user (`s3portal.query.draft.{username}`, prefix
  `QUERY_DRAFT_STORAGE_PREFIX` in `query.constants.ts`). Swallows all storage failures (disabled /
  quota) → degrades to "not persisted," never throws. Empty username (dev-unauth) is a no-op.
- `QueryWorkspace` — seeds `sql` once at mount from `readQueryDraft(username) || DEFAULT_SQL`; an
  `applySql` helper persists on every editor change (and on history re-open / re-run / schema-insert,
  since those route through it). Clear bypasses `applySql` so the removed key is not re-written.
- `ClearQueryDialog` — warn-and-confirm before wiping (SPEC-026 pattern, mirrors `DeleteConfirmDialog`:
  `alertdialog`, Escape/backdrop cancel, focus defaults to Cancel, no undo). Toolbar **Clear** ghost
  button (`aria-label="Clear query"`) sits left of History; disabled while a query is in flight or the
  editor is already empty.

## What changed from earlier specs?

- `QueryWorkspace` (SPEC-035): editor `onChange` and the SPEC-036 history re-open/re-run handlers now
  go through `applySql` instead of bare `setSql`, so the persisted draft stays in sync. No signature
  or behavior change to the data layer, services, or IAM.

## Verification

`npm run lint`, `npm run test` (403 pass — +9: `queryDraft` read/write/clear/per-user/empty-user/
error-swallow, plus workspace restore-on-mount, fallback-to-default, and the Clear confirm/cancel/
in-flight-disabled flows), and `npm run build` all pass locally. Live browser checkpoint (type → switch
tabs → reload → text persists; Clear → confirm → empties) deferred to deploy — `/query` needs an
authenticated Cognito + Glue session not reproducible in local preview. No new dependency, no IAM change.

> **Note for SPEC-041 (tabs):** as flagged in 040's Open Questions, the multi-tab model supersedes the
> single-draft store — `QUERY_DRAFT_STORAGE_PREFIX`, `queryDraft.ts`, and the `applySql` single-string
> wiring are the migration surface. `ClearQueryDialog` is reusable as-is.
