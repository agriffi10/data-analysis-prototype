# Completed Spec — SPEC-111: Data Quality — Temp Tables + the Athena Profile Query

The arc's load-bearing spec: build throwaway Glue tables over the source, run three
separately-degradable Athena queries, let the STATE MACHINE poll them, tear the tables
down on every path. Shipped in two PRs — #238 (execution-role IAM + LF admin, applied
first) then #239 (the four verbs + the queries). The live end-to-end run was unblocked
and completed 2026-07-20 (see Verification).

## What was completed?

- **`dq_create_temp_tables.py`** — `dq_tmp_{hex32}` typed external table from the
  manifest's column union; CSV all-string OpenCSVSerde, JSON **Hive** JsonSerDe, Parquet
  native; partition projection from SPEC-110's detected keys; `IF NOT EXISTS`. CSV also
  gets `dq_tmp_raw_{hex32}` (one column, LazySimpleSerDe, `\001`, no header skip). Table
  names are written onto the outgoing state **before** any CREATE runs.
- **`dq_start_profile_query.py`** — starts three queries with distinct
  `ClientRequestToken`s (`{hex32}-profile|-ragged|-dupes`) and a per-query
  `ResultConfiguration`. Never waits.
- **`dq_check_query.py`** — one `GetQueryExecution` per *pending* query; profile failure
  is terminal (`query_failed` / `query_timeout`), ragged/duplicates degrade to
  `not_computed`.
- **`dq_drop_temp_tables.py`** — idempotent, tolerant of nothing to do, and it never
  raises.
- **`dqcommon.sql`** — the DDL builders + the three query builders.
- **`dqcommon.manifest`** — the manifest read, shared by the verbs (SPEC-112 will use it).
- **`cpcommon.ddl`** — table-builder's verb-local `ddl.py` consolidated with an injectable
  storage clause; **`cpcommon.athena`** gains `start_query` + `describe_query`.

## What changed from earlier specs?

- **`table-builder-infer-schema/ddl.py` is gone**, folded into `cpcommon.ddl` (user
  decision; mirrors PR #229's `type_mapping` move). Its five golden-string tests moved to
  `test_ddl_cpcommon.py` **unchanged**. SPEC-118 should use this module.
- **The `QueryComplete` Choice branches on ONE aggregate `queryStatus`**, not three
  per-query rules — a Choice reading `$.ragged.status` on a null (JSON/Parquet) raises
  an un-catchable `States.Runtime`.
- **`athena:StopQueryExecution` was deliberately not granted** — no verb stops a query.
- **Three new reason codes** (`too_many_columns`, `query_failed`, `query_timeout`);
  deliberately none for a failed ragged/duplicates query (those never become terminal).

## Deviations / decisions made in flight

- **`union_columns` keeps the FIRST-SEEN type on a cross-file conflict** (the spec says
  "their union" without addressing conflict); SPEC-112 FR-002's cross-file drift check is
  what reports the disagreement.
- **The raw-line table is flat even for a partitioned source** — SPEC-110 refuses a layout
  mismatch, so both tables see the same object universe.
- **The ragged query excludes blank lines explicitly** (a blank line splits to one empty
  field → would count as ragged on any multi-column source).
- **Two offending-value samples per column** (non-numeric, non-temporal); SPEC-112 picks
  the one matching the dominant type family.
- **`drop-temp-tables` swallows all errors** — raising would mask the user's real reason
  on the failure path / report a finished check as failed on the success path.
- **DDL vs DML quoting** — Athena parses DDL as Hive (backticks), DML as Trino (double
  quotes); `cpcommon.ddl` exposes both `quote` and `quote_dml`.

## Verification

- `pytest lambdas/` — **667 passed**; `ruff` clean; `tofu fmt -check` + `validate` clean.
- **11 mutations, each caught** (list below).
- All 10 generated statements parse under `sqlglot` (6 DML `trino`, 4 DDL `hive`) — a
  one-off isolated-venv check; sqlglot is not a repo dependency.
- Measured at `DQ_MAX_COLUMNS = 200`: profile query **174,178 bytes (66% of Athena's
  262,144 cap)**, 1,403 result columns, `1 + fileCount` rows. Parquet: 17,238 bytes.

### The live end-to-end run (2026-07-20) — RESOLVED

Phase 3's "end-to-end run against a real multi-file folder" ran green against the
production account (actor `agriffith`, `agriffith/dq-smoke/`, 3 CSVs, 4 columns), driving
the verbs directly with the state `validate-authorize` emits (auth bypassed on purpose —
the browser entry point is SPEC-113):

- **`inspect-source`** → `format=csv, files=3`, manifest written.
- **`create-temp-tables`** → created `dq_tmp_…` + `dq_tmp_raw_…` in `agriffith` (real Glue
  DDL against a real catalog — the `$path` GROUPING SETS + `max_by` sample DDL).
- **`start-profile-query`** → all three queries launched.
- **`check-query`** → `profile=SUCCEEDED ragged=SUCCEEDED duplicates=SUCCEEDED` (real
  Athena engine, real query states through the poll shape).
- **`drop-temp-tables`** → `dropped=[both]`, `failed=[]` (cleanup against real tables).

**Unblocked by the TBAC fix (PRs #243–#246, this session).** SPEC-070/111's premise that an
LF *admin* execution role can create tables catalog-wide is **false** — admin grants
neither `CREATE_TABLE` on a database it didn't create nor `ASSOCIATE` on an LF-Tag. The fix
(now the settled decision — see CLAUDE.md → *Control-plane table creation = TBAC*) tags
every managed DB with a `portal-managed` LF-Tag and grants the three control-plane roles on
the tag (+ static per-bucket `DATA_LOCATION_ACCESS`). Before it, `create-temp-tables` failed
with *"Required Create Table on agriffith."*

**Not asserted:** the exact profile *values* (row counts, the deliberately-dirty-column
finding). The queries provably SUCCEEDED, but the result files land in `agriffith`'s
prefix, which the operator seat (`tofu-deploy-user`) is denied by the user-space bucket
policy — reading the numbers needs `agriffith`/admin creds (or SPEC-112's `assemble-report`,
which reads them as the execution role). Everything else in Phase 3 is exercised and green.

### Three defects the work surfaced (during build)

1. **Profile query exceeded Athena's 262,144-byte cap** (323,776 bytes / 124% first form) —
   fixed by projecting each column once to a short alias; a test pins the size.
2. **A vacuous Parquet-skip test** (used a `bigint` column → passed via the non-string
   rule, never exercised the format rule) — now a string column + a CSV twin.
3. **Backticks in DML** (all three queries built with the DDL quoter) — every unit test was
   green with the bug; caught by reading against Athena's dialect rules.

## Docs sweep (completion-ritual step 6)

Nothing to do — no `apps/` code touched and the arc still has no user-facing surface (the
file-browser entry point + report view are SPEC-113). Component inventory untouched (it
covers `apps/portal/src/` only).

## Mutation list

injected storage ignored · override inherits the CSV header skip · ragged/duplicates no
longer degrade · profile failure no longer terminal · `ClientRequestToken` dropped ·
Parquet no longer skips TRY_CASTs · ragged blank-line exclusion removed · GROUPING SETS →
plain GROUP BY · column cap removed · cleanup drops nothing · DML quoting reverted to
backticks.
