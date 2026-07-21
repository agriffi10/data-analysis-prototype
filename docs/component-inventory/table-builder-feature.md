# Table-builder feature (`apps/portal/src/features/table-builder/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `enqueueTableBuild(req)` | `tableBuild.service.ts` | The browser's only table-builder call: builds the SPEC-067 envelope (`idToken` + `space` + `tableName` + `partitionKeys` + `requestId`) and FIFO-sends to `VITE_TABLE_BUILD_QUEUE_URL` (`MessageGroupId` = `space.database`, dedup = `requestId`) via `getSqsClient`; `ServiceResult<void>` (enqueued ≠ created), never throws (SPEC-071). |
| `suggestTableName(folder)`, `isValidTableName(name)` | `tableBuild.service.ts` | Pure: sanitize a folder name to a catalog-safe suggestion / test a name against `CATALOG_IDENTIFIER_RE` (UX only — server re-validates) (SPEC-071). |
| `buildPartitionKeys`, `buildPartitionKey`, `validateDraftKey`, `emptyDraftKey`, `parseValues` | `partitionKeys.ts` | Pure draft→wire partition-key logic + per-row validation (name/uniqueness, integer/date/string-enum config); empty list ⇒ valid flat `[]` (SPEC-071). |
| `CreateTableButton` | `CreateTableButton.tsx` | File-browser toolbar action → opens the dialog, enqueues for the active space + prefix, success/error `Toast` (SPEC-071). |
| `CreateTableDialog` | `CreateTableDialog.tsx` | Name prompt (suggested + validated) + optional partition-keys section; Confirm gated on name **and** keys valid; inline submit-error banner (SPEC-071). |
| `PartitionKeysField` | `PartitionKeysField.tsx` | Controlled, ordered, reorderable/removable partition-key rows (name + type `<select>` + per-type projection config) with focus management + labelled dynamic rows (SPEC-071). |
| `TableBuildRequest`, `PartitionKey`, `DraftPartitionKey`, `PartitionKeyErrors`, `PartitionType`, `PartitionKeysResult` | `tableBuild.types.ts`, `partitionKeys.ts` | The request + wire partition-key shapes (match the SPEC-067 contract) + the editor's draft/error/result types (SPEC-071). |

