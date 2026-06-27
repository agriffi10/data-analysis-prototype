# Completed Spec — SPEC-054: Leave & Delete a Shared Space

The two terminal lifecycle actions for shared connections: a **member** leaves (revokes
only their own access); an **owner** deletes (cascades the whole space away). Both go
through the pipeline and are authorized server-side. Delivered in one PR (app + pipeline).

## What was completed?

- **App:** `LeaveSharedSpaceDialog` (simple danger confirm — leaving deletes no data) and
  `DeleteSharedSpaceDialog` (irreversible, **type-the-name** guard, given the cascade) on
  the SPEC-052 Connections screen. Per-row actions are role-gated on **active** rows:
  **Leave** for members, **Delete** for owners (never the other's). `useLeaveOrDeleteSharedSpace`
  enqueues `leave`/`delete` (no payload) — the browser makes no direct AWS call. A local
  optimistic `leaving`/`deleting` overlay shows pending until Refresh-connections
  reconciles the entry away (mirrors the `retrying` pattern).
- **Pipeline:** provisioner `leave_space` — clear the actor's slot + cache entry, drop
  them from the registry, refresh the owner projection; data/DB/other-members untouched;
  registry write **last** (retry-safe); no-op success for a non-member; defensive owner
  guard. `delete_space` (owner cascade) — flag the registry `deleting`, then: recursive S3
  delete of `dat-prod-shared-space/{name}/` (paginated, incl. marker + `athenaresults/`),
  best-effort LF revoke, drop all tables + the Glue DB, clear **every** member's slot +
  cache entry, and delete the registry object **last** (frees the name). Idempotent +
  tolerant of partial prior progress; on a hard error records terminal `failed` + reason
  (registry + owner cache) without deleting the registry, then re-raises → Fail.
- **Shared primitive:** `ConfirmDialog` gains a `confirmDisabled` prop (disables only the
  confirm button, Cancel/dismiss stay live) — backs the type-the-name guard.

Design decisions (asked + recorded): (1) on a hard delete failure record **failed + reason**
(registry + owner cache) for the screen's Retry, never a dangling `active`; (2) delete uses
the **type-the-name** guard (spec default), not a plain confirm.

## What changed from earlier specs?

- **`SharedConnectionStatus`** gains `'deleting'` (alongside existing `'leaving'`) — added to
  the type, `connectionStatusLabel`, the `StatusBadge` transient set, and the service's
  `VALID_STATUS`. **SPEC-052 `ConnectionsPage`:** gains member **Leave** / owner **Delete**
  row actions + the optimistic transition overlay. **Provisioner (SPEC-056/051/053):**
  `leave`/`delete` verbs implemented (were authorize-only stubs); `authorize` unchanged
  (its SPEC-056 owner-leave / non-owner-delete contract already gates both). **No IAM/infra
  change** — the orchestrator role already had `glue:DeleteDatabase/DeleteTable/BatchDeleteTable/GetTables`,
  `lakeformation:RevokePermissions`, shared-bucket `DeleteObject`+`ListBucket`, and registry
  `DeleteObject` (front-loaded in SPEC-050/056).

## Verification

`npm run lint` / `format:check` / `test` green — app tests cover the type-the-name gate,
Enter-to-confirm-on-match, role-gated Leave/Delete visibility, single well-formed request,
optimistic overlay, no direct AWS call, and the new `ConfirmDialog.confirmDisabled`. **33
provisioner tests** (script + CI ruff/pytest): leave (slot+cache+registry+projection, data
intact, no-op non-member, owner guard); delete (full cascade + name freed, idempotent /
partial-safe, failure recording); handler leave-for-member + delete-for-owner, and
owner-leave + non-owner-delete fail with no effect. e2e doc gains a SPEC-054 section (live
checks). Frontend deploys with the app bundle; the Lambda deploys via `deploy-lambdas.yml`.
