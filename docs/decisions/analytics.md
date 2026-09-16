# Analytics, the catalog, and two SQL dialects

Part of the **Key Decisions register** — [`INDEX.md`](INDEX.md) is the router, and `CLAUDE.md`
carries a table pointing at each area's Fences. This file opens with those fences — the traps that
apply green and fail later — and holds the reasoning, the constraints and the explicit "do NOT
build" fences for one area beneath them. **Read the Fences before working in the area, then the
entry you need, not the file.**

## Contents

- [Fences](#fences)
- [Analytics (SPEC-032→036)](#analytics-spec-032036)
- [Query workspace has NO active database (SPEC-077)](#query-workspace-has-no-active-database-spec-077)
- [Multi-statement scripts (SPEC-078)](#multi-statement-scripts-spec-078)
- [Table Builder (SPEC-066→072)](#table-builder-spec-066072)
- [Table Share (SPEC-088→094)](#table-share-spec-088094)
- [Data-quality report view (SPEC-113)](#data-quality-report-view-spec-113)
- [Data-quality runs index + dashboard (SPEC-123)](#data-quality-runs-index--dashboard-spec-123)
- [Control-plane table creation = TBAC (SPEC-070/111 correction)](#control-plane-table-creation--tbac-spec-070111-correction)
- [Refresh eligibility turns on SHAPE, never on a marker (SPEC-143)](#refresh-eligibility-turns-on-shape-never-on-a-marker-spec-143)
- [Removing a column requires an explicit opt-in, and the refusal IS the warning (SPEC-144)](#removing-a-column-requires-an-explicit-opt-in-and-the-refusal-is-the-warning-spec-144)
- [The refresh apply replaces the definition in place (SPEC-149, supersedes SPEC-144's apply)](#the-refresh-apply-replaces-the-definition-in-place-spec-149-supersedes-spec-144s-apply)
- [A per-table lock serializes refresh, because the catalog cannot (SPEC-157)](#a-per-table-lock-serializes-refresh-because-the-catalog-cannot-spec-157)
- [Every DDL literal goes through `literal()` (SPEC-151)](#every-ddl-literal-goes-through-literal-spec-151)
- [A generalized signature is the whole point of the second extraction, and one moved constant must not be renamed (SPEC-177)](#a-generalized-signature-is-the-whole-point-of-the-second-extraction-and-one-moved-constant-must-not-be-renamed-spec-177)
- [The renderer's signature is the rule, and the browser's first SQL value interpolation is two gates wide (SPEC-178)](#the-renderers-signature-is-the-rule-and-the-browsers-first-sql-value-interpolation-is-two-gates-wide-spec-178)
- [A space maps to ONE database, so the picker has no database step — and a deep link resolves without asking (SPEC-179)](#a-space-maps-to-one-database-so-the-picker-has-no-database-step--and-a-deep-link-resolves-without-asking-spec-179)
- [Calc computes what only the browser has, grouping computes what only Athena can, and the percentage says which page it is of (SPEC-182)](#calc-computes-what-only-the-browser-has-grouping-computes-what-only-athena-can-and-the-percentage-says-which-page-it-is-of-spec-182)
- [A saved exploration follows the flag that owns the STORE, not the one that owns the screen (SPEC-183)](#a-saved-exploration-follows-the-flag-that-owns-the-store-not-the-one-that-owns-the-screen-spec-183)
- [Results are read only at SUCCEEDED, and `isPending` is not a substitute (2026-08-16)](#results-are-read-only-at-succeeded-and-ispending-is-not-a-substitute-2026-08-16)
- [`stateChangeReason` rides a 200 and the wording is chosen in the browser (SPEC-199)](#statechangereason-rides-a-200-and-the-wording-is-chosen-in-the-browser-spec-199)
- [A stale result must not be served at all, so the eviction reaches the tab in front of you (2026-08-19)](#a-stale-result-must-not-be-served-at-all-so-the-eviction-reaches-the-tab-in-front-of-you-2026-08-19)
- [A column name is user data, and the renderer must be safe without it being validated (2026-08-19)](#a-column-name-is-user-data-and-the-renderer-must-be-safe-without-it-being-validated-2026-08-19)
- [Athena's two dialects need two escapers in the browser, and the second was missing (2026-08-19)](#athenas-two-dialects-need-two-escapers-in-the-browser-and-the-second-was-missing-2026-08-19)
- [A table's LOCATION is read recursively, so the space root is not a data folder (2026-08-19)](#a-tables-location-is-read-recursively-so-the-space-root-is-not-a-data-folder-2026-08-19)
- [A result's total is Athena's own count, and only a SELECT's count is the grid's (SPEC-231)](#a-results-total-is-athenas-own-count-and-only-a-selects-count-is-the-grids-spec-231)
- [A CSV is checked against the columns its table declares, and a refusal is for the misread a report cannot show (2026-09-16)](#a-csv-is-checked-against-the-columns-its-table-declares-and-a-refusal-is-for-the-misread-a-report-cannot-show-2026-09-16)
- [Data-quality merges column names that differ only by case across files, and refuses them inside one (2026-09-16)](#data-quality-merges-column-names-that-differ-only-by-case-across-files-and-refuses-them-inside-one-2026-09-16)
- [A CSV column named after a partition keeps its values under a new name, instead of being refused (2026-09-16)](#a-csv-column-named-after-a-partition-keeps-its-values-under-a-new-name-instead-of-being-refused-2026-09-16)

## Fences

An in-app Athena/Glue/Lake Formation workspace. Isolation is the `username` principal tag on the
Glue database ARN — **not** LF-Tags. Table creation is **TBAC**: LF admin does **not** grant
`CREATE_TABLE`; a `portal-managed` LF-Tag plus one tag-policy grant per execution role does.

- **The query workspace has NO active database.** Every base table is fully qualified
  `database.table`; the rail is browse-only. A space maps to exactly one database, so the picker has
  no database step.
- **Every DDL literal goes through `literal()`** — `TBLPROPERTIES` and `LOCATION` included — and
  the escapers split on **two axes that are easy to conflate**. *Values:* `ddl.literal`
  backslash-escapes (Hive/DDL), `sql._literal_dml` and the browser's `sqlLiteral` double the quote
  (Trino/DML). *Identifiers:* `sqlIdentifier` (Trino, `CREATE VIEW`), `sqlDdlIdentifier` and
  `ddl.quote` (Hive, `DROP`, inner backtick doubled — data-quality partition keys come from S3 folder
  names). **The wrong one fails SILENTLY, as a predicate that never matches**, and it matters because
  a shared space's name is format-checked **nowhere** server-side. A quoting fix is not done until
  every statement built from the same value is swept.
- **A column name is user data.** Creates refuse empty, non-`[a-z0-9_]`, over-255 and fold-collision
  names. A data-quality check judges a fold collision **per file** and merges one across files into
  one column, as Athena reads it — judged on the union, a collision inside one file merges too and
  shifts a CSV. A refresh skips the check, or it would strand pre-rule tables, but its diff still
  refuses a fold collision. **Every step of a refresh, and the DDL builder's partition-key match,
  folds through `columns.fold`, which is `lower()` and never `casefold()`**: the second merges `ß`
  into `ss`, so a diff and a write folding differently removed a column without the opt-in, and a
  match by exact name left a header `Year` beside the key `year`, which Athena refuses as a repeated
  column.
- **A CSV is read by POSITION, so a column naming a partition key is kept under a new name, never
  dropped or refused.** `ddl.declare_columns` renames it `<fold>_in_file` in its place — in a
  create, a refresh's diff and write, and data-quality's temp table and figures — because dropping
  it answers every later column with its neighbour's values; Parquet and JSON are matched by name
  and leave it out. In a CSV, cross-file agreement checks each file against the columns the table
  DECLARES, by the files' names — comparing files with each other read a swap as agreement.
- **A table's `LOCATION` is read recursively**, so the space root is not a data folder — and
  **both planes that build one over a user's folder refuse it**, table-builder on a create and
  data-quality on a check. Excluding the app-managed sub-trees from the plane's LISTING does not
  help, which is the trap: the manifest is what the plane knows about, the location is what Athena
  reads. A single FILE at the root is not this case — its queries carry a `"$path"` predicate,
  **decided once, by inspect-source, and carried on the state**: a verb that re-reads the manifest
  re-decides, and the manifest is an object that can change between two reads.
- **Results are read only at `SUCCEEDED`.** A too-early `GetQueryResults` reached users as a generic
  "contact the administrator"; the API now answers **409 `QueryNotFinished`**, classified by Athena's
  **message** — the same `InvalidRequestException` is a malformed query at submit, and a name-keyed
  mapper passes any test exercising one at a time. The client gate is **kept**, and asserts on the
  **CALL**: with the 409 in place the screen looks right either way.
- **A result's total is Athena's `OutputRows`, and only a `SELECT`'s count is the grid's.** A walked
  page is a billed API call, never "free", so the count comes from `GetQueryRuntimeStatistics` in
  one call, and the exact walk runs only where Athena does not count. `EXPLAIN` is **DML**, and it
  reports **1** over a many-row plan, so the rule needs `SubstatementType` `SELECT`, never
  `StatementType` alone — a DML-keyed rule passes every test that uses a real `SELECT`. The total is
  **never capped** (Andrew's ruling). A pending count walks only after the seventh ask, and a failed
  ask never walks, so a broken route shows as a missing total, not as the old cost.
- **A failed query is a 200.** `stateChangeReason` rides the body byte-identical and the browser
  picks the sentence; enveloping it retires six authored ones at a stroke. Lake Formation denies in
  **two shapes** — a Glue 403, and an execution that reaches FAILED on a 200 — and a 403 is **never**
  a re-login. `dataScannedBytes` is `null` while non-terminal, never `0`. The generic sentence is
  reserved for what a user **cannot** act on, held by a computed `USER_FIXABLE_CODES`.
- **A refresh is judged by SHAPE, not by a marker** — never by the `portal.managed` property it also
  writes, which pre-existing tables lack and users can set. Removing a column needs an opt-in, and
  **the refusal is the warning**. The apply is a read-modify-write on the live table, serialized by a
  per-table lock whose loser is **refused with a notification**, never queued.
- **Multi-statement scripts** split client-side on `;`, run sequentially, stop on first failure. No
  transactions.

## Analytics (SPEC-032→036)

In-app Athena/Glue/Lake Formation query workspace. Per-user isolation = the **`username` IAM principal tag** on the Glue DB/table ARN (DB name = username), **not LF-Tags**; single shared role; user-space bucket registered in LF **hybrid** mode; results in `{username}/athenaresults/` (delete-denied). Detail: SPEC-032, architecture.md.

## Query workspace has NO active database (SPEC-077)

Supersedes SPEC-047/076. Database *selection* is removed entirely — no "current database" anywhere. Queries carry **no** `QueryExecutionContext.Database`, so every base table must be **fully-qualified `database.table`** (an unqualified name fails); this enables cross-database joins in one statement. The schema rail (`useConnections` seam) is **browse-only** (no radio/active); per-table actions (View DDL/data/Drop) take the DB from the rail node; Create view **derives** its target DB from the body's qualified tables; autocomplete (`useAllSchemas`) spans **all** accessible databases with fully-qualified suggestions. The rail no longer inserts into the editor (FR-004 dropped, user decision). Results always land in the personal prefix; shared save destinations stay a Save-time choice (SPEC-049/055).

## Multi-statement scripts (SPEC-078)

The editor splits `;`-separated statements client-side and runs them **sequentially, stop-on-first-failure**, one history entry each; three run scopes — **Run Statement** (⌘⏎, selection/cursor), **Run Script single-result** (⌘⇧⏎), **Run Script tab-per-statement** (⌘⌥⏎, ephemeral per-run **result tabs**; DDL/DML earn none). No transactions (Athena has none); statements never run in parallel. Detail: SPEC-078 + delivery doc.

## Table Builder (SPEC-066→072)

"Create a Glue/Athena table from a folder of files" via a **dedicated** async control plane (its own FIFO SQS → EventBridge Pipe → **linear** Step Function → five single-task verb Lambdas `validate-authorize → check-table-absent → inspect-source → infer-schema → execute-ddl`) sharing **one execution role** (all five verbs; consolidated from the SPEC-066 per-verb roles — user decision, mirroring shared-spaces) + `tbcommon` and polars, which were CI-built **layers** until SPEC-213 and now come from the fleet's one container image. **Partitions:** keys are **user-declared in the modal in granularity order** (Hive `key=value/`, never auto-detected), exposed via **Athena partition projection** (no `MSCK REPAIR`); per-key type+range collected in the modal. **CSV is not type-inferred** (all-string, OpenCSVSerde); Parquet/JSON infer + parse dates. **The shared execution role creates tables via the `portal-managed` LF-Tag (TBAC), NOT via LF-admin status** (SPEC-070/111 correction — LF *admin* alone does NOT grant CREATE_TABLE; target DBs are dynamic per-user/per-shared-space so are tagged at provision time and the role is granted on the tag + a static per-bucket DATA_LOCATION_ACCESS; see the Control-plane TBAC decision below; IAM otherwise scoped, delete denied). Any **unexpected (non-Terminal/non-Transient) verb error notifies the actor** via `tbcommon.notify.notifies_on_failure` (no more silent failures); SFN terminal states record `{…, status: created|failed, reason}` (the outcome SPEC-072 notifies from). Decision record: `lambdas/info/planes/table-builder.md`. Do NOT build MSCK-based partition loading or auto-detect partition keys.

## Table Share (SPEC-088→094)

**COMPLETE:** "share a table across databases" — from the Query schema rail, copy a table's data files into recipient spaces under `shared_tables/{table}/` and create a clone table in each recipient DB (personal users and/or shared spaces). Its own **dedicated** async control plane (FIFO SQS+DLQ → Pipe → Standard SFN with a recipient `Map`, single-task Lambdas + `tscommon` (a **layer** until SPEC-213; now in the fleet image), **one shared execution role** — creates tables via the `portal-managed` LF-Tag, not LF-admin status; SPEC-070/111 correction). SFN: validate-authorize (actor must have **source** access — personal=own DB, shared=active member) → inspect-source (**clone the source Glue table definition**, not re-infer; reject views/catalog-partitioned/non-external; cap object count+size) → Map(recipient): check-target-absent (fail-that-recipient on conflict, no overwrite) → copy-objects (parallel server-side `CopyObject`, multipart >5 GiB, layout-preserving) → create-table (repoint `LOCATION`, Athena `CREATE EXTERNAL TABLE IF NOT EXISTS`; projection ⇒ no `MSCK`). **Push** (no consent; recipient notified); **any shared space is a valid target** (sender needn't be a member — source access still gated); v1 sources = flat or projection-partitioned base external tables. UI = schema-rail per-table **"Share table"** (`features/table-share/` dialog + `useTableShare`, SPEC-093); **outcomes = SPEC-058 notifications** (sender per-recipient success/failure + whole-request failure; on success the recipient user / space **owner** is also told — `tscommon.notify`/`messages`, best-effort, `sqs:SendMessage` on the notifications queue only, SPEC-094). ~~New browser grant: `sqs:SendMessage` + `VITE_TABLE_SHARE_QUEUE_URL`.~~ **— superseded by SPEC-200:** the browser holds no grant; a share is a `POST /v1/enqueue/table-share` to the API, whose execution role writes the queue. Decision record: `lambdas/info/planes/table-share.md`. Do NOT build a consent/accept flow, schema re-inference, or catalog-partition-metadata copy in v1.

> **Amended (SPEC-160, 2026-08-10) — S3 Batch Operations is REJECTED, not deferred.** The original fence read "do NOT build … S3 Batch Ops … in v1", which recorded it as the scale path to reach for later. It is not one. Its Copy operation **cannot rewrite a key**: `TargetKeyPrefix` prepends to the *full* source key, so a job can only ever produce `bob/shared_tables/sales/alice/tables/sales/year=2024/part-0.parquet` — the sender's own prefix layout echoed inside the recipient's space, with the clone's `LOCATION` pointed at a path naming the sender's directory structure. It also caps objects at **5 GB**, where `tscommon.copy` already handles more via `UploadPartCopy`, and one job writes to exactly one destination bucket while recipients span two. The scale path is a **top-level Step Functions Distributed Map** over a flat `(recipient × object)` JSONL manifest in the admin bucket, running the existing copy code unchanged (SPEC-160), with the engine on `cpcommon.transfer` because the send-files plane (SPEC-164→167) is its second caller. **Do not re-propose Batch Ops** — the refusal is a property of the API, not of the current implementation.

## Data-quality report view (SPEC-113)

The report is read at `/data-quality/:space/:requestId` — **the space is in the route, not derived**, because `requestId` alone cannot say which space holds `{space}/_data-quality-reports/{requestId}/report.json`. Resolution precedence: the actor's **own username always wins**; shared-space names are consulted only when the segment differs (SPEC-114's link builder pins the same rule). An unreachable space renders the friendly denied state and **issues no S3 request** — no existence oracle. The SPA's report types mirror `dqcommon/report.py` byte-for-byte; the banner **warns on `hasIncompleteFigures`** and only softly qualifies on `hasApproximateFigures`, which is true on every report the arc can produce. Detail: `spec-delivery/SPEC-113`.

> **Fixed (2026-09-16) — a folder's report named it without its slash, so Open folder opened the
> parent.** SPEC-112 and SPEC-123 both specify `"location": "alice/sales/"` for the report and the
> runs-index entry, but validate-authorize normalises the location with `posixpath.normpath`, which
> drops the slash, and every verb threaded that form — so the report, the completion notification and
> the runs row all named a folder the way a file is named, and `sourceFolderPrefix` reduced it to its
> parent. The code had drifted from the contract; the browser's fixtures and assemble-report's own
> test event were written to the contract, which is why nothing caught it. `assemble-report` now
> spells the location from the `pathFilter` inspect-source carries — a folder target has none — and
> threads that form onward, so one fix corrects all three places the location is shown. It reads the
> value through `carried_path_filter` and refuses a state without it, like the two verbs before it.
> **Reports written before the fix keep the slash-less form, and Open folder on one still opens the
> parent** — a known limit, decided, with no browser fallback.

## Data-quality runs index + dashboard (SPEC-123)

The `/data-quality` list is backed by a per-space **`index.json`**, not by listing the reports prefix — S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) gives NO chronology, and building rows from the reports themselves costs one GET per row and gets slower the more the feature is used. `assemble-report` appends one small entry (the row's fields and nothing else) under **optimistic ETag CAS** with bounded retry, because checks of DIFFERENT locations run in parallel (the queue serializes only same-location checks **— superseded 2026-09-15: it only starts them in order, so same-location checks run at once too, which the CAS already covers; [the group id entry](control-planes.md#a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on-each-plane-control-plane-wide) —**) — the same lost-update fix SPEC-082 applied to the registry. It was duplicated in `dqcommon` because `casio` sat in a layer the data-quality functions don't attach (**SPEC-125 did NOT merge it** — it folded the shared *client/config/JWT/notify* surface onto `cpcommon` and deliberately left the CAS retry loop domain-side).

> **Superseded (SPEC-156 FR-001, 2026-08-07) — the duplication ONLY.** The loop and the 409 predicate live in `cpcommon.cas`, which every data-quality verb already attaches; `DQ_INDEX_CAS_RETRIES` is gone and the cap is one value (6) for all callers. The twin had drifted before anyone merged it, which is this paragraph's real lesson. Everything below is unchanged and still live.

The index is **capped at 200, oldest dropped first**, and every failure is **logged and swallowed**: the report is the artefact, the index is a convenience, so write order is report → notification → index, most durable to least. The page **aggregates across spaces** (this is "my checks", not "checks in one folder") and one unreadable space is skipped rather than blanking it. It lists **completed checks only**, and the footer line saying failures live in notifications was worded **"usually"** until **SPEC-126** closed the never-started-an-execution hole, then **"always"**; it now carries **no adverb**, the Help guide likewise, because `States.Runtime` and `States.DataLimitExceeded` escape every Catch in the machine and never reach `NotifyFailure` — designed out, not impossible. No new IAM. Detail: `spec-delivery/SPEC-123`.

## Control-plane table creation = TBAC (SPEC-070/111 correction)

Supersedes "execution role = LF admin ⇒ catalog-wide create". LF data-lake **admin status does NOT grant `CREATE_TABLE`** on a database the admin didn't create — so table-builder/table-share/data-quality (all admins) silently failed to create tables in user/shared DBs. Fix: a single **`portal-managed` LF-Tag** stamped on **every** personal + shared DB at provision time (`post_confirmation.py` / `create_space.py` call `AddLFTagsToResource`; backfill existing DBs via `scripts/backfill-portal-managed-tag.sh`), with **one tag-policy grant per execution role** (DB `CREATE_TABLE`… + inherited table perms) — **not** per-DB named grants. Locations (which LF-Tags can't express) get a **static per-bucket `DATA_LOCATION_ACCESS`** grant (3 roles × user-space + shared buckets). The portal role keeps its named per-DB grant (per-user isolation needs the named ARN). Not-in-scope-to-change: the "per-user isolation = username IAM principal tag, not LF-Tags" decision — that's a *different, per-user* tag. Detail: `infra/modules/analytics/lakeformation.tf`.

## Refresh eligibility turns on SHAPE, never on a marker (SPEC-143)

A refresh reads a table this run did not create, so before re-deriving anything it must answer *can
this be faithfully rebuilt from its own definition plus a fresh look at its files?* **It answers from
what Glue reports, never from a `portal.managed` marker** — and the marker exists anyway, written by
`cpcommon.ddl.build_create_table_ddl` from this spec onward. Both halves of that are deliberate.

**Why not the marker.** Every table created before SPEC-143 lacks it, so a marker test refuses the
entire existing estate. Worse, `TBLPROPERTIES` are user-writable through `ALTER TABLE SET
TBLPROPERTIES` from the query workspace — so it can be trusted neither as a permission nor as a
fact, and the moment a verb branches on it a user can grant themselves whatever that branch guards.
A test scans the whole Lambda tree and fails if anything outside `ddl.py` (which writes it) and
`glue.py` (which excludes it) so much as references it. That scan reads the **parsed AST**: a
literal-only grep waves through `from cpcommon.ddl import PORTAL_MANAGED`, and a text scan flags the
comments that warn against confusing `portal.managed` with `portal-managed`. **Those two names are
one character apart and unrelated** — the dotted one is a table TBLPROPERTY that records and grants
nothing; the hyphenated one is the Lake Formation tag on DATABASES that is how control-plane roles
get `CREATE_TABLE` at all (`infra/modules/analytics/lakeformation.tf`). Every site of both carries a
comment saying so.

**What the shape checks are.** `cpcommon.glue.clone_definition` — moved here from `tscommon.glue`
because table-share asks the identical question — refuses views, non-external tables, catalog-
partitioned tables and unusable locations. The refresh path **maps** its four codes to its own
vocabulary at its call site rather than parameterising them (the stems differ, so no substitution
produces both sets), and asserts its mapping covers `clone_definition`'s whole set. That assertion
is load-bearing: `cpcommon.glue` now registers those codes itself, because `TerminalError` validates
at the raise site and they were previously registered only as an import side effect of
`tscommon.messages`, which a table-builder Lambda never imports. Registration is what lets the
refresh path speak — and its cost is that an **unmapped** code no longer explodes; it would sail
through as a valid terminal and resolve to the generic `unexpected_error`.

**Beyond the shape: the reconstruction needs two guards, and neither suffices alone.** SPEC-069's
declared partition keys are recorded nowhere but on the table, as `projection.*` properties, and
`build_create_table_ddl` requires the declared shape (it raises a bare `ValueError` on a Glue-shaped
key). So the verb rebuilds them and then **re-renders each one through the create path's own
renderer, demanding exact equality** — which catches a dropped property, a rewritten one (a
zero-padded bound), and any extra `projection.*` option. What it structurally cannot see is the
**column type**: Athena permits a projection over a wider set than this builder writes, and an
`integer` projection on a `string` column is precisely how a zero-padded partition gets declared.
That table round-trips *perfectly* and would be rebuilt as `int`, retyping the column while
reporting success. Table-level `storage.location.template` is refused for the same reason — it sits
outside the namespace the per-key round-trip compares. **The rule: a reconstruction that cannot be
performed is a refusal, not a guess.**

**Three ASL/marker traps worth carrying.** (1) **A `Choice` rule whose `Variable` path is ABSENT
raises `States.Runtime`, which no Catch anywhere can catch — it does not fall through to `Default`,
which covers only a value that is present and matching no rule.** So the one input `Default` exists
for is the one a bare `StringEquals` kills; both rules are `And` + `IsPresent`. (2) The same hazard
on the success side — `RecordSuccess` reads `$.mode` and a `Pass` state's JSONPath hard-fails the
same way — is closed by `execute-ddl` defaulting the field, since only a create reaches it; the
window is an execution starting after the state machine deploys but before the Lambda code does,
which would otherwise die *after* the table was created and the actor notified. (3) **Marking is an
explicit `mark` argument, never inferred from `storage is None`.** That inference reads correctly
against today's two callers and is wrong for the next: SPEC-144's `apply-refresh` is a `DROP` +
`CREATE` supplying a rebuilt `Storage`, so inference would strip the marker from every table a
refresh touched. Full account: `docs/spec-delivery/SPEC-143-refresh-table-contract-and-eligibility.md`.

## Removing a column requires an explicit opt-in, and the refusal IS the warning (SPEC-144)

A refresh that would drop a column does **nothing** and fails terminally with `columns_removed`,
naming the columns in the notification. The user re-submits with `allowRemovals: true`. Removal is
singled out because it is the one class of change that breaks things somewhere the person who ran
the refresh is not looking: every saved query, view and dashboard referencing the column starts
failing, and nothing tells them.

**Two designs were rejected, and they are the two a later reader will propose.** *A plan-then-apply
pair* — run one writes a plan artifact into the user's prefix, notifies, the user clicks Apply, run
two references the plan. The textbook shape, and it costs a new artifact, a new index, a new view, a
new IAM surface and two async round trips for what the user experiences as one button. *A
browser-side preview* — the browser can already read the table's Glue columns and list the folder,
but it **cannot infer types**: that needs polars over a bounded Parquet footer or CSV head, which is
why `infer-schema` exists and needs polars, which was a 240 MB layer until SPEC-213 put it in the fleet image. A preview showing guessed types would be a
preview of something other than what the apply does.

**What the chosen design guarantees, stated honestly:** the *specific columns* are named to the user
in a durable notification before any removal happens. It does **not** guarantee they read it —
SPEC-145's dialog requires an explicit tick with explicit consequence copy, and names the columns
when it can via the notification's link. Do not overclaim this as consent.

**Three things about the mechanism are load-bearing.** (1) **`allowRemovals` is validated, not
coerced** — a non-boolean is refused, because truthiness reads the string `"false"` as opting *in*,
on the one flag that authorises data loss. (2) It is **persisted nowhere** — not on the table, not in
a registry, not in an index; a test greps the Lambda tree for it. The flag authorises one run, and a
stored copy would carry that authorisation into a refresh nobody opted into. (3) **The notification
link is the only channel that names the columns to the browser**, and its column names are
**percent-encoded** — column names are NOT catalog-safe (`infer-schema` reads them verbatim from a
file header and nothing validates them), so `Order ID` puts a raw space in a URL and `&` invents a
query parameter. SPEC-145 must not re-validate them as identifiers: `CATALOG_IDENTIFIER_RE` rejects
`id`, `ts` and `Amount`, which would discard the whole link for most real tables.

> **Superseded in part by SPEC-149 (2026-08-04): the apply is no longer a DROP + CREATE.** It is a
> single in-place `glue:UpdateTable`, so the metadata loss described below no longer happens and the
> reason codes named in it are gone. Everything above this line — the opt-in, the refusal-as-warning,
> the three load-bearing mechanism points — is unchanged. See *The refresh apply replaces the
> definition in place* below.

**The apply WAS a DROP + CREATE, and what that cost is recorded in SPEC-144 FR-004** — table
identity, `Description`/`Owner` and any table-level Lake Formation grant were destroyed with the
catalog entry (column comments were carried). `ALTER TABLE ADD COLUMNS` cannot retype or remove, so it
would have covered only the easiest third. Full account:
`docs/spec-delivery/SPEC-144-refresh-table-schema-diff-and-apply.md`.

## The refresh apply replaces the definition in place (SPEC-149, supersedes SPEC-144's apply)

`apply-refresh` issues **one `glue:UpdateTable`**, not two Athena statements. There is no moment at
which the user's table does not exist, no new catalog entry, and therefore no loss of table identity,
`Description`, `Owner` or table-level Lake Formation grants. A **failed update changes nothing**,
which is what retires SPEC-144's "a committed drop followed by exhausted retries notifies nobody"
exposure: there is no committed destructive step left to be silent about. It also stops the portal
entrenching a pattern it would have to unpick for Iceberg, where drop-and-recreate destroys the
snapshot history that is most of the reason to adopt it.

**The one thing to understand before touching this verb: it is a READ-MODIFY-WRITE on the live table,
never a rebuild from SPEC-143's capture.** `UpdateTable` replaces the WHOLE definition — a
`TableInput` omitting a field does not leave that field alone, it **clears it** — and
`clone_definition` never carried `Description` or `Owner` and deliberately strips `EXTERNAL`. Building
the input from the capture would delete exactly what the change exists to preserve. The verb reads the
live table immediately before writing it and mutates only the **columns** and the **`projection.*`
parameters**.

**Three mechanism points are load-bearing.** (1) The `TableInput` is an **allowlist projection** of
the live `Table`, pinned against botocore's service model by a test — `Table` returns 25 members and
`TableInput` accepts 14, so a denylist of the extras goes stale whenever AWS adds a field, and four of
today's eleven already postdate the obvious set. (2) **Column names are lowercased on write**, because
AWS documents that Athena folds names created through DDL — the create path gets the fold for free and
this path, bypassing Athena, must reproduce it or leave a mixed-case entry the create path could never
produce. (3) **`portal.managed` is re-asserted through `ddl.mark_managed`, never named in the verb**,
so SPEC-143's guard against a verb branching on a user-writable marker stays strict.

**IAM moved the right way: `glue:DeleteTable` was REMOVED, `glue:UpdateTable` added.** No verb on this
plane deletes a table any more, and a test greps the table-builder modules to keep it so. The explicit
`Deny s3:DeleteObject` is untouched — it never depended on the drop, and it outlives the mechanism
that prompted it. Lake Formation needed no change: the `portal-managed` table tag policy already
grants `ALTER`.

**What is NOT fixed, and must not be claimed:** the concurrent-refresh race is **reduced, not
closed**. The Pipe still starts executions `FIRE_AND_FORGET`, and **Glue offers no compare-and-set on
`UpdateTable`** — `VersionId` is documented only as "the version ID at which to update the table
contents", with no precondition-failure error. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions. A real fix is a serialization change to the Pipe.

> **Superseded in part by SPEC-157 (2026-08-09).** The race is now serialized by a per-table lock
> outside Glue, so the second refresh is refused rather than raced — the paragraph above stands as
> the state SPEC-149 left, not as the state today. What it says about Glue is still true and is
> exactly why the lock exists: `UpdateTable` has no compare-and-set, and `VersionId` is still not a
> precondition. The fix was NOT a Pipe change — see *A per-table lock serializes refresh* below.

Full account: `docs/spec-delivery/SPEC-149-refresh-table-in-place-rebuild.md`.

## A per-table lock serializes refresh, because the catalog cannot (SPEC-157)

Two refreshes of one table could overlap. `MessageGroupId` is the target database, so SQS serializes
*delivery* per database — but the Pipe starts the machine `FIRE_AND_FORGET`, so **delivery ordering is
not execution ordering**. SPEC-149 reduced the damage to last-write-wins between two definitions and
could not close it, because **Glue offers no compare-and-set on `UpdateTable`**.

**The serialization is a lock object in the admin bucket, claimed under ETag CAS**, one per
`{database}/{table}` under `locks/table-builder/`. The loser is **refused, not queued**: a held lock
means a refresh of that table is already running *against the same files*, so a queued run would pay a
full `inspect-source` to compute an identical definition. The refusal is a `TerminalError` through the
plane's existing notify path — the refusal **is** the notification.

**Two rejected alternatives, recorded so they are not re-proposed.** `REQUEST_RESPONSE` on the Pipe is
**impossible, not merely undesirable**: botocore's `pipes` model states that it "is not supported for
STANDARD state machine workflows", so making the Pipe synchronous means converting the machine to
EXPRESS — rejected on two independent grounds, its 5-minute ceiling against `inspect-source`, and its
**at-least-once** semantics, which would introduce the duplicate executions this spec exists to
prevent. A finer `MessageGroupId` would change nothing, because delivery is already ordered.

> **The PROTOCOL moved to `cpcommon.lock` (SPEC-187).** Everything below still describes what the
> table-builder's lock does and why; what changed is where the code lives. The three-way acquire, the
> 412/409 mapping, the staleness and future-date rules, the re-claim and the release-by-overwrite are
> now shared, and `tbcommon.table_lock` binds them to this plane's key, thresholds and wording. Its two
> suites were not rewritten — the protocol moved out from under them — which is what makes the move
> provably behaviour-preserving.

**The lock releases by OVERWRITING, and that is forced rather than chosen.** The execution role
carries an explicit `Deny` on `s3:DeleteObject` for the whole admin bucket, which SPEC-149 kept when it
removed `glue:DeleteTable`. Releasing by deletion would mean amending a standing safety property for an
implementation convenience, so **"free" is a state of the object, not its absence**.

**The holder is the EXECUTION ARN and must never be the request id.** A request id is whatever the
caller sent, and the queue deduplicates it for only five minutes, so two executions can carry the same
id — and the re-entrancy branch (which exists so an SFN Task retry does not self-refuse) would hand the
lock to both, silently. A redelivered message should not be the road to that second execution:
reusing an execution name [was measured](../../infra/info/control-plane-shape.md#a-redelivered-message-is-not-a-re-run)
to return the original ARN while that run is going and to fail with `ExecutionAlreadyExists` once it
has closed, so a redelivery that reuses its name is either swallowed or fails its start, and a start
that keeps failing ends on the request DLQ. That the Pipe reuses the name for a redelivered message is
inferred from its v5 UUIDs rather than proven, so the lock does not rely on it. The ARN reaches the verb through a `Pass` state, **not** the task's own
`Parameters`: reading `$$` there means building an object, which wraps the payload, and every
notification path in this plane reads the request at the **top level** of the event.

**A lock is stealable only because executions are bounded, so the bound came first.** The machine had
no `TimeoutSeconds` — a Standard execution may run for a year, against which no age threshold is
defensible. It is a **top-level field of the ASL**, not a resource argument (`aws_sfn_state_machine`
has none; `tofu validate` rejects it). A malformed body, an unparseable stamp and a **future-dated**
one are all stolen: a timestamp that cannot be true is no evidence a refresh is running, and the
alternative is a table that can never be refreshed again.

**The freshness guard narrows the residual window and does not close it.** `apply-refresh` compares the
`UpdateTime` captured at the start of the run against its own pre-write read. **A moved stamp is not by
itself another writer** — the state retries on faults that can fire *after* the update committed, so
the retry re-reads a table whose stamp this run moved; judging on the stamp alone failed a run that had
already succeeded and sent the user a notification contradicting the success one. The columns settle
it: a live table already carrying what this run intends to write was written by this run.

Full account: `docs/spec-delivery/SPEC-157-serialize-concurrent-table-refresh.md`.

## Every DDL literal goes through `literal()` (SPEC-151)

`cpcommon.ddl` renders **every** string literal in a `CREATE EXTERNAL TABLE` through `literal()` —
`TBLPROPERTIES` keys and values and the `LOCATION`, alongside the column comments that already did.
Raw `f"'{value}'"` is forbidden in DDL construction.

The demonstrated consequence of the old form: a partition enum value of
`eu','projection.enabled'='false` rendered as
`'projection.region.values'='eu','projection.enabled'='false'`, **injecting a property that switched
partition projection off**. Blast radius is **self-scoped** — a user can only reach a table in their
own database and Athena rejects multi-statement DDL — so this is robustness, not cross-tenant
escalation. The sharper everyday path is data-quality, where the `LOCATION` and the partition values
both come from **S3 key segments**: a folder named `year=2024'` or `o'brien` broke the temp-table DDL
and killed the whole check as `query_failed`.

**Two escapers exist and must not be confused.** `cpcommon.ddl.literal` escapes with a **backslash**,
which is Hive's rule and what Athena parses `CREATE`/`DROP` with. `dqcommon.sql._literal_dml` **doubles
the quote**, which is Trino's rule and what Athena parses `SELECT` with. Using the Hive form in a
query would render a backslash into the S3 path being matched, and the predicate would silently match
nothing. Each lives in its own module with a docstring saying so; `tscommon.ddl._lit` is the
table-share twin of the DDL one and has always done this.

Ordinary values render **byte-identically** to the old form, which is why the golden-DDL tests are
untouched — a rendering change that moved any existing statement would have been a different and much
riskier decision.

**Corroborated, not demonstrated:** the escaped form has never been exercised against Athena itself.
The tests assert the rendered string. If a `'` in a partition segment ever still fails, suspect the
engine's acceptance of `\'` before suspecting the renderer.

## A generalized signature is the whole point of the second extraction, and one moved constant must not be renamed (SPEC-177)

`features/saved-queries/` is the arc's second extraction and it follows SPEC-176's shape exactly:
the `.sql` store — the service, the space memory, the pager, the save flow — came out of
`features/query/` before its second consumer exists, with no user-visible change and nothing live
owed. The reasoning in the SPEC-176 entry above applies unchanged; what follows is only what is
different here.

**The one deliberate signature change is what makes the extraction worth doing.** `useSaveQuery`
took `activeTab: QueryTab` — a shape the Data Explorer cannot produce, since it has no tabs. Moving
the module without changing it would have left SPEC-183 reimplementing the collision-and-confirm
path SPEC-175 spent a whole spec getting right: validate, `ensureSavedQueriesFolder` on the CHOSEN
space, write, the `Collision` round-trip that survives a cancelled Replace, the inline failure that
leaves the dialog open with the destination intact. So it takes `{sql, link}` — the two fields the
flow actually reads — and the Query workspace passes `{sql: activeTab.sql, link: activeTab.savedQuery}`
at the call site. An extraction that moves a module but leaves it unusable by the second consumer
has not extracted anything.

**`onSaved` keeps its second argument, against the spec's own Data Model.** The spec sketched
`onSaved: (link: SavedQueryLink) => void`; it ships as `(query: SavedQuery, sql: string) => void`,
because the workspace clears its dirty marker with `rememberSavedSql(query.key, sql)` — against the
bytes that were **written**, not against whatever the buffer holds by the time an async write
returns. Dropping the body would have changed workspace behaviour, which FR-002 AC2 forbids. A
`SavedQuery` is structurally a `SavedQueryLink` plus two fields, so a caller needing only the link
is served by the wider callback; a caller needing the body cannot be served by the narrower one.

**`QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX` moved without being renamed, and its VALUE is the reason.**
`s3portal.query.savedQuerySpace.` is a live `sessionStorage` key. The `query.` segment describes
where the module used to live, which is exactly the kind of thing a move invites tidying — and
tidying it silently discards every user's remembered space on the deploy that ships it. The constant
name and the string are both untouched; the docstring says why.

**The layering rule gained a third participant and its message had to change with it.** SPEC-176's
clause governs `features/query/` ↔ `features/data-explorer/` and the layer below them;
`features/saved-queries/` joins on the same footing — it may import neither sibling, while
`features/query/` importing the store stays open (`saved-queries` appears in no `group` pattern).
The rule was verified the only way this rule can be verified — by committing a violation in the
**relative** form a sibling actually produces (`'../query/useQueryTabs'`) and watching lint fail,
in each of the four directions. Reading the config proves nothing; SPEC-176's first version resolved
onto the right files and caught nothing.

**One a11y test had to split rather than move.** `saveQuery.a11y.test.tsx` drove the Replace confirm
through `QueryDialogs`, which is a Query workspace component and stays. Moving the file whole would
have made the new feature's own test suite the rule's first violation. The three dialog passes moved
with the dialog; the confirm pass became `features/query/queryDialogs.a11y.test.tsx`, assertions
byte-identical.

## The renderer's signature is the rule, and the browser's first SQL value interpolation is two gates wide (SPEC-178)

The Data Explorer reduces to one idea: a user's grid gestures are a *description of a query*, and
the app renders that description and runs it. SPEC-178 builds that engine with no route, no grid
and nothing a user can see, because it settles two things that would be expensive to get wrong
after five specs have built on them.

**Filter, order and grouping render SQL; everything else is presentation — and that is enforced by
a PARAMETER LIST, not by discipline.** `renderExplorationSql(source, query)` takes two arguments,
so column visibility, order, pinning, width and SPEC-184's colours and transformers are not merely
documented as unable to change the SQL: they are unreachable from the function that renders it. A
later edit cannot make the projection depend on which columns are visible without changing the
signature, which is a change a reviewer sees. `SELECT *` always follows. The rejected optimization
is recorded rather than left as an apparent inefficiency: narrowing the projection to the visible
columns would cut bytes scanned substantially on Parquet, and would turn un-hiding a column into a
billed, several-second re-run — cost depending on a gesture users read as cosmetic. Predictable
cost wins. A feature-scoped AST-style sweep forbids a second builder; a **repo-wide** one was
specified and is not achievable, since `useTableActions`, `useRunDdl` and `CreateViewDialog` build
real DDL today and `DEFAULT_SQL` is `SELECT 1;` — a sweep exempting three legitimate builders would
prove nothing about the fourth.

**This is the first place the browser interpolates a user-supplied VALUE into SQL, and the escaper
is the Trino/DML one.** Everything the portal built before is either typed into Monaco or assembled
from identifiers already validated against `CATALOG_IDENTIFIER_RE`; a filter value is neither.
`lib/sql.ts`'s `sqlLiteral` **doubles the quote** and is not `cpcommon.ddl.literal`, which
backslashes for Hive — the repo's "two escapers, never confused" note gains its TypeScript half
here, and the failure mode of confusing them is the bad one: no error, just a predicate that
silently never matches. The raw expression bar does **not** relax this and the asymmetry is the one
thing a reader must not get backwards — the bar is the *user's own SQL* and passes through
verbatim, as Monaco's does, while a filter value arrives *from data* and is quoted on their behalf.
A cell containing `O'Brien` filtered by one click is the whole hazard, and it arrives from real
data long before anyone thinks to type it.

**The spec's own filter model would not have worked, and nothing offline would have caught it.**
`value?: string` with every value quoted renders `WHERE "qty" > '5'`, and Trino does not coerce
varchar to bigint — a *query-time* error, invisible on the CSV-derived tables the Table Builder
makes all-string, surfacing on the first Parquet table. `ColumnFilter` therefore carries an optional
`valueKind`, and `'number'` renders **bare**; the repo's own Trino renderer already does exactly
this (`dqcommon/sql.py` interpolates a count unquoted beside a `_literal_dml`-quoted path). The bare
value is the one thing the renderer does not escape, so what admits it IS the trust boundary, and it
is **two gates**: a bounded charset, which is load-bearing rather than a fast path because `Number`
alone accepts `0x1f`, `0b11` and `Infinity`; and `Number.isFinite`, because a hand-written numeric
grammar is exactly the thing that is subtly wrong — the first one written here tripped
`security/detect-unsafe-regex`, and deferring to the engine's own parser is both safer and shorter.
A value failing either gate is **refused, never quoted as a fallback**, since quoting restores the
type error the kind exists to prevent.

**One execution per distinct rendered SQL, and the failed one is evicted on the way OUT.** The
rendered SQL is the cache key, which makes the cache the cost control: an identical description is a
cache hit, so changing a filter and changing it back is free, and paging *within* an execution
scans no extra bytes. Requiring that a re-applied description **retry** after a failure is the
subtle part — evicting on observing `FAILED`, with an observer still mounted, refetches
immediately, which is start → FAILED → evict → start, an **unbounded loop against
StartQueryExecution** on any permanently-bad statement. The eviction happens in the effect cleanup,
when the statement changes or the hook unmounts. **Be precise about what that loop costs**: AWS does
not bill a FAILED Athena query, so the first cost is the API hammering and the account-wide query
concurrency it consumes — but the same branch covers **CANCELLED**, which *is* billed for whatever it
scanned before it stopped, so a loop over a statement the user keeps stopping bills every pass. A
paired test asserts a SUCCEEDED
execution is *not* evicted, because an unconditional eviction makes every remount a fresh bill and
the failure test alone would still pass.

**A tab's cost ledger is keyed by execution id rather than accumulated**, which makes "a cache hit
adds nothing" true by construction — a re-rendered identical statement resolves to an id already in
the map. A running total would have to *detect* a hit, and a detector can be wrong in the direction
that overcharges. Athena offers no pre-flight estimate, so reporting after the fact is the only cost
signal the feature can give.

**`ExplorationSource` is a union from the outset with only the `table` arm reachable for five
specs.** A saved `.sql` file cannot be reverse-engineered into a table plus filters without a SQL
parser, so SPEC-183's loaded file is a **source**, not a view state; filters, ordering and grouping
compose over either arm without knowing which. Retrofitting the union at 183 would have touched
every spec in between.

## A space maps to ONE database, so the picker has no database step — and a deep link resolves without asking (SPEC-179)

The Data Explorer's front door. FR-005 specified the picker as *space → database → table*, and the
middle step does not exist in this codebase: a space maps to exactly **one** Glue database — the
personal space to the username, a shared space to its own name, both built by `useConnections` — so
the control would have offered a single option, which is the one-option control SPEC-163 declined to
render for the share dialog's recipient kind. The picker is two panes with the database **shown**
beside its space, and `spaceDatabase()` is the single definition of the mapping. `?db=` survives in
the deep link as a **cross-check rather than a choice**: a link naming a database that is not that
space's resolves to nothing and opens the picker.

FR-005 AC3's "a database the user cannot see is absent rather than present-and-failing" therefore
lands one step later than its wording implies. The space list comes from **memberships**, which are
known reachable; an unreadable database renders an explanation instead of a failing table list. No
table is ever offered that cannot be read, which is the property the AC is protecting.

**The deep link resolves from the LIST, never by probing** (SPEC-113's rule, applied to the
catalog). `denied` and `none` are deliberately different states: a named space this user cannot
reach renders a refusal, while anything malformed opens the picker — an error page for a bad
parameter would tell a user their correct-looking link is broken when the honest answer is "pick
something". Own username always wins over a same-named shared space, mirroring
`useDataQualityReport`'s `resolveSpace`, and `?space=` is **not read at all** with
`sharedWorkspaces` off — never resolved-then-fallen-back, because a "we sent you somewhere else"
banner over a parameter that was never consulted would be a lie (SPEC-167's rule).

**The page must not mount the picker while a link is still resolving, and this was found by a test
rather than by design.** `useConnections` reports loading before the shared spaces arrive; the
workspace rendered the picker meanwhile, and the picker reads the *personal* space's database on
mount — so a denied link issued a Glue call and swapped to the refusal a tick later. Still an answer
about a catalog, just about the wrong space. `LoadingState` now holds the page while a resolution is
pending, and the hook reports `loading` **only when a `?space=` is actually present**: without one
there is nothing to wait for, and a blanket wait would put a spinner in front of every visit to
`/explore`. This is `FeatureRoute`'s own rule one layer down. (Since 2026-09-16 it waits only while
that space is refused, and until a read of the list after the link rather than on `isLoading`: see
browser.md, *A `?space=` the cached list lacks is refused only on a read after the link*.) The
parameters are then **dropped with
`replace`** once acted on — tabs survive a reload through `sessionStorage`, so a link left in the URL
would stack a duplicate of the linked table on every reload.

**One surface, registered under TWO flags.** *Explore data* on the Query rail is the mirror image of
"Create table": a Data Explorer capability living on a Query-workspace surface. It is gated by
`dataExplorer && query` and carries a row under each, because either gate can be deleted alone and a
single row would leave the other unwatched. Verified by violation — dropping `explorerEnabled`
reddened both the walking test and the menu-shape test that asserts the **rest of the menu is
unchanged** with the flag off, which is the half the walking test cannot see: a conditional written
one bracket wide takes Refresh table and Share table with it while "the item is gone" still passes.

**Adding a flag key lands in SIX places and two of them are Python.** The spec named the publish
workflow's matrix; the matrix is per **environment**, not per flag, and needed no edit. The two that
matter are `scripts/validate_feature_flags.py`, which refuses an unknown key — without it the publish
job would have failed on the very document the key was added to — and
`lambdas/test_feature_flags_config.py`, which **re-states the same tuple on purpose** so a test
cannot pass by agreeing with a mistake it imported. That second one went red on CI: this repo's four
named local gates (`format:check`, `lint`, `build`, vitest) run no pytest, so **a change touching
`scripts/` or `lambdas/` needs `pytest lambdas/` before the push**, not just `ruff`.
`FEATURE_FLAG_KEYS` **order** is load-bearing beyond iteration: `FeatureRoute` offers the first
ENABLED feature as its fallback link, so a new key goes **last** or an existing unavailable page
silently changes where it points.

**An unsettled link must run NOTHING, and "denied" is not the same condition.** Review measured a
real `StartQueryExecution` behind the refusal: the guard read `denied ? null : …`, and `denied` is
false during the resolution window, so a tab restored from `sessionStorage` started a billed query
for a page that then rendered only the refusal. FR-006 AC2's letter survived — the execution is
against the user's *own* table and no Glue call is made — but cost is this feature's declared
through-line, so the guard is now "the link is not settled". The connections read that resolution is
*made of* stays: it is the user's own cache of their own memberships, the same document
`useDataQualityReport` reads on the same path, and no request touches the space named in the link.

**A tab's close control may not be a `<button>`, because it lives inside `role="tab"`.**
`ExplorationTabStrip` shipped one and tripped axe's `nested-interactive` — the exact arrangement
`QueryTabStrip`'s comments forbid, in a component whose own docstring claimed to mirror it. The ✕ is
a non-focusable `role="presentation"` span and **Delete on the focused tab** is the operable path
(WCAG 2.1.1). The feature had **no axe assertion at all** while 19 other feature suites have one;
that absence is what let a violation ship past a review of the markup.

## Calc computes what only the browser has, grouping computes what only Athena can, and the percentage says which page it is of (SPEC-182)

Two panels that look like siblings and are the opposite of one another. The split is not a
compromise between fidelity and cost — it falls out of what each panel *is*, and everything else in
the spec follows from getting that right.

**Calc is client-side because a selection is client state.** It aggregates the cells the user has
selected, and those exist nowhere but the browser, so a server-side Calc means a billed
`StartQueryExecution` **per selection change** — for a gesture as cheap as dragging across ten
cells. Grouping is the mirror image: aggregating in the browser would aggregate whichever rows
happened to have been fetched, which is the scale lie the whole feature was designed to avoid. So
Calc issues **zero** executions (asserted by count, FR-001 AC7) and grouping mints exactly one per
apply, however many columns and aggregates changed — which it gets for free by staging a draft and
going through SPEC-181's single `apply`.

Because Calc's numbers are true only of loaded, selected cells, the panel **says so every time it
says anything**: `calcScopeText` renders "N selected cells on this page", and none of those words
are droppable. With nothing selected it explains itself rather than showing zeroes — a column of
`0`s reads as a computed answer to a question nobody asked. The numeric predicate is the renderer's
own `isBareNumeric` rather than a second rule, so the panel and the filter cannot disagree about
which cells are numbers; a `count` of an empty set is `0` and an empty `sum` is `0` (both real
answers) while every other function shows a no-value marker, which is the guard that is easy to draw
one line too wide.

**The percentage is of the rows on the CURRENT PAGE, and its column header says so.** Only one page
of a result is in the browser — `useQueryResults` exposes exactly one — so a share computed here is
a share of those rows and nothing else. A column headed `% of count_all` beside a paged result would
be read as a share of the table, which is precisely the class of claim grouping exists to prevent,
so the header is `% of count_all (this page)`. The alternative, a windowed total in the SQL, is a
second scan of the same data for a column the user asked only to *see*; the flag renders no SQL at
all, and a test pins that. It rides on `Grouping` rather than on `ExplorationPresentation` even so:
it is meaningless apart from the grouping it describes, and a grouping restored from
`sessionStorage` has to restore whole.

**Grouping mode is exactly "at least one grouping column".** A grouping with aggregates and no
columns is legal SQL — a global aggregate — but FR-003 AC6 says removing every column leaves
grouping mode, and the alternative reading strands the user in a mode with nothing in it. So
`setGrouping` maps an empty-column grouping to `null`, and **leaving grouping mode drops any sort on
an aggregate's output column**: `count_all` exists only while the grouping does, so carrying that
`ORDER BY` onto the raw table is a query Athena rejects — and it would also miss the cached ungrouped
execution AC6 promises to return to. That is the half of AC6 the spec does not mention and the whole
of what makes it work.

**`groupingOrderingViolation` is exported for the same reason `isBareNumeric` was.** Trino rejects an
`ORDER BY` on a column that is neither grouped nor aggregated, and the renderer refuses it first —
but that refusal is an `ExplorationRenderError` naming a column and an operator, which SPEC-106
forbids showing a user. So the rule returns the offending **column** and the two callers word it
differently: operator text in the renderer, a sentence naming the sort to clear on the panel's Apply
(`Button.disabledReason` — `aria-disabled`, reachable rather than hover-only). A second rule at the
panel is a rule that can disagree, and the way it would disagree is a grouping the panel accepts and
the renderer throws on, which takes the whole exploration to an error banner. The refusal belongs on
Apply because that is where the conflict is *built* — sort a column, then group it away.

**But the panel's Apply is not the only guard the rule needs, and this spec falsified its own premise
in the same commit.** "While a grouping is in force the grid shows only the grouping columns and the
aggregates" stopped being true the moment the percentage column was appended: it is a real
`GridColumn`, so it gets a header menu, a row in the settings dialog (the ONLY sort/filter path below
`tablet`) and the toolbar's *Filter by this value* — and it exists in no statement, so sorting it is
a description the renderer REFUSES and filtering it is a `COLUMN_NOT_FOUND`. `ColumnQueryActions`
therefore carries **`queryRefusalOf`**, asked by every per-column surface before it offers a filter
or a sort; the header menu opens and states the reason rather than offering controls that each fail,
while Show, Pin, width and order stay available, because geometry applies to a calculated column like
any other. The lesson generalises past this column: **appending anything to `columns` before
`useColumnGeometry` hands it every affordance a real column has**, and the grid has no other way to
tell the two apart.

The same reachability argument closed a second hole. `assertGroupingIsRenderable` compared aggregate
aliases with each other and not with the **grouping columns**, which are projected beside them under
their own names — so grouping by a column called `count_all` while `COUNT(*)` is present produced two
result columns of one name, sharing one geometry key and leaving `groupingOrderingViolation` to
answer for whichever the reader meant. Unreachable before this spec, because nothing let a user
choose what to group by. `groupingNameCollision` is now the renderer's rule, exported on the same
precedent, and the panel refuses at the gesture.

**Both panels are `<aside>`s, not `Drawer`s, and that is structural rather than stylistic.** A
`Drawer` traps focus. Calc has to recompute as the selection changes and grouping takes a column
**dragged from a grid header**, so a focus trap would put the grid out of reach of the panel that
needs it. The dragged column travels by an additive `onColumnDrag` callback rather than through
`dataTransfer`, for the reason the header's own reorder ref already exists: `DataTransfer` is not
implemented everywhere, and a drop handler that depends on it works in a browser and nowhere else.
The panel is also offered the **source's** columns while a grouping is active, not the result's —
the result's are the grouping columns and the aggregate aliases by then, and offering those would
let a user group by `count_all`, a column that exists only inside the query it would be added to.

**The disclosure shows the string the execution used, never a second rendering of it.**
`useExploration` renders once, runs that string and returns it; `GeneratedSqlDisclosure` shows that
value. Re-deriving it for display is one `renderExplorationSql` call away and would drift the moment
a caller passed a slightly different description — and a disclosure that is right most of the time
is worse than none, because it would be believed. It is available whether or not grouping is active:
the Explorer writes SQL the user did not, grouped or otherwise, and every statement it writes is an
invoice.

**Calc opens on MIXED aggregation, and that default is not cosmetic.** Numbers-only narrows every
function, so a numbers-only default answers `Count 0` over a selection of three text cells — printed
directly under "3 selected cells on this page", which is the one pair of numbers this panel must
never show together. The toggle still narrows everything when a user asks for it; what changed is
which reading is the default.

Two smaller things worth carrying. `canonical()` folds the grouping's two new flags **explicitly**
and `readExplorationTabsState` normalises them (absent ⇒ false) — needed together, because a
document written before this spec carries neither flag and an absent flag comparing unequal to
`false` would push a history entry for an apply that changed nothing; the validator accepts them
absent rather than requiring them, since requiring them would discard **every tab** in the document
over a field that did not exist when it was written. And `CalcPanelState` is region state, not tab
state: it describes a selection, and a selection does not survive a page change, let alone a session.

---

## A saved exploration follows the flag that owns the STORE, not the one that owns the screen (SPEC-183)

An exploration can be saved as a `.sql` file through SPEC-177's generalized flow. The body written
is the **rendered** SQL — the exact string `useExploration` handed `StartQueryExecution`, not a
second rendering of the description — because what the user is looking at is what the file should
reproduce, and saving the bare `SELECT *` would produce a file that reopens as something they did
not save. `SaveExplorationDialog` is a thin host over `SaveQueryDialog`: every rule about names,
destinations, collisions and in-place replacement stays in `useSaveQuery`, which is what SPEC-177's
`{sql, link}` signature was for.

**The gate is `query`, not `dataExplorer`, and the registry is what found it.** Registering the
control under `dataExplorer` reads naturally — it is a Data Explorer control on a Data Explorer
surface — and the walking test failed it immediately, because there was no gate to find: `/explore`
already hides the whole workspace, so the row asserted nothing. The right question is not which
screen a control is on but which feature it belongs to, and this is the exact mirror of SPEC-179's
**Explore data** on the Query rail. With `query` off there is no editor to open a `.sql` file in and
SPEC-173's `saved_queries` folder has already left both the file browser and the destination picker,
so a file written from here lands somewhere the user cannot see, open or delete — the failure
"Create table" is on the `query` list for. The control is **removed** with the flag rather than
disabled: a `disabledReason` would explain a state the user has no way to change.

**A save mints a link even though a load cannot.** `ExplorationTab.savedQuery` is written by
`setTabSavedQuery` on success, **by tab id** — the write is async and a tab switch behind it would
link the wrong tab, whose next re-save would then replace a file it has nothing to do with. Without
it, every SPEC-175 rule about in-place replacement would be vacuously satisfied by a predicate that
is permanently false. It does **not** rename the tab: a Query workspace tab IS its buffer, so a save
renames it; an exploration tab is named for the source it is exploring, which a save does not
change. Restored all-four-fields-or-none, so a document written before this spec restores the tab
without a link rather than being discarded (SPEC-182's precedent).

**A FAILED exploration is refused, and it is the case that has teeth.** The obvious refusal —
"there is no statement" — is keyed on a null `sql`, and a failed apply has a perfectly good one: the
statement Athena rejected. Meanwhile `ExplorationResultsRegion` has deliberately fallen back to the
LAST GOOD execution's rows (SPEC-181), so the grid on screen belongs to a different query. Saving
there writes the rejected statement under a name whose rows the user was reading from somewhere
else, and the file then fails to open in the Query workspace this decision promises it opens in. It
is **not** the suspended state and cannot be folded into it: SPEC-181 suspends only on a *history
step* onto a known-bad statement, so the FIRST failure is exactly the window in which Save is
offered. It is checked first, and worded apart, because something did run.

**The sidecar stays rejected.** A JSON document beside the `.sql` file, carrying the exploration's
view state so a saved exploration could reload as an exploration, would reintroduce exactly the JSON
store SPEC-173 deleted — plus a second artifact to keep in sync with a file users can freely rename,
edit, copy or delete from the file browser. The guard is a count: a save issues **exactly one
`PutObject`**, asserted over a space whose folder marker already exists, so the number is a statement
about sidecars rather than about folder creation.

**Loading a `.sql` file as a source was descoped during build (2026-08-13, user decision) and is
deferred to a later spec.** The `sql` arm of `ExplorationSource` stays as SPEC-178 left it,
unreachable; nothing was half-built for it. One thing that arc will have to face first:
`splitSqlStatements` lives in `features/query/query.sql.ts`, which `features/data-explorer/` may not
import (SPEC-176's sibling rule), and the refusals a wrapped subquery needs are built on it. The
answer is to move the lexer down into `lib/sql.ts`, whose own docstring already claims language
rules rather than feature domain — not to write a second one.

---

## Results are read only at SUCCEEDED, and `isPending` is not a substitute (2026-08-16)

**Found by running the live-check script against deployed prod, not by review.** Opening a table in
the Data Explorer occasionally showed *"Something went wrong. Contact the Administrator."* on an
ordinary first load.

`ExplorationResultsRegion` handed `useQueryResults` the execution id the moment
`StartQueryExecution` returned, with no gate on the query having finished. `GetQueryResults` against
a QUEUED execution is **400 `InvalidRequestException` / `INVALID_QUERY_EXECUTION_STATE`, "Query has
not yet finished"** — a name in no `CODE_RULE` whose message matched no `MATCH_RULE`, so
`toUserMessage` returned the **generic fallback**. The most alarming sentence the app owns, for a
transient race of our own making.

**`useQueryResults` already documented the contract** — "a pager over a **succeeded** query's
results" — and cannot enforce it, because it is handed an id and never sees the state. So the
contract is kept at the caller, and the caller is now the only place it can be broken.

**`isPending` looks like the obvious gate and is wrong, which is the part worth carrying.** Between
`StartQueryExecution` resolving and the FIRST poll landing, `state` is still `null`, so
`isPending`'s `state !== null && !isTerminalState(state)` clause is *already false*. That window is
exactly where the race lived: gating on `isPending` leaves the bug in place while looking fixed.
The region therefore takes `state` as a prop.

**It read as intermittent, and the reason generalises.** The race fired on **every** load; what
varied was whether TanStack's `retry: 1` re-asked before or after the query finished. A bug that
self-heals on retry presents as flaky and hides in exactly the place a rendering assertion would
look — so **the guard asserts on the CALL, not the screen**, and was verified by reverting the gate
(`expected getQueryResults to not be called at all, but actually been called 1 times`).

**The mapping rule is defence in depth and is matched on the MESSAGE, never the name.**
`InvalidRequestException` is also the name for a rejected MALFORMED_QUERY, and a `code` rule
outranks every message rule — keying on the name would have turned a rejected-at-submit syntax error
into "still running". (An execution that reaches FAILED arrives as `code: 'FAILED'` and was never at
risk.) Rule ordering is **not** load-bearing; the two regexes are disjoint, measured.

**`QueryWorkspace` was never affected** — `displayedResultTab` is null unless the batch is done, and
result tabs are only pushed at SUCCEEDED.

**Two consequences left standing.** While a statement runs the status line now says **"Running…"**
where it said "Loading rows…" — the old text was wrong, and wrong *because* the app really was
fetching rows then. And a query outliving `MAX_POLL_DURATION_MS` (5 min) now shows an indefinite
"Running…" rather than a permanent wrong error banner; neither self-heals, and the behaviour is
unspecified.

> **Superseded by SPEC-234** for the second consequence: a query outliving the watch's ceiling, now
> 30 minutes, settles with a warning that says where its results go, and no longer shows an
> indefinite "Running…". Full entry: `browser.md`, *A long query settles at the ceiling, judged on
> a read after it, and says where its results go*.

**EXTENDED by SPEC-199, when the API landed in this path.** The ambiguity that forced a message rule
in the browser is now resolved at the one layer holding the message: the route classifies Athena's
`InvalidRequestException` **by its text** and answers **409 `QueryNotFinished`** for a too-early read
and **400 `QuerySyntaxError`** for a statement refused at submit. Three things follow, and each is a
place a careful implementation goes wrong.

- **The client rule becomes a `code` rule** — the first time this one could be. A code rule outranks
  every message rule, which is what made the name-keyed version unsafe before and makes this version
  stronger. The old `invalid_query_execution_state|query has not yet finished` match rule is deleted,
  and the sentence is asserted byte-identical so no wording moved.
- **The caller-side gate is KEPT, and its test asserts on the CALL rather than the screen.** With the
  409 mapping in place, removing the gate produces a *correct-looking* "still running" message
  instead of the old alarming one — so a rendering assertion cannot fail any more. The assertion is
  **zero** results requests while the state is `QUEUED` or `RUNNING`. `useResultRowCount` is gated by
  a different mechanism and deliberately so: it reads no state, and its walk is stopped by
  `hasResultSet` — columns having arrived — which is a consequence of a succeeded execution rather
  than a reading of one.
- **Mapping by exception name still passes any test that exercises one case at a time**, which is
  exactly how the original defect survived; the malformed-query counter-case sits in the same file
  for that reason.

## `stateChangeReason` rides a 200 and the wording is chosen in the browser (SPEC-199)

A query Athena refuses is not an error anywhere in the plumbing: `GetQueryExecution` **succeeds** and
the reason arrives as a field. So a FAILED or CANCELLED execution is a **200** with the engine's
string byte-identical on the body — never truncated, never mapped to a code, never merged into
`detail` — and `lib/errorMessages.ts` chooses the sentence.

**This is not in tension with the API answering machine codes** (SPEC-197), and the distinction is
the whole entry: a code describes what happened to the **request**, and `stateChangeReason` is data
about a **query** that the request retrieved successfully. Mapping a failed execution onto an error
envelope is the change that looks most correct, and it retires six authored sentences — unqualified
table, table not found, column not found, Lake Formation permission, still-running, syntax error — the
`FAILED`/`CANCELLED` codes `useExploration` mints, and the last-good-rows fallback, in one move. Every
failed query then says *"Something went wrong. Contact the Administrator."* and nothing looks broken.
**No later spec may move that mapping server-side**; that is SPEC-106 reversed by a route that looked
like it was being helpful.

**Lake Formation denies in two different shapes and both must survive.** A Glue read the caller has
no `DESCRIBE` on raises `AccessDeniedException` → **403**, envelope-shaped, no AWS text in `detail`.
An Athena query the caller has no `SELECT` on does not fail the call at all — the execution reaches
FAILED and the reason names Lake Formation, on a **200**. An implementation that maps every LF denial
to a 403 handles the first perfectly and silently converts the second into an error envelope. A 403
from either is **never** a re-login: collapsing 401 and 403 makes the isolation model present as a
broken session.

**Two related fields are load-bearing and easy to lose.** `dataScannedBytes` and
`engineExecutionTimeMillis` are `null` while an execution is non-terminal, as Athena reports them — a
poll that reports a confident `0` freezes the tab's cost figure at zero. And `outputLocation` must
survive, because the export copies that object and Save results parses it.

**The generic sentence is reserved for what a user cannot act on.** That rule is why
`QuerySyntaxError` exists rather than folding into `InvalidRequest`, and it is held by
`USER_FIXABLE_CODES`, computed from the rules: a code marked user-fixable that resolves to
"contact the administrator" is a contradiction the guard can see.

## A stale result must not be served at all, so the eviction reaches the tab in front of you (2026-08-19)

The Data Explorer caches an Athena execution at `staleTime: Infinity, gcTime: Infinity`, keyed by
the SQL it rendered. That cache **is** the cost control — changing a filter and changing it back is
a hit rather than a second bill. What it could not see is a table dropped and rebuilt over
different data under the same name: the SQL renders byte-identical, so the entry stayed a hit and
the pre-rebuild rows came back for the rest of the session, with nothing on the page able to ask
otherwise.

**It evicts what is on screen, and a reload fixing it is not a fix.** The first attempt spared
observed entries to avoid a second billed `StartQueryExecution` — measured, 2 calls where there
should be 1 — which left the tab in front of the user showing old rows until they came back to it.
That is the bug, quieter. `resetQueries` rather than `removeQueries`: removal only re-runs an
observed query if something re-renders afterwards, and in the app something usually does (a toast,
a dialog closing), which is exactly the accident correctness must not rest on.

**The narrowing is what makes that affordable.** The execution key carries the TABLE, and
`invalidateSchema(client, db, table?)` takes the table its caller changed. Dropping the table you
are exploring re-runs it; creating a view beside it does not. Only a change that names no table
falls back to the whole database — an arbitrary DDL statement the user typed and the rail's own
refresh button, both of which ARE requests to re-read everything. A caller that could name its
table and does not is a bug in that caller.

**The rebuild had a second road in, and it was the reported one.** A table build is asynchronous:
the browser enqueues and the table appears minutes later, announced by a notification nothing in
the tab hears. So dropping invalidated and rebuilding did not. `armCatalogCatchUp` is **module
state drained by a listener mounted once in `ProtectedLayout`** — held per component, the arm died
with the control that set it, and both controls that enqueue a build unmount when the user leaves
that route. Residual: `focus` fires on blur→focus only, so a user who never leaves the window gets
no catch-up until they do.

**A registration, not a call beside each `invalidateSchema` site.** `features/catalog/` reaching
into `features/data-explorer/` is the undeclared shared layer pointing the wrong way; five call
sites is five things to forget, and the sixth would be written by someone who had never heard of
this cache. Not a query-cache subscription either: TanStack emits no event for invalidating a key
nothing has cached, and the rail's schema is not always loaded when DDL runs.

## A column name is user data, and the renderer must be safe without it being validated (2026-08-19)

Column names are the one part of a schema this portal does not choose — they are read out of a
file's own header or Parquet footer. Nothing judged them, and Glue accepts what Athena then cannot
read: the result is not a failed build but a table that is CREATED, appears in the rail, and fails
or returns nothing when queried.

`cpcommon.columns` is one rule shared by both planes that infer a schema. It refuses an empty name
(a blank CSV header cell), leading or trailing whitespace, anything outside `[a-z0-9_]` after the
fold, over Glue's 255, and two names that fold to the same lowercase string — the last being the
one that reads as a portal bug rather than a file bug, because `Total` and `TOTAL` are two columns
to every tool the user has and one column to Athena. It ALLOWS a leading digit, a leading
underscore and a reserved word: those are what the quoters exist for.

**The blanket `[a-z0-9_]` is stricter than AWS documents, and that is a product decision, not an
oversight.** `Order ID` builds and queries today. It is refused so that one rule holds everywhere
rather than a narrower one holding until someone writes a query by hand without the quoting this
app applies for them. Reversing it is a change to one regex.

**Creates only.** A refresh re-derives the columns of a table that already exists, so refusing one
would break every refresh of a table built before the rule and leave rewriting the source files as
the only repair. It selects on the storage descriptor, not on `mode` — a tripwire forbids the
shared verbs reading that field, because the moment one does, "a refresh reuses these verbs
unchanged" stops being true.

**On a refresh, a fold collision is refused by the diff, in a create's words.** diff-schema raises
`invalid_column_names` naming every colliding name before it classifies anything. Until then a
collision was the write's to refuse, and the write runs only when the diff reports a change, so
`Amount,region,amount` against a live `amount,region` read as unchanged, and with anything else
changed it reached the user as "couldn't be updated, try again", which cannot help. Refusing it
strands nothing: the write already refused every definition carrying one. The write keeps its
own guard, because nothing after its fold would notice a column collapsed. The mechanism is on
the [table-builder plane page](../../lambdas/info/planes/table-builder.md#the-fences).

**The fold is Athena's, `lower()`, and one function applies it to every name a refresh
compares.** diff-schema matched on `casefold()` while apply-refresh wrote and refused on `lower()`.
Full case folding maps `ß` to `ss`, so against a live `strasse` the header `Straße,notes` reported
only `notes` added. The write then landed `straße` in place of `strasse`, removing a column without
the opt-in, and the read-back passed because it compared casefolded sets. AWS documents that
Athena lowers names, and Hive normalises an identifier with Java's `toLowerCase`, which, like
Python's `lower()`, is Unicode lowercasing and keeps `ß`. So `cpcommon.columns.fold` is `lower()`,
and the create rule, the diff's match and partition-key exclusion, the write's names, comment carry
and refusal, and both catalog reads around the update all call it, as does results-conversion's
duplicate check. The two folds differ only on non-ASCII characters, which the name rule keeps out
of a create; a refresh skips that rule, and results-conversion never applies it to a query's
column names. The evidence that Athena keeps `ß` is the documentation and the Hive source, not a
live Athena run.

> **Superseded in part (2026-09-16): a CSV no longer drops the column, anywhere.** A CSV column
> naming a partition key is kept in its place under a new name, in every position, by a create, a
> refresh and a data-quality check; Parquet and JSON still drop it. The fold match and the
> measurements below still stand and are why; the drop-from-the-END rule and the
> `partition_column_not_last` refusal are gone. Full entry: *A CSV column named after a partition
> keeps its values under a new name, instead of being refused (2026-09-16)*, below.

**A column naming a partition key is dropped on the fold, and in a CSV only from the END — the
drop that reads correctly is a narrower thing than the drop that builds.** `build_create_table_ddl`
leaves such a column out of the body so the DDL stays valid, and it matched by exact name. Both
halves were measured live through the portal, and the second is why this entry exists.

*The match.* A CSV header `Year,id,region` under `year=2025/` with the key `year` rendered
`` (`Year` string, …) PARTITIONED BY (`year` string) ``, and Athena failed it with
`SemanticException [Error 10035]: Column repeated in partitioning columns`, not retryable — the
user read "creating the table failed. Please try again or contact the Administrator", which no
retry can fix. Hive's `CreateTableDesc.validate` compares the two with `equalsIgnoreCase`. A
data-quality check over the same folder failed on its temp table the same way. So the match folds.

*The drop.* Folding alone would have turned that failure into something worse. **CSV is read by
POSITION** — OpenCSVSerde takes fields in order and only skips the header — so leaving a column
out shifts every later one onto its neighbour's field, and every CSV column is a string, so
nothing errors. The exact-case drop had been doing this since the builder was written: the control
table built from `year,id,region` over the row `2025,1,south` read `id` as `2025` and `region` as
`1`, with `south` unreachable, while the rail looked right. Dropping is safe only when nothing the
table keeps follows — `id,region,year` built and read `1, south, 2025` — and Athena matches Parquet
and JSON by name, so there the drop is always safe.

So a CSV column naming a partition key anywhere but at the end is **refused**, by table-builder as
`partition_column_not_last` and by data-quality under its own reason of the same name, each naming
the column and asking for it to be moved last or taken out. `ddl.shifting_partition_columns` is the
one place that decides, and `build_create_table_ddl` raises rather than render a shifted statement,
because a renderer safe only because a caller validated first is one refactor from not being safe.
Data-quality's queries and report read the columns the drop keeps, `ddl.body_columns`, so its
duplicates grouping and its profile name only the columns its temp table has, and a column naming a
partition gets no per-column figures. The profile once projected it anyway, and Athena bound the
name to the partition column, reporting the folder's value under the user's column name. Refusing
beats renaming the column for the user: a rewritten name no longer matches the file's own header,
which is the same reason the name rule refuses rather than repairs. The refresh path drops the same
way and is NOT covered here — it writes Glue columns directly rather than through this builder, so
a CSV refresh can still shift a live table.

**The rule is not what makes the renderer safe.** `cpcommon.ddl.quote` now doubles an embedded
backtick, as `quote_dml` always did for the double quote. A renderer that is safe only because
someone else validated first is one refactor from not being safe — and data-quality proved it:
its partition keys are derived from S3 path segments, so a folder named ``ab`c=eu`` put a backtick
straight into `PARTITIONED BY`. Those keys are checked too, under their **own** reason code: the
repair is renaming a folder, and a user told to fix a column name goes looking in the wrong place.

## Athena's two dialects need two escapers in the browser, and the second was missing (2026-08-19)

`CREATE VIEW` is Trino (double quotes); `DROP TABLE` / `DROP VIEW` is Hive (backticks, an inner
backtick doubled). The browser had only `lib/sql.ts` `sqlIdentifier`, the Trino one, so both
statements interpolated their identifiers raw.

The identifier that matters is the **database**. A view or table name is typed into a dialog held
to `CATALOG_IDENTIFIER_RE`; a shared space's name is held to nothing the browser cannot bypass —
`shared-space-validate` applies **no format check** to `space` on the create path, and the SPA
talks to its queue directly. A crafted space name reaches a member's space list and from there
into DDL, under their own Athena credentials.

Both statements are quoted now, each with its own dialect's escaper (`sqlIdentifier` /
`sqlDdlIdentifier`). The lesson that generalises is the ordering: `buildCreateViewSql` was fixed
first and `DROP` two functions down was left live for a commit — **a quoting fix is not done until
every statement built from the same value is swept**, because the second one is the one nobody
tests against a real engine.

## A table's LOCATION is read recursively, so the space root is not a data folder (2026-08-19)

AWS is explicit: "Athena reads *all* data stored in the Amazon S3 folder that you specify." A table
built at a space root therefore covers `athenaresults/`, `saved_queries/`, `user_settings/`,
`shared_files/`, `shared_tables/` and `archive/` as well as the user's own data. It does not fail —
it **succeeds**, and every later read returns the portal's own bookkeeping mixed into the answer.
Succeeding is what makes it worth blocking rather than warning about.

Refused on the control with its reason (`createTableRefusal`, on `writeLockRefusal`'s
predicate-with-its-words precedent) and in `validate-authorize` as `location_is_space_root`. A
refusal rather than a hidden control: the button is where a user standing at the root looks for it,
and a control that vanishes teaches nothing about where to go instead. **Creates only** — a refresh
reads the location the table already has, so refusing one would strand any root table already in a
catalog with no way to repair it.

> **Extended (2026-09-15) — the rule was one plane short.** A data-quality check builds an external
> table over its target too, and its validator explicitly ALLOWED the root ("a legitimate, if broad,
> folder target") while the dialog offered it as the DEFAULT. So the numbers a user got for "check
> my whole space" counted the space's own `system_settings/athenaresults/` — including the running
> check's own output, which lands inside the table it is reading — plus archive receipts and
> shared-table copies. The listing already skipped those and it changed nothing, because the
> manifest is not the location. Now refused under its own reason, `location_is_space_root`,
> re-declared in `dqcommon.messages` rather than shared: the planes are independent, so **a change
> to this rule belongs in both validators**. A single file at the root stays allowed — its queries
> carry the `"$path"` predicate, so its numbers are its own — and the picker exempts a selected
> file from the folder gate for exactly that reason.
>
> **The validator's refusal is not the only route to a root table, and the second one is easy to
> miss.** `_location` promotes a SINGLE-file target to its parent folder, so a `single_file_path`
> answering "one file" for a target that is not one turns a folder ONE LEVEL BELOW the root into a
> table over the root — measured, not reasoned. The containment assertion in `_location` cannot
> catch that: the space root is inside the space. What catches it is the negative control on
> `single_file_path`, which is the only test in the fleet that plant fails. Of the exemption's two
> failure modes only one is a leak — a MISSING predicate widens the read to the whole space, a
> wrong escaper (the quoting fence above) makes it match NOTHING, a zero-row report. Presence is
> pinned both ways now; the escaper is pinned by nothing, and an apostrophe is legal in an S3 key.
>
> **Fixed (2026-09-16) — the exemption was decided twice, from an object a caller could write.**
> create-temp-tables promoted the table and start-profile-query attached the predicate, and EACH
> called `single_file_path` over the manifest it had just loaded — one definition, two reads. The
> manifest key is a function of the caller's own request id and the API's object routes took writes
> under `_data-quality-reports/`, so a two-file list written between the verbs left the table over
> the root and the queries unnarrowed. A create RETRY re-read it too, so moving the call into create
> alone would still have been once per attempt rather than once per run. Now inspect-source decides
> over the list it holds in memory and carries `pathFilter`; both verbs read that value and refuse a
> state without it rather than default to "a folder". Two guards narrow what a replaced manifest
> can still do. The manifest loader refuses any file outside the checked location — byte-scan GETs
> each listed key under a role that reads both buckets whole, so a forged list was also another
> tenant's bytes — and that holds whoever wrote the object. The object routes refuse the reports
> folder (`protected.is_in_reports_folder`), and so does the file-ops plane, the other writer a
> member reaches: it judged a copy or move by its destination prefix alone, so moving a nested
> `_data-quality-reports/` folder to the root wrote there and deleting a report was accepted. It now
> refuses each item's derived key and the folder as a delete or move source, with no role Deny
> behind it by choice — [where each item lands](storage.md#an-item-copied-into-itself-is-refused-per-item-where-a-containment-breach-fails-the-request-spec-187).
> **Closed 2026-09-16:** a request id reused past the dedup window shared the temp table, whose
> create is `IF NOT EXISTS`, so a folder check could inherit a running root-file check's table and
> query it unnarrowed, held off only by the shared Athena tokens. One execution now claims the id
> before anything is named from it — [the claim](control-planes.md#a-data-quality-request-id-is-claimed-by-one-execution-before-anything-is-named-from-it-data-quality).
>
> **Extended (2026-09-16) — the report page offered a Re-run the server refuses.** A report written
> before the refusal can name the top of a space, and its **Re-run check** sent that location
> straight back, to be refused by notification after the click. The button now carries the picker's
> own sentence as its disabled reason, through `rerunRefusal` beside `CHECK_AT_ROOT_REFUSAL` in
> `dataQuality.format.ts`, which mirrors the server's check on `isAtRoot` as `createTableRefusal`
> does. The report's location is the server's normalised form, so it gains a trailing slash before
> the comparison; a single file at the root stays re-runnable, for the predicate's reason above.

## A result's total is Athena's own count, and only a SELECT's count is the grid's (SPEC-231)

**The walk was never free once the catalog moved behind the API.** SPEC-080 counted a succeeded
result by fetching every `GetQueryResults` page. That was costless while the browser called Athena
directly; after SPEC-199 every page became a billed Lambda invocation, plus its CORS preflight,
since each page's URL carries a new `nextToken` and the preflight cache is keyed by URL. Four log
records went with every page. A 10-million-row result was about 10,000 pages over about 1.7 hours,
and on 2026-09-10 the walk wrote 23% of the log queue's messages in its saturation window.

**Athena already holds the count.** `GetQueryRuntimeStatistics` → `QueryRuntimeStatistics.Rows.OutputRows`
is the number of rows the query returned, not the rows it read: a `GROUP BY` over 5,000 rows read
reports 12. It costs one call and scans nothing. While a query runs, Athena refuses the call rather
than report a partial count. Measured in production before the browser trusted it, the first number
after `SUCCEEDED` was already final on every run. `GET /v1/queries/{id}/row-count` serves it, on
the user plane, behind `_owned_execution`.

**Only a `DML`/`SELECT`'s count is the grid's count.** `EXPLAIN` and `EXPLAIN ANALYZE` are `DML`
too, labelled `SubstatementType` `EXPLAIN`. Their `OutputRows` is 1 over a plan the grid shows as
twenty or more rows. `SHOW` is `UTILITY` and reports no rows at all (measured; `DESCRIBE` is
`UTILITY` too and is expected to do the same), and CTAS reports a summary row. So the route answers a number only for a `SELECT`. For anything else it answers "not counted",
and the browser counts by the walk, which is exact. `WITH` and `VALUES` are labelled `SELECT`. A
route keyed on `StatementType` passes every test that uses a real `SELECT`. For an `EXPLAIN` it
answers 1, and so the walk is skipped. The workspace's grid guard keeps the bar honest while the
plan fits on one page, since a 1 below the rows loaded is never shown. A longer plan, though, loses
its exact total. The discriminator is the route's answer and the missing `maxRows=1000` call, never
the bar; the guard that fails on it is the `("DML", "EXPLAIN")` case in `test_athena_routes.py`.

**Exact, never capped, and never an estimate** (Andrew, 2026-09-10). A `pending` count is asked
again on a fixed schedule (1, 2, 4, 8, 15, 30 s), and the walk runs only after the seventh ask. A
failed ask leaves the total missing rather than falling back to the walk, so a broken route shows as
"100+ rows", not as a silent return of the cost. The workspace hands every surface one total: the
pager's own count once it holds the last page, otherwise Athena's count, and only while it is at
least the rows already loaded. That guard reads the pager's current pages, so after a page-size
change it starts again from the rows loaded since. It matters only if Athena's count is ever wrong.

**The no-SQL sweep admits reading Athena's classification.** `test_no_route_module_inspects_sql`
fails any route-module literal naming a SQL keyword. It admits exactly one shape: a literal that is
a direct operand of a comparison with a `.get("SubstatementType")` read, which is Athena's answer
about the statement rather than the statement itself.

Measurements: `docs/specs/SPEC-231-count-rows-from-athenas-statistics.md`; the live readings,
`docs/testing/sessions.md` (2026-09-13).

## A CSV is checked against the columns its table declares, and a refusal is for the misread a report cannot show (2026-09-16)

> **Superseded in part (2026-09-16): the refusal this entry judged is gone.** A CSV column named
> after a partition is declared under a new name, so no file is refused and `shifted` compares each
> file with the declared columns by the name the FILES give them. The cross-file ruling — report a
> misread caused by files disagreeing, and compare each file with the table, not with the others —
> stands. See *A CSV column named after a partition keeps its values under a new name* below.

**The finding.** Data-quality's `partition_column_not_last` is judged on `sql.union_columns`, the
folder's columns in first-seen order, not on each file's header. Driving create-temp-tables with
`a.csv` = `id,amount` and `b.csv` = `id,Year,amount` under `year=2025/` gave the union
`[id, amount, Year]`, no refusal, and a temp table of `(id, amount)` over OpenCSVSerde, so `b.csv`'s
`Year` is profiled as `amount`.

**The premise under it was half false.** The finding took for granted that files whose headers
disagree are already reported by cross-file agreement. `report.cross_file` compared each file's
**sorted** names, so it caught `b.csv`'s extra `Year` but read `id,amount,Year` beside
`id,Year,amount`, and `id,amount` beside `amount,id` with no partition at all, as agreement. The
refusal and cross-file agreement were both clean for the first pair, and a layer test pinned the
second as agreeing, while a table over either reads a file under the wrong names.

**The ruling (Andrew's): report it, and keep the union.** A per-file refusal was the other option.
It would have refused only the folders with a partition-named column, traded a report that names
the odd file for a refusal that names only the column, and left the plain swap silent. The rule
recorded instead: **a refusal is for the misread no report could show** — every file agreeing, so
cross-file agreement is clean and every later column is wrong — and **a misread caused by files
disagreeing is reported**. The union is then the right unit, because a file whose own header puts a
partition column before a kept one while the union does not is always a file the report flags.

**What is checked: each file against the columns the table DECLARES, not against the other
files.** OpenCSVSerde reads field `i` of every file as declared column `i` — `sql.profiled_columns`
over the union, the same list the profile and the per-column figures use — ignores trailing fields
past the last one, and reads nulls for a short row. So a file is `shifted` exactly when a field it
has lands under a column of another name, and Parquet and JSON, matched by name, never are. Two
designs came first, and both leaked:
- *Relative order of the shared columns against the modal header* could not see a column inserted
  mid-header — `discount` added between `id` and `amount` from July on shifts every later column
  and read only as an extra column.
- *Prefix agreement with the modal header, after trimming trailing partition columns,* caught that,
  and still missed two files adding DIFFERENT trailing columns: beside `id,amount`, `id,amount,note`
  and `id,amount,region` build `(id, amount, note, region)`, so `region` is read as `note`, while
  each file lines up with the modal header.

Both compared files with each other, which is a proxy for the table; comparing with the table has
no residual case and needs no partition trimming, since a trailing partition column is simply past
the declared columns. Missing and extra still come from the modal SET, unchanged, because they name
the minority, which is the repair.

**The files named as shifted are the ones this report misreads, which is not always the minority.**
The declared order is first-seen across the files as listed, so when the first file is the odd one
out the other files are shifted and it is not. That is the honest reading of the figures the user
is looking at. The issue points at the report's own Columns section, which is the declared order,
rather than at another file.

**One issue line for all of them.** A folder whose export changed part-way through splits in two,
and a line per shifted file filled the five-line cap with one sentence, each wrongly saying it
differed from "the other 11 files" when five of them matched it. The line counts the shifted files
and names the first.

**Deploy window.** An SPA older than the field shows a shifted file with no missing or extra columns
under the disagreement heading with no detail line; the field is optional in the portal type.

**Table-builder asks a different question.** It has no union: infer-schema reads ONE sample file's
header, judges the refusal on it, and reads no other header. A file in another order is read under
the sample's names there too, and a data-quality check over the folder is what reports the
disagreement.

## Data-quality merges column names that differ only by case across files, and refuses them inside one (2026-09-16)

**The finding.** A check over a folder whose files spell one header two ways — `CustomerID,Name,Region`
in one CSV, `customerid,name,region` in another — was refused as `invalid_column_names`, naming all
six, although no file has a clash. `sql.union_columns` unioned by exact name, and the name rule then
saw two names folding to one. Table-builder, reading one sample header, builds the same folder.

**The ruling (Andrew's): merge them.** `union_columns` keys on `columns.fold`; the column is declared
once, under the first-seen spelling and with the first-seen type. The table, the profile and
duplicates queries and the report all read that one function, so the aliases stay numbered over one
list.

**Why it reads correctly in every format.** A CSV is read by position, so the name never reaches the
file. Parquet and JSON are matched by name, the catalog's lowercase against the file's own spelling,
and nothing in either storage clause maps or preserves case — so a SINGLE file with a mixed-case
column, accepted by both planes all along, already depends on that match; the merge only adds files
leaning on the same one. Confirmed on the deployed code, before the merge, through data-quality's
own readers (its JSON table uses the Hive SerDe; table-builder's OpenX one was not measured): a
check over one Parquet and one JSON file with `CustomerID` (integer), `Region` and an all-blank
`Notes` read 0%, 0% and 100% null or blank (reports `01751827-9c78-4798-9c4f-fc08af390d68` and
`fccdf86c-a992-4a33-921b-a11db4ce4b12` in `agriffith`, folder `dq_case_premise/`). The `Notes`
column is the control: a name the engine failed to match would read as 100% too. Trino's Parquet
reader tries the exact name and then `equalsIgnoreCase`; its JSON reader lowercases keys.

**A collision inside one file is still refused, and is now judged per file.** Merged by the union,
`Total,TOTAL` would be declared as one column, and a CSV read by position would take every later
column from its neighbour's field — so create-temp-tables runs `columns.check` on each file's header
and raises one refusal naming every file's offenders, first-seen. A name of the wrong shape is
judged exactly as before. In JSON the probe unions a file's sampled rows, so `CustomerID` in one row
and `customerid` in another is also refused; the engine would read those as one column, and the
refusal stands because the probe cannot tell them from both keys in ONE object, where Trino's JSON
reader keeps only the last value and drops the other without an error.

**What the report shows.** The column once, under its first-seen spelling — as a single mixed-case
file is reported — with `otherSpellings` on its entry and "Also spelled … in other files" beneath the
name. A disclosure, not a finding: it touches neither the verdict, the top issues nor cross-file
agreement, which compares folded names, naming a missing column in the union's spelling and an extra
one in the file's own. Absent when there is none, which is also how older reports read.

**Parquet type drift under two spellings** fails the profile query, as two same-named columns with
two types already did; it used to be refused by name first.

## A CSV column named after a partition keeps its values under a new name, instead of being refused (2026-09-16)

**The ruling (Andrew's).** The refusal above stopped a common export shape: a pandas groupby written
out with its index puts the key first, so `sales/year=2025/` holds files headed `year,id,region`. Create table had no way through it — inspect-source refuses leaving the
keys out when the files sit in `key=value` folders — so the only repairs were rewriting every file
or renaming every folder. A reviewer driving the real code found it refusing, with the same
message, a folder whose older files had `year` last and whose later export added a column after
it. A CSV is read by POSITION, so the file's column is kept, under a name that cannot collide, and the folder's
partition stays the partition. Nothing shifts and nothing is refused.

**The rule, in `ddl.declare_columns`.** For a format in `POSITIONAL_FORMATS`, a data column whose
fold equals a partition key's is kept in its place, in EVERY position including last, as
`<fold>_in_file`, then `_in_file_2`, `_3`… until the candidate's fold is free of every kept column,
every partition key and every rename earlier in the pass; the name is cut from the right, whole
characters, to Glue's 255-byte ceiling. Each part is there for a reason:
- *The fold as the base*, because Athena lowercases the name anyway and the name rule has already
  held a create's header to `[a-z0-9_]`, so the result passes the same rule.
- *Every position*, rather than dropping a trailing one as before: one rule to explain, and the
  data-quality report then profiles the column wherever it sits. A table built under the old drop
  gains `year_in_file` as an added column on its next refresh.
- *The taken set includes kept columns and the keys*, or `year` beside a header's own
  `Year_In_File`, or beside a second key named `year_in_file`, renders a repeated column Athena
  refuses.
- *A pure function of the columns, keys and format*, so a create and every later refresh of the
  same header agree on the name.

Parquet and JSON are matched by name, so a renamed column would read NULL there; they keep the drop.

**Every reader of the table's columns moved with it.** A create renders the renamed body. A refresh
compares (diff-schema) and writes (apply-refresh) `ddl.body_columns` for the event's `format`,
which both now require: renamed at create but dropped at refresh, the next refresh reported
`year_in_file` removed and refused without the opt-in. The refresh's fold-collision check reads the
FILES' names of the declared columns, because renamed, `Year` and `year` would become two distinct
columns and pass where a create and a check refuse that header. Data-quality's temp table, profile,
duplicates grouping and report all read `sql.profiled_columns` with one format, so the figures sit
under `year_in_file`; the report's cross-file `shifted` check compares each file with the declared
columns by the files' names through the fold, or every file carrying the column in its place would
read as misread.

**What the user is told.** Create table's ready notification appends one sentence naming each
rename (`"Year" is "year_in_file"`), derived from the state the DDL was built from and omitted,
never raised, when that state cannot be read — the table already exists. The data-quality report
carries `partitionNamedColumns`, one `{name, outcome: "renamed", as}` or `{name, outcome:
"omitted"}` per such column, and the report page says which above Columns; the omitted half closes
the gap where a JSON or Parquet column simply vanished from Columns with nothing saying why. The
field is optional in the portal type, so an older report renders as before. A refresh says nothing
extra: a renamed column it adds belongs to a table built before this rule, or to the known limit
below, and either way its count already says a column was added. The earlier objection to renaming
— a new name no longer matches the file's own header — is met by naming both, in the ready
notification and in the report. A single-file check detects no partitions, so there the column
keeps its own name.

**A known limit, not refused.** A header that later gains its OWN `year_in_file` column pushes the
rename to `year_in_file_2` on refresh; the diff reports that name added, and the live
`year_in_file` now reads the file's new column, keeping the Glue comment it had, since comments
are carried by name. It needs a user to name a column after the rename, and the refresh
notification does report a change.

**Rejected.**
- *Keep refusing, and word it better.* It leaves Create table with no path for the commonest shape,
  which is what the ruling overturned.
- *Drop a trailing column and rename only a mid-header one.* Two rules for one collision, a
  report that profiles the column in one position and not the other, and a table whose shape
  changes when an export appends a column.
- *Map the file's name through the SerDe.* OpenCSVSerde has no column-name mapping; it never reads
  the header at all.
- *Rename the partition instead.* Its name is the one the user writes in every `WHERE`, and the
  folder is what it is named after.
- *A bare number, `year_1`.* It says nothing about where the values came from.
