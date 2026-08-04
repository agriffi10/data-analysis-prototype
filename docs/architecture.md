# Architecture: S3 File Portal

**Status:** Living doc of durable design decisions + constraints. Read the section you need —
not the whole file. Code/config is the source of truth for *how*; this doc captures *why*.

Pointers (don't duplicate these here):
- Spec index + status → `docs/specs/INDEX.md`
- Env vars → `apps/portal/.env.example`; GitHub Actions vars → `.github/workflows/README.md`
- IAM policies → the `.tftpl` templates under `infra/modules/*/policies/`
- Amplify / S3 client wiring → `apps/portal/src/lib/amplify.ts`, `src/lib/s3Client.ts`

**Contents** — jump straight to the section a task needs:

- **System Overview** — orientation; the no-backend + principal-tag model in one paragraph.
- **Authentication Flow** — read when touching login, the token→credential exchange, or refresh.
- **Authorization Model** — read when touching IAM/isolation: user space, shared-space slots, analytics (TBAC).
- **Control Planes** — read *The shared pattern* before any plane work; each plane section is its decision record:
  - **Control Planes → Shared Spaces** — space lifecycle, registry, per-user caches, roster.
  - **Control Planes → Table Builder** — create-table-from-folder, inference, partition projection.
  - **Control Planes → Table Share** — snapshot push, clone-not-re-infer, recipient Map.
  - **Control Planes → Data Quality** — Athena-computed checks, report/index discovery, cost.
- **Known Constraints** — read before building on S3/LF/deploy semantics: non-atomic move, no versioning, pagination, LF hybrid mode, parallel-deploy conflict, the depends_on/ForceNew rule.
- **Infrastructure & Deployment** — read when touching IaC layout, CI/CD, CORS, or LF-admin ordering.
  - **Deploy-role IAM — adding a new resource type** — read before any spec adding new infra (self-grant propagation, scopability, refresh deadlocks).
  - **Lambda code/infra split** — read before adding or rewiring a Lambda or layer.
- **Deferred / Future Scope** — read when scoping: what is recorded as deliberately not built.

---

## System Overview

A single-page app with **no backend server**. All AWS calls come from the browser using temporary
credentials for **one shared IAM role**, issued by a Cognito **Identity Pool** that federates the
User Pool token (Amplify v6 does the exchange; `fetchAuthSession()` returns the credentials — no STS
SDK). Per-user isolation is enforced by **IAM principal tags**: the Identity Pool's *attributes for
access control* map the username claim to a `username` principal tag **server-side** (unspoofable),
and the role's policy scopes access with `${aws:PrincipalTag/username}`. No per-user roles.

**Two browser-facing data buckets.** Bucket 1 (user-space) is self-contained — IAM enforces per-user
prefix isolation by the Cognito username. Bucket 2 (shared-space, `dat-prod-shared-space`) holds
user-created shared spaces; every mutation goes through a privileged async **control plane** — the
deliberate, scoped exceptions to "no backend" (§ Control Planes). Four planes exist: **Shared
Spaces**, **Table Builder**, **Table Share**, and **Data Quality**; all share one pattern, the
`cpcommon` layer, a DLQ-drain sweep (SPEC-126), and structured logging (SPEC-127→137). An
admin-only bucket (SPEC-032) holds Athena results, the shared-space registry, and the `logs/` store.

## Authentication Flow (summary)

Amplify checks the session → no session redirects to the Cognito Hosted UI (Managed Login v2 —
`decisions.md`) → on login Cognito issues
JWTs → Amplify exchanges them with the Identity Pool (enhanced flow: `GetId` →
`GetCredentialsForIdentity`, no app code, no role ARN) → the Identity Pool stamps
`{ username: <cognito:username claim> }` as a principal tag → the portal role's trust policy admits
authenticated identities from this pool (`sts:AssumeRoleWithWebIdentity` + `sts:TagSession`) → 1-hour
temp credentials → Amplify caches/refreshes them; the app reads them via `fetchAuthSession()` and
passes them to the S3 client. On credential-expiry errors, retry once with
`getS3Client(true)` / `fetchAuthSession({ forceRefresh: true })`.

Trust policy → `infra/modules/data/policies/portal-role-trust.json.tftpl`. The `username` tag mapping
is `aws_cognito_identity_pool_provider_principal_tag` in `infra/modules/auth/identity-pool.tf` — the
tag **value** must be the `cognito:username` claim (the bare `username` claim doesn't exist in a User
Pool ID token, so it never stamps).

## Authorization Model

Two buckets, both enforced purely at the IAM layer (no app-level access control).

### Bucket 1 — User Space
Each user has exactly one prefix named after their Cognito username (`{username}/…`). The shared
portal role's permission policy (`infra/modules/data/policies/portal-role-permissions.json.tftpl`)
scopes object CRUD to `…/${aws:PrincipalTag/username}/*` and `ListBucket` to the user's prefix, with
a `Deny` on `*/DO_NOT_DELETE.txt` (the prefix marker, SPEC-014). A session without the tag matches
nothing → implicit deny. `${aws:PrincipalTag/username}` expands at evaluation time from the tag the
Identity Pool stamped, so one statement scopes every user with no per-user policy.

**How file operations map onto IAM (SPEC-015→020, +039):** the object actions
(`GetObject`/`PutObject`/`DeleteObject` + the multipart actions `AbortMultipartUpload`,
`ListMultipartUploadParts`) cover nearly everything:
- Download (presigned `GetObject`), Metadata (`HeadObject`, authorized by `GetObject`).
- Upload / create-folder (managed `lib-storage` `Upload`; single PUT ≤5 MiB, auto-multipart above —
  SPEC-016 added the multipart actions + a 7-day abort-incomplete lifecycle rule).
- Delete (`DeleteObject`/`DeleteObjects`), Move/Rename/Copy (`CopyObject` = `GetObject`+`PutObject`,
  same prefix — no new IAM).
- `ListBucketMultipartUploads` is deliberately **not** granted (unscopable per-prefix → would leak
  other users' in-progress uploads).

Frontend derives the prefix from `getCurrentUser().username` → `${username}/`.

### Bucket 2 — Shared Space (membership slots)
Access is gated by **membership principal tags** on the same shared role, extending the
`username`-tag idea. The hard AWS constraint: the Identity Pool enhanced flow maps each claim to
exactly **one single-valued** tag — no native multi-valued session tag, and IAM cannot iterate a
list inside a `Resource` ARN. Resolution: **bounded slots** (`MAX_SHARED_MEMBERSHIPS = 10`). Each
user has Cognito custom attributes `custom:shared_space_1..10`, each mapped to a principal tag; the
portal role holds one templated statement-pair per slot scoping S3 to
`dat-prod-shared-space/${aws:PrincipalTag/shared_space_k}/*` (+ a prefix-conditioned `ListBucket` +
the Glue DB ARN). An **unset slot tag is simply not stamped**, so its statement matches nothing —
implicit deny, no "empty tag grants root" risk. LF grants the shared role per shared DB; the IAM tag
is the per-user gate (not LF-Tags, not per-user roles).

**Propagation is not instant:** a membership change updates Cognito attributes; the tag stamps at
the *next* credential vend. Grant/revoke takes effect on token refresh — the UI's
Refresh-connections control forces one — and real-time revocation would need a backend (Deferred
Scope). Escape hatch if unbounded membership is ever required: a token-vending Lambda with true
multi-valued `sts:AssumeRole` tags — replaces the whole credential path; recorded, not built.

All mutations (create/membership/delete) go through the Shared Spaces control plane (§ below).

### Analytics (SPEC-032→036)
Per-user Glue-database isolation works exactly like S3 isolation — the **`username` IAM principal
tag** scopes the portal role's Glue ARN to `database/${aws:PrincipalTag/username}` (DB name =
username), **not** LF-Tags. Lake Formation grants the shared role broadly (per-DB grant issued by the
SPEC-033 post-confirmation Lambda); IAM is the per-user gate. The user-space bucket is registered in
LF **hybrid** mode so the file browser keeps direct-IAM S3 access while Athena reads via LF.
**Control-plane table creation is TBAC** (070/111 correction): a `portal-managed` LF-Tag on every DB +
one tag-policy grant per execution role + a static per-bucket `DATA_LOCATION_ACCESS` — LF **admin**
status does **not** grant `CREATE_TABLE` on a DB the admin didn't create (it buys grant-ability +
catalog-wide Describe, which fixes the `AccessDenied`-vs-`EntityNotFound` read foot-gun only). See
`infra/modules/analytics/lakeformation.tf` + `decisions.md`. Detail: `docs/specs/ARCS.md`
(analytics arc) + `docs/specs/SPEC-032`.

---

## Control Planes (privileged async pipelines)

Four features perform privileged, cross-user, multi-step AWS work that browser-scoped credentials
must not: shared-space lifecycle, table creation, table sharing, and data-quality checks. Each is a
deliberate, recorded reversal of "no backend" for its mutations only — the rest of the app stays
browser-direct.

### The shared pattern

- **Enqueue-only browser.** The browser's sole new grant per plane is `sqs:SendMessage` to that
  plane's request queue (URL via a `VITE_*` var); the request body carries the caller's ID token.
- **FIFO SQS (+ FIFO DLQ) → EventBridge Pipe → Standard Step Function → single-task verb Lambdas**
  (never an `action`-switch monolith); Retry/Catch live in the state machine. Each plane is its own
  `infra/modules/<plane>/` module — reuse the **pattern**, never the resources. Rationale: keeps the
  privileged surface off user credentials, durable retry/replay + DLQ, explicit observable states.
  (The notifications write pipeline, SPEC-058→061, is deliberately simpler: FIFO SQS → writer
  Lambda, single-writer, no Pipe/SFN.)
- **Trusted actor.** `validate-authorize` verifies the ID token offline (User Pool JWKS) and derives
  the actor server-side — never from the untrusted body. Shared-space authorization reads the
  registry; personal targets must resolve inside the actor's own prefix/DB.
- **One shared execution role per plane.** Per-verb least-privilege roles were built and deliberately
  consolidated (SPEC-062; table-builder post-072) — the union policy lives in the module's
  `execution.json.tftpl`. Creates on LF-gated DBs come via **TBAC** (Authorization Model →
  Analytics); roles are LF admins for Describe only.
- **Layers.** Every verb attaches `cpcommon` (SPEC-107/125: boto/JWKS clients, env config, ID-token
  verification, notifications send, observability, `errors`) + a domain layer
  (`shared-space-common` / `tbcommon` / `tscommon` / `dqcommon`). polars is its own layer, attached
  only to verbs that read file bytes (table-builder `infer-schema`, data-quality `inspect-source`).
- **Replay-safe.** Verbs tolerate already-exists/already-absent; `CREATE … IF NOT EXISTS`;
  deterministic S3 keys; shared JSON mutates under **ETag compare-and-swap** (`casio`, SPEC-082).
- **The 256 KB SFN state cap.** `States.DataLimitExceeded` escapes every `Catch` — the worst failure
  mode (no notification). Pass **S3 pointers between states, never inline lists** (learned
  independently in table-share PR #256 and data-quality). Never decode an error `Cause` in ASL
  (#252, uncatchable `States.Runtime`) — carry raw `$.error`, decode via
  `cpcommon.errors.failure_reason`.
- **Outcomes via the notifications inbox** (SPEC-058 trusted-producer contract; best-effort;
  `@notifies_on_failure` on every verb; friendly wording per SPEC-106). The UI never blocks —
  transient toast + pending state; terminal SFN states write nothing durable.
- **Ops.** Request DLQs are swept every 10 min by the shared drain (SPEC-126; the notifications DLQ
  stays undrained — circular). All planes emit structured logs (SPEC-127→137).

### Shared Spaces — SPEC-050→057, 062, 073, 075, 082, 125

A shared space is a named collaborative space: name = S3 prefix in `dat-prod-shared-space` = Glue DB
name, globally unique, non-renameable (exactly as a username is for a personal space). Creator =
**owner**: adds/removes members (validated against the User Pool via `ListUsers`/`AdminGetUser`,
unknowns silently dropped), deletes the space (cascade: files, tables, DB, all slots/caches,
registry). Members leave; everyone sees one shared copy. **Create is creator-only** — members are
added post-creation.

- **SFN:** validate-authorize → `Choice(action)` → one verb (`create-space` / `add-members` /
  `remove-members` / `leave` / `delete-space`; SPEC-073 added `acknowledge-membership` — flips the
  member's chip pending→active, display/bookkeeping only, access is granted at add time). One shared
  **`orchestrator`** role for the SFN + all verbs.
- **Registry = source of truth:** `<admin-bucket>/shared-spaces/{name}.json`, pipeline-writable
  only. Name uniqueness via conditional `PutObject` (`If-None-Match: *`); mutators are ETag-CAS
  (SPEC-082). The admin bucket's expiry lifecycle excludes this prefix.
- **Per-user UI cache:** `{username}/user_settings/shared-connections.json`, written by the pipeline
  into each member's prefix, with per-entry status (`provisioning`/`active`/`failed`/`leaving`).
  Missing cache = empty state, never an error. SPEC-075: every member gets a read-only roster;
  `cache.write_roster_to_all` fans out on add/remove/leave.
- **Results routing:** querying a shared DB sets the per-query `OutputLocation` to
  `dat-prod-shared-space/{name}/athenaresults/{username}/` (delete-denied, mirroring the personal
  lock); personal queries route to the personal `athenaresults/` unchanged.
- **LF:** the bucket is registered hybrid; create-space issues the per-DB grant to the shared portal
  role (as SPEC-033 does per personal DB).

### Table Builder — SPEC-066→072, extended by SPEC-143

"Create table from this folder" in the file browser: create a Glue/Athena **external table** over a
folder's data files in the database the space maps to. Data columns are **inferred**; partition keys
are **user-declared** in the modal.

- **SFN — two branches over one shared spine** (was linear until SPEC-143): validate-authorize →
  `RouteByMode` → {check-table-absent (Glue `GetTable`) | load-table-definition} → inspect-source →
  infer-schema → `RouteTailByMode` → {execute-ddl | the refresh tail}. The `mode` field on the
  envelope (`"create" | "refresh"`, absent ⇒ create) selects the branch; **inspect-source and
  infer-schema are shared and know nothing about it**, because load-table-definition normalises the
  state into exactly what a create would have handed them. FIFO `MessageGroupId` = **target
  database** (same-DB creates *and refreshes* serialize; the duplicate-name race is closed by
  check-table-absent + `IF NOT EXISTS`). Refresh eligibility and the reconstruction rules:
  `decisions.md` → *Refresh eligibility turns on SHAPE*.
- **Formats (v1):** Parquet, CSV, JSON/NDJSON — one consistent format per folder; ORC out (no
  native polars reader). **CSV is not type-inferred** — all columns `string` (names from the header;
  header + comma assumed) via OpenCSVSerde. Parquet/JSON infer types and parse dates.
  **JSON must be NDJSON** (one object per line — what Athena's SerDe needs anyway), and the schema
  comes from **one sample file** — fields present only in other files are silently dropped
  (multi-file schema union is a deferred enhancement; both limits are user-guide material).
- **Partitions = user-declared keys + Athena partition projection, never `MSCK REPAIR`.** Keys are
  declared in granularity order, each with a projection type + range (`integer` / `date` /
  `enum`-string — not `injected`); `inspect-source` validates the declared `key=value/` segments
  exist. The table is queryable the instant `CREATE` succeeds; later partitions are picked up
  automatically. A value outside a declared range is silently excluded (modal copy warns).
- **DDL via Athena** `StartQueryExecution` (`CREATE EXTERNAL TABLE IF NOT EXISTS`), polled to
  terminal — the same LF-enforced create path users already exercise, not the Glue `CreateTable`
  API.
- **Authorization:** personal = target DB equals the actor's username; shared = actor is an active
  member (any member may create, not owner-only). The table location must resolve inside the target
  space; the name is catalog-safe (`CATALOG_IDENTIFIER_RE`).
- **Notifications:** single recipient = the actor; per-step failure reasons + a success message.

### Table Share — SPEC-088→094

"Share table" from the Query schema rail: a **one-time snapshot push** (no consent step, no sync) —
copy the source table's data files into each recipient's `shared_tables/{tableName}/` and create a
table over them in the recipient's DB.

- **Clone the source Glue definition — never re-infer.** Columns, SerDe, `TableType`, partition
  keys, and `TBLPROPERTIES` (incl. projection props) are reused verbatim with only `LOCATION`
  repointed — format-agnostic, exact schema, no `MSCK`. **v1 sources:** flat or
  projection-partitioned base `EXTERNAL_TABLE`s; views, catalog-registered-partition tables,
  non-external tables, and unresolvable `LOCATION`s are rejected (partition-metadata copy deferred).
- **SFN:** validate-authorize → inspect-source (clone def, list objects, enforce caps) → **`Map`
  over recipients** (check-target-absent → copy-objects → create-table) with a **per-item `Catch`**
  — one recipient's failure never aborts siblings. Conflict (name exists, or a non-empty target
  prefix) fails **that recipient only**; no overwrite. FIFO `MessageGroupId` = source
  `database.table` (a heavy copy never overlaps itself).
- **Recipients:** a `user` must exist in the User Pool; a `space` is **any space by name** — the
  sender need not be a member (deliberate, recorded: the execution role does the write). The sender
  must have **source** access (own DB, or active member of the source space).
- **Copy:** parallel server-side `CopyObject` (multipart above 5 GiB), key layout preserved. Caps:
  `SHARE_MAX_OBJECTS` / `SHARE_MAX_TOTAL_BYTES` / `SHARE_MAX_RECIPIENTS` (50) /
  `SHARE_MAX_DEFINITION_BYTES`. S3 Batch Operations is the recorded scale escape hatch.
- **The 256 KB cap, twice:** the copy plan rides as an S3 pointer
  (`<admin-bucket>/table-share/{hash}/copy-plan.json` — inline, the Map's `ItemSelector` put the
  state at 101% of the cap, PR #256); the recipient cap exists because each failed Map item carries
  raw `{Error, Cause}` and `cpcommon.errors.bounded_detail` truncation is the other half of the
  bound.
- **Notifications:** the sender hears every per-recipient outcome; on success the recipient is also
  told (a user directly; a space via its **owner only**, never the members). Failures notify the
  sender only.

### Data Quality — SPEC-108→114, 123, 124

"Check data quality" on a file or folder (CSV/TXT, JSON/NDJSON, Parquet; classification by
**extension**; no Excel — convert to Parquet first). Diagnostic only — it never writes to the
source.

- **The work is Athena's, not Lambda's.** Real sources reach 250 GB; a Lambda byte-pass would take
  hours against a 900 s ceiling. Athena computes the exact checks in minutes. The accepted cost:
  the execution role holds Glue + Athena + LF (TBAC create; admin = Describe only) — the same blast
  radius as table-builder, deliberately surrendered for exactness (sampling and Fargate-in-a-VPC
  were both rejected; Fargate remains the recorded escape hatch).
- **The Athena poll lives in the state machine** (`Wait(30s)` → check-query → `Choice`), not inside
  a Lambda — the plane's key structural difference; Standard executions remove the time ceiling.
  What remains is the **account-level Athena DML quota: 30 min default, 240 by support ticket** —
  the real ceiling on the feature. The dedicated workgroup leaves `bytes_scanned_cutoff_per_query`
  **unset** (the portal workgroup's 10 GiB cutoff would fail every real check); result location is
  set per query. `StartQueryExecution` carries `ClientRequestToken = requestId` (a retry must not
  start a second query); temp tables are `dq_tmp_{hex32}` (hyphens parse as subtraction).
- **Verbs:** validate-authorize → inspect-source (writes a **manifest to S3**; probes every file's
  header/schema — it carries the polars layer, because Athena needs an explicit column list for
  Parquet/JSON) → create-temp-tables → start-profile-query → poll → byte-scan → assemble-report →
  **drop-temp-tables, reached from every failure path** — safe because it touches Glue only and the
  role has **no `s3:DeleteObject` anywhere**, plus an explicit `Deny s3:PutObject` on
  `*/user_settings/*` and `*/DO_NOT_DELETE.txt` (an overwrite of `notifications.json` would be
  unrecoverable).
- **Checks — exact:** per-column type consistency via `TRY_CAST` (skipped for Parquet, and the
  report says so — the format enforces types), null/blank ratios, row counts per file (`"$path"`)
  and total, JSON key drift (the **Hive** JSON SerDe, never OpenX — OpenX yields nondeterministic
  nulls and the story rests on "null = missing key"). **Duplicates run as a separate query** (a
  full shuffle — the most expensive thing Athena does) and degrade to `not_computed` on resource
  exhaustion rather than failing the check. `DQ_MAX_COLUMNS` (200) guards Athena's 262,144-byte
  query-string cap.
- **Checks — approximate (labelled in report and notification):** ragged rows via a single-column
  raw-line temp table (`\001` delimiter; quoted delimiters and embedded newlines over-report;
  SPEC-142 tracks the union-column-count double-count bug); invalid UTF-8 via `byte-scan`, bounded
  **per request** (`DQ_SCAN_TOTAL_BYTES`, 2 GiB, divided across the manifest) with coverage %
  stated. Compressed text isn't splittable — a large `.gz` is rejected with guidance.
- **Queueing:** `MessageGroupId` = SHA-256 of the canonical location (raw S3 keys can exceed SQS's
  128-char cap); `MessageDeduplicationId` = `requestId`.
- **Report & discovery:** `{space}/_data-quality-reports/{requestId}/report.json` — the key is a
  pure function of `requestId`, so a replay overwrites byte-identically. The folder is hidden in
  the browser; the notification deep-links to `/data-quality/:space/:requestId` (SPEC-113: space in
  the route, a denied view issues **no** S3 request); the `/data-quality` dashboard (SPEC-123)
  reads a per-space `index.json` appended under ETag CAS (capped 200, every failure swallowed —
  durability order report → notification → index) and can start new checks (SPEC-124).
- **Cost, honestly:** ~$5/TB scanned × multiple scans (profile, raw-line, duplicates) ≈ $2.50–3.75
  per 250 GB check, with **no scan guardrail** and nothing capping runs per user — revisit before
  real users arrive.

---

## Known Constraints

- **No backend / API proxy.** All AWS calls are from the browser. A use case needing elevated
  permissions beyond user-scoped IAM would require adding a Lambda/API layer — a significant change.
  (The control planes are the recorded, scoped exceptions.)
- **Move and rename are non-atomic.** S3 has neither; the app does `CopyObject` + `DeleteObject`
  (rename = move within the same parent). For a folder this is *recursive* and can *partially fail* —
  a per-key copy failure must never delete that source and never abort the rest (SPEC-018/019). No
  transactional rollback; the UI reports which keys succeeded/failed.
- **No overwrite protection from S3.** Versioning is off (SPEC-010; deferral re-affirmed 2026-08-03
  pre-production — revisit before real user data lands, see `security-baseline.md`), so writing an
  existing key destroys the prior object. The app guards in the UI with warn-and-confirm (HEAD-check →
  Overwrite or Rename) on upload and move/rename — there is no server-side safety net.
- **Listing pagination.** `ListObjectsV2` returns ≤1,000 keys/call. The browser paginates with
  `ContinuationToken` via TanStack `useInfiniteQuery` + a "Load more" control; never assume one page
  is the whole folder.
- **File size limits.** Uploads use managed `lib-storage` (auto-multipart above 5 MiB), configurable
  max (default 5 GiB, `VITE_MAX_UPLOAD_BYTES`); files above it are rejected client-side.
- **Lake Formation hybrid mode.** Both data buckets are registered in *hybrid* access mode
  (SPEC-032/050). Do **not** flip to enforced (non-hybrid) without first opting in every principal —
  it would break the file browser's direct-S3 access. Enabling LF enforcement (dropping the
  `IAMAllowedPrincipals` Super grant) is safe only alongside the portal-role Glue scoping +
  SPEC-033's per-DB grants.
- **Usernames are constrained at signup** (= S3 prefix = principal tag = Glue DB name). Pre-signup
  Lambda enforces the rule; SPEC-033 tightens it to catalog-safe `^[a-z][a-z0-9_]{2,62}$`. Pool is
  case-insensitive.
- **SPA client-side routing.** CloudFront must serve `index.html` for 403/404 or refresh/direct-URL
  navigation returns a raw S3 error.
- **`shared-connections.json` is a cache, not the record.** The pipeline-written per-user file under
  `user_settings/` only mirrors the S3 registry; the UI treats a missing file as empty, not an error.
- **`Deploy Infrastructure` and `Deploy Lambdas` run in parallel on the same push.** A change that
  rewrites a function's Terraform **env block** while CI is calling `UpdateFunctionConfiguration`
  to attach its layers fails with `ResourceConflictException: An update is in progress for
  resource: <arn>`. Nothing is wrong with the code — re-running the failed job after the apply
  settles succeeds. It bites any spec that changes Lambda **env** and Lambda **code** in one push
  (seen on SPEC-129, which moved all nine data-quality functions to a new queue URL); a real fix,
  if ever needed, is a `needs:` edge or a retry, not a spec change.
- **Inside a module with a module-level `depends_on`, prefer a variable over a data source for
  anything feeding a ForceNew attribute** — a pending change in the dependency defers the data
  source to apply time, and `(known after apply)` on a ForceNew attribute plans *"must be
  replaced"*. This had every infra apply destroying and recreating `module.auth`'s identity-pool
  principal-tag mapping (the ABAC keystone) until `data.aws_region.current.name` became
  `var.aws_region`; `ignore_changes` is the wrong tool — nothing drifts (contrast
  `aws_lakeformation_permissions`, where the API genuinely reads back different values and
  `ignore_changes` is correct). The two `archive_file` placeholders in `modules/auth` defer the
  same way but are harmless (`ignore_changes = [filename, source_code_hash]`). Full narrative:
  the comment above the resource in `infra/modules/auth/identity-pool.tf`.

## Infrastructure & Deployment

IaC is OpenTofu under `infra/`, organized as bounded-context modules — `app`, `base`, `auth`, `data`,
`analytics`, `lambda-artifacts`, `notifications`, `observability`, `control-plane-dlq-drain`, and one
per control plane (`shared-spaces`, `table-builder`, `table-share`, `data-quality`); IAM policies are
`.tftpl` templates under each module's `policies/`. The GitHub Actions
**deploy role** (`infra/modules/base`) applies all IaC via `deploy-infra.yml` — **any spec adding new
infra must expand the deploy-role policy** as in-scope work. The SPA deploys as static files to S3 +
CloudFront (OAC origin; custom error responses 403/404 → `/index.html` for SPA routing; a
response-headers policy carries the enforcing CSP + security header set — SPEC-140, `decisions.md`).
`deploy-app.yml` uploads `dist/` in **three prefix-scoped passes** so hashed assets are `immutable`
and the shell is `no-cache`, with exactly one `--delete` — SPEC-141, `decisions.md`. Build-time
`VITE_*` vars are GitHub Actions variables (see `.github/workflows/README.md`); resource→spec mapping
and current values come from `tofu -chdir=infra output`. Security scanning: `security.yml` runs the
report-only scanner suite (SPEC-138); `deploy-infra.yml`'s plan job Checkov-scans the **rendered**
`tofu show -json` plan for IAM (SPEC-139) — details in `docs/decisions.md` + `docs/security-baseline.md`.

> **CORS:** both browser-facing buckets need CORS or all SDK calls fail — the most common first-time
> setup issue. Managed in the bucket modules' `.tftpl`/`s3.tf`.

**Cross-module LF-admin ordering:** a role named in `aws_lakeformation_data_lake_settings.admins`
must exist first (LF rejects unknown principals) — `module.analytics` carries `depends_on` on the
control-plane modules whose execution roles it admits, and the admins list is built from
**constructed strings in root `locals`** (an unknown element inside `compact()` silently drops the
change — see the deploy-role trap list below).

### Deploy-role IAM — adding a new resource type

The deploy role **self-grants** (in `module.base`) the permissions it then uses later in the *same*
`tofu apply`. Adding a new resource type to the IaC repeatedly surfaces the same traps — work through
this list before merging:

- **Self-grant propagation.** A freshly-granted permission may not have propagated by the time a new
  resource uses it. Gate first-use resources on a `time_sleep` (~60s). Caveat: a `time_sleep` with no
  `triggers` runs **once** at creation and never re-fires — so adding an Nth resource that `depends_on`
  an existing sleep gets zero delay and can hit `AccessDenied` on the **first** apply. Accepted fix:
  **re-run the deploy** (`module.base` attaches the policy first, so the grant is propagated by the
  re-run). Expect one first-apply failure when extending an existing module, then a clean re-run.
- **Some actions are not resource-scopable** — they only authorize on `Resource: "*"`; a narrower ARN
  is an implicit deny. Known offenders: `logs:DescribeLogGroups`, `cognito-idp:DescribeUserPoolDomain`,
  `cognito-idp:CreateUserPool`. Put each in its own `"*"` statement. Verify scopability cheaply with
  `aws iam simulate-custom-policy --action-names <a> --resource-arns <arn>` (`allowed` vs `implicitDeny`)
  before spending a CI round.
- **CloudWatch log-group actions need both ARN forms.** `logs:ListTagsForResource` authorizes against
  the **bare** ARN (`…:log-group:NAME`) while others use the `…:log-group:NAME:*` form — scope the
  statement to a list of both.
- **`s3:ListBucketMultipartUploads` does not support `s3:prefix`** — under a prefix condition it is
  always an implicit deny (a dead grant), and it would leak other users' in-progress uploads. Don't
  grant it. The prefix-scopable multipart actions are `s3:AbortMultipartUpload` /
  `s3:ListMultipartUploadParts`; create/upload/complete ride on `s3:PutObject`.
- **Refresh-before-policy-update deadlock.** Once a resource is in state, `tofu apply` **refreshes**
  it (using the role's *current* policy) before applying the policy fix — so a scope fix that the
  refresh itself needs can never land. **Break-glass (preferred): dispatch `Deploy Infrastructure`
  with `skip_refresh=true`**, which applies from cached state; then dispatch again *normally*, because
  an apply that skipped refresh has proved nothing about drift. Out-of-band `aws iam put-role-policy`
  remains the fallback when even that cannot run.
  - **Tightening a grant deadlocks exactly like widening one** (the SPEC-139 follow-up). Two
    imperatives: (a) a **mapping ARN and a function ARN are different resource types** — check
    every resource type an action accepts before scoping, not just the one you have in mind;
    (b) **a green `plan` is not proof the apply will work** — IAM is eventually consistent.
    Narrative: `decisions.md` → *Deploy-role refresh deadlock*.
- **Resource policies (bucket/KMS) can lock out the deploy role too.** Always **except the deploy role**
  from any resource-policy `Deny` that covers a read the AWS provider uses on refresh — otherwise the
  provider sees the resource as "deleted" and every plan proposes a destructive recreate. Same
  break-glass shape (`put-bucket-policy` out-of-band, then merge).
- **`depends_on` defers data sources (benign plan noise).** `module.auth`/`module.data` declare
  `depends_on = [module.base]`, so any PR touching `module.base` makes their data sources unknown at
  plan → cascades to `(known after apply)` and can show the identity-pool principal tag as
  *force-replace*. At apply these resolve to identical values (no-op / identical recreate). This is
  **not** drift — don't panic at the plan.
- **An unknown ARN inside `compact()`/a list silently drops the change.** A cross-module ARN that is
  unknown-at-plan (e.g. a role created in the same apply) inside `compact()` made OpenTofu plan *no*
  change to a list attribute — the value was never written. **Rule:** any cross-module ARN feeding a
  list/set attribute must be a **constructed string in root `locals`** (so it's known at plan time);
  apply ordering is still preserved via the `depends_on` chain.
- **Lake Formation enforcement hides the catalog from non-admins.** After LF enforcement, a principal
  with no LF grant sees empty `get-databases` / `AccessDenied` on `list-permissions` — that's the
  isolation working, not a failure. Verify per-user provisioning via the post-confirmation Lambda's
  CloudWatch logs or by querying as an LF admin (only the deploy role + control-plane execution
  roles + post-confirmation exec role are LF admins).

### Lambda code/infra split (established SPEC-012)

Lambda **code** and **infrastructure** are deliberately separated; `tofu apply` never touches code:

- **Source** lives at repo-root `lambdas/<function-name>/<module>.py` (Python) with a shared
  `lambdas/requirements.txt`. Use **underscores** in the `.py` filename (e.g. `pre_signup.py`,
  handler `pre_signup.handler`) — a hyphenated filename can't be imported as a module.
- **Terraform owns only the function infrastructure** (function resource, exec role, log group,
  trigger wiring) and bootstraps the function with an inline `archive_file` placeholder +
  `lifecycle { ignore_changes = [filename, source_code_hash] }`.
- **GitHub Actions owns the code.** `.github/workflows/deploy-lambdas.yml` (matrix over functions)
  builds each package, uploads to the artifacts bucket (`infra/modules/lambda-artifacts/`) at
  `<name>/<git-sha>.zip`, and runs `update-function-code --publish`. Triggered on push to `main`
  touching `lambdas/**`, plus manual dispatch.
- **IAM trust + permission policies are `.tftpl` templates** under the owning module's `policies/`,
  rendered with `templatefile()` — **no inline `jsonencode` IAM policies** anywhere.
- **Shared layers deploy like code.** CI builds + publishes the Lambda layers (`cpcommon`, the
  per-plane `*-common` layers, polars) and attaches them; Terraform never manages layer versions.
  `lambdas/test_deploy_matrix.py` joins the deploy matrix against what each function **imports** —
  the gate that catches a function shipped without a layer it needs (the SPEC-137 outage).
- Adding a Lambda = create `lambdas/<name>/`, add function infra in the owning module
  (placeholder + `ignore_changes`), add a `{ name: <name> }` row to the `deploy-lambdas.yml` matrix,
  and extend the deploy-role policy for any new actions. The first `deploy-infra.yml` apply must
  precede `deploy-lambdas.yml` (function + bucket must exist first).

## Deferred / Future Scope

File preview (PDF/image in-browser) · admin UI (user mgmt, access audit) · audit logging
(CloudTrail/S3 access logs) · staging environment + promotion pipeline · real-time access revocation
(needs a backend) · Excel support + a file-converter pipeline (arc cancelled; convert externally,
then check/build over Parquet) · table-share partition-metadata copy + S3 Batch Ops scale path ·
table-builder multi-file schema union · data-quality report retention/TTL + cost guardrails.
