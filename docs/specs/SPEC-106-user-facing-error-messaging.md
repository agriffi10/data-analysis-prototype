---
type: Spec
id: SPEC-106
title: "User-Facing Error Messaging — Friendly, Consistent, No AWS Leaks"
description: "Replaces raw AWS, Cognito and Athena error text everywhere users see it, including control-plane notifications, with short friendly messages that say how to fix it or to contact the Administrator."
spec_status: Completed
depends_on: []
---

**Dependency notes:** None (touches existing SPA services/UI + Lambda notification producers; no infra/IAM change)
## Overview

Today every error a user can hit is surfaced by passing the raw AWS/Cognito/Athena error text
straight through to the screen. Ten SPA service files hand-roll the same `{message: e.message ??
fallback, code: e.name}` helper, so an S3 `AccessDenied`, an expired-credential stack, or an Athena
`SYNTAX_ERROR: line 1:8: Column 'x' cannot be resolved` lands verbatim in a toast, a banner, or a
`<code>` block. The async control planes (table-builder, table-share, shared-spaces) do the same in
the notifications they send — a failed table build forwards the raw Athena `StateChangeReason` into
the user's inbox. There is **no** central place that turns a failure into human wording.

This spec makes user-facing error messaging friendly, short, and consistent everywhere a user can see
it. Every message either tells the user how to fix the problem in one short sentence (when it's
theirs to fix — e.g. "Add a database to each table, like `mydb.sales`.") or says "Contact the
Administrator" (when it isn't). Raw AWS/Cognito/Athena text is never shown to a user again. To keep
this from silently drifting, the mapping lives in one documented module that records **why** each
message triggers (so a developer reading the code knows which condition produced it), and the
original error is still available to developers via a dev-build-only console log — never to users.

## Scope

### In Scope

- A **single SPA error-mapping module** (`src/lib/errorMessages.ts`) that converts any caught
  error / `ServiceResult` error `{message, code}` into a user-facing `{title?, message}` — the one
  source of truth for wording. Every service and UI surface routes error text through it.
- **Rewriting the SPA service helpers** (`toServiceError`/`toError` in the 10 feature services +
  the 2 `lib/` credential helpers) so the raw AWS `.message` is no longer the user-facing string:
  services carry a stable **`code`** (an app error code, defaulting to the AWS error `name` when
  present) and the *technical* message for logging; the *display* text is produced by the mapping
  module at the surface.
- **A unified surfacing layer**: one app-level toast provider (`ToastProvider` + `useToast`)
  replacing the per-page `useState<ToastState>` pattern and the ad-hoc inline error strings, and a
  small `<ErrorBanner error=…>` convenience over the existing `Banner` that renders mapped text. The
  existing `Toast` and `Banner` presentational components are reused, not rewritten.
- **Query failure display**: stop rendering raw Athena `stateChangeReason` in the FAILED `<code>`
  banner and in the Create-view / Drop-table toasts; map common Athena engine errors (syntax,
  column/table-not-found, permission, missing-database) to friendly guidance, with a generic
  fallback otherwise.
- **The specific "missed information" cases** the user called out get first-class, fix-it wording —
  most importantly an **unqualified table name** in a query (SPEC-077: no active database, every
  base table must be `database.table`). When Athena reports the resulting failure, the app detects it
  and shows "Add a database to each table, like `mydb.sales`." rather than the raw engine text.
- **Dev-only original-error logging**: in a dev build only, the mapping module logs the original
  error (name + message + code) to the console so developers can debug; production builds log
  nothing and users never see it.
- **Developer-facing documentation of triggers**: each mapped code/pattern carries a short JSDoc/
  comment stating what condition produces it and whether it's user-fixable, so the "why does a user
  see this?" answer lives next to the mapping.
- **Consolidating the duplicated identifier message**: the catalog-identifier rule text (currently
  hand-copied in 5 dialogs) becomes one exported constant next to `CATALOG_IDENTIFIER_RE`.
- **Lambda notification sanitization** (the async control planes that write to a user's inbox):
  - `tbcommon/messages.py` and `tscommon/messages.py`: stop interpolating the raw Athena
    `StateChangeReason` `{detail}` into `ddl_execution_failed` / `ddl_timeout` / `create_failed` /
    `create_timeout` bodies. The failure notification a user reads carries only friendly text.
  - `shared-space-*` verbs (`create_space.py`, `delete_space.py`): stop putting `str(exc)` (raw
    boto3/AWS text) into the user's notification **and** into the `reason` stored in the cache
    (which the Connections card shows). Store/emit a friendly reason; keep the raw text in the log
    and the registry record for operators.

### Out of Scope

- **Preserving operator/debug detail server-side.** Raw AWS errors stay in CloudWatch logs and in
  the Step Function execution history / registry `failed` records — this spec only changes what a
  **user** sees, not what operators can inspect.
- **Pre-signup / Hosted UI messages.** `lambdas/pre-signup/pre_signup.py` already returns friendly
  text and Cognito's Managed Login renders it outside the SPA; no change.
- **Internationalization / a message catalog for non-error UI copy.** English strings only; this is
  not an i18n framework.
- **Changing which errors are retried, any IAM/infra, Step Function topology, notification transport,
  or the `ServiceResult` contract shape.** Behavior on the happy path and the success/terminal paths
  is unchanged; only failure *wording* and *routing of wording* change.
- **New notification events.** No new producers or inbox actions — only the text of existing ones.

---

## Functional Requirements

### FR-001: Central SPA error-mapping module

#### Description:

Add `src/lib/errorMessages.ts` exporting a single function that maps an error (a caught `unknown`, or
a `ServiceResult` error `{message, code}`) to a user-facing `{title?: string; message: string}`. It
resolves in this order: (1) an app error `code` it recognizes → the mapped friendly message; (2) a
known AWS/Cognito/Athena error `name`/pattern → its mapped message; (3) otherwise the generic
non-fixable fallback **"Something went wrong. Contact the Administrator."**. It **never** returns the
raw input `message`. Each mapping entry carries a one-line comment describing the trigger condition
and whether it is user-fixable. The module is the only place error wording is authored.

#### Acceptance Criteria:

- [ ] `errorMessages.ts` exports a mapper (e.g. `toUserMessage(error): {title?: string; message: string}`)
      that accepts either a thrown `unknown` or a `ServiceResult` `error` object.
- [ ] A recognized app code (e.g. `Collision`, `ProtectedObject`, `TooLarge`, `Cancelled`,
      `InvalidName`, `InvalidDestination`, credential-expiry codes) returns its authored message.
- [ ] A recognized AWS error name (e.g. `AccessDenied`, `NoSuchKey`/`NotFound`, `NetworkingError`,
      throttling) returns a friendly message; user-fixable ones give a short fix, non-fixable ones
      return "Contact the Administrator" wording.
- [ ] An unrecognized error returns the generic "Something went wrong. Contact the Administrator."
      message and **never** the raw input `message`.
- [ ] Every mapping entry has a comment stating what triggers it and whether the user can fix it.
- [ ] Unit tests cover: known code, known AWS name, unqualified-table Athena error (FR-005), and the
      generic fallback (asserting the raw message is not echoed).

### FR-002: Services stop making the raw AWS message the display string

#### Description:

Rewrite `toServiceError`/`toError` and the inline passthrough sites across the SPA so the
user-visible string is no longer `e.message`. Services keep returning `ServiceResult` (contract
unchanged) but the `error` they return carries a **stable `code`** (an app code where one applies,
else the AWS error `name`) and the raw technical message is retained only for logging — the
*display* string is derived at the surface via FR-001. Services that already build friendly messages
(collision, "already exists", marker-protected, folder-name validation) keep them and additionally
set an app `code` so the mapper passes them through unchanged.

#### Acceptance Criteria:

- [ ] The shared error helpers in the 10 feature services (`auth`, `query`, `glue`, `queryHistory`,
      `savedQueries`, `notifications`, `tableBuild`, `tableShare`, `fileBrowser`, `sharedSpaces`)
      and the 2 `lib/` helpers (`s3Client`, `awsCredentials`) no longer set the user-visible display
      text to the raw AWS `.message`.
- [ ] Existing friendly, code-tagged errors (`Collision`, `ProtectedObject`, `TooLarge`,
      `InvalidName`, `InvalidDestination`, `Cancelled`, `NotFound`) are preserved and still map to
      their current wording.
- [ ] The `deleteObjects` per-key path (`e.Message ?? e.Code`) no longer surfaces raw S3 field text;
      per-key failures carry a code the mapper turns into friendly text.
- [ ] `ServiceResult<T>`'s shape is unchanged; existing service tests pass (updated only where they
      asserted the old raw-message wording).

### FR-003: Unified toast + banner surfacing

#### Description:

Introduce an app-level `ToastProvider` and `useToast()` hook that replaces each page's private
`useState<ToastState>` + local `<Toast>` render (QueryWorkspace, ConnectionsPage, CreateTableButton,
NotificationsPage). Add an `<ErrorBanner error=…>` that wraps the existing `Banner` and renders the
FR-001-mapped `{title, message}`. All error surfaces — toasts, banners, and the current ad-hoc inline
error strings (`UploadList`, `DatabaseNode` schema-load else-branch, the auth error in `Header`) —
render mapped text, not raw error strings. The `Toast`/`Banner` presentational components and their
variants/behavior (auto-dismiss, actionable toast) are reused unchanged.

#### Acceptance Criteria:

- [ ] A `ToastProvider` is mounted once (app shell) and `useToast()` exposes push/dismiss; the four
      pages listed above use it instead of local toast state.
- [ ] `<ErrorBanner error={serviceError}>` renders the mapped title/message via FR-001; the
      file-browser and query danger banners use it.
- [ ] `UploadList`, the `DatabaseNode` schema-load failure branch, and the `Header` auth error render
      mapped text (no raw `item.error` / raw Glue message / raw Cognito message).
- [ ] No user-facing surface reads `result.error.message` directly for display; all go through
      FR-001. (Passing `error` objects around is fine; rendering the raw `.message` is not.)
- [ ] Existing toast/banner behavior (variants, auto-dismiss, actionable "View in Files" toast,
      `role="alert"`) is preserved; affected component tests pass.

### FR-004: Query failure display shows friendly guidance, not Athena text

#### Description:

The query FAILED banner (rendered in a `<code className="font-mono">`) and the Create-view /
Drop-table failure toasts currently print the raw Athena `stateChangeReason`. Route these through
FR-001's Athena mapping so a user sees friendly guidance for common cases (syntax error, table/column
not found, insufficient permissions, missing database) and the generic "Contact the Administrator"
fallback otherwise. The raw `stateChangeReason` is still logged in dev (FR-006) and retained in the
`QueryStatus`/history record for developers, just not rendered as the primary user message.

#### Acceptance Criteria:

- [ ] The FAILED-query banner shows an FR-001-mapped message; it does not render the raw
      `stateChangeReason` as the user-facing text (the raw reason may remain available as
      dev-only/collapsed detail, not the headline).
- [ ] Create-view and Drop-table failure toasts show mapped text, not raw `stateChangeReason`.
- [ ] `getTableDdl`'s failure path (View DDL) surfaces a mapped message, not `stateChangeReason`.
- [ ] Query-history rows are unaffected (they already show only a status badge).
- [ ] Tests cover a syntax error, a not-found error, and the unqualified-table case (FR-005) mapping
      to their friendly strings.

### FR-005: First-class "missed information" messages

#### Description:

The user-highlighted cases where a user *omitted required input* get explicit, fix-it wording rather
than a generic failure. The primary case: an **unqualified table name** in a query. Under SPEC-077
there is no active database, so `SELECT * FROM sales` fails at Athena with a table-not-found /
missing-database style error. Detect that class of Athena failure and show "Add a database to each
table, like `mydb.sales`." Also give first-class wording to the other omitted-input paths that reach
a user: empty/whitespace folder name (already friendly — preserve), no partition keys when the folder
is partitioned (table-builder), no recipients chosen (table-share), and an empty required dialog
field. Each such message names the missing thing and the one action to fix it.

#### Acceptance Criteria:

- [ ] A query using an unqualified base table surfaces "Add a database to each table, like
      `mydb.sales`." (or equivalent fix-it wording), driven by matching the Athena failure text/code
      in the mapping module — not by the raw engine string reaching the UI.
- [ ] The existing friendly folder-name / identifier / partition-key / recipient validation messages
      are preserved and routed through the same mapping so wording is consistent.
- [ ] Each "missed information" message states what's missing and the single action to fix it, in one
      short sentence.
- [ ] Tests assert the unqualified-table message and at least two other missed-input messages.

### FR-006: Dev-only original-error logging

#### Description:

So developers can still debug, FR-001's mapper logs the original error (name, message, code) to
`console` **only in a dev build** (`import.meta.env.DEV`), tagged so it's greppable (e.g.
`[errorMessages] <code>: <original>`). Production builds log nothing from this path and never expose
the original error to the DOM. This is captured at the mapping boundary, once, so no service needs to
sprinkle its own logging.

#### Acceptance Criteria:

- [ ] In a dev build, calling the mapper logs the original error's name/message/code to the console.
- [ ] In a production build the mapper does not log and does not place the original message in the
      returned user text or the DOM.
- [ ] The dev-log read of `import.meta.env.DEV` is at module scope / guarded so it tree-shakes out of
      the production bundle (per the `import.meta.env` CI note in `docs/process/ci-and-deploy-traps.md`).
- [ ] A test asserts the prod path returns mapped text with no raw message and does not log.

### FR-007: Consolidate the duplicated identifier message

#### Description:

The catalog-identifier rule text — "Use 3–63 characters: lowercase letters, digits, or underscore,
starting with a letter." — is hand-duplicated in five dialogs (`CreateViewDialog`, table-share
`TableShareDialog`, table-builder `CreateTableDialog`, `CreateSharedConnectionDialog`,
`partitionKeys.ts`). Export it once next to `CATALOG_IDENTIFIER_RE` in `query.constants.ts` and have
all five import it, so the identifier guidance has a single source of truth like the regex already
does.

#### Acceptance Criteria:

- [ ] One exported constant holds the identifier-rule message next to `CATALOG_IDENTIFIER_RE`.
- [ ] All five prior copies import it; no hand-duplicated copy of that string remains.
- [ ] The rendered wording is unchanged; the affected dialog tests pass.

### FR-008: Sanitize table-builder / table-share failure notifications

#### Description:

`tbcommon/messages.py` and `tscommon/messages.py` interpolate the raw Athena `StateChangeReason`
(`{detail}`) into the `ddl_execution_failed` / `ddl_timeout` (table-builder) and `create_failed` /
`create_timeout` (table-share) bodies, and `notify.py` passes `err.detail` through — so raw Athena
engine text reaches the user's inbox. Remove the raw `{detail}` from the user-facing body; the
failure notification carries only friendly text ("creating the table failed. Contact the
Administrator." or equivalent). The raw reason stays in CloudWatch logs and the SFN terminal record
for operators.

#### Acceptance Criteria:

- [ ] The `{detail}` interpolation into user-facing bodies is removed for the four DDL failure
      reasons in both `messages.py`; no `StateChangeReason` text appears in an emitted notification.
- [ ] The friendly, non-detail reasons (invalid name, table exists, no data files, etc.) are
      unchanged.
- [ ] The raw reason is still recorded where operators can see it (log / SFN terminal state / registry
      record) — only the user-facing notification changes.
- [ ] `tbcommon`/`tscommon` message tests updated to assert no raw detail leaks; existing behavior
      otherwise unchanged.

### FR-009: Sanitize shared-space create/delete failure notifications

#### Description:

`shared-space-create/create_space.py` and `shared-space-delete/delete_space.py` put `str(exc)` (raw
boto3/AWS text from Glue/S3/IAM calls) into both the user's failure notification and the `reason`
stored in the cache entry the Connections card reads. Replace the user-facing `reason` with friendly
text (e.g. `We couldn't create the shared workspace "{name}". Contact the Administrator.`), keeping
the real `str(exc)` in the log and the registry `failed` record. The friendly membership-limit case
(a deliberate custom exception) keeps its specific wording.

#### Acceptance Criteria:

- [ ] The create-failed and delete-failed **notifications** contain friendly text, not `str(exc)`.
- [ ] The **cache** `reason` the Connections card shows is friendly text, not `str(exc)`; the
      registry `failed` record and logs still keep the raw reason for operators.
- [ ] The deliberate friendly exceptions (e.g. "membership limit reached") still surface their own
      specific message.
- [ ] Shared-space verb tests updated to assert no raw AWS text in the user-facing notification/cache
      reason.

---

## Data Model

```ts
// src/lib/errorMessages.ts

/** What a surface renders: an optional bold title + one short sentence. */
export type UserFacingMessage = {
  title?: string;
  message: string;
};

/** Accepts a thrown value or a ServiceResult error object. */
type MappableError = unknown | {message?: string; code?: string};

/**
 * Map any error to friendly, user-safe text. Resolution order:
 *   1. known app `code`  2. known AWS/Cognito/Athena name/pattern
 *   3. generic "Contact the Administrator" fallback.
 * Never returns the raw input message. Logs the original to the console in dev only.
 */
export function toUserMessage(error: MappableError): UserFacingMessage;

// One authored entry per known condition. The comment on each records the
// trigger + whether the user can fix it — the "why does a user see this?" answer.
type ErrorRule = {
  /** App code or AWS error name this matches. */
  code: string;
  /** Or a matcher over the technical message (e.g. Athena "cannot be resolved"). */
  match?: (technicalMessage: string) => boolean;
  title?: string;
  message: string;
  /** True → message tells the user how to fix it; false → "Contact the Administrator". */
  userFixable: boolean;
};
```

```ts
// src/components/ToastProvider.tsx (surfacing) — app-level, distinct from the
// notifications *inbox* feature; reuses the existing features/query/Toast.tsx view.
export function useToast(): {
  push(toast: {variant: 'success' | 'danger' | 'info'; message: string; action?: {label: string; onClick: () => void}}): void;
  dismiss(): void;
};
```

The `ServiceResult<T>` type (`src/types/service.types.ts`) is **unchanged**. Services keep returning
`{success: false, error: {message, code?}}`; the change is that `message` is treated as technical
(logged, not rendered) and `code` is the stable key the mapper reads.

---

## API / Interface Contract

```ts
// Surface usage — banner
import {ErrorBanner} from '../../components/ErrorBanner';
{writeError && <ErrorBanner error={writeError} onDismiss={clear} />}

// Surface usage — toast
const toast = useToast();
const result = await createFolder(...);
if (!result.success) toast.push({variant: 'danger', message: toUserMessage(result.error).message});

// Athena-failure mapping (FR-004/005)
const {message} = toUserMessage({code: status.state, message: status.stateChangeReason});
// e.g. stateChangeReason "…Table sales does not exist…" (no db) → "Add a database to each table, like `mydb.sales`."
```

## Environment Variables

None. (Dev-only logging keys off the existing `import.meta.env.DEV`.)

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── errorMessages.ts            # FR-001/006 — the mapping + dev log (single source of truth)
│   └── errorMessages.test.ts
├── components/
│   ├── ErrorBanner.tsx             # FR-003 — Banner wrapper rendering mapped text
│   ├── ErrorBanner.test.tsx
│   ├── ToastProvider.tsx           # FR-003 — app-level toast context + useToast
│   └── ToastProvider.test.tsx
└── features/query/query.constants.ts   # FR-007 — export the identifier-rule message

lambdas/
├── table-builder-common/tbcommon/messages.py   # FR-008 — drop raw {detail}
├── table-share-common/tscommon/messages.py      # FR-008 — drop raw {detail}
├── shared-space-create/create_space.py          # FR-009 — friendly reason, not str(exc)
└── shared-space-delete/delete_space.py           # FR-009 — friendly reason, not str(exc)
```

(Plus edits to the 10 feature services + 2 `lib/` helpers for FR-002, and the surfacing edits in
FileBrowser / QueryWorkspace / ConnectionsPage / CreateTableButton / NotificationsPage / UploadList /
DatabaseNode / Header / the five identifier dialogs.)

## Implementation Phases

The SPA phases (1–4) and the Lambda phases (5) are independent and can land as separate PRs. Within
the SPA, Phase 1 is the foundation the rest consume.

### Phase 1: Mapping module + service normalization (FR-001, FR-002, FR-006)

- Build `errorMessages.ts` with the code/name/pattern rules, per-entry trigger comments, generic
  "Contact the Administrator" fallback, and the dev-only original-error log.
- Normalize the service/lib error helpers so `code` is the stable key and the raw `.message` is
  technical-only; preserve existing app codes; fix the `deleteObjects` `.Message`/`.Code` site.
- Unit-test the mapper (known code, AWS name, unqualified-table, fallback, no-raw-echo, prod no-log).

### Phase 2: Unified surfacing (FR-003)

- Add `ToastProvider`/`useToast` and `ErrorBanner`; mount the provider in the app shell.
- Migrate QueryWorkspace / ConnectionsPage / CreateTableButton / NotificationsPage toasts and the
  file-browser / query banners; route `UploadList`, `DatabaseNode` schema-load, and `Header` auth
  error through mapped text.

### Phase 3: Query + missed-information wording (FR-004, FR-005)

- Add the Athena-failure mapping (syntax / not-found / permission / missing-database → friendly),
  including the unqualified-table fix-it message; stop rendering `stateChangeReason` as the headline
  in the FAILED banner, Create-view/Drop toasts, and `getTableDdl`.
- Verify the omitted-input dialog messages route through the mapping.

### Phase 4: Identifier-message consolidation (FR-007)

- Export the identifier-rule string next to `CATALOG_IDENTIFIER_RE`; replace the five copies.

### Phase 5: Lambda notification sanitization (FR-008, FR-009)

- Remove raw `{detail}` from the four DDL failure bodies in `tbcommon`/`tscommon` `messages.py`.
- Replace `str(exc)` with friendly text in the shared-space create/delete user-facing
  notification + cache `reason`; keep raw text in logs / registry records; update tests.
```
