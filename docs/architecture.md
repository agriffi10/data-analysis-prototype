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

Six features perform privileged, cross-user, multi-step AWS work that browser-scoped credentials
must not: shared-space lifecycle, table creation, table sharing, data-quality checks, sending files
to another person or space, and archiving a file or folder into Glacier (with its restore). Each is a deliberate, recorded reversal of "no backend" for its
mutations only — the rest of the app stays browser-direct.

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
- **Layers.** Every verb attaches `cpcommon` (SPEC-107/125: boto/JWKS clients, lazily-resolving env
  config, ID-token verification, notifications send + FIFO `dedup_id`, observability, `errors`,
  `messages`, `cas`, `results`, `athena.bound_runner`, `events`, `ddl`, `glue`, `s3_listing`,
  **`transfer` — the bulk-copy engine: JSONL manifest writer, batch copier, Map Run result reader
  (SPEC-160; table-share is the first caller, file-send and archive are the next two)**) + a
  domain layer (`shared-space-common` / `tbcommon` / `tscommon` / `dqcommon`). polars is its own
  layer, attached only to verbs that read file bytes (table-builder `infer-schema`, data-quality
  `inspect-source`). **SPEC-156 folded the deliberate twins onto `cpcommon`** — the CAS loop, the
  failure-message resolver, the results-location builder, the JWKS path, the SQS parser, the Athena
  DDL runner and the dedup-id builder each exist once now; a domain layer holds its *tables and
  wording*, not its own copy of the algorithm.
- **Replay-safe.** Verbs tolerate already-exists/already-absent; `CREATE … IF NOT EXISTS`;
  deterministic S3 keys; shared JSON mutates under **ETag compare-and-swap** (`cpcommon.cas`,
  SPEC-082; consolidated from three copies by SPEC-156 FR-001).
- **The 256 KB SFN state cap.** `States.DataLimitExceeded` escapes every `Catch` — the worst failure
  mode (no notification). Pass **S3 pointers between states, never inline lists** (learned
  independently in table-share PR #256 and data-quality). Never decode an error `Cause` in ASL
  (#252, uncatchable `States.Runtime`) — carry raw `$.error`, decode via
  `cpcommon.errors.failure_reason`.
- **Outcomes via the notifications inbox** (SPEC-058 trusted-producer contract; best-effort;
  `@notifies_on_failure` on every verb; friendly wording per SPEC-106). The UI never blocks —
  transient toast + pending state; terminal SFN states write nothing durable.
- **At-least-once delivery does NOT give you a re-run** (measured 2026-08-10, applies to all four
  planes). The Pipe starts executions `FIRE_AND_FORGET` and **cannot name them** — Pipes exposes no
  execution-name parameter at all — and the names it generates are **v5 UUIDs**, i.e. derived
  deterministically from something stable per message (the SQS `messageId` is v4/random, so it is
  not simply copied). What a repeated name does is **measured, not just documented** (2026-08-10,
  against the deployed table-share machine), and the middle case is the trap: same name + same input
  **while the original is still running** → the call succeeds and **returns the original execution
  ARN**, no second run; once the original has **closed** → **400 `ExecutionAlreadyExists`**; and the
  name is only reusable **90 days after it closes**. So a redelivered SQS message does not retry the work — it is either swallowed or it
  **fails the target invocation**, and a target that keeps failing exhausts the redrive policy and
  lands on the request DLQ, where SPEC-126's drain turns it into a **user-facing failure
  notification for a request that may have SUCCEEDED**. Do not design a plane's recovery story
  around SQS redelivery.
  > **How the name semantics were verified, and how to re-verify:** start an execution with a
  > deliberately malformed input (`[]`), which dies at `validate-authorize` **before an actor
  > exists** — so `NotifyFailure` runs with `actor=` and messages nobody. Call `StartExecution`
  > again with the same name and input while it runs (expect the same ARN back), then again once it
  > has closed (expect `ExecutionAlreadyExists`). Zero blast radius; the only cost is a FAILED
  > execution in history and **a name burned for 90 days**, so pick a fresh one.
  >
  > **Still unproven:** that Pipes derives the name *per message*. It is inferred from the v5
  > version nibble — the namespace is private, and no combination of the message id, pipe ARN or
  > state-machine ARN reproduces an observed name. **A redrive cannot settle it and is not worth
  > attempting:** an SQS DLQ redrive needs a message in the DLQ, and Step Functions'
  > `RedriveExecution` restarts states *within the same execution ARN* — it never calls
  > `StartExecution`, so it can never collide on a name. Only a genuine SQS **redelivery of the same
  > `messageId`** tests it, which means forcing the Pipe to miss its delete inside the queue's
  > 60-second visibility timeout — production drift on an IaC-managed queue, racing a sub-second
  > window. Declined as not worth it. Until then, treat redelivery as unreliable.
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
  API. **The CREATE path only.** The refresh apply issues **one `glue:UpdateTable`** as a
  read-modify-write on the live table (SPEC-149) — no statements, no window in which the table is
  absent, and no verb on this plane holds `glue:DeleteTable`. `decisions.md` → *The refresh apply
  replaces the definition in place*.
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
- **SFN (SPEC-160 shape):** validate-authorize → inspect-source (clone def, list objects, enforce
  caps) → **guard `Map`** (check-target-absent, per-item `Catch`) → build-transfer-manifest →
  **top-level Distributed `Map`** over a `(recipient × object)` JSONL manifest (batched
  copy-objects, `STANDARD` children, `ToleratedFailurePercentage: 100`, `ResultWriter` export) →
  collect-transfer-results → **finish `Map`** (create-table for the recipients that copied cleanly,
  the rest carried through). One recipient's failure never aborts siblings — the guard by its
  per-item `Catch`, the copy by attribution after the fact. Conflict (name exists, or a non-empty
  target prefix) fails **that recipient only**; no overwrite. FIFO `MessageGroupId` = source
  `database.table` (a heavy copy never overlaps itself).
- **Recipients:** a `user` must exist in the User Pool; a `space` is **any space by name** — the
  sender need not be a member (deliberate, recorded: the execution role does the write). The sender
  must have **source** access (own DB, or active member of the source space).
- **Copy:** a **top-level Step Functions Distributed Map** over a flat `(recipient × object)` JSONL
  manifest in the admin bucket, batched into parallel server-side `CopyObject` (multipart above
  5 GiB), key layout preserved. **Not** one Lambda per recipient, and **not S3 Batch Operations** —
  Batch Ops cannot rewrite a key (`TargetKeyPrefix` prepends to the *full* source key, so a job
  cannot produce `bob/shared_tables/sales/…` from `alice/tables/sales/…`) and caps objects at 5 GB
  where this path already handles more via `UploadPartCopy`. **Do not re-propose it** — the refusal
  is a property of the API. The copy code lives on `cpcommon.transfer` (SPEC-160).

- **Caps (current, SPEC-161).** Every one is a **whole-request terminal in `inspect-source`**,
  raised before either artifact is written, and every one is **computed by a test** from the
  constants rather than asserted as a number.

  | constant | value | what sizes it |
  |---|---|---|
  | `SHARE_MAX_OBJECTS` | 20,000 | `inspect-source`'s listing time (20 `ListObjectsV2` pages) |
  | `SHARE_MAX_TOTAL_BYTES` | 1 TiB | **one copy of the source** — says nothing about the transfer |
  | `SHARE_MAX_OBJECT_BYTES` | 10 GiB | a batch's **makespan** vs `copy-objects`' 900 s |
  | `SHARE_MAX_TRANSFER_ITEMS` | 20,000 | `recipients × objects` — the manifest write + the collector's read-back |
  | `SHARE_MAX_TRANSFER_BYTES` | 3 TiB | `recipients × bytes` — the state machine's `TimeoutSeconds` |
  | `SHARE_MAX_RECIPIENTS` | 50 | the inline Map's state + per-item error detail (unchanged since 090) |
  | `SHARE_MAX_DEFINITION_BYTES` | 64 KiB | **Athena's 262,144-byte query-string quota**, not the state payload |
  | `MAX_ITEMS_PER_BATCH` | 8 | `= COPY_CONCURRENCY`, so a batch is exactly one round of the pool |
  | `TimeoutSeconds` | 10,800 | `SHARE_MAX_TRANSFER_BYTES` at a makespan rate, minus both Maps and the serial verbs |

  **The two product caps exist because the per-source caps cannot express them:** every manifest
  item is a full copy, so both what the Map lists and what it moves scale with the recipient count.
  20,000 objects is fine and 50 recipients is fine and together they are a million lines; 1 TiB is
  fine and 50 recipients is fine and together they are 50 TiB. **Read `decisions.md` before changing
  any of these** — five review rounds found four bounds measured against the wrong quantity, and the
  tests are what hold the models now.

  The cloned definition **travels by pointer** (`definitionKey` → `table-share/{hash}/definition.json`),
  which is why its cap bounds Athena rather than the payload. The `TimeoutSeconds` **cannot itself
  reach `NotifyFailure`** — AWS catchers do not cover top-level execution failures — so it ships
  with an **EventBridge `TIMED_OUT` rule** invoking the same verb through a second door. Full
  entries: `decisions.md` → *Everything unbounded on the state travels by pointer* and *Every
  control-plane machine that can run for hours*.
- **Per-recipient attribution is a verb, not a Map item (SPEC-160).** The fan-out is over
  `(recipient × object)` pairs, so `collect-transfer-results` reads the Map Run's export and decides
  who gets a table: **one failed item ⇒ no table for that recipient**. It reads **both**
  `SUCCEEDED_n.json` (a batch reports per-item failures and still succeeds) and
  `FAILED_n`/`PENDING_n` (whole-batch failures, attributed from the child's input); a record whose
  payload Step Functions omitted is **unattributable and fails the whole request**, never "no
  failures found". It is also where a copy failure is notified from — the batch verb has no
  recipient to name.
- **The 256 KB cap, twice:** the copy plan rides as an S3 pointer
  (`<admin-bucket>/table-share/{hash}/copy-plan.json` — inline, the Map's `ItemSelector` put the
  state at 101% of the cap, PR #256); the recipient cap exists because each failed Map item carries
  raw `{Error, Cause}` and `cpcommon.errors.bounded_detail` truncation is the other half of the
  bound.
- **The admin-bucket key layout, and what the hash is NOT.** Three levels, only the first two ours:

  ```
  table-share/{digest}/copy-plan.json                              ← the SOURCE's file list
  table-share/{digest}/{executionName}/transfer-manifest.jsonl     ← one RUN's (recipient × object) items
  table-share/{digest}/{executionName}/results/{mapRunId}/…        ← Step Functions' ResultWriter export
  ```

  **The digest names the copy plan, not a share request.** It is a SHA-256 of
  `actor + source database + source table + result name` and **deliberately excludes recipients**:
  the plan is the source object list, identical whoever receives it, and content-addressing is what
  makes an `inspect-source` retry rewrite the same object instead of orphaning a second one
  (SPEC-090). So **two shares of the same table to different people share a root** and differ one
  level down, where the recipient-dependent manifest lives — which is exactly the split SPEC-160
  FR-001 needed, since a manifest's lines depend on which recipients the guard accepted *at that
  moment*. It reads as one share swallowing another and is not; verified 2026-08-10 against two real
  runs. The bucket is **not readable by eye** — go from the execution's state output (or the Map
  state's `ResultWriterDetails`) to the keys, never by browsing. Recorded improvement, **not built**:
  the nesting puts run-scoped artifacts under a plan-scoped name, and a `plans/{digest}/` +
  `runs/{execution}/` split would separate the two identities (neither the `table-share/*` IAM grant
  nor the `table-share/` lifecycle rule would change).
- **Notifications:** the sender hears every per-recipient outcome; on success the recipient is also
  told (a user directly; a space via its **owner only**, never the members). Failures notify the
  sender only.

### Send Files — SPEC-164 → 167 (complete)

"Send these files to Bob": copy a user's selected files and folders into another person's or
space's `shared_files/{sender}/` inbox. The browser cannot write into another user's prefix —
that is the isolation model working — so this needs a privileged path for the same reason table
share did.

- **Its own plane, not a mode of table share.** The two share an *algorithm*
  (`cpcommon.transfer`, SPEC-160) and nothing else: different request contract, different
  authorization question, different failure vocabulary. One queue and one DLQ under two unrelated
  features would let a malformed send dead-letter someone's table share.
- **The envelope is FLAT** — `{requestId, actor (raw ID token, top level), source: {space, items},
  recipients[]}` — and unknown top-level fields are **rejected, not ignored**. The flatness is a
  contract with SPEC-126's drain, not a style choice: `_notify_one` reads `body.get("actor")` and
  `_redacted` replaces top-level keys only, so a nested token would notify nobody on a
  dead-lettered send *and* write the raw JWT to CloudWatch. `MessageGroupId` is the SHA-256 of
  `{bucket}/{spaceRoot}` (a hash — SQS caps it at 128 chars, an S3 key reaches 1024);
  `MessageDeduplicationId` is the `requestId`, the only double-submit guard.
- **SFN:** `ValidateAuthorize → Validated → InspectSource → GuardRecipients → BuildTransferManifest
  → HasTransferItems → TransferObjects → CollectTransferResults → ShapeSummary → Succeeded`, with
  `ValidateFailureSeed`/`RequestFailureSeed → RecordFailure → NotifyFailure → Failed` complete from
  day one. **The failure seeds read the request back from `$$.Execution.Input`** — the validate
  task's input is the Pipe's JSON *array*, so its catch cannot carry a `ResultPath` and the error
  replaces the state; without the context read, `NotifyFailure` would take its no-recipient branch
  on every failure. Threading the request through the state was tried and rejected: the Pipe record
  carries the same selection again as an escaped string, so it roughly doubles the payload for the
  whole run. **TWO seeds, not one, and the second is not decoration:** `RecordFailure` reads
  `$.raw`, which exists on no post-validate state, so a catch routed straight to it — as every
  other plane's catches are — raises an uncatchable `States.Runtime` and the sender hears nothing.
  The fleet guard identifies a seed structurally by `error.$ == "$"` and **cannot see the second
  shape** (`"$.error"`, because that catch carries a `ResultPath`); the plane's own suite walks
  every catch instead.
- **Expansion happens once, in `inspect-source`, and travels by pointer** (SPEC-165). A `file` item
  HEADs; a `folder` walks `cpcommon.s3_listing` past its 1,000-key pagination boundary. The plan
  goes to `{admin}/file-send/{requestId}/copy-plan.json` — the object list is two orders of
  magnitude over the 256 KB payload limit, so inline was never tunable — and only
  `{copyPlanKey, objectCount, totalBytes}` return to the state. Each entry carries its owning item
  name, its key **relative to that item**, its absolute source key and its size: everything
  SPEC-166's manifest builder needs with no second listing.
- **The destination is `{targetRoot}shared_files/{sender}/{item}[/{relKey}]`**, built by ONE
  function in `fscommon.paths` with a sweep forbidding a second. Namespacing by sender mirrors
  `shared_tables/{table}/`, so two senders never collide and provenance is visible in the file
  browser with no metadata lookup — and the layout is independent of the sender's own folder
  depth. Three refusals protect it: an **overlapping** selection, and two items whose **names**
  would collide, are whole-request terminals; a **repeated** item collapses.
- **The exclusion rule is this plane's own, anchored at the SPACE ROOT** — `is_ignored`'s rules are
  anchored at the *listing prefix*, which here is whichever item the user picked, so reusing it
  would silently drop a user-made `reports/athenaresults/` and any `_drafts/` from a copy.
  `list_data_objects` took an optional `ignore` predicate rather than being forked. A genuinely
  empty **file** is sent; a folder **placeholder** (zero bytes, trailing slash) is not, so an empty
  subfolder does not survive a send.
- **Authorization is about the SOURCE only.** A `personal` source must equal the verified username
  (never a lookup — the username IS the prefix); a `shared` source needs `is_active_member`, i.e.
  the space's own status is `active`. A member whose join chip reads *pending* is authorized —
  SPEC-073 settled that access is granted at add time. Recipients are **not** an authorization
  question: any space by name, any existing user, unreachable ones annotated and carried.
- **Containment is two rules and a third about ancestors**, and it is the one place here where a
  bug is a cross-tenant read. (a) trailing-slash-normalised root, so `alice2/` never passes as
  inside `alice/`; (b) any `.`/`..` **path segment** refused outright, because
  `"alice/../bob/x".startswith("alice/")` is `True`; (c) `athenaresults/` refused as the folder,
  as anything under it, **and as any folder that contains it** — selecting the space root passes
  (a) and (b), and SPEC-165 expands a folder by listing its prefix. Folder keys are normalised to a
  trailing slash for the same reason. (c) is a **new rule for this plane** —
  `protectedFolders.ts` keeps three divergent lists and none refuses copying *out* of it.
- **Four caps, because there are four quantities.** `SEND_MAX_OBJECTS` (20,000) bounds what the
  selection EXPANDS to — sized by the plan held in memory, against `inspect-source`'s configured
  1024 MB, which a test reads back from `locals.tf`. Its timeout twin is sized per-ITEM, not
  per-page: a `file` costs its own serial HeadObject, so 200 files is 200 round trips where 20,000
  objects is 20. `SEND_MAX_TOTAL_BYTES` (1 TiB) bounds one selection's bytes at
  `cpcommon.transfer`'s **makespan** rate (500 MB/s, never the aggregate 4 GB/s). **SPEC-166 added
  three more, each against a different budget**: `SEND_MAX_OBJECT_BYTES` (10 GiB) against
  `COPY_TIMEOUT_SECONDS`, because one object is one worker and a batch is one round of the pool;
  `SEND_MAX_TRANSFER_ITEMS` (50,000) against the memory the two verbs either side of the Map hold
  the manifest in; `SEND_MAX_TRANSFER_BYTES` (3 TiB) against the machine's own ceiling. Both
  product caps are measured on the **requested** recipient count, before the guard.
- The other two are the request-shape caps. `SEND_MAX_ITEMS` (200) bounds the per-item work;
  `SEND_MAX_ITEM_BYTES` (96 KiB) bounds the serialised selection against the chain it travels —
  SQS body → the Pipe's record with that body **re-escaped** → `StartExecution`'s 256 KB limit. A
  count cap cannot bound bytes (a control character escapes to six), and a byte cap measured
  against the state alone permits a request whose execution cannot start. The producer mirrors
  both, held to the Python constants by a test.
- **The transfer is the shape SPEC-160 established, reused rather than re-derived** (SPEC-166): a
  fast inline **guard Map** (one delimited listing of `{targetRoot}shared_files/{sender}/` per
  recipient — a `MaxKeys=1` probe per item **cannot** answer the question, because `/` is not the
  lowest byte a key may carry), a `(recipient × object)` JSONL manifest beside the plan, a
  **top-level** Distributed Map with `STANDARD` children and `ToleratedFailurePercentage: 100`, and
  `collect-transfer-results` reading `SUCCEEDED_n` **as well as** `FAILED_n`/`PENDING_n` and
  reconciling the count against the manifest. A recipient is `ok` only if none of its items failed;
  an earlier terminal is never overwritten. **The guard's expected refusals are RETURN VALUES**, not
  exceptions, because a conflict must name the colliding item and a `TerminalError` cannot carry one
  to a user.
- **`TimeoutSeconds` (10,800) is top-level and ships WITH its rule** (SPEC-166): catchers do not
  cover top-level execution failures, so an EventBridge `TIMED_OUT` rule (never `FAILED`) invokes
  `notify-failure` through a second door — which on this plane needs `states:DescribeExecution` to
  read the input back, because EventBridge drops an input this plane's own cap allows to approach
  200 KB. A `NoDataObjectDelete` **Deny** ships from the first apply, and the only write into a
  user's space is `*/shared_files/*`.
- **One producer says everything (SPEC-167).** `NotifyOutcomes` runs on the terminal summary, not
  inside the Maps: sender per outcome, recipient on success only, a `space` through its registered
  **owner**, a failed recipient told nothing. Its link carries the RECIPIENT's own space root
  (`/files?prefix={recipientRoot}shared_files/{sender}/`, plus `?space=`), because the route keeps
  a `?prefix=` only when it starts with the resolved space's root — a root-relative one is
  discarded and lands them at their space root. Its `Catch` goes to **Succeeded**: the copy has
  already happened, and a missed message must never turn a delivered send into a failed execution.
- **The browser's only privilege remains `sqs:SendMessage`.** The **Send to…** control sits on the
  selection toolbar; `useFileSend` mints the `requestId` per SUBMIT, which is the FIFO dedup id and
  therefore what makes a retry possible rather than a queue-level guard.
- **No LF-admin designation** — no table is created here.
- **The execution role is on the user-space bucket policy's allowlist (FR-006)** — see that
  spec-delivery doc before building any future plane that touches Bucket 1.

### Archive — SPEC-168 → 172 (168, 169, 170 complete; 171-172 pending)

"Put this away": move a file or folder out of a user's space into a separate bucket at the
`GLACIER` storage class, delete the original, and leave behind a plain-text receipt. Reversible
only through a restore request that takes **hours**, not a click.

- **The storage class is the whole design.** `GLACIER` (Flexible Retrieval) is not readable, and a
  `CopyObject` whose source is in it fails `InvalidObjectState` — so a restore is `RestoreObject` +
  a 3-5 hour wait + a copy, and SPEC-171 grows a `Wait`/poll loop no other plane here has.
  `GLACIER_IR` was rejected (readable in real time, which deletes the restore machinery but makes
  "archive" mean "moved to a cheaper bucket") and `DEEP_ARCHIVE` too (12-48 h, 180-day minimum).
  The **90-day minimum duration is surfaced to the user** in SPEC-172's confirm dialog: archive on
  Monday and restore next week and you are still billed for 90 days.
- **The archive bucket is the first bucket the browser has no relationship with at all** — no CORS,
  absent from the CSP `connect-src`, and the portal role holds **zero** statements naming it. What
  the browser does get is a **Deny**: `PutObject`/`DeleteObject`/`AbortMultipartUpload` under
  `archive/` in **both** space buckets, so a receipt cannot be forged or deleted by the user it
  describes. `lambdas/test_archive_bucket_isolation.py` pins all of that, because it is a NEGATIVE
  claim and those rot silently.
- **Retention is a CEILING, not a floor.** A 7-year expiry lifecycle, deliberately **bucket-wide
  with no prefix filter** — the inverse of the admin bucket's `admin_lifecycle_rules_are_prefix_
  scoped` check, which exists only because that bucket mixes retained and expiring content. Object
  Lock is out of scope: it needs versioning (deferred 2026-08-03) and in compliance mode would make
  SPEC-171's archive cleanup impossible.
- **ONE plane serves both archive and restore**, branching on `mode` — SPEC-143's create/refresh
  branch is the precedent, not a sixth module. The `Choice` guards every comparison with
  **`IsPresent`**: a `Choice` on an absent path raises uncatchable `States.Runtime` and `Default`
  does not cover it.
- **The archived key encodes its own origin.** `personal/alice/archive/{uuid}/reports/q1.csv` came
  from `alice/reports/q1.csv`, so SPEC-170 rebuilds every restore destination from a
  `ListObjectsV2` over the archive prefix. **The receipt is a report, not a record** — same posture
  as SPEC-143 judging a table by shape rather than by the marker it also writes.
- **The leading `personal/` / `shared/` segment is not cosmetic.** Nothing anywhere checks a
  proposed shared-space name against the User Pool, so a user `alice` and a space `alice` can both
  exist. Flat, they would share one archive prefix — and since restore authorizes by *space* and
  then reads whatever sits there, a member of space `alice` could restore user `alice`'s files.
  Receipts need no such segment: they live in each space's own bucket.
- **Containment lives in `cpcommon.paths`, not in `arcommon`** (SPEC-156). Archive is the third
  plane to ask "is this key inside the root I authorized?", and it is the one place a second copy
  is a cross-tenant read. `fscommon.paths` re-exports the three names.
- **`ARCHIVE_BUCKET` is NOT a `cpcommon.config` required var.** That set is a fleet-wide contract
  every plane's Lambda environment must satisfy; a variable only this plane sets belongs in
  `arcommon.config.archive_bucket()` — a *function*, so the layer stays import-safe.
- **The delete grant is the one this role could not inherit** (SPEC-169). Every other plane's
  execution role carries a blanket `Deny s3:DeleteObject` from its first apply; this one cannot, so
  the property that replaces it is written out: `DeleteObject` on the two SPACE buckets only, plus
  an explicit **Deny** under `athenaresults/`, `user_settings/`, `archive/` and on any
  `DO_NOT_DELETE.txt` at any depth. IAM is the second line — the first is the commit gate, and
  `arcommon.delete.assert_deletable` refuses the whole list **before issuing anything**, so a key
  the policy would refuse fails the run rather than stopping a deletion half way through.
- **THE COMMIT GATE is the machine's shape** (SPEC-169). `collect-transfer-results` returns one
  boolean — every object copied, or not — and `CommitOrRollback` branches on it: one arm reaches
  `DeleteSource`, the other cannot, which a graph walk asserts rather than a comment. Its `Default`
  is the ROLLBACK, so an unrecognisable verdict fails closed. Three ways to be short are one
  verdict: a reported item failure, an export accounting for fewer items than the manifest, and a
  manifest disagreeing with the plan. **"Copied 900 of 1000, deleted 1000" is the failure this
  feature must never have.**
- **The rollback deletes by LISTING the archive prefix**, not from a collector-supplied key list:
  keys are the unbounded term, and the prefix is this request's alone — so the listing also catches
  objects a batch copied before it died and never reported, which a list could not. A rollback that
  itself fails partially does **not** change the outcome; the residue is billed at the GLACIER
  90-day minimum, is unreachable by the user and is swept by the 7-year expiry.
- **Most durable to least**: `_manifest.json` into the vault → the source deletion → the receipt
  into the user's own space. A receipt therefore only ever exists for an archive that completed,
  and its write failing **fails the run** even though the data is safe — a user with no receipt has
  no id and no route to a restore, so the message says the data IS archived and names the id.
- **`TimeoutSeconds` 10,800 is top-level and ships WITH its EventBridge `TIMED_OUT` rule**
  (SPEC-169), notify-failure's second door and its 15s → 60s raise. Catchers do not cover a
  top-level execution failure. Sized by a **makespan** (`MAP_MAX_CONCURRENCY` ×
  `CONSERVATIVE_STREAM_BYTES_PER_SECOND` = 500 MB/s), never an aggregate; a test adds the copy, the
  per-child overhead and the seven serial verbs and reads the ceiling out of `locals.tf`.
- **The restore guard is absolute** (SPEC-170): any occupied destination key refuses the whole
  restore — no skip, no overwrite, no merge, no "restore what fits" — and a `403` counts as
  occupied, because a key this role cannot head is a key it must not overwrite. It runs **before
  any `RestoreObject`**, which is why the arc splits here: everything on this side is verifiable
  in seconds and everything on the other takes hours and is billed the moment it starts. That
  asymmetry with archiving's rollback is deliberate — deleting restored data to make the
  operation atomic would destroy the thing the restore was for.
- **A restore takes its SPACE from the request and its ARCHIVE from a pasted id** (SPEC-170), so
  authorization is a question about *that* space and an archive belonging to another one simply is
  not found — `archive_not_found` never distinguishes "never existed" from "not yours". The id is
  matched against `arcommon.paths`' one UUID rule **before** it is concatenated into a key, and the
  root is then built by the same `archive_root` that wrote it. `requestId` ≠ `archiveId` is
  enforced: the run and the archive are different things, or a refused restore could not be
  re-submitted.
- **The front door serves both modes and returns the SAME five keys** (SPEC-170). `ChooseMode` sits
  downstream of validate-authorize and reads `$.mode` off the parsed request — in the raw Pipe
  record that field is inside an escaped JSON string ASL cannot look into — so a separate restore
  validator is not possible, and one shared `Validated` Pass means a key present in one mode and
  absent in the other would raise an uncatchable `States.Runtime`. `source` is therefore the
  authorized SPACE in both: the archive's source in one, the restore's destination in the other.
- **One body table, two prefixes, and the failure path carries `mode`** (SPEC-170). The codes only
  one mode can reach are unambiguous; the ones BOTH reach — `forbidden`, `malformed_event`,
  `invalid_request` — are exactly the ones a single "Couldn't archive that" prefix gets wrong. Every
  failure seed supplies `mode` (a literal `null` on the pre-identity one, whose input is the raw
  error).
- **`RESTORE_HEAD_CONCURRENCY` is bounded by botocore's CONNECTION POOL, not by the thread count**
  (SPEC-170). "Workers × timeout / latency" says to widen the pool until the arithmetic fits, but
  `boto3.client("s3")` takes the default `max_pool_connections` of 10 — threads past that contend
  and urllib3 discards sockets rather than reusing them, so a wider pool buys throughput the client
  cannot deliver while every bound computed from it reads as satisfied. 8 workers; the guard's
  600 s **timeout** is what pays for 20,000 heads. A test reads the ceiling off botocore.

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
then check/build over Parquet) · table-share partition-metadata copy ·
table-builder multi-file schema union · data-quality report retention/TTL + cost guardrails.

**No longer deferred:** the table-share *scale* path. S3 Batch Operations was the recorded escape
hatch and is **rejected** (it cannot rewrite a key); the Step Functions Distributed Map that replaces
it **shipped with SPEC-160**. Don't re-file Batch Ops here. What remains open is the *ceiling* —
SPEC-161 raises the caps 160 deliberately left in place.
