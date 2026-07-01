# Completed Spec — SPEC-071: Table Builder "Create Table from this Folder" (File Browser UI)

## What was completed?

The **only browser surface** of the table-builder arc: a file-browser toolbar action that
enqueues a create-table request (SPEC-067 contract) for the current folder. Frontend +
one workflow env line only — no infra, no new AWS grant beyond the SPEC-067 portal-role
`sqs:SendMessage` already in place.

- **`features/table-builder/`** (new feature):
  - **`tableBuild.service.enqueueTableBuild`** — builds the SPEC-067 envelope
    `{idToken, space:{kind,bucket,prefix,database}, tableName, partitionKeys, requestId}`,
    attaches the verified **ID token** (`getIdToken`), and FIFO-sends to
    `VITE_TABLE_BUILD_QUEUE_URL` via `getSqsClient` with **`MessageGroupId = space.database`**
    and **`MessageDeduplicationId = requestId`** (= the correlation id). Wrapped in
    `withCredentialRetry`; returns `ServiceResult<void>`, never throws. Mirrors
    `enqueueNotificationAction` exactly. Plus pure `suggestTableName` / `isValidTableName`.
  - **`partitionKeys.ts`** — pure draft→wire logic: `DraftPartitionKey` (string-backed
    inputs), `validateDraftKey` (name `CATALOG_IDENTIFIER_RE` + uniqueness; integer min<max
    + optional digits; date start/end/format; string ≥1 value), `buildPartitionKey`,
    and `buildPartitionKeys` (empty list ⇒ valid flat `[]`).
  - **`PartitionKeysField`** — optional, ordered, reorderable/removable key rows (name +
    type `<select>` + per-type projection config), controlled by the dialog; focus moves to
    the new/neighbour row on add/remove; labelled dynamic rows (fieldset/legend + per-row
    `role="group"` inside `<li>`), range-exclusion helper copy (arch §10).
  - **`CreateTableDialog`** — `Modal` + name `Input` (pre-filled `suggestTableName`, inline
    `CATALOG_IDENTIFIER_RE` validation) + `PartitionKeysField`; Confirm disabled until the
    name **and** every key are valid; inline error `Banner` on submit failure (stays open).
  - **`CreateTableButton`** — toolbar action; opens the dialog, calls `enqueueTableBuild`
    with the active space (`kind`/`bucket`/`database`) + current `prefix`, shows a success
    `Toast` (async — outcome arrives via notifications, SPEC-072) or keeps the dialog open on
    a send error.
- **`FileBrowser.tsx`** — mounts `CreateTableButton` in the toolbar, gated `writable &&
  username` (needs the space's database = marker owner = username | shared name); available
  at any folder incl. the space root. Eligibility is server-side (SPEC-067/068).
- **`deploy-app.yml`** — adds `VITE_TABLE_BUILD_QUEUE_URL` to the build env (the SPEC-067
  deferred item). **Ops action required:** set the `VITE_TABLE_BUILD_QUEUE_URL` GitHub repo
  **variable** to the queue URL, else production ships it undefined (the VITE deploy gotcha).
  `.env.example` already documented the var (SPEC-067).

## What changed from earlier specs?

- Nothing behavioural elsewhere. The wire contract is exactly SPEC-067's; partition-key wire
  shapes match the validator (integer/date/string-enum).
- **Deviation:** the spec mentions reusing a `Select` primitive — none exists in the repo, so
  the type field uses the same native styled `<select>` pattern as `SaveResultsDialog` /
  `DestinationPicker` (no new primitive introduced).

## Verification

`npm run test` (852 passed, incl. 46 new table-builder), `lint`, `format:check`, `tsc`, and
`build` all green. New tests cover: envelope/token/`MessageGroupId`/dedup for flat +
partitioned requests + SQS-error → `ServiceResult`; name suggestion + validation; partition
add/remove/reorder + per-type validation (integer min<max, date format required, string ≥1
value, duplicate blocked), empty ⇒ `[]`; the button flow (open → invalid blocks → valid
enqueues with the active space+prefix → success toast; send-error keeps the dialog open); and
no axe violations on the dialog + the dynamic partition rows.

**Not browser-verified locally:** the action only renders in the authenticated **writable**
flow; the local dev server runs the read-only dev-unauth path, which shows no write controls.
Behaviour (incl. a11y) is covered by the unit suite. A live end-to-end check belongs with the
SPEC-072 notification wiring, per `docs/testing/table-builder-e2e.md`.
