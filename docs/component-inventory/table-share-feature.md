# Table-share feature (`apps/portal/src/features/table-share/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `enqueueTableShare(req)` | `tableShare.service.ts` | The browser's only table-share call: builds the SPEC-089 envelope (`actor` ID token + `source` + `tableName` + `recipients[]`) and FIFO-sends to `VITE_TABLE_SHARE_QUEUE_URL` (`MessageGroupId` = `"{db}.{table}"`, dedup = SHA-256 content hash + 1-min bucket) via `getSqsClient`; `ServiceResult<void>` (enqueued ≠ shared), never throws (SPEC-089). |
| `ShareRecipient`, `TableShareRequest` | `tableShare.types.ts` | The share-request shapes matching the SPEC-089 contract (SPEC-089). |
| `useTableShare(notify)` | `useTableShare.ts` | Dialog + enqueue state for "Share table": `open(db, table)` / `close` / `submit` → `enqueueTableShare`; success closes + emits the pending toast via `notify`, failure keeps the dialog open with `error` set (SPEC-093). |
| `TableShareDialog` | `TableShareDialog.tsx` | The Share modal: read-only `db.table`, Users/Shared-spaces radio toggle, ONE combined recipient chip list with kind badges (removable, mixed kinds allowed), catalog-safe result-name field, busy lock + inline submit-error `Banner`; axe-tested (SPEC-093). **Since SPEC-148 the USER-kind entry is a `UsernameCombobox`** — still a bulk field (`onCommitMany`), still with its **Add** button (which drives the combobox's own `commit()` so button and Enter share one path). The SPACE kind keeps the plain `Input` + `parseMemberInput` with no suggestions, and the current user is deliberately NOT excluded. |

