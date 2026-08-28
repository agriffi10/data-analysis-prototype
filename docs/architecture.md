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
- **The Browser Application** — how the SPA is built: the three layers, the state split, the service
  boundary, and the two network paths. Read before writing front-end code.
- **Authentication Flow** — read when touching login, the token→credential exchange, or refresh.
  - **The API's auth boundary** — one token, one verification path, two transports; read before
    touching the API's identity handling or a provider parameter.
- **Authorization Model** — read when touching IAM or isolation: user space, shared-space slots,
  and the per-user catalog.
- **Control Planes** — the shared pattern every privileged pipeline follows. Read it before any plane
  work; the individual planes have their own pages under `lambdas/info/planes/`.
- **Known Constraints** — read before building on S3, Lake Formation or deploy semantics: non-atomic
  move, no versioning, pagination, LF hybrid mode, parallel-deploy conflict, the depends_on rule.
- **Infrastructure & Deployment** — read when touching IaC layout, CI/CD, CORS, or LF-admin ordering.
  - **Runtime configuration** — the `/config.json` document and its no-fallback rule.
  - **The OIDC provider block** — the API's token verifier and its five fields.
  - **Deploy-role IAM — adding a new resource type** — read before any spec adding new infra
    (self-grant propagation, scopability, refresh deadlocks).
  - **The container platform** — the VPC, the endpoints, and what a successful pull does not prove.
  - **Lambda code/infra split** — read before adding or rewiring a Lambda or layer.
- **Deferred / Future Scope** — what is recorded as deliberately not built.

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
deliberate, scoped exceptions to "no backend" (§ Control Planes). **Seven** planes exist: **Shared
Spaces**, **Table Builder**, **Table Share**, **Data Quality**, **Send Files**, **Archive** and
**File Operations**; all share one pattern, the
`cpcommon` layer, a DLQ-drain sweep (SPEC-126), and structured logging (SPEC-127→137). An
admin-only bucket (SPEC-032) holds Athena results, the shared-space registry, and the `logs/` store.

## The Browser Application

Most of the code in this repo is the SPA, and it is the part with the least AWS in it. `apps/portal/`
is a React 18 + Vite + TypeScript (strict) app; `infra/` is the OpenTofu that stands everything else
up; `lambdas/` is the privileged server-side work. `packages/` is reserved and empty.

**One tree, three layers, and the dependency runs one way.** `src/lib/` holds the clients and the
primitives; `src/components/` holds shared UI; `src/features/<name>/` holds a feature's own
components, hooks, services and types. **`components/` may not import from `features/`** — a lint
rule enforces it — and a leaf feature that becomes a shared layer is *extracted before its second
consumer*, not after. `src/routes/` holds the page-level components the router mounts, and it is the
only place a default export is allowed.

**A feature is a fixed shape:** an `index.ts` barrel, `Component.tsx` with its test beside it,
`useFeature.ts`, `feature.types.ts` and `feature.service.ts`. The catalogue of what already exists is
[`apps/portal/info/component-inventory/INDEX.md`](../apps/portal/info/component-inventory/INDEX.md),
which is a reuse router rather than a description — read the row for the area you are touching.

**Two kinds of state, kept apart.** Server state is TanStack Query; UI state is Context plus
`useReducer`. There is no Redux, and the separation is the reason there is no cache of a cache. Query
keys are centralised in `lib/queryKeys.ts`.

**Every AWS call goes through a service file, and services never throw.** They return
`ServiceResult<T>` — `{success: true, data}` or `{success: false, error: {message, code?}}` — so a
caller branches instead of catching. Clients are instantiated in `src/lib/` and never in a component.

**Raw AWS, Cognito and Athena text is never shown to a user.** `lib/errorMessages.ts` is the single
source of wording, and rendering `error.message` is a defect rather than a shortcut.

**Mobile-first, one tree.** Only two breakpoints are compiled — `tablet:` at 900 and `desktop:` at
1300 — and the same tree reflows. A `*Mobile`/`*Desktop` component twin is a smell, not a pattern.

### The two network paths

The browser talks to AWS **directly** for almost everything: S3 through `@aws-sdk/client-s3` with
presigned URLs and `lib-storage` uploads, Athena and Glue for the analytics workspace, and
`sqs:SendMessage` to enqueue a control-plane request. Those calls carry the scoped role credentials
described under *Authentication Flow*, and IAM is what makes them safe.

The second path is newer and still small: `api.dataquarry.app`, reached through `lib/apiClient.ts`,
which attaches a bearer token and returns the same `ServiceResult` shape. Its wire types are
**generated** from a Python declaration rather than hand-written, so a contract change fails the
build at every call site. Moving work onto it is the ongoing arc; CloudFront remains production and
the rollback until it is finished.

The rule that keeps the two from drifting: **no new browser-side AWS SDK call on a path an API route
already serves**, and no second API.

## Authentication Flow

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

### The API's auth boundary, beside the control planes'

**One token, one verification path, two transports.** The seven control-plane verbs have taken the
identity from a *verified* Cognito ID token since SPEC-011, carried in an SQS message body. The API
verifies the same token through the same code — `cpcommon.auth` — carried in an `Authorization`
bearer header instead. Nothing re-derives a username, and nothing anywhere reads a username the
caller stated.

The verifier is driven by a `VerifierConfig` (issuer, audience, JWKS URI, username claim, required
claims) rather than by Cognito-shaped constants, so the target environment swaps the provider by
changing five environment values. The API resolves a principal **before** dispatch and refuses any
route that has not declared itself public, including one that does not exist; every refusal is
byte-identical, and a provider that cannot be *read* answers 5xx rather than 401 — an outage is not
a bad token, and "sign in again" cannot fix one.

Sign-in itself is unchanged: Hosted UI, Amplify and the Identity Pool flow above all behave exactly
as described. The API is a **verifier, not an OIDC client** — see `decisions.md`.

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

### Analytics — per-user catalog isolation
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

## Control Planes

SEVEN features perform privileged, cross-user, multi-step AWS work that browser-scoped credentials
must not: shared-space lifecycle, table creation, table sharing, data-quality checks, sending files
to another person or space, archiving a file or folder into Glacier (with its restore), and copying,
moving or deleting files and folders. Each is a deliberate, recorded reversal of "no backend" for its
mutations only — the rest of the app stays browser-direct.

> **The seventh is complete server-side and reaches no user yet.** File operations run end to end
> and notify, but the browser's enqueue service is still called by nothing: every gesture in the file
> browser takes the old synchronous path until SPEC-190 lands.

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
- **One lock protocol.** A plane that must serialize its own executions binds `cpcommon.lock`
  (SPEC-187, extracted from `tbcommon.table_lock` at its second consumer): the three-way conditional
  acquire, the 412/409 mapping, the staleness steal and release-by-overwrite. Each domain keeps its
  key layout, its thresholds — derived from *its* machine's ceiling — and its own wording.
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

### The planes themselves

Each plane's own page carries its state graph, its rules, its fences and its layer — read the one you
are changing rather than this file. They live in [`lambdas/info/planes/`](../lambdas/info/planes/),
and every verb is listed in [`lambdas/info/INDEX.md`](../lambdas/info/INDEX.md).

| Plane | What it does | Page |
|---|---|---|
| Shared spaces | space lifecycle, the registry, per-user caches, the roster | [`shared-spaces.md`](../lambdas/info/planes/shared-spaces.md) |
| Table builder | create a table from a folder, inference, partition projection, refresh | [`table-builder.md`](../lambdas/info/planes/table-builder.md) |
| Table share | snapshot push, clone-not-re-infer, the recipient Map | [`table-share.md`](../lambdas/info/planes/table-share.md) |
| Data quality | Athena-computed checks, report and index discovery, cost | [`data-quality.md`](../lambdas/info/planes/data-quality.md) |
| File send | a selection into another person's or space's inbox | [`file-send.md`](../lambdas/info/planes/file-send.md) |
| Archive | the GLACIER vault and its restore — the one unrecoverable surface | [`archive.md`](../lambdas/info/planes/archive.md) |
| File operations | one machine for copy, move and delete; the per-space lock; the plan | [`file-ops.md`](../lambdas/info/planes/file-ops.md) |

The API is not a control plane and has its own page,
[`api.md`](../lambdas/info/planes/api.md); so do the standalone functions,
[`standalone.md`](../lambdas/info/planes/standalone.md).

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
and the shell is `no-cache`, with exactly one `--delete` — SPEC-141, `decisions.md` — and renders and
publishes `/config.json` (below) alongside them.

> **Superseded in part by SPEC-194 (2026-08-27).** The passes, the single `--delete` and the
> stale-root-object orphan class are properties of the S3 delivery path, and they describe **one of
> two** delivery paths now. The container is the file set: nothing to reconcile, no key surviving a
> build, no pass ordering, and no orphan class — it reproduces the per-class cache scheme in nginx
> and nothing else. Both claims retire outright when the distribution does; until then this
> paragraph is true of `deploy-app.yml` and false of the image.

`VITE_*` vars are GitHub Actions variables (see
`.github/workflows/README.md`) and are now the **dev fallback only**; resource→spec mapping and
current values come from `tofu -chdir=infra output`. Security scanning: `security.yml` runs the
report-only scanner suite (SPEC-138); `deploy-infra.yml`'s plan job Checkov-scans the **rendered**
`tofu show -json` plan for IAM (SPEC-139) — details in `docs/decisions.md` + `docs/security-baseline.md`.

### Runtime configuration — `/config.json`

The SPA reads its configuration at **runtime**, from a same-origin `/config.json` fetched once before
the first render. A `VITE_*` variable is inlined into the bundle at build time, so an artifact
carries one environment's bucket names, queue URLs and Cognito ids everywhere it is promoted; the
document is what makes `dev → prod` a repoint rather than a rebuild, and a rollback a repoint back.

- **The contract.** A JSON object with a numeric `version` (currently `1`) and **string** values for
  every classified key. A wrong version is refused **whole**. An empty string reads as unset. A key
  the build does not classify is **ignored**, so a task definition ahead of an image cannot break it.
- **Same-origin, and it boots without the API.** The SPA must render its own error states while the
  API is down, so the document is served by the SPA's own server and is never proxied.
- **`Cache-Control: no-store`, and the distribution enforces it independently.** A document answered
  from a cache populated in the previous environment renders a working, fully-functional portal
  pointed at the wrong account, and nothing on screen distinguishes it. The upload sets the header
  and `/config.json` has its own `Managed-CachingDisabled` cache behaviour — with the response-headers
  policy re-attached, because it is per-behaviour and not inherited.
- **A production boot with bad configuration fails hard.** Unreachable, unparseable, unsupported
  version or missing a required key each render `BootFailure` and mount no route. One `console.error`
  carries the reason and the missing key **names** — never a value.
- **A dev build falls back to `import.meta.env`**, and a production build must not. The fallback's key
  tables are eliminated from the production bundle, asserted on the built output by
  `npm run check:bundle`.
- **A key is wired in six places:** the classification in `types/runtimeConfig.types.ts` (+ its
  `VITE_` name in `lib/env.ts`), `.env.example`, the GitHub repository variable, **both** the build
  env and the render step in `deploy-app.yml`, the ECS task definition, and the container
  entrypoint's own `KEYS`/`REQUIRED` lists in
  `apps/portal/docker/docker-entrypoint.d/40-render-portal-config.sh` — which is the leg that
  actually renders the served document. A test compares them.

### The OIDC provider block — the API's token verifier

Server-side configuration for the API Lambda, and **not part of the browser's document at all**. It
is what the API needs to decide a bearer token is genuine, and it is **provider-agnostic** so a later
provider swap is a change of values rather than a rewrite of the verifier.

| Variable | What it is |
|---|---|
| `OIDC_ISSUER` | the `iss` a token must carry, compared exactly |
| `OIDC_AUDIENCE` | the `aud` / `client_id` a token must carry |
| `OIDC_JWKS_URI` | where signing keys are fetched from — **a field, not a path derived from the issuer**: the well-known location is a convention, not a guarantee, and hard-coding it makes the verifier provider-specific in the one place that would fail closed and silently |
| `OIDC_USERNAME_CLAIM` | which verified claim becomes `actor` |

**This is a verifier, not an OAuth client.** No code exchange, no PKCE verifier, no client secret, no
redirect URI, no scope list — those belong to Amplify, in the browser, unchanged by this arc.
Building a client here is the shape of error the small field set exists to prevent.

**The exclusion cuts one way only.** The browser's four Cognito values are Amplify's, they are
legitimately browser-side, and a test written to forbid "anything that smells of identity" would
delete them and break sign-in — `cognitoUserPoolClientId` survives an exact-match rule and dies under
a substring one. `cognitoDomain` is **not** a provider-block field: Amplify POSTs the code exchange
to it. The forbidden set is about *the API's trust anchors*, not about the word Cognito.

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

  > **Superseded for the two PLATFORM policies (2026-08-26).** Re-run is no longer the accepted
  > remedy there: `time_sleep.wait_for_platform_grant` sits **after** their attachments and carries
  > `triggers` keyed to both policy bodies, so it re-fires whenever a grant changes. Measured, and
  > the reason it stopped being acceptable: a grant written at `14:56:08.95` was refused at
  > `14:56:10.67` and `main` went red. Two lessons generalise beyond those policies — **placement**
  > (a sleep guarding the inline policy sits at the top of the graph and cannot cover a managed
  > policy written far below it) and **the failing shape** (this was an existing policy *modified*,
  > not the "Nth resource added" the rule above describes, which is the commoner case). The rule as
  > written still holds for the control-plane policies, whose sleeps remain create-only.
- **A service may call an action ON YOUR BEHALF that appears in no action list for it (2026-08-26).**
  ELBv2 calls `ec2:GetSecurityGroupsForVpc` inside `CreateLoadBalancer`, so a sweep of every
  `elasticloadbalancing:` action the provider makes finds nothing, and the apply fails on an EC2
  permission while creating a load balancer. It is scopable (`vpc`), like most of them.
- **The provider's call is the authority, not the action's name (2026-08-26).** `aws_ecs_cluster`
  calls `ecs:UpdateCluster` on any `setting` change and calls `UpdateClusterSettings` never — the
  grant named the second, and the first apply that edited the cluster would have failed on main.
  Read the resource's source at the pinned version when a grant looks obviously right.
- **A condition on a key the caller does not populate fails CLOSED (2026-08-26).** ELB validates the
  access-log bucket policy with a `PutObject` of its own; `aws:SourceAccount` and then
  `aws:SourceArn` were each refused alone, and the message named neither. An "extra" condition is not
  a tightening — it is a bet that the caller supplies the key.
- **Some actions are not resource-scopable** — they only authorize on `Resource: "*"`; a narrower ARN
  is an implicit deny. Known offenders: `logs:DescribeLogGroups`, `cognito-idp:DescribeUserPoolDomain`,
  `cognito-idp:CreateUserPool`. Put each in its own `"*"` statement. Verify scopability cheaply with
  `aws iam simulate-custom-policy --action-names <a> --resource-arns <arn>` (`allowed` vs `implicitDeny`)
  before spending a CI round.
- **CloudWatch log-group actions need both ARN forms.** `logs:ListTagsForResource` authorizes against
  the **bare** ARN (`…:log-group:NAME`) while others use the `…:log-group:NAME:*` form — scope the
  statement to a list of both.
- **An action that CREATES a numbered resource authorizes against the un-numbered one.**
  `ecs:RegisterTaskDefinition` creates revision 1, so at the moment of the call there is no revision
  for an ARN to carry. A grant scoped to `task-definition/NAME:*` matched every revision and not the
  register itself. Generalise it: whenever the action's own effect is to mint the identifier the ARN
  would contain, the pattern has to cover the form **without** it. Writing one pattern that covers
  both is usually enough — IAM's `*` spans `:`, so `task-definition/NAME*` matches `NAME` and
  `NAME:1` alike, and a separate `…:*` line beside it is dead.
  **Two documentation traps here, both live:** the ECS developer guide still states *"Task definition
  IAM policies do not support resource-level permissions"* with a `Resource: "*"` example, and the
  roadmap issue asking for them is still open — both contradicted by the Service Reference, which is
  what IAM evaluates against. Trust the Service Reference. And note what a policy simulate can
  answer: whether a **pattern matches a string**, never **which resource the service passes** — so it
  can prove a grant sufficient and cannot tell you which form is required.
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

### The container platform

The network, the API's front door and the SPA's runtime. It serves the **real SPA** — built and
deployed on every push to `main`, with CloudFront still production and still the rollback until the
cutover retires it. What the image IS, and the five CloudFront jobs its nginx configuration
reproduces (three of them as named divergences), live in `decisions.md`.

**`infra/modules/network/`** — a VPC across two AZs, two public and two private /20s. The private
subnets carry **no default route of any kind**: a task reaches ECR through `ecr.api`, `ecr.dkr` and
`logs` interface endpoints (all `private_dns_enabled`), and reaches the image layers through an S3
**gateway** endpoint, whose prefix-list route is what makes it reachable with no default route at
all. Flow logs are on because the residual failure is a **connect timeout**, and a timeout leaves
nothing behind. The no-NAT assertion is **repo-wide**, not module-scoped — scoped, it would be
satisfied by adding the gateway somewhere else, which is exactly what a quick fix for a mysterious
timeout looks like.

**`infra/modules/api/`** — an HTTP API, one `$default` route, one integration, a regional custom
domain at `api.`, CORS admitting both origins, access logging, and a placeholder function that is
**not in the VPC**. Authorization is a **verifier the router calls** — never an authorizer, which would be a second reader of the same token — and the verifier deliberately has no router dependency, so the gate can later move without the verification moving with it.

**`infra/modules/spa/`** — ECR (immutable tags, scan on push, AES256, bounded lifecycle), an ECS
cluster, two task roles (**the task role holds nothing** — the container makes no AWS call), the task
definition, a Fargate service on **platform 1.4.0** in the private subnets, an ALB in the public ones
with a TLS 1.3 listener and a redirect-only :80, the rules on both security groups, the admin
bucket's first policy (ALB access logs), and the `portal.` alias record.

**Reading the platform's failures.** Three of them look like each other and are not:

| Symptom | Usually means |
|---|---|
| `CannotPullContainerError` naming a tag | the service points at a revision whose image was never pushed — **not** the endpoints |
| `CannotPullContainerError` with no tag issue | an endpoint, its security group, private DNS, or the platform version |
| `ResourceInitializationError` | the log group or the execution role, before the pull is even attempted |

Pair any pull result with `describe-route-tables`: a pull that succeeded through a route somebody
added reads as proof of the endpoints.

**Writable paths under `readonlyRootFilesystem`.** A Fargate **task volume** arrives empty and
root-owned and does **not** initialise from the image — measured, with `/var/cache/nginx` (shipped
owned by uid 101) arriving as root's. So `volumes` + `mountPoints`, a read-only root filesystem and a
non-root user are **any two of the three**. The mechanism is `linuxParameters.tmpfs`, whose
`mountOptions` take `uid`, `gid` and `mode`; the uid is one value feeding both the container's `user`
and every mount option.

**Ownership between Terraform and CI.** `task_definition` is in the service's `ignore_changes` and
`desired_count` is not. CI therefore **must point the service** at the revision it wants — Terraform
registers revisions and never moves the service — while the count stays Terraform's, because raising
it is a verification step an ignored attribute would silently swallow.

### Lambda code/infra split

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
