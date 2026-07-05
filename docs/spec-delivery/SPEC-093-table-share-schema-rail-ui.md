# Completed Spec — SPEC-093: Table Share "Share table" UI (Query Schema Rail)

## What was completed?

- **Share table menu item** in the SPEC-044 per-table options menu (`DatabaseNode`), on every **base table** in any accessible database; **absent for views** (matching the server rejection). Invokes with the rail node's database (SPEC-077 model). `TableActions` gains `onShareTable`.
- **`TableShareDialog`**: read-only `database.table`, a **Users / Shared spaces radio toggle** (fieldset+legend), a **multi-entry recipient input** — comma/space-separated names parsed via the shared `parseMemberInput`, added as **removable chips tagged with the selected kind** (mixed user+space lists allowed; Enter adds, never submits) — and a **result-name field** defaulted to the source table, validated against `CATALOG_IDENTIFIER_RE` with the standard inline guidance. Submit disabled until ≥1 recipient + valid name; busy locks form + dismissal; an enqueue failure shows a danger `Banner` and keeps entered values (FR-003). Free-text recipients only — the server owns existence/conflict checks; copy points at notifications.
- **`useTableShare(notify)`**: dialog + enqueue state; submit → `enqueueTableShare` (SPEC-089); success closes + emits the transient "Sharing…" success toast (auto-dismisses, matching the table-builder convention); failure sets `error`. Wired in `QueryWorkspace` through the existing `setToast`.
- **Help sweep (SPEC-074)**: new "Share a table" guide in the Query section (snapshot semantics, conflict behavior, notification outcomes).

## What changed from earlier specs?

- No data-layer/IAM/infra changes — `enqueueTableShare`, the queue grant, and `VITE_TABLE_SHARE_QUEUE_URL` (env example, deploy-app, GH repo var) all landed with SPEC-089. The spec's "chips" AC is met with an input+Add+chips pattern (not typeahead — optional in spec, skipped).

## Verification

12 new dialog tests + 4 hook tests + 2 axe cases + a base-table/view menu test pair; full portal suite 1026 green; lint/format/tsc clean. Live end-to-end proof of the whole arc (share → copy → recipient table queryable) is recorded in the SPEC-092 delivery note's plan: exercised from this UI once deployed.
