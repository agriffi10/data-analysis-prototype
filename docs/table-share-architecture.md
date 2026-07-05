# Architecture Decision: Share a Table Across Databases (the "Table Share" control plane)

**Status:** Proposed — pending review, then drives the table-share spec arc (SPEC-088+).
**Last Updated:** 2026-07-04
**Related:** `docs/table-builder-architecture.md` (the control-plane + clone/DDL pattern this reuses), `docs/shared-spaces-architecture.md` (registry + membership model), `docs/best-practices/lambdas/lambdas.md` (single-task Lambdas), SPEC-032/033 (analytics + per-DB LF model), SPEC-044 (schema-rail table options menu), SPEC-056/057 (shared-space access + Files space model), SPEC-058 (notifications write pipeline), SPEC-066→072 (table-builder control plane).

> Read this before writing or implementing any table-share spec. It records *why* the feature looks the way it does. Implementation detail lives in the arc specs (SPEC-088+) and the code; this doc is the durable decision record.

---

## 1. What we're building

From the **Query schema rail**, on **any table in any database the user can access** (their personal DB or a shared space they can query), a user can press **"Share table"**. A modal asks: share to **users** or to **shared connection spaces**; the **recipient names** (one or more); and the **resulting table name**. Submitting **copies the table's underlying data files** into each recipient's space under `shared_tables/{table_name}/` and **creates a table** of the given name over the copied data in each **recipient's database** (personal DB = username; shared DB = space name). The sender is told — via the notifications inbox (SPEC-058→060) — how each recipient fared; each recipient is told a table was shared with them.

This is a **one-time snapshot**: the copy reflects the source at share time and does not track later changes to the source. It is a **push** — no recipient consent step; the recipient learns via a notification (decided — see §9).

Copying another concern's data into their bucket, creating a Glue table in a database that is not the caller's, and running catalog DDL under Lake Formation are **privileged, multi-step** operations that browser-scoped credentials must not perform directly. So, exactly like shared-space mutations (SPEC-050) and table creation (SPEC-066), this is an **asynchronous, server-side control plane**; the browser only **enqueues a request**.

## 2. Orchestration — a dedicated SQS → EventBridge Pipe → Step Function (decided)

The browser enqueues a **share request**; from there an async pipeline does the work:

```
Browser (scoped creds: sqs:SendMessage only, + the ID token in the body)
   │  request: { actor(idToken), source{database,table}, tableName,
   │             recipients:[{ kind:'user'|'space', name }] }
   ▼
SQS (FIFO) ──▶ EventBridge Pipe ──▶ Step Function (Standard; orchestrates single-task Lambdas)
                                      │
                                      ├─ validate-authorize  (verify ID token → actor; authorize actor's access to the SOURCE table; validate result name; validate each recipient exists)
                                      ├─ inspect-source      (Glue GetTable on the source → base external table? flat or projection-partitioned? clone its definition; list source objects; enforce copy caps)
                                      └─ Map(over recipients):        # per-recipient, isolated, parallel
                                           ├─ check-target-absent   (Glue GetTable in the recipient DB → fail THIS recipient if the name exists)
                                           ├─ copy-objects          (server-side CopyObject of every source object → recipient shared_tables/{tableName}/…, layout preserved)
                                           └─ create-table          (clone source def, repoint LOCATION → recipient prefix; CREATE EXTERNAL TABLE IF NOT EXISTS via Athena in the recipient DB)
                                         (per-item Catch → that recipient recorded failed + actor notified; siblings continue)
                                   → success (summary)
                                   (Retry/Catch live in the state machine; a top-level Catch routes a whole-request failure to a recorded-failure state)
```

**Decision — a NEW, dedicated pipeline** (not an action on the table-builder or shared-spaces machine). Sharing is an unrelated workflow; folding it into either orchestrator would re-broaden that role and mix concerns (against `lambdas.md` §1). We stand up a **dedicated** SQS+DLQ → Pipe → Step Function in a new `infra/modules/table-share/` module, mirroring the **dedicated-notifications / dedicated-table-builder** precedent. It reuses the **pattern**, not the resources.

**Decision — single-task Lambdas orchestrated by the Step Function** (`lambdas.md` §1/§10): each step is its **own** Lambda with shared helpers (auth/registry/clients/copy/notify) in a **`table-share-common` (`tscommon`) Lambda layer** — never one `action`-switch monolith. The `Map`/sequence lives in the state machine.

**Decision — the recipient fan-out is a Step Function `Map`** (user-stated): the Map iterates the recipient list, running `check-target-absent → copy-objects → create-table` per recipient, with a **per-item `Catch`** so one recipient's failure (unknown target, name conflict, copy error) is recorded and notified **without** aborting the others (§9 conflict decision).

**Why SQS → Pipe → Step Function:** keeps the privileged surface off the user's credentials (browser gets only `sqs:SendMessage`), gives durable retry/replay + DLQ for a multi-step, potentially long S3 copy, and makes validate→inspect→copy→create explicit and observable — the same rationale as shared spaces and the table builder.

**FIFO + serialization.** The request queue is **FIFO** with **`MessageGroupId` = the source `database.table`**, so repeated shares of the same source serialize (a heavy copy doesn't overlap itself), while shares of different sources run in parallel. The recipient-name conflict race is closed **per recipient** by `check-target-absent` + `CREATE EXTERNAL TABLE IF NOT EXISTS`.

## 3. Authorization — reuse the existing identity + access model (decided)

There is **no new access model**. The request carries the caller's Cognito **ID token**; `validate-authorize` verifies it offline against the User Pool JWKS and derives the actor server-side (never trusts a body `username`), exactly as the shared-space `validate-authorize` and the table-builder do.

- **Sender must have access to the SOURCE** (user-stated "validate the user has permission to the data they're sending"): **personal** source ⇒ the source database must equal the actor's own username; **shared** source ⇒ the actor must be an **active member** of that space (checked against the shared-spaces registry `<admin-bucket>/shared-spaces/{name}.json`, SPEC-056). A source the actor cannot access fails validation (whole-request failure — nothing is copied).
- **Recipients** (decided 2026-07-04):
  - **user** recipient ⇒ must be an **existing Cognito User Pool account** (`ListUsers`/`AdminGetUser`, as SPEC-053 add-members validates); an unknown user is that recipient's terminal failure (siblings proceed).
  - **space** recipient ⇒ must **exist in the shared-spaces registry**. The sender does **not** need to be a member of the recipient space — **any space by name is a valid target** (user decision — broader collaboration over strict isolation). The privileged execution role does the write; the sender's own IAM membership tags are irrelevant to the server-side copy.
- The **result table name** must be catalog-safe (`CATALOG_IDENTIFIER_RE`, SPEC-033/048 — same rule as usernames, DB names, view names). One result name applies to **all** recipients in the request.

There is no consent/accept gate — sharing is a **direct push** (§9). This is the one place the model is more permissive than shared-spaces membership management; it is a deliberate, recorded choice for a *data-sharing convenience* feature on a greenfield app with no production users.

## 4. Source resolution & the copied table definition (decided)

**Clone the source Glue table definition — do not re-infer** (decided 2026-07-04). `inspect-source` runs Glue `GetTable` on `source.database.source.table` and reuses that table's **columns, SerDe/InputFormat/OutputFormat, `TableType`, partition keys, and `TBLPROPERTIES` (incl. partition-projection props)** verbatim. `create-table` emits the recipient DDL from this cloned definition with **only the `LOCATION` repointed** to the recipient's `shared_tables/{tableName}/` prefix. Consequences:

- **Format-agnostic.** Whatever the source table is (Parquet/CSV/JSON/ORC/…), the recipient table matches exactly — we are not re-running polars inference, so the table-builder's format limits do **not** apply here.
- **Exact schema.** No inference drift; column names/types/SerDe options are identical to the source.
- **Partitions carry over cleanly for projection tables** — the `projection.*` (+ `storage.location.template`) `TBLPROPERTIES` are copied, so the recipient table is queryable the instant `CREATE` succeeds, with **no `MSCK REPAIR`** and no partition enumeration.

**Supported source shapes (v1):** a **base external table** (`EXTERNAL_TABLE`) that is **flat** (no partition keys) **or** **partition-projection-based** (decided 2026-07-04). Rejected at `inspect-source` with a clear reason:

- **Views** — no data files to copy (a view has no `LOCATION`); out of v1.
- **Catalog-registered partitions** (partition keys present but **no** projection props — e.g. from a crawler or manual `ADD PARTITION`) — the cloned table would declare partition columns with **zero** registered partitions and return nothing. Copying partition metadata (`GetPartitions` → `BatchCreatePartition` with repointed locations) is a **deferred enhancement**; v1 rejects such a source.
- **Managed/non-external** tables, or a source whose `LOCATION` can't be resolved to a single prefix we can list.

**Copy plan & caps.** `inspect-source` lists the source `LOCATION` prefix (`tscommon.s3_listing`, reused from the table-builder) to produce the object set to copy and the total byte size, and enforces an **object-count cap** and **total-size cap** (named constants) so a pathological share can't run unbounded. The relative key layout under the source prefix is preserved under each recipient prefix (so `key=value/` partition dirs and flat files both land correctly — satisfying "works for both flat structure data and partitioned data").

## 5. The copy — parallel server-side CopyObject (decided)

`copy-objects` (inside the Map, per recipient) performs a **server-side S3 `CopyObject`** for every source object into `{recipient-base}/shared_tables/{tableName}/{relative-key}`, **parallelized** within the Lambda, preserving the key layout (decided 2026-07-04 — over S3 Batch Operations, which is deferred as the scale escape hatch). Details:

- **Same-region, server-side** copy (no bytes through the Lambda). Objects **> 5 GiB** use **multipart copy** (`UploadPartCopy`) — required by S3's single-part copy limit.
- **Recipient base prefix** resolves by kind: **user** ⇒ `s3://<user-space-bucket>/{recipientUsername}/shared_tables/{tableName}/`; **space** ⇒ `s3://dat-prod-shared-space/{spaceName}/shared_tables/{tableName}/`. Both live inside an already-LF-registered (hybrid) bucket, so the created table's `LOCATION` is a valid registered data location.
- **Idempotent / replay-safe.** A retried `copy-objects` re-copies (overwrite of identical keys is harmless); `check-target-absent` + `IF NOT EXISTS` keep the create replay-safe. Because a name **conflict** fails the recipient *before* copying (§9), we don't clobber an existing recipient table's data.
- **Long copies** are why the pipeline is a Step Function (Map item can run a long time; SFN gives durable state + retry). If a single recipient's object set is very large, the size cap (§4) applies; beyond it, that recipient fails with a "too large for v1 — use a shared space" reason (S3 Batch Ops is the future path).

## 6. Recipient table creation = Athena DDL (decided)

`create-table` runs the cloned **`CREATE EXTERNAL TABLE IF NOT EXISTS …`** (LOCATION repointed) through **Athena `StartQueryExecution`** against the **recipient database** in the shared analytics workgroup (SPEC-032), polling to a terminal state — identical to how the table-builder creates tables, so the LF-enforced create path is the same one users already exercise. `IF NOT EXISTS` + the prior `check-target-absent` make it replay-safe. Projection props ⇒ **no `MSCK`**; a flat table is immediately queryable.

## 7. Execution role — one shared role, Lake Formation admin (decided)

Mirroring the table-builder's post-072 consolidation, the Step Function **and all five verb Lambdas share ONE execution role** (union policy in `infra/modules/table-share/policies/execution.json.tftpl`); per-verb roles are **not** used (user-stated: "one execution role that is an LF admin"). That one role is a **table-share Lake Formation admin** (analytics `data_lake_settings`) so it can:

- `glue:GetTable` on the **source** (which may be an LF-gated personal/shared DB — the same `AccessDenied`-vs-`EntityNotFound` foot-gun the table-builder hit, §table-builder-arch, forces the LF-admin grant),
- `glue:GetTable` on each **recipient** DB (conflict check),
- **`CREATE_TABLE`** on recipient DBs + **`DATA_LOCATION_ACCESS`** on the registered recipient locations (as SPEC-033 does per personal DB),
- **S3 read** on both buckets (list/get source objects) and **S3 write** on both buckets (put copied objects under any `{...}/shared_tables/...` prefix) + Athena results,
- **Athena** run/poll for the DDL, and `cognito-idp` `ListUsers`/`AdminGetUser` (recipient-user validation), registry `GetObject` (source/space membership + space existence), `sqs:SendMessage` on the **notifications** queue.

`module.analytics` must `depends_on module.table_share` so the role exists before it is named an LF admin (LF rejects unknown principals) — same ordering caveat as the table-builder. Expect the SPEC-050/056/070 first-apply self-grant-propagation caveat (`time_sleep`) on the LF grants; one re-run may be needed.

## 8. Async UX + notifications (decided)

The browser **never blocks**. After enqueueing, it shows a transient "sharing table…" toast; durable outcomes go to the **notifications inbox** (SPEC-058→060):

- **Sender (actor)** gets a notification **per recipient outcome** — success (*"Shared 'orders' to user alice as 'orders'."*) or failure with the reason (*"Couldn't share 'orders' to space salesteam: a table named 'orders' already exists there."*, *"…to user bob: no such user.")*. (A batch summary vs. per-recipient granularity is a SPEC-094 detail; the recorded terminal reasons drive it.)
- **On success, the recipient party is also notified** (decided 2026-07-04): a **user** recipient in their own inbox (*"alice shared table 'orders' with you in 'yourdb'."*); a **shared-space** recipient via the **space's owner** (resolved from the registry `owner`) — *"alice shared table 'orders' into your space 'salesteam'."* — **the owner only**, never the space broadly and never its non-owner members.
- **Failures notify the sender only** — no recipient/owner notification on a failed recipient or a whole-request failure.

This reuses the SPEC-058 **trusted-producer** `create` contract and the SPEC-061/072 emit pattern (execution-role `sqs:SendMessage` on the notifications queue + `NOTIFICATIONS_QUEUE_URL` env + a best-effort shared `emit_notification` helper). Unlike the table-builder's single-recipient model, table-share **fans out to the actor + (on success) the per-recipient target** (the user, or the recipient space's owner). Notifications are a **dependency** (SPEC-058) wired by the producer spec (SPEC-094); the rest of the arc ships without it (per-recipient outcomes are still recorded in the SFN execution).

## 9. Key behavioral decisions (from the 2026-07-04 Q&A)

- [x] **Push, no consent.** The share copies + creates immediately; the recipient is notified (not asked). No pending/accept store. (User decision.)
- [x] **Notification targets (decided 2026-07-04).** The **sender** is notified of **every** outcome (success + failure). On **success**, the recipient party is also notified — a **user** recipient directly, a **shared-space** recipient via the **space's owner** (from the registry), owner-only (no member fan-out). **Failures notify the sender only.** (User decision.)
- [x] **Clone the source table definition** (not re-infer) — exact schema/SerDe/partition-projection, LOCATION repointed. Format-agnostic. (User decision.)
- [x] **Parallel server-side `CopyObject`** (multipart for >5 GiB), preserving layout, with object-count + total-size caps; S3 Batch Operations deferred as the scale escape hatch. (User decision.)
- [x] **Any shared space is a valid target** by name — the sender need **not** be a member of the recipient space (the execution role does the write). Source access still requires membership/ownership. (User decision.)
- [x] **Conflict = fail that recipient only** (no overwrite): if the name exists in a recipient DB (or the target prefix is non-empty), that recipient is recorded failed + notified; siblings proceed. (User decision.)
- [x] **v1 sources = flat or partition-projection base external tables.** Views and catalog-registered-partition tables are rejected with a clear reason; copying partition metadata is deferred. (User decision.)
- [x] **One shared execution role = LF admin** for all five verbs (not per-verb roles). (User-stated.)
- [x] **Recipient data lands at `{recipient-base}/shared_tables/{tableName}/`**, layout preserved (flat + `key=value/`). (User-stated.)
- [x] **One-time snapshot** — no ongoing sync from source to copies. (Implied by "copying the data files"; recorded to set expectations.)
- [x] **Entry point = the Query schema-rail per-table options menu** (SPEC-044), on any accessible table. (Derived from "click on any table in the Databases they have access to.")

## 10. New infrastructure (summary; detail in SPEC-088)

- **`infra/modules/table-share/`** (standalone-deployable, `compact()`-safe cross-module locals): a **FIFO SQS** request queue + **FIFO DLQ**; an **EventBridge Pipe** (SQS → Step Function) + role; a **Step Function** (Standard) orchestrating five single-task Lambdas via a recipient `Map`; **five Lambda functions** (placeholder zip + `ignore_changes`, Python 3.12) on **one shared execution role**; a **`table-share-common` Lambda layer** (built + published in CI, attached to all five); CloudWatch log groups (14-day).
- **Portal role**: `sqs:SendMessage` to the table-share request queue **only** (the sole new browser grant); queue URL exported as `VITE_TABLE_SHARE_QUEUE_URL` (deploy-app build env **and** a GH repo var).
- **Deploy-role IAM** expanded for every new resource type (FIFO SQS + DLQ, Pipes, Step Functions, the five Lambdas + their shared role incl. scoped `iam:PassRole`, the Lambda layer, the log groups, LF grants + admin for the execution role) — per the CLAUDE.md infra rule + architecture.md "adding a new resource type" traps.
- **Analytics module** gains `depends_on module.table_share` for the LF-admin ordering (§7).
- **No new bucket** — recipients reuse the existing user-space bucket and `dat-prod-shared-space`; the registry reuses the existing admin bucket (read-only here).

## 11. Proposed spec arc (to write after this doc is approved)

UI is folded into the feature spec (SPEC-093), as in the other arcs. Build order **088 → 089 → 090 → 091 → 092 → 093**, with **094** after the notifications arc (SPEC-058) + the verb Lambdas.

| Spec | Scope |
|---|---|
| SPEC-088 | **Foundation infrastructure + common layer** — the dedicated FIFO SQS+DLQ → Pipe → Step Function **skeleton**, the five single-task Lambda infra stubs on **one shared execution role**, the **`table-share-common` layer**, log groups, the new module, deploy-role IAM, a control-plane smoke test. Plumbing only — no action logic. |
| SPEC-089 | **Request contract, browser enqueue & validate-authorize** — the request envelope (`source`, `tableName`, `recipients[]`); portal-role `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`; the **validate-authorize** Lambda (ID-token actor; authorize actor's access to the **source** table; catalog-safe result name; validate each recipient exists — users via Cognito, spaces via registry) + the SFN `validate` state + Catch→recorded-failure. Downstream verbs stubbed. |
| SPEC-090 | **Source resolution + copy plan (inspect-source)** — Glue `GetTable` on the source; reject views / catalog-partitioned / non-external sources; clone the table definition; list the source objects (`tscommon.s3_listing`); enforce object-count + total-size caps; emit `{ tableDefinition, objects[], location, partitioned }`, wired as an SFN state. |
| SPEC-091 | **Recipient Map + copy (check-target-absent + copy-objects)** — the SFN `Map` over recipients with per-item `Catch`; **check-target-absent** (Glue `GetTable` in the recipient DB → fail that recipient on conflict; also treat a non-empty target prefix as a conflict) + **copy-objects** (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving into `shared_tables/{tableName}/`). Per-recipient terminal reasons recorded. |
| SPEC-092 | **Recipient table creation + terminal states (create-table)** — clone the source def, repoint `LOCATION`, run `CREATE EXTERNAL TABLE IF NOT EXISTS` via Athena against the recipient DB (projection ⇒ no `MSCK`); SFN success (summary) + per-recipient/whole-request failure terminals; the shared execution role's LF/Glue/Athena/S3/Cognito grants. End-to-end share (sans notifications/UI polish). |
| SPEC-093 | **Query schema-rail "Share table" UI** — a **Share table** action in the SPEC-044 per-table options menu (any accessible table); the modal (recipient kind: **users** vs **shared spaces**; multi-entry recipient names; result table name, catalog-safe, default = source table name); enqueue via the SPEC-089 contract using the source node's `database.table`; pending/toast UX. Server-side validation owns eligibility. |
| SPEC-094 | **Notification producer** — the verb Lambdas emit outcomes to the **actor** (per-recipient success/failure) and to **each recipient** (a "table shared with you" on success), via the SPEC-058 queue (execution-role `sqs:SendMessage` + `NOTIFICATIONS_QUEUE_URL` + the shared best-effort `emit_notification`). Mirrors SPEC-061/072; depends on SPEC-058. |

## 12. Open items to confirm at implementation

- **Non-empty target prefix as a conflict.** §9 fails a recipient whose table name exists. We additionally treat a **non-empty `shared_tables/{tableName}/` prefix** in the recipient as a conflict (prevents mixing a new copy into leftover data from a prior partial run). Confirm during SPEC-091.
- **LF grant timing.** The execution role's `CREATE_TABLE`/`DATA_LOCATION_ACCESS` + LF-admin grant may hit the SPEC-050/056/070 first-apply self-grant-propagation caveat (`time_sleep`); expect one re-run.
- **Copy caps.** Pick concrete `SHARE_MAX_OBJECTS` / `SHARE_MAX_TOTAL_BYTES` defaults in SPEC-090 (sized so a Map item finishes within the Lambda timeout with multipart copies); document the "too large — use S3 Batch Ops (deferred)" failure reason.
- **Source `LOCATION` normalization.** A source table whose `LOCATION` is not a clean single prefix (e.g. object-level location, or a `LOCATION` outside the space's bucket) is a validation failure — nail the exact rule in SPEC-090.
- **Recipient == source no-op.** Sharing a table back into its own database under the same name is a self-conflict (fails at `check-target-absent`); a different name in the same DB is a legitimate in-place copy — allow it.
