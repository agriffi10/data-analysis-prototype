# Architecture — how the S3 File Portal works

**What this doc is:** the shape of the running system — the pieces, what each one does, and how a
request travels between them. It is the orientation doc, short enough to read whole.

**What this doc is not:** it holds no coding rules, no operational trap lists and no history. Those
live beside the code they govern, and the last section here — the **Architecture Decision Record** —
indexes the decisions that put the system in this shape, each pointing at its full entry in the
register.

| Looking for | Read instead |
|---|---|
| Why a decision was taken, and what was rejected | [`decisions/`](decisions/INDEX.md) — the register, one file per area |
| What already exists in the SPA, to reuse it | [`apps/portal/info/component-inventory/INDEX.md`](../apps/portal/info/component-inventory/INDEX.md) |
| How a control plane's machine actually runs | [`lambdas/info/planes/`](../lambdas/info/planes/) |
| A Terraform module, its resources and its traps | [`infra/info/INDEX.md`](../infra/info/INDEX.md) |
| Coding rules — React, accessibility, Lambda shape, Python | [`docs/best-practices/INDEX.md`](best-practices/INDEX.md) |
| How work gets done here | [`process.md`](process.md) |

---

## The system at a glance

```
  Cognito Hosted UI ──▶ ┌──────────────────────────────────────────────┐
  (Managed Login v2)    │  the browser — React 19 SPA, Vite, strict    │
                        │  TypeScript, TanStack Query; configuration   │
                        │  read at runtime from /config.json           │
                        └───┬─────────────┬──────────────┬─────────────┘
                            │             │              │
                   presigned bytes   bearer token
                 (signed server-side)      │              │
                            │              ▼              ▼
                            │       API Gateway    FIFO request queue
                            │        HTTP API             │
                            │             │               ▼
                            │      Lambda router    EventBridge Pipe
                            │      (verifies, then        │
                            │       assumes the           ▼
                            │       same role)       Step Functions
                            │             │               │
                            │             │               ▼
                            │             │         verb Lambdas ──▶ notifications
                            ▼             ▼               │              inbox
                     ┌──────────────────────────────────────────┐
                     │   S3 · Glue · Athena · Lake Formation    │
                     └──────────────────────────────────────────┘
```

Two things decide almost everything else.

**One shared IAM role, and isolation by principal tag.** Every authenticated caller — the browser
directly, and the API on the browser's behalf — ends up as the same portal role, tagged with the
caller's `username`. The Cognito Identity Pool stamps that tag **server-side from the verified
claim**, so it cannot be spoofed, and every policy scopes itself with
`${aws:PrincipalTag/username}`. There are no per-user roles and no app-level access control.

**One string is four things.** A username is also the S3 prefix, the principal tag and the Glue
database name, which is why it is constrained at signup to `^[a-z][a-z0-9_]{2,62}$` and is
catalog-safe by construction.

The SPA reaches AWS by three routes at once, and which one a feature uses is a deliberate choice per
feature: **directly** with scoped credentials (most reads), **through the API** (the routes ported so
far), or **by enqueuing onto a control plane** (anything privileged, cross-user or multi-step).

---

## The browser application

`apps/portal/` is a React 19 + Vite + TypeScript (strict) SPA, and it is most of the code in this
repo. `infra/` is the OpenTofu that stands everything else up, `lambdas/` is the privileged
server-side work, and `packages/` is reserved and empty.

**One tree, and the dependency runs one way.** `src/lib/` holds the clients and primitives,
`src/components/` shared UI, `src/hooks/` shared hooks, and `src/features/<name>/` a feature's own
components, hooks, services and types. The first three are the shared layers and **none of them may
import from `features/`** — lint enforces it, with two named exemptions (`Header`, `ProtectedLayout`)
that are app chrome and compose features by definition. `src/routes/` holds the page-level components
the router mounts; named exports are the rule everywhere else.

**A feature has a fixed shape:** an `index.ts` barrel, `Component.tsx` with its test beside it,
`useFeature.ts`, `feature.types.ts`, `feature.service.ts`.

**Two kinds of state, kept apart.** Server state is TanStack Query; UI state is Context plus
`useReducer`. No Redux — which is why there is no cache of a cache. Query keys are centralised in
`lib/queryKeys.ts`.

**Every AWS call goes through a service file, and services never throw.** They return
`ServiceResult<T>` — `{success: true, data}` or `{success: false, error: {message, code?}}` — so a
caller branches instead of catching. Clients are built in `src/lib/`, never in a component.

**Raw AWS, Cognito and Athena text is never shown to a user.** `lib/errorMessages.ts` is the single
source of wording; rendering `error.message` is a defect, not a shortcut.

**Mobile-first, one tree.** Two breakpoints are compiled — `tablet:` at 900, `desktop:` at 1300 — and
the same tree reflows. A `*Mobile`/`*Desktop` twin is a smell.

Routing is `react-router` v8, imported from `react-router` (v8 removed `react-router-dom`).

## How the SPA reaches a user

**Two delivery paths run at once, and that is the state of the arc rather than the target.**

| Path | What it is | Status |
|---|---|---|
| CloudFront + S3 | the built `dist/` uploaded in three prefix-scoped passes behind an OAC origin, with a response-headers policy carrying the enforcing CSP | **production, and the rollback** |
| ECS Fargate | the same SPA inside an nginx container behind an internet-facing ALB, built and deployed on every push to `main` | built and live, not yet the cutover |

The container reproduces every job CloudFront does, with three deliberate divergences —
`Server: nginx`, no brotli, and HSTS without `preload`. The two front doors are admitted
**additively** to CORS and the CSP; narrowing to one happens at the cutover, because an allowlist
naming a single origin makes the other a rollback nobody can exercise.

**Configuration is a runtime document.** The SPA fetches a same-origin `/config.json` once before the
first render, rather than reading `VITE_*` values inlined at build time — so promoting a build is a
repoint, not a rebuild, and a rollback is a repoint back. It is served `no-store`, refused whole on a
version mismatch, and a production boot with bad configuration renders `BootFailure` and mounts no
route. Detail: [`apps/portal/info/runtime-configuration.md`](../apps/portal/info/runtime-configuration.md).

## The API layer

`api.dataquarry.app` is an **API Gateway HTTP API** with **one `$default` route** and one `AWS_PROXY`
integration onto a single Lambda, reached through a regional custom domain. The route table lives in
the function's code; a per-route integration would put it in two places.

The browser reaches it through `lib/apiClient.ts`, which takes a **route id from the generated
contract** rather than a URL, attaches a bearer token, and returns the same `ServiceResult` shape as
every other service. **The wire is declared in Python and the TypeScript is generated from it**, so a
contract change fails the build at every call site rather than at runtime.

Today it serves `/healthz`, the username directory, the feature-flag document and the whole **object
surface** — listing, head, exists, content read and write, copy, move, delete, free-name, and the two
presign routes. File **bytes** do not travel through it: an upload is a presigned `PUT` and a download
a presigned `GET`, both signed server-side by the caller's own assumed session, so the transfer is
between the browser and S3 and compute never touches it. It also serves the **catalog surface** —
Athena start, status, results and stop, and Glue get-database and list-tables — and the **ten enqueue
routes** over the eight control-plane queues, so **no `@aws-sdk/*` package is left in the browser at
all**. The browser still reaches AWS without one: a presigned
`PUT`/`GET` goes straight to S3, and Amplify talks to Cognito throughout. The rule that keeps the two from drifting is **no new
browser-side AWS SDK call on a path an API route already serves**, and **no second API**.

A document that belongs to no user — `_directory/usernames.json`, `_config/feature-flags.json` — gets
a route of its own rather than riding the object surface, because the space resolver refuses a prefix
no caller's claims authorize, and correctly so.

The function is deliberately **not in the VPC**, and authorization is a verifier **the router calls**
— not an API Gateway authorizer, which would be a second reader of the same token. Detail:
[`lambdas/info/planes/api.md`](../lambdas/info/planes/api.md) and
[`infra/modules/api/README.md`](../infra/modules/api/README.md).

## Identity

Sign-in is **Cognito**: a standalone User Pool with the Hosted UI (Managed Login v2), federated into
an Identity Pool that vends the AWS credentials.

```
Amplify checks the session
  → no session redirects to the Hosted UI
  → Cognito issues JWTs
  → Amplify exchanges them with the Identity Pool (enhanced flow: GetId → GetCredentialsForIdentity)
  → the Identity Pool stamps { username: <cognito:username> } as a principal tag
  → the portal role's trust policy admits this pool (AssumeRoleWithWebIdentity + TagSession)
  → 1-hour temporary credentials, cached and refreshed by Amplify
```

The app reads them with `fetchAuthSession()` and hands them to the SQS client; on a
credential-expiry error it retries once with a forced refresh. **There is no browser-side S3, Athena
or Glue client any more** — those surfaces are the API's, and the expired-credential retry that used
to wrap every one of their calls is a server-side re-assume. Tokens are held **per tab**, not for the whole browser.

The tag mapping is `aws_cognito_identity_pool_provider_principal_tag` in
`infra/modules/auth/identity-pool.tf`, and the tag **value** must be the `cognito:username` claim —
the bare `username` claim does not exist in a User Pool ID token, so it would never stamp.

### The API's auth boundary

**One token, one verification path, two transports.** The control-plane verbs have taken identity
from a *verified* Cognito ID token carried in an SQS message body since the beginning; the API
verifies the same token through the same code — `cpcommon.auth` — carried in an `Authorization`
bearer header instead. Nothing re-derives a username, and nothing anywhere reads a username the
caller stated.

- **It is a verifier, not an OIDC client.** No code exchange, no PKCE, no client secret, no redirect
  URI — those belong to Amplify, in the browser. Provider-agnosticism is five server-side config
  fields ([`infra/modules/api/README.md`](../infra/modules/api/README.md)), so swapping the identity
  provider is a change of values.
- **It assumes the same role with the same tags from the same claims** as the Identity Pool, which is
  why no policy had to be rewritten and why the hand-maintained bucket-policy allowlist stays
  correct. The role is reused, never minted.
- **Refusals are byte-identical and expiry is not disclosed**; a provider that cannot be *read*
  answers 5xx rather than 401, because an outage is not a bad token and "sign in again" cannot fix
  one.

## Authorization

Two browser-facing data buckets, both enforced purely at the IAM layer.

**User space.** Each user has exactly one prefix named after their username. The portal role's
permission policy scopes object CRUD to `…/${aws:PrincipalTag/username}/*` and `ListBucket` to that
prefix, with a `Deny` on the `DO_NOT_DELETE.txt` prefix marker. A session without the tag matches
nothing, so the default is an implicit deny. One statement scopes every user.

Every file operation maps onto the object actions plus the multipart pair
(`AbortMultipartUpload`, `ListMultipartUploadParts`) — kept although the browser no longer
multiparts, because the same role signs every presigned URL and a later multipart route would need
them back. `ListBucketMultipartUploads` is deliberately **not** granted: it cannot be scoped per
prefix, so it would leak other users' in-progress uploads.

**Shared space — bounded membership slots.** Access is gated by membership principal tags on the same
role. The hard AWS constraint is that the Identity Pool maps each claim to exactly **one
single-valued** tag, and IAM cannot iterate a list inside a `Resource` ARN. So what is bounded is **how
many spaces one user can belong to**: ten Cognito custom attributes `custom:shared_space_1..10`, each
holding one space name and each mapped to a principal tag, with one templated statement-pair per slot.
**A space's own member count is not bounded at all** — the limit is per person, not per space.
**An unset slot is simply not stamped**, so its statement matches nothing — there is no "empty tag
grants everything" risk.

**Where the tag VALUES come from is now a configured choice.** `MEMBERSHIP_SOURCE` selects the
claims above or a per-user index the shared-space plane maintains in the admin bucket, resolved once
at cold start. The default is the claims, wired into no Terraform, so nothing about the running
system changes — the index exists so the tags survive an environment where those claims do not
(row 44).

**Propagation is not instant.** A membership change updates Cognito attributes; the tag stamps at the
*next* credential vend. The UI's Refresh-connections control forces one. Real-time revocation would
need a different credential path entirely. Under the index source the window is shorter: the index is
read per request, so a removal lands on the next one with the same token.

**Analytics isolation works the same way.** The `username` tag scopes the portal role's Glue ARN to
`database/${aws:PrincipalTag/username}` — **not** LF-Tags. Lake Formation grants the shared role
broadly and IAM is the per-user gate. Table creation by a control plane is **TBAC**: a
`portal-managed` LF-Tag plus one tag-policy grant per execution role, because LF **admin** status does
not grant `CREATE_TABLE` on a database the admin did not create.

## Storage

Five buckets. The constraint the project holds to is **one bucket of personal prefixes**, not one
bucket overall.

| Bucket | Holds |
|---|---|
| user-space | every user's own prefix, plus two shared documents every signed-in user may read: the username directory under `_directory/` and the feature flags under `_config/` |
| shared-space | user-created shared spaces. The **lifecycle** — create, membership, delete — goes through a control plane; a member's browser writes objects inside a space it belongs to directly |
| admin | the shared-space registry, the planes' scratch, `logs/` (retained forever), and Athena's **fallback** output — a user's own results land in their user-space prefix |
| static assets | the built SPA, reachable only through the CloudFront OAC |
| archive | the GLACIER vault, which the browser has no relationship with at all |

Plus a Lambda artifacts bucket and a CloudTrail bucket, neither of which the app touches.

**The product presents filesystem UX over a store that has neither move nor rename.** Every move is
`CopyObject` + `DeleteObject`; folder operations are recursive and **non-atomic**; a per-key failure
must never delete that source and never abort the rest. Collisions are handled in the UI by
warn-and-confirm, because **versioning is off** — which is exactly what makes a failure between those
two steps unrecoverable. That deferral is pre-production and is recorded to be revisited before real
user data lands.

## The control planes

Seven features do privileged, cross-user, multi-step AWS work that browser-scoped credentials must
not: shared-space lifecycle, table creation, table sharing, data-quality checks, sending files,
archiving into Glacier with its restore, and copying/moving/deleting files. Each is a deliberate,
recorded exception to browser-direct access, **for its mutations only**.

```
browser ──▶ API ──sqs:SendMessage──▶ FIFO request queue ──▶ Pipe ──▶ Step Function ──▶ verb Lambdas
                                     │                                                          │
                                     └──▶ DLQ ──▶ scheduled drain              notifications queue
```

- **The browser has no privilege on any plane.** It calls an API route; the API's execution role is
  the only principal that may write a request queue (SPEC-200).
  The request body carries the caller's ID token.

  > **Superseded in part by SPEC-208 (row 46).** A request queue's writers are *enumerated*, and
  > the shared-space queue now has two: the API, and a scheduled reader that turns an operator's
  > CSV of ownership transfers into requests. It carries no identity block and is admitted by the
  > `SenderId` SQS stamps on its message. The browser still has no privilege on any plane — that
  > half is unchanged. Full entry:
  > [`decisions/control-planes.md`](decisions/control-planes.md#a-control-plane-queue-may-have-a-second-producer-admitted-by-senderid-spec-208).
- **One shared execution role per plane, and its own DLQ** — a plane sharing another's DLQ lets one
  malformed request dead-letter someone else's work.
- **Single-task verb Lambdas**, never an `action`-switch monolith; retry and catch live in the state
  machine.
- **`cpcommon` owns the algorithm; a per-plane domain layer owns its wording.** The CAS loop, the
  failure-message resolver, the lock protocol, the JWKS path and the bulk-copy engine each exist
  once.
- **Outcomes arrive through the notifications inbox.** The UI never blocks: a transient toast and a
  pending state, with nothing durable written by a terminal machine state.

| Plane | What it does | Page |
|---|---|---|
| Shared spaces | space lifecycle, the registry, per-user caches, the roster | [`shared-spaces.md`](../lambdas/info/planes/shared-spaces.md) |
| Table builder | create a table from a folder, inference, partition projection, refresh | [`table-builder.md`](../lambdas/info/planes/table-builder.md) |
| Table share | snapshot push, clone-not-re-infer, the recipient Map | [`table-share.md`](../lambdas/info/planes/table-share.md) |
| Data quality | Athena-computed checks, report and index discovery, cost | [`data-quality.md`](../lambdas/info/planes/data-quality.md) |
| File send | a selection into another person's or space's inbox | [`file-send.md`](../lambdas/info/planes/file-send.md) |
| Archive | the GLACIER vault and its restore — the one unrecoverable surface | [`archive.md`](../lambdas/info/planes/archive.md) |
| File operations | one machine for copy, move and delete; the per-space lock; the plan | [`file-ops.md`](../lambdas/info/planes/file-ops.md) |

The Terraform side of the shared machine is
[`infra/info/control-plane-shape.md`](../infra/info/control-plane-shape.md); the Lambda side, with
every verb, is [`lambdas/info/INDEX.md`](../lambdas/info/INDEX.md). The API is **not** a control
plane and has its own page, [`api.md`](../lambdas/info/planes/api.md); so do the standalone
functions — the DLQ drain, the log sweep, the Cognito triggers and the directory builder —
[`standalone.md`](../lambdas/info/planes/standalone.md).

## Analytics

An in-app Athena, Glue and Lake Formation workspace. A user's Glue database is their username; a
shared space maps to exactly one database, so the space picker has no database step. **The query
workspace has no active database** — every base table is written fully qualified, and the browsing
rail is read-only.

Both data buckets are registered in Lake Formation **hybrid** access mode, which is what lets the file
browser keep direct-IAM S3 access while Athena reads through LF. Flipping to enforced without first
opting in every principal would break the file browser.

The six calls the workspace and the Data Explorer ride on — Athena start, status, results and stop,
and Glue get-database and list-tables — go **through the API**, which derives the workgroup, the
results location and the caller's identity server-side. Lake Formation is unaffected by that move
because its grants attach to a **principal**, and the principal is the same portal role, now assumed
by the API instead of vended to the browser. Two properties are load-bearing and easy to lose in a
port: **the API makes exactly one AWS call per request and never waits**, so every poll and page walk
stays in the browser; and **a failed query is a 200**, carrying Athena's `stateChangeReason` verbatim
for the browser to choose wording from.

## Notifications and observability

**Notifications** are a single-writer FIFO queue feeding one writer Lambda — deliberately simpler than
a control plane, with no Pipe and no state machine. The browser only reads its own feed;
every plane's outcome reaches the user this way, and a request that dead-letters is swept by a
scheduled drain into the same inbox.

**Structured logging** goes through `cpcommon.observability` only, into a FIFO logs queue swept on a
schedule into one NDJSON object per service per day under `logs/`, retained forever.

## Infrastructure and delivery

IaC is **OpenTofu** under `infra/`, organised as bounded-context modules with S3 remote state. IAM
policies are `.tftpl` templates rendered by `templatefile()` — never inline `jsonencode`. Every module
carries a `README.md` beside its `.tf`, and [`infra/info/INDEX.md`](../infra/info/INDEX.md) is the
router.

**GitHub Actions owns delivery**, through a role assumed by OIDC:

| Workflow | Runs on | Does |
|---|---|---|
| `ci.yml` | pull requests | lint, format check, `tsc -b`, unit tests, ruff, mypy, pytest, contract regeneration, doc-layout validation |
| `spa-image.yml` | pull requests | builds the container and asserts its behaviour against every criterion the image is built to meet |
| `deploy-infra.yml` | pull requests (`plan`) and push to `main` (`apply`) | `tofu plan` with a Checkov scan of the rendered plan, then `tofu apply`, with a `skip_refresh` break-glass |
| `deploy-app.yml` | push to `main` | builds the SPA, uploads it to the CloudFront origin, and renders `/config.json` alongside |
| `deploy-spa-image.yml` | push to `main` | builds the image, pushes it to ECR tagged by commit sha, and points the ECS service |
| `deploy-lambdas.yml` | push to `main` | packages each function and every layer, and updates the function code |
| `deploy-config.yml` | push to `main` | publishes the feature-flag document to the user-space bucket |
| `security.yml` | pull requests and a weekly schedule | the scanner suite — Semgrep, pip-audit, gitleaks and Checkov **block**; npm audit and the ZAP baseline report |

**Lambda code and infrastructure are deployed separately** — `tofu apply` never touches code, and CI
owns every layer attachment. That split, and the traps that come with it, are
[`lambdas/info/deployment.md`](../lambdas/info/deployment.md).

**The deploy role self-grants**, which makes adding a new AWS resource type its own small discipline:
the grant lands in **its own PR, applied before the resources that need it**. The trap list is
[`infra/info/deploy-role-iam.md`](../infra/info/deploy-role-iam.md), and it is in-scope work for any
spec that provisions new infra.

**The container platform has no NAT gateway anywhere.** Private subnets carry no default route at all;
a task reaches ECR, CloudWatch Logs and S3 through interface and gateway endpoints. The residual
failure mode is a connect timeout, which is why flow logs are on.

## Constraints that shape the system

The durable ones — each is a property of a service rather than of our code, and each has already cost
something.

- **S3 has no move or rename**, so every one is `CopyObject` + `DeleteObject`, folder operations are
  recursive and can partially fail, and there is no transactional rollback.
- **Versioning is off**, so a failure between those two steps is unrecoverable. Deferred
  pre-production; revisit before real user data lands.
- **`ListObjectsV2` returns at most 1,000 keys per call.** The browser paginates with
  `useInfiniteQuery` and a "Load more" control — never assume one page is a whole folder.
- **An upload is ONE presigned `PUT`**, which caps at 5 GiB — exactly the ceiling the managed
  multipart upload it replaced already had, so the limit moved nowhere. What did move: there is no
  part-level retry, so a dropped connection restarts the file.
- **Lake Formation is in hybrid mode**, and leaving hybrid mode breaks direct-IAM S3 access.
- **Usernames are constrained at signup** because the same string is a prefix, a tag and a database
  name. The pool is case-insensitive.
- **SPA client-side routing needs the origin to serve `index.html` for 403/404**, or a refresh on a
  deep link returns a raw error.
- **`shared-connections.json` is a cache, not the record.** The per-user file only mirrors the S3
  registry; a missing file means empty, not broken.
- **A membership or flag change lands at the next credential vend**, not immediately.

## Deliberately not built

File preview in the browser · an admin UI · audit logging (CloudTrail beyond the archive trail) · a
staging environment and promotion pipeline · real-time access revocation · Excel support and a
file-converter pipeline (arc cancelled — convert externally, then build over Parquet) · table-share
partition-metadata copy · table-builder multi-file schema union · data-quality report retention and
cost guardrails.

**No longer deferred:** the table-share *scale* path. S3 Batch Operations was the recorded escape
hatch and is **rejected** — it cannot rewrite a key — and the Step Functions Distributed Map that
replaces it has shipped. Don't re-file Batch Ops here.

---

## Architecture Decision Record

The decisions that put the system in the shape described above. **Context** is why this one rather
than the obvious alternative; **Notes** is what to carry forward — the fence, the thing that bites, or
the thing that will need revisiting. Each **Decision** links to where the full reasoning and the
rejected alternatives live — an entry in [`decisions/`](decisions/INDEX.md) for most, a tree page for
the few the register never got an entry for — and that source is the authority when it and this table
disagree.

**Rows are append-only and never renumbered.** A new row takes the next number in the table as a
whole and is appended to the sub-table for its area — so the numbering runs in the order decisions
were taken, not in reading order, and an area's block will not stay contiguous. That is intended: a
row number is a stable name people cite, and keeping the blocks tidy is not worth breaking it. A
superseded decision keeps its row and gains a note saying which row replaced it.

### Identity and access

| # | Decision | Context | Notes |
|---|---|---|---|
| 1 | [Cognito User Pool plus Identity Pool, no custom auth](decisions/identity-and-access.md#auth) | A greenfield app with no existing identity estate; the managed pair vends AWS credentials directly, so the browser needs no token-exchange code of ours. | The Hosted UI is [Managed Login v2](decisions/identity-and-access.md#hosted-ui--managed-login-v2) — the classic UI broke the post-signup redirect. Tokens are held per tab, not per browser. |
| 2 | [One shared IAM role, isolation by principal tag](decisions/identity-and-access.md#auth) | Per-user roles need a provisioning step per user and hit account limits; the Identity Pool can stamp a verified claim as a session tag, which scopes one policy to every user. | The tag is stamped server-side, so it cannot be spoofed. A session without the tag matches nothing — the default is an implicit deny. |
| 3 | [The username is also the prefix, the tag and the database name](decisions/identity-and-access.md#usernames) | One identifier means one thing to keep consistent; three would need a mapping table nobody could see. | Constrained at signup to `^[a-z][a-z0-9_]{2,62}$` so it is catalog-safe. The client-environment transition re-keys exactly this. |
| 4 | [A user may belong to ten shared spaces](decisions/identity-and-access.md#bucket-2-shared-space) | The Identity Pool maps a claim to exactly one single-valued tag and IAM cannot iterate a list inside an ARN, so a per-user list of memberships is not expressible — ten fixed slots are. | **The bound is per user, not per space** — a space's member count is unlimited. Raising it enlarges the portal-role policy by a statement-pair. Unbounded membership would need a token-vending Lambda, which replaces the whole credential path — recorded, not built. |
| 5 | [The username directory is built from S3, not Cognito](decisions/identity-and-access.md#the-username-directory-is-built-from-s3-not-cognito-spec-146) | Today Cognito is the complete list and S3 is not; the directory is still built from S3 because that is what the client transition inverts. | Readable by every authenticated user, accepted deliberately: usernames only, never emails. |
| 6 | [A feature flag is presentation, never authorization](decisions/identity-and-access.md#a-feature-flag-is-presentation-never-authorization--and-it-lives-beside-the-username-directory-spec-162) | A flag decides what is offered; IAM decides what is permitted, and conflating them puts an access decision in the browser. | The flag document lives in the **user-space** bucket beside the directory — the admin bucket's grant would not have worked. |
| 7 | [The API is a verifier, not an OIDC client](decisions/identity-and-access.md#the-api-is-a-verifier-not-an-oidc-client-spec-195) | Sign-in already works in the browser; the API only needs to decide a bearer is genuine. Building a client here duplicates the flow in the one place a mistake fails closed and silently. | Five config fields, no cookie so no CSRF surface, CORS still required. A key-retrieval fault is 5xx, never 401. |
| 8 | [The API assumes the same role with the same tags from the same claims](decisions/identity-and-access.md#the-api-reads-the-same-claims-and-assumes-the-same-role-with-the-same-tag-set-spec-196) | One computation over one input means no policy is rewritten and the bucket-policy allowlist stays correct as routes port over. | Role chaining caps `DurationSeconds` at 3600 both ways: shorter caps every presigned link, longer is refused. |
| 9 | [Two credential planes, declared on the route](decisions/identity-and-access.md#two-credential-planes-declared-per-route-defaulting-to-the-user-plane-spec-196) | A route either acts as the user or as the service. A central registry mapping route to plane was the alternative and is what this replaced: it puts the declaration somewhere other than the thing it describes, and its set-equality guard passes while a route is wrong. A required field on the route cannot be forgotten. | **This failure fails open** — a wrong client succeeds against the wrong identity. Hence one construction site, an AST sweep, and a raise on any third value. |
| 10 | [The credential cache is keyed on the whole tag set](decisions/identity-and-access.md#the-credential-cache-is-keyed-on-the-whole-tag-set-spec-196) | Keying on the username freezes membership until the next cold start; keying on nothing serves one user another's session. | Its margin is the life of one request. It retries on a **new** client, because boto3 binds credentials at construction. |
| 11 | [Authorization lives in the router, not an API Gateway authorizer](decisions/identity-and-access.md#authorization-lives-in-the-router-not-in-an-api-gateway-authorizer-spec-193) | An authorizer would verify the same token independently and could disagree with the router about the claim the role scoping depends on, with no arbiter. | One `$default` route means an authorizer would have to duplicate the route table before it could say anything. The verifier is a module with no router dependency, so the gate can move later without the verification moving with it. |

### The browser and the API contract

| # | Decision | Context | Notes |
|---|---|---|---|
| 12 | [TanStack Query for server state, Context and `useReducer` for UI state](decisions/browser.md#state) | Server state has caching, staleness and retries; UI state has none of them. A single store for both means hand-writing the first set, which is what Redux would have been here. | Query keys live in `lib/queryKeys.ts` — a key built at a call site is invisible to every invalidation written against it. |
| 13 | [Services return `ServiceResult<T>` and never throw](../apps/portal/info/component-inventory/foundations.md) | A caller branching on a result handles the failure path visibly; a caller catching an exception mostly does not — and an un-caught one reaches a user as raw AWS text. | The register never got an entry for this; the shape and its adapters are in the inventory. The wording half — never render `error.message` — is [`decisions/browser.md`](decisions/browser.md) → *User-facing error messaging*. |
| 14 | [The shared layers may not import from `features/`](decisions/browser.md#components-may-not-import-from-features-spec-155) | Without the rule the dependency graph inverts quietly, and a shared component starts depending on a feature it is used by. | Lint-enforced with two named exemptions. Extract a leaf feature **before** its second consumer, not after. |
| 15 | [Mobile-first, two compiled breakpoints, one tree](decisions/browser.md#responsive-spec-095) | Tailwind compiles every breakpoint you declare whether or not you use it, and each one is a state every surface can be wrong in. Two is what the layouts actually need. | Only `tablet:` (≥900) and `desktop:` (≥1300) exist — an unprefixed class is mobile. Reaching for a third means the tree is doing something a reflow cannot, which is worth stopping on. |
| 16 | [The wire is declared in Python and the TypeScript is generated](decisions/identity-and-access.md#the-contract-is-declared-in-python-and-the-typescript-is-generated-spec-197) | Two hand-written halves of one contract drift, and the drift surfaces at runtime in the browser. Python is the declaring half because the server is what actually enforces the shape — generating the other way would make the browser's belief authoritative over the thing validating it. | CI refuses a regeneration diff in both directions. The type vocabulary is closed and **never falls back** — a fallback type agrees with everything. |
| 17 | [`apiRequest` retries nothing, except one forced refresh on 401](decisions/identity-and-access.md#apirequest-retries-nothing-and-idempotency-is-declared-per-route-spec-197) | A blanket retry replays non-idempotent writes; idempotency is a property of the route, never of the HTTP method. | That single 401 retry is the browser's only refresh path — deleting it signs everyone out at the hour mark with a green suite. |

### Storage and data

| # | Decision | Context | Notes |
|---|---|---|---|
| 18 | [Filesystem UX over a store with no move or rename](decisions/storage.md#file-ops--filesystem-ux) | The alternative is showing users the store as it is — flat keys, no folders, no rename — which is honest and unusable for the file-handling this product exists to do. The gap is bridged in the app, and the cost is that every move is two operations that can half-succeed. | Folder operations are recursive and non-atomic. A per-key failure must never delete its source nor abort the rest. |
| 19 | [S3 versioning stays off](security-baseline.md#iac--checkov-305-failures--25-rules) | Pre-production with no real user data, so the exposure is theoretical today; enabling it has a storage-cost and lifecycle story nobody has written. | This is what makes a failure between copy and delete unrecoverable. **Turning it on is not free elsewhere** — the archive's Object Lock decision and several plane fences read on versioning being off. **Revisit before real user data lands.** |
| 20 | [A multi-file operation belongs on a plane; one file stays synchronous](decisions/storage.md#a-file-operation-on-more-than-one-file-belongs-on-a-plane-and-the-boundary-is-the-selection-spec-187) | A single file completes inside a request; a folder tree does not, and holding the browser open for it is the thing that fails. | The boundary is the **selection**, not the byte count. The lock is per space, and its loser waits. |
| 21 | [Per-user catalog isolation by principal tag, not LF-Tags](decisions/analytics.md#analytics-spec-032036) | Glue database isolation is the same problem as S3 prefix isolation, and one mechanism is one thing to reason about. | Lake Formation grants the shared role broadly; IAM is the gate. Both buckets stay in LF **hybrid** mode or the file browser loses direct S3 access. |
| 22 | [Control-plane table creation is TBAC](decisions/analytics.md#control-plane-table-creation--tbac-spec-070111-correction) | LF **admin** status does not grant `CREATE_TABLE` on a database the admin did not create — which is not what the console's admin screen suggests. | A `portal-managed` LF-Tag plus one tag-policy grant per execution role, and a static per-bucket data-location grant. |
| 23 | [Every DDL literal goes through an escaper, and there are two axes of them](decisions/analytics.md#every-ddl-literal-goes-through-literal-spec-151) | Hive/DDL and Trino/DML escape differently, and so do values and identifiers; a shared space's name is format-checked nowhere server-side. | **The wrong escaper fails silently, as a predicate that never matches.** A quoting fix is not done until every statement built from the same value is swept. |
| 39 | [Bytes go to S3 presigned; small text goes through the API](decisions/storage.md#bytes-go-to-s3-presigned-small-text-goes-through-the-api-spec-198) | Routing file bytes through the API would put a 6 MB response ceiling and a 29-second integration ceiling in front of every upload and download, and would pay compute for a transfer S3 can do itself. Routing *documents* through S3 instead would need a second credential path in the browser for objects a few kilobytes long. | The document route's **byte cap is what holds the split** — without it it is a second upload path that works perfectly to 6 MB. The upload is `XMLHttpRequest`, not `fetch`, or the progress bar silently dies. **No part-level retry** any more. |
| 40 | [A presigned URL is a bearer token](decisions/identity-and-access.md#a-presigned-url-is-a-bearer-token-spec-198) | Handing the browser a capability instead of a credential keeps every credential server-side, and S3 evaluates the signer's own scope at redemption — which is what makes the design survive the target environment's move to Access Grants. | Signed by the **caller's** assumed session, never the execution role. Clamped to the credential that signed, read in the **same** call. In no emitted record. |

### The control planes

| # | Decision | Context | Notes |
|---|---|---|---|
| 24 | [Privileged work runs on a control plane, not in the browser](decisions/identity-and-access.md#no-backend) | Cross-user, multi-step work needs permissions no browser session should hold, and durable retry across a closed tab. A synchronous API route would need the same permissions and still lose the work when the request ends. | The browser held one grant, `sqs:SendMessage`, which kept the privileged surface off user credentials; SPEC-200 moved even that behind the API, so the browser now holds none (ADR row 42). The register has no entry of its own for this: the decision lives as the **superseded marker** on the `No backend` entry it reversed, which is what the link lands on. The pattern and its fences are [`decisions/control-planes.md`](decisions/control-planes.md). |
| 25 | [One execution role and one DLQ per plane](../infra/info/control-plane-shape.md) | Per-verb roles were built and deliberately consolidated: the union policy is readable, and seven roles per plane were not. | A plane sharing another's DLQ lets one malformed request dead-letter someone else's work. |
| 26 | [`cpcommon` owns the algorithm; a domain layer owns the wording](decisions/control-planes.md#the-deliberate-twins-are-discharged-one-implementation-per-cross-plane-helper-spec-156) | The same CAS loop, lock protocol and failure resolver existed three times and had already diverged. | **Do not merge the domain layers wholesale.** Where a layer is packaged by an explicit file list, a test asserts set equality with the directory. |
| 27 | [Everything unbounded travels by pointer, never on the state](decisions/control-planes.md#everything-unbounded-on-the-state-travels-by-pointer--including-the-definition-spec-161-extending-spec-090160) | The 256 KB Step Functions state cap raises `States.DataLimitExceeded`, which escapes every `Catch` — so the failure mode is silence. | A cap on the list is not a substitute for a pointer. Every cap that does exist is computed by a test against the budget that sized it. |
| 28 | [Outcomes arrive through the notifications inbox, on a single-writer queue](decisions/control-planes.md#notifications-spec-058061) | The work is asynchronous and may outlive the tab, so the completion channel has to be durable and readable later. | The UI never blocks. Delivery is at-least-once and **a redelivered message is not a re-run** — do not design recovery around it. |
| 29 | [A restore is guarded absolutely, and the guard runs twice](decisions/archive-and-restore.md#the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee-into-a-promise) | Archive is the one surface where a mistake is unrecoverable, and the billed retrieval hours are exactly when a user re-creates the file. | Any occupied destination refuses the **whole** restore, and a 403 counts as occupied. The source is deleted only when every object is confirmed copied. |

### Infrastructure and delivery

| # | Decision | Context | Notes |
|---|---|---|---|
| 30 | [OpenTofu, bounded-context modules, IAM as `.tftpl` templates](decisions/infrastructure.md#iac) | OpenTofu over CDK, Pulumi and SST — the infrastructure is the product's security boundary, so a declarative document a reviewer reads beats a program they have to execute in their head. `.tftpl` for the same reason: inline `jsonencode` hides a policy inside HCL. | An IAM policy document must be printable ASCII, so rationale never goes in a `.tftpl` — an em dash is rejected at `CreatePolicy`, invisible to plan and validate. |
| 31 | [Lambda code and infrastructure deploy separately](../lambdas/info/deployment.md) | Terraform applying code means every code change waits on an infra apply, and layer attachment belongs with the build that produced the layer. | `tofu apply` never touches code. `ignore_changes` must name `layers`, or an apply strips a layer back off and the next cold start fails. |
| 32 | [Configuration is a runtime document with no production fallback](decisions/infrastructure.md#configuration-is-a-runtime-document-and-a-production-build-has-no-fallback-spec-192) | A `VITE_*` value inlined at build time makes an artifact environment-specific, so promotion becomes a rebuild and rollback becomes a rebuild back. | `no-store`, refused whole on version. A key is wired in six places, asserted across all of them, and the container refuses to start on a missing one. |
| 33 | [The SPA ships as a container on Fargate, with CloudFront still production](decisions/infrastructure.md#the-nginx-configuration-reproduces-cloudfronts-jobs-and-three-are-divergences-spec-194) | The target environment needs a runtime it controls; running both paths keeps a rollback that is exercised rather than theoretical. | Three deliberate divergences: `Server: nginx`, no brotli, no HSTS `preload`. Origins are admitted **additively** and narrowed only at the cutover. |
| 34 | [No NAT gateway; private subnets reach AWS through endpoints alone](decisions/infrastructure.md#there-is-no-nat-gateway-and-the-endpoints-are-the-whole-outbound-story-spec-193) | "No route to the internet" is a property a reviewer reads off a route table; "a NAT gateway nobody uses" is a claim re-argued every year. | The residual failure is a **connect timeout**, which leaves nothing behind — hence flow logs. Read any successful pull beside `describe-route-tables`. |
| 35 | [The image tag is the commit sha and `:latest` does not exist](decisions/infrastructure.md#the-image-tag-is-the-commit-sha-and-latest-does-not-exist-spec-193) | An immutable tag makes a running task traceable to a commit, and makes a rollback a repoint. | `task_definition` is ignored and `desired_count` is not, so **CI must point the service** — a pipeline that only registers a revision produces a pull error indistinguishable from an endpoint failure. |
| 36 | [The deploy role self-grants, and grants land in their own PR first](../infra/info/deploy-role-iam.md) | The role that creates everything has to be able to create the thing that grants it — so the grant and its first use cannot be in the same apply. | Scopability is **measured** with `simulate-custom-policy`, never assumed. A simulate matches patterns, not the ARN a service actually passes. |
| 37 | [A gate blocks on a narrowed count, never a total](decisions/gates-and-tests.md#a-scanner-gate-blocks-on-a-narrowed-count-never-a-total-2026-08-09-completes-spec-138) | Enforcing what passes is a ratchet; suppressing what fails is a list that grows. A line matching no finding is a hard error. | **"Did not run" is never "clean."** A broken scanner fails the job even in report mode. |
| 38 | [Coverage floors and compiler strictness are declared, never inherited](decisions/gates-and-tests.md#compiler-and-coverage-defaults-are-declared-never-inherited-spec-150) | An inherited default changes under you when a tool upgrades, and the change is invisible in the diff. | Ratchets at the measured level. Never lower one for a regression — the doc-layout budgets follow the same rule. |
| 41 | [The API makes exactly one AWS call per request, and every loop stays in the browser](decisions/identity-and-access.md#the-api-makes-exactly-one-aws-call-per-request-and-every-loop-stays-in-the-browser-spec-199) | "The API waits for the query" is the shape a reader reaches for. A five-minute query is 10× a **non-raisable** 30-second integration ceiling, so the rejected design does not fail at the margin — it fails always, and it holds a Lambda open for the duration of a user's query while doing so. | The count is on the **route's own service client**, never on botocore — the session cache fires `AssumeRole` on some invocations and not others. SPEC-198's free-name route is the arc's one exception. A route may now carry **path parameters**, and a value that is not one segment is refused in the browser. |
| 42 | [The browser's queue grants come off with the switchover, not with the trust flip](decisions/identity-and-access.md#the-browsers-queue-grants-come-off-with-the-switchover-not-with-the-trust-flip-spec-200) | The eight FIFO request queues were the browser's last privileged write and its only remaining AWS grant. Moving the send behind the API is what lets a plane trust an actor the API stamps from a verified bearer rather than a token it verifies itself — and the grant had to come off in the SAME change, because the Identity Pool survives to SPEC-202 and a trusted `actor` field plus a browser credential able to write the queue is impersonation. | The API's execution role is the only principal that may write a request queue; the browser holds no AWS grant at all. The message carries a nested `identity` block ALONGSIDE the token it does not yet replace — SPEC-201 flips the planes onto it and only then stops the token being sent. Supersedes row 24's "the browser's only grant is `sqs:SendMessage`". |
| 43 | [The planes trust a body field because of who may WRITE it, not because of cryptography](decisions/identity-and-access.md#the-planes-trust-a-body-field-because-of-who-may-write-it-not-because-of-cryptography-spec-201) | Eight planes each verified a Cognito ID token out of the queue message. Once the API became the only principal that may write those queues, that was a second answer to a settled question — and the last reason a raw JWT travelled through eight queues, sat in eight execution inputs, and reached CloudWatch on every dead-letter. | The planes read `identity.actor` through one reader that **cannot verify**; `cpcommon.auth` keeps one caller, the API. Dropping a verification is not dropping an authorization — every authorizer has zero diff. Two deploys, the second irreversible. Completes row 42.
| 44 | [The membership index is an authorization input, where the username directory is not](decisions/identity-and-access.md#the-membership-index-is-an-authorization-input-where-the-username-directory-is-not-spec-203) | The session's shared-space tags come from Cognito custom-attribute claims, which do not exist in the successor account under either identity variant. The registry could answer "which spaces is this user in" but not cheaply — one object per space, keyed by space name, so a listing plus a read per space on every credential mint. A new per-user projection in the admin bucket answers it in one `GetObject`. | The source is a **cold-start choice** (`MEMBERSHIP_SOURCE`), default `claims`, wired into no Terraform — nothing here changes what runs today. The index is **user-unreachable, plane-written, CAS-written**, which is what lets it be an authorization input where SPEC-146's directory may not be. The user's own connections cache has the same shape, is one `GetObject` away, and is **user-writable** — reading it is a complete bypass. |
| 45 | [A shared-space delete removes people, not things](decisions/control-planes.md#a-delete-removes-people-not-things--and-retention-keys-on-a-durable-fact-never-live-status-spec-205) | Deleting a workspace destroyed every object under its prefix, its Glue database and its registry record, on a bucket with **no versioning** — so a mistaken delete had no recourse at all. It now ends every member's access and destroys nothing, which makes the mistake recoverable by an administrator and removes SPEC-151's whole failure class from the route (nothing frees a name, so a partial teardown cannot). | Retention keys on the durable `everActive`, **never live `status`** — which moves `active → deleting → failed` over intact data. `deleting` is **not** evidence a space was usable: delete is gated on ownership alone, so a never-active create reaches it too. **One predicate**, `is_destroyable`, routes the delete AND refuses the add; complements written twice drift silently in both directions. Two permanent, user-visible costs: a name is never reusable, and deleted data is retained. The residual is the credential window — a removed member's query workspace still reaches the retained database until their token expires. |
| 46 | [A control-plane queue may have a second producer, admitted by SenderId](decisions/control-planes.md#a-control-plane-queue-may-have-a-second-producer-admitted-by-senderid-spec-208) | A shared space's owner was whoever created it, forever — so an owner who had left could only be worked around by abandoning the space or deleting it, and both are worse than the problem. Transfer fixes the ordinary case; the case the UI cannot serve is an owner who is already gone, which needs a door no signed-in session goes through. | The reader enqueues onto the **existing** queue, so operator and user transfers are one verb, one authorization and one notification pair. That reuse is what forces the fence: with no bearer to present, an operator message declares `origin` and is admitted only by the **`SenderId` role-id half** — the mechanism SPEC-206 established, inverted from a denylist to an allowlist. Two things make it real rather than nominal: the reader holds its **own execution role** (sharing the orchestrator's would admit every verb on the plane, invisibly), and `origin` is **undeclarable through the API**, so a signed-in caller cannot claim it at all. Narrows rows 42 and 43's "the API is the only principal that may write a request queue" to "the writers are enumerated"; the browser still holds no grant. |
