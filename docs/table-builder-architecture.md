# Architecture Decision: Create Table from Files (the "Table Builder" control plane)

**Status:** Proposed — pending review, then drives the table-builder spec arc (SPEC-066+).
**Last Updated:** 2026-06-27
**Related:** `docs/shared-spaces-architecture.md` (the control-plane pattern this reuses), `docs/best-practices/lambdas/lambdas.md` (single-task Lambdas), SPEC-032/033 (analytics + per-DB LF model), SPEC-056/057 (membership-tag access + Files space model), SPEC-058 (notifications write pipeline).

> Read this before writing or implementing any table-builder spec. It records *why* the feature looks the way
> it does. Implementation detail lives in the arc specs (SPEC-066+) and the code; this doc is the durable
> decision record.

---

## 1. What we're building

From the **file browser**, while looking at a folder of data files (in their personal space or a shared
space), a user can press **"Create table from this folder"**, give the table a name, and have a Glue/Athena
**external table** created over those files in the **database that the space maps to** (personal DB = username;
shared DB = shared-space name). The folder may contain a set of flat data files **or** Hive-style partitioned
data (`key=value/…`); the schema is **inferred automatically**. The user is told — via the notifications inbox
(SPEC-058→060) — when the table is ready or why it couldn't be created.

Creating a Glue table over another concern's database, inferring schema with a heavy library, and running
catalog DDL are **privileged, multi-step** operations that browser-scoped credentials should not perform
directly. So, exactly like shared-space mutations, this is an **asynchronous, server-side control plane**; the
browser only **enqueues a request**.

## 2. Orchestration — a dedicated SQS → EventBridge Pipe → Step Function (decided)

The browser enqueues a **create-table request**; from there an async pipeline does the work:

```
Browser (scoped creds: sqs:SendMessage only, + the ID token in the body)
   │  request: { actor(idToken), space{kind,bucket,prefix,database}, tableName }
   ▼
SQS (FIFO) ──▶ EventBridge Pipe ──▶ Step Function (Standard; orchestrates single-task Lambdas)
                                      │
                                      ├─ validate-authorize   (verify ID token → actor; authorize access to the target space/DB; validate name + location)
                                      ├─ check-table-absent    (Glue GetTable in the target DB → fail if it already exists)
                                      ├─ inspect-source        (list the prefix; flat vs Hive-partitioned; validate one supported, consistent format)
                                      ├─ infer-schema          (polars LazyFrame on a sample object → columns; + partition keys → CREATE EXTERNAL TABLE DDL)
                                      └─ execute-ddl           (run the DDL via Athena against the target DB; MSCK REPAIR if partitioned) → success
                                   (Retry/Catch live in the state machine; a Catch routes any step's terminal failure to a recorded-failure state)
```

**Decision — a NEW, dedicated pipeline (not an action on the shared-spaces machine).** Table creation is an
unrelated workflow from shared-space lifecycle; folding a `create_table` action into the shared-spaces
orchestrator would re-broaden that role and mix concerns (against `lambdas.md` §1). Instead we stand up a
**dedicated** SQS+DLQ → Pipe → Step Function in a new `infra/modules/table-builder/` module, mirroring the
**dedicated-notifications** precedent (SPEC-058). It reuses the **pattern**, not the resources.

**Decision — single-task Lambdas orchestrated by the Step Function** (`lambdas.md` §1/§10): each step above is
its **own** Lambda with its **own least-privilege role** and shared helpers (auth/clients/notify) in a common
module/layer — never one `action`-switch monolith. The `Choice`/sequence lives in the state machine.

**Why SQS → Pipe → Step Function:** keeps the privileged surface off the user's credentials (the browser only
gets `sqs:SendMessage`), gives durable retry/replay + DLQ for a multi-step AWS provisioning flow, and makes the
validate→inspect→infer→execute pipeline explicit and observable — the same rationale as shared spaces.

**FIFO + per-database serialization.** The request queue is **FIFO** with **`MessageGroupId` = the target
database name**, so two concurrent "create table `orders`" requests against the *same* DB are processed
strictly one-at-a-time (the duplicate-name race is closed by `check-table-absent` + `CREATE EXTERNAL TABLE IF
NOT EXISTS`), while creates in *different* databases run in parallel. (Shared spaces used a single global
group; per-DB grouping is the right granularity here.)

## 3. Authorization — reuse the existing identity + access model (decided)

There is **no new access model**. The request carries the caller's Cognito **ID token**; `validate-authorize`
verifies it offline against the User Pool JWKS and derives the actor server-side (never trusts a body
`username`), exactly as the shared-space `validate` step and the pre-/post-signup Lambdas do. It then
authorizes that the actor may create a table in the **target space**:

- **Personal space:** the target database must equal the actor's own username (their personal DB / prefix).
- **Shared space:** the actor must be an **active member** of the space — checked against the **shared-spaces
  registry** (`<admin-bucket>/shared-spaces/{name}.json`, SPEC-056 source of truth). Members already hold
  Glue/LF create-table rights on the shared DB (SPEC-033/056), so a member creating a shared table is
  consistent with the model. (Owner-only is **not** required — any active member may create.)

The **table location** must resolve to within the target space's own bucket+prefix (personal user-space prefix
or `dat-prod-shared-space/{name}/…`); a request whose location escapes the space fails validation. The
**table name** must be catalog-safe (`CATALOG_IDENTIFIER_RE`, SPEC-033/048 — the same rule used for usernames,
DB names, and view names).

## 4. Source inspection & schema inference (decided)

- **Layout detection.** `inspect-source` lists the request's prefix and classifies it as **flat** (data files
  directly under the prefix) or **Hive-partitioned** (subdirectories shaped `key=value/`). Mixed/ambiguous
  layouts are a terminal failure with a clear reason.
- **Format support (v1): Parquet, CSV, JSON/NDJSON** — the three polars reads natively. A folder must be a
  **single, consistent** supported format (mixed formats = terminal failure). **ORC is out of v1** (not a
  native polars reader). 
- **Schema via polars LazyFrame.** `infer-schema` opens a **sample object** with the matching polars lazy
  scanner (`scan_parquet` / `scan_csv` / `scan_ndjson`), collects the schema, and maps polars dtypes →
  Glue/Athena (Hive) column types. **Partition columns** come from the Hive path keys (typed `string` unless
  trivially inferable) and are emitted as `PARTITIONED BY`, **not** repeated in the table column list.
- **polars packaging = Lambda layer (zip).** polars' Rust-native readers cover all three formats **without
  pyarrow**, keeping the layer small enough for the 250 MB unzipped limit and consistent with the repo's
  existing zip + placeholder-zip/`ignore_changes` packaging (no container/ECR path introduced). Only the
  `infer-schema` function attaches the layer; the other verb Lambdas stay lean (faster cold starts).

## 5. Table creation = Athena DDL (decided)

`execute-ddl` runs the generated **`CREATE EXTERNAL TABLE IF NOT EXISTS …`** through **Athena
`StartQueryExecution`** against the **target database** in the shared analytics workgroup (SPEC-032), polling
to a terminal state — the user's stated "use the create statement to run against the database." For
**partitioned** tables it then runs **`MSCK REPAIR TABLE`** to load existing partitions. Using Athena DDL
(rather than the Glue `CreateTable` API) keeps the LF-enforced create path identical to how users already
create tables in-app, and yields a real, queryable table immediately. `IF NOT EXISTS` + the prior
`check-table-absent` make the step replay-safe.

The `execute-ddl` role is the broad one (Athena run + Glue table ops on the target catalog DB + S3 read of the
source data and write of Athena results + the LF grant needed to create over the registered location). Both
buckets are already LF-registered in **hybrid** mode (SPEC-032/050); the role is made an LF principal with
`CREATE_TABLE` on target DBs + `DATA_LOCATION_ACCESS` on the registered locations (as SPEC-033 does for the
portal role per personal DB). Other verb roles stay tightly scoped (validator: registry read only; checker:
Glue GetTable; inspector: S3 list/get; infer: S3 get + the polars layer).

## 6. Async UX + notifications (decided)

The browser **never blocks** on provisioning. After enqueueing, it shows a transient "creating table…" toast;
the durable outcome is delivered through the **notifications inbox** (SPEC-058→060):

- **Each step** raises a **typed terminal failure** on a bad outcome; the Step Function `Catch` routes to a
  recorded-failure state and the responsible Lambda emits a **failure notification** to the **requesting
  actor** (e.g. *"Couldn't create table 'orders': a table with that name already exists."*, *"…: the folder
  has no supported data files."*, *"…: mixed file formats.")*.
- **execute-ddl** emits a **success notification** on terminal success (*"Table 'orders' is ready to query in
  'salesdata'."*).

This reuses the SPEC-058 **trusted-producer** `create` contract and the SPEC-061 emit pattern (per-verb role
`sqs:SendMessage` on the notifications queue + `NOTIFICATIONS_QUEUE_URL` env + a best-effort shared
`emit_notification` helper). Unlike shared-spaces' fan-out, every table-builder event has a **single
recipient: the actor**. Notifications are a **dependency** (SPEC-058) wired by the producer spec (SPEC-072);
the rest of the arc ships without it (failures still recorded in the SFN execution).

## 7. New infrastructure (summary; detail in SPEC-066)

- **`infra/modules/table-builder/`** (standalone-deployable, `compact()`-safe cross-module locals): a **FIFO
  SQS** request queue + **FIFO DLQ**; an **EventBridge Pipe** (SQS → Step Function) + role; a **Step Function**
  (Standard) orchestrating the five single-task Lambdas; **five Lambda functions** (placeholder zip +
  `ignore_changes`, Python 3.12) each with its **own least-privilege role**; a **polars Lambda layer**
  (built + published) attached to `infer-schema`; CloudWatch log groups (14-day).
- **Portal role**: `sqs:SendMessage` to the table-build request queue **only** (the sole new browser grant);
  queue URL exported as `VITE_TABLE_BUILD_QUEUE_URL`.
- **Deploy-role IAM** expanded for every new resource type (FIFO SQS + DLQ, Pipes, Step Functions, the five
  Lambdas + their roles incl. scoped `iam:PassRole`, the Lambda layer, the log groups, LF grants for the
  execute-ddl role) — per the CLAUDE.md infra rule + architecture.md "adding a new resource type" traps.

## 8. Proposed spec arc (to write after this doc is approved)

UI is folded into the feature spec (SPEC-071), as in the shared-spaces arc. Build order
**066 → 067 → 068 → 069 → 070 → 071**, with **072** after the notifications arc (SPEC-058) + the verb Lambdas.

| Spec | Scope |
|---|---|
| SPEC-066 | **Foundation infrastructure + polars runtime** — the dedicated FIFO SQS+DLQ → Pipe → Step Function **skeleton**, the five single-task Lambda infra stubs + per-verb least-privilege roles, the **polars Lambda layer**, log groups, the new module, deploy-role IAM, a control-plane smoke test. Plumbing only — no real action logic. |
| SPEC-067 | **Request contract, browser enqueue & validate-authorize** — the request envelope; portal-role `sqs:SendMessage` + `VITE_TABLE_BUILD_QUEUE_URL`; the **validate-authorize** Lambda (ID-token actor; personal/shared authorization via the shared-spaces registry; catalog-safe name + in-space location checks) + the SFN `validate` state + Catch→recorded-failure. Downstream verbs stubbed. |
| SPEC-068 | **Name uniqueness + source inspection** — **check-table-absent** (Glue GetTable) + **inspect-source** (flat vs Hive-partition layout; single consistent supported format; emit `{format, partitioned, partitionKeys, sampleObjectKey, location}`), wired as SFN states. |
| SPEC-069 | **Schema inference & DDL generation (polars)** — the **infer-schema** Lambda (polars LazyFrame on a sample; dtype→Hive mapping; partition columns from the path; generate `CREATE EXTERNAL TABLE IF NOT EXISTS … PARTITIONED BY … STORED AS … LOCATION …`), on the SPEC-066 polars layer. |
| SPEC-070 | **Execute DDL + partitions + terminal states** — the **execute-ddl** Lambda (run the DDL via Athena on the target DB; `MSCK REPAIR TABLE` if partitioned; record terminal success), SFN success/failure terminal states + Catch across all verbs, execute-ddl role LF/Glue/Athena/S3 grants. End-to-end table creation (sans notifications/UI polish). |
| SPEC-071 | **File-browser "Create table from this folder"** — the toolbar action on the current folder (personal or shared space), the table-name prompt (catalog-safe; default from folder name), enqueue via the SPEC-067 contract using the active space → bucket/prefix/database (SPEC-057), pending/toast UX. Server-side validation owns eligibility. |
| SPEC-072 | **Notification producer** — each verb Lambda emits a **failure** notification on its terminal-failure branch; **execute-ddl** emits a **success** notification — to the **actor**, via the SPEC-058 queue (verb-role `sqs:SendMessage` + `NOTIFICATIONS_QUEUE_URL` + shared best-effort `emit_notification`). Mirrors SPEC-061; depends on SPEC-058. |

## 9. Decisions

- [x] **Reverses "no backend" for table creation** (as shared-spaces did for its mutations), via a **dedicated
  SQS → EventBridge Pipe → Step Function** control plane; the browser only gains `sqs:SendMessage`. (User
  decision, 2026-06-27.)
- [x] **Dedicated pipeline, single-task Lambdas** — a new `infra/modules/table-builder/` machine + five
  per-verb least-privilege Lambdas (not an action on the shared-spaces orchestrator). (User decision.)
- [x] **Formats = Parquet, CSV, JSON/NDJSON** (v1); ORC deferred (not a native polars reader). (User decision.)
- [x] **Schema inference = polars LazyFrame**, packaged as a **Lambda layer (zip)** attached only to
  `infer-schema` (polars-native readers, no pyarrow). (User decision.)
- [x] **Table creation = Athena DDL** (`CREATE EXTERNAL TABLE IF NOT EXISTS`; `MSCK REPAIR TABLE` for
  partitions), run against the database the space maps to. (User-stated intent.)
- [x] **Authorization reuses the existing model** — ID-token-derived actor; personal = own DB; shared = active
  member (per the shared-spaces registry). Any active member may create a shared table (not owner-only).
- [x] **Outcomes delivered via notifications** (SPEC-058) — per-step failure + on-success, single recipient =
  the actor; wired in SPEC-072 (the rest of the arc is independent of notifications).

## 10. Open items to confirm at implementation

- **CSV header + options.** v1 assumes a **header row** for CSV and comma delimiter; `inspect-source`/
  `infer-schema` record/assume these. Non-header or alternate-delimiter CSV is a deferred enhancement (could be
  a future request option). Confirm the default.
- **Partition value typing.** Hive partition keys are emitted as `string` by default. Inferring numeric/date
  partition types from the values is a possible follow-up.
- **execute-ddl LF grant timing.** Granting the execute-ddl role `CREATE_TABLE`/`DATA_LOCATION_ACCESS` may hit
  the same first-apply self-grant-propagation caveat as SPEC-050/056 (architecture.md `time_sleep`); expect one
  re-run.
