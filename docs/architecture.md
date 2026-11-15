# Architecture — how Data Quarry works

**What this doc is:** the shape of the running system — the pieces, what each one does, and how a
request travels between them. It is the orientation doc, short enough to read whole.

**What this doc is not:** it holds no coding rules, no operational trap lists and no history. Those
live beside the code they govern, and the last section here — the **Architecture Decision Record** —
indexes the decisions that put the system in this shape, each pointing at its full entry in the
register.

| Looking for | Read instead |
|---|---|
| Why a decision was taken, and what was rejected | [`decisions/`](decisions/index.yaml) — the register, one file per decision |
| What already exists in the SPA, to reuse it | [`apps/portal/info/component-inventory/INDEX.md`](../apps/portal/info/component-inventory/INDEX.md) |
| How a control plane's machine actually runs | [`lambdas/info/planes/`](../lambdas/info/planes/) |
| A Terraform module, its resources and its traps | [`infra/info/INDEX.md`](../infra/info/INDEX.md) |
| Coding rules — React, accessibility, Lambda shape, Python | [`docs/best-practices/INDEX.md`](best-practices/INDEX.md) |
| How work gets done here | [`process/INDEX.md`](process/INDEX.md) |

---

## The system at a glance

```
  Cognito Hosted UI ──▶ ┌──────────────────────────────────────────────┐
  (Managed Login v2)    │  the browser — React 19 on Next.js, strict   │
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

**One shared IAM role, and isolation by principal tag.** Every authenticated caller ends up as the
same portal role, tagged with the caller's `username`. **The API stamps that tag** — server-side,
from the verified ID token's claim, so it cannot be spoofed — and every policy scopes itself with
`${aws:PrincipalTag/username}`. There are no per-user roles and no app-level access control. The
Cognito Identity Pool stamped the same tag from the same claim until SPEC-202 retired it; the model
is unchanged, and the browser now holds no AWS credentials at all.

**One string is four things.** A username is also the S3 prefix, the principal tag and the Glue
database name, which is why it is constrained at signup to `^[a-z][a-z0-9_]{2,62}$` and is
catalog-safe by construction.

The SPA reaches AWS by three routes at once, and which one a feature uses is a deliberate choice per
feature: **directly** with scoped credentials (most reads), **through the API** (the routes ported so
far), or **by enqueuing onto a control plane** (anything privileged, cross-user or multi-step).

---

## The browser application

`apps/portal/` is a React 19 + TypeScript (strict) app on Next.js, served by a Node server, and it is
most of the code in this repo. `infra/` is the OpenTofu that stands everything else up, `lambdas/` is
the privileged server-side work, and `packages/` is reserved and empty.

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

**Every API call goes through a service file, and services never throw.** They return
`ServiceResult<T>` — `{success: true, data}` or `{success: false, error: {message, code?}}` — so a
caller branches instead of catching. The one client is `lib/apiClient`'s `apiRequest`, reached only
through service files and never from a component; no `@aws-sdk/*` package may be added.

**Raw AWS and Cognito text is never shown to a user, and Athena's only beneath the sentence of a
query that failed on the user's own SQL,** in a closed Details disclosure. `lib/errorMessages.ts` is
the single source of wording; rendering `error.message` is a defect, not a shortcut.

**Mobile-first, one tree.** Two breakpoints are compiled — `tablet:` at 900, `desktop:` at 1300 — and
the same tree reflows. A `*Mobile`/`*Desktop` twin is a smell.

**Navigation goes through one seam.** Every feature navigates through `src/lib/navigation/`, which
works under both routers while the areas move onto the App Router: it holds what the App Router lacks
(a navigation's state, its type and a key per history entry), decides per path which router performs a
navigation, and feeds react-router inside the catch-all as a matcher. The providers and the signed-in
shell live in the root layout above every page, behind a client-only boot, and the chrome decides by
the address, through the area records, whether a page is public or signed in.

## How the SPA reaches a user

**The web tier is the only front door, and it has an off switch.** The portal is a Next.js app on a
Node server, run on ECS Fargate behind an internet-facing ALB in a VPC that exists for nothing else,
and it answers `portal.dataquarry.app`. A Node app has no static fallback, so with
`web_tier_enabled` off nothing serves the portal; that is accepted, and the tier is switched on
through CI while someone is working (`infra/info/web-tier.md`). Every signed-in area is an App Router page
since SPEC-258; only the landing page and the 404 still render inside the optional catch-all route,
matched by react-router, until SPEC-263.

The server does the jobs a static origin did: it renders `/config.json`, refuses to start without
its configuration, and its request proxy stamps every page with an enforcing CSP carrying a fresh
nonce, plus the security headers, leaving each cache class to its owner. Two divergences from the
CloudFront path that came before it remain — no brotli, and HSTS without `preload` — and the image
**is** the file set, so there is no `--delete` pass and no orphan class.

**Configuration is a runtime document.** The browser fetches a same-origin `/config.json`, which the
Next.js server renders from its environment, once before the first render, rather than reading `VITE_*` values inlined at build time — so promoting a build is a
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
surface** — listing, head, exists, content read and write, copy, move, delete, free-name, the
download presign and the four upload routes. File **bytes** do not travel through it: a download is
a presigned `GET`, and an upload is a presigned `PUT` **or a multipart plan, whichever the server
chooses** from the declared size. Both are signed server-side by the caller's own assumed session,
so the transfer is between the browser and S3 and compute never touches it. It also serves the **catalog surface** —
Athena start, status, results and stop, and Glue get-database and list-tables — and the **eleven
enqueue routes** over the nine control-plane queues, so **no `@aws-sdk/*` package is left in the browser at
all**. The browser still reaches AWS without one: a presigned
`PUT`/`GET` goes straight to S3. *(Marked 2026-11-15: until SPEC-262 Amplify also talked to Cognito from the browser; the portal server signs in now, and the browser holds no token.)* The rule that keeps the two from drifting is **no new
browser-side AWS SDK call on a path an API route already serves**, and **no second API**.

A document that belongs to no user — `_directory/usernames.json`, `_config/feature-flags.json` — gets
a route of its own rather than riding the object surface, because the space resolver refuses a prefix
no caller's claims authorize, and correctly so.

The function is deliberately **not in the VPC**, and authorization is a verifier **the router calls**
— not an API Gateway authorizer, which would be a second reader of the same token. Detail:
[`lambdas/info/planes/api.md`](../lambdas/info/planes/api.md) and
[`infra/modules/api/README.md`](../infra/modules/api/README.md).

## Identity

Sign-in is **Cognito**: a standalone User Pool with the Hosted UI (Managed Login v2). It
authenticates people and issues JWTs, and that is all it does — nothing in the browser turns a token
into AWS credentials.

```
The browser asks the portal server's /auth/session
  → no session: the landing page's Sign in visits /auth/login, which redirects to Managed Login
  → Cognito issues JWTs to the portal server, which keeps them in its session store
  → the browser calls /api/ on its own origin, and the server sends the ID token to the API as a bearer
  → the API verifies it, reads { cognito:username, custom:shared_space_1..10 } from the claims
  → and assumes the portal role with those as session tags, for that request
```

**The browser makes no AWS call except presigned S3 bytes**, which the API mints for it, and it
holds no token: the expired-credential retry that wrapped every AWS call is a server-side re-assume,
and the token refresh is the portal server's. **One session covers the whole browser**, and every
API request names the tab's user so that a tab never acts as someone who signed in elsewhere
(rewritten 2026-11-15 for SPEC-262; until then tokens were held per tab).

A **Cognito Identity Pool** did this exchange in the browser from SPEC-011 until SPEC-202 retired it
on 2026-08-31, stamping the same tag from the same claim. Two of its constraints survive it: the tag
**value** is the `cognito:username` claim, because the bare `username` claim does not exist in a User
Pool ID token; and a session tag is single-valued, which is why membership is ten numbered slots
rather than a list.

### The API's auth boundary

**One token, verified once, at the API.** The API verifies the caller's Cognito ID token from an
`Authorization` bearer header through `cpcommon.auth`, which has no other caller now, and stamps
the verified username into the `identity` block of every control-plane message it enqueues. The
verbs used to verify the same token out of the SQS message body; since SPEC-201 they read the block
through `cpcommon.actor` instead, because who may write their queues is enumerated — the API, and on
the shared-space queue an operator reader admitted by `SenderId` (rows 43 and 46). Nothing re-derives a username, and nothing anywhere reads a username the caller stated.

- **It is a verifier, not an OIDC client.** No code exchange, no PKCE, no client secret, no redirect
  URI — those belong to the portal's Next.js server, a confidential OIDC client with its own secret,
  which signs the browser in since SPEC-262 (Amplify did, in the browser, until then). The API is only a verifier. Provider-agnosticism is five server-side config
  fields ([`infra/modules/api/README.md`](../infra/modules/api/README.md)), so swapping the identity
  provider is a change of values.
- **It assumes the same role with the same tags from the same claims** the Identity Pool read, which
  is why no policy had to be rewritten and why the hand-maintained bucket-policy allowlist stays
  correct. The role is reused, never minted — and reusing it is what let the pool be deleted without
  touching a single permission policy.
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
(`AbortMultipartUpload`, `ListMultipartUploadParts`) — load-bearing again now the API multiparts,
because the same role signs every presigned URL and `AbortMultipartUpload` is what discards the
parts of an upload that was cancelled or failed to assemble. `ListBucketMultipartUploads` is deliberately **not** granted: it cannot be scoped per
prefix, so it would leak other users' in-progress uploads.

**Shared space — bounded membership slots.** Access is gated by membership principal tags on the same
role. The hard AWS constraint is that a session tag holds exactly **one value** — the Identity Pool
mapped one claim to one tag, and the API that replaced it stamps one tag per claim for the same
reason — and IAM cannot iterate a list inside a `Resource` ARN. So what is bounded is **how
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

Four buckets. The constraint the project holds to is **one bucket of personal prefixes**, not one
bucket overall.

| Bucket | Holds |
|---|---|
| user-space | every user's own prefix, plus two shared documents every signed-in user may read: the username directory under `_directory/` and the feature flags under `_config/` |
| shared-space | user-created shared spaces. The **lifecycle** — create, membership, delete — goes through a control plane; a member's browser writes objects inside a space it belongs to directly |
| admin | the shared-space registry, the planes' scratch, `logs/` (retained forever), and Athena's **fallback** output — a user's own results land in their user-space prefix |
| archive | the GLACIER vault, which the browser has no relationship with at all |

Plus a Lambda artifacts bucket and a CloudTrail bucket, neither of which the app touches.

**The product presents filesystem UX over a store that has neither move nor rename.** Every move is
`CopyObject` + `DeleteObject`; folder operations are recursive and **non-atomic**; a per-key failure
must never delete that source and never abort the rest. Collisions are handled in the UI by
warn-and-confirm, because **versioning is off** — which is exactly what makes a failure between those
two steps unrecoverable. That deferral is pre-production and is recorded to be revisited before real
user data lands.

## The control planes

Eight features do privileged, cross-user, multi-step AWS work that browser-scoped credentials must
not: shared-space lifecycle, table creation, table sharing, data-quality checks, sending files,
archiving into Glacier with its restore, copying/moving/deleting files, and converting a query's
result set into another format. Each is a deliberate,
recorded exception to browser-direct access, **for its mutations only**.

```
browser ──▶ API ──sqs:SendMessage──▶ FIFO request queue ──▶ Pipe ──▶ Step Function ──▶ verb Lambdas
                                     │                                                          │
                                     └──▶ DLQ ──▶ scheduled drain              notifications queue
```

- **The browser has no privilege on any plane.** It calls an API route; the API's execution role is
  the only principal that may write a request queue (SPEC-200).
  The request body carries the API's `identity` block, which a plane reads through `cpcommon.actor`;
  no token travels (SPEC-201, row 43).

  > **Superseded in part by SPEC-208 (row 46), widened by SPEC-217.** A request queue's writers are
  > *enumerated*, and the shared-space queue now has two: the API, and a scheduled reader that turns
  > an operator's CSV of membership changes — adds, removals and transfers — into requests. It carries no identity block and is admitted by the
  > `SenderId` SQS stamps on its message. The browser still has no privilege on any plane — that
  > half is unchanged. Full entry:
  > [`decisions/control-planes/`](decisions/control-planes/a-control-plane-queue-may-have-a-second-producer-admitted-by-senderid.md).
- **One shared execution role per plane, and its own DLQ** — the DLQ drain names the feature by the
  DLQ a request lands on, so a shared DLQ would tell the user the wrong feature failed.
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
| Results conversion | a finished execution's result set written into a space as Parquet, JSON, Excel, or CSV when the file keeps a subset of its columns | [`results-conversion.md`](../lambdas/info/planes/results-conversion.md) |

The Terraform side of the shared machine is
[`infra/modules/control-plane/README.md`](../infra/modules/control-plane/README.md); the Lambda side, with
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
browser's S3 access stay IAM-authorized — the API's calls under the caller's assumed role, and bytes
on URLs that role presigned — while Athena reads through LF. Flipping to enforced without first
opting in every principal would break the file browser.

The seven calls the workspace and the Data Explorer ride on — Athena start, status, results, row
count and stop, and Glue get-database and list-tables — go **through the API**, which derives the workgroup, the
results location and the caller's identity server-side. Lake Formation is unaffected by that move
because its grants attach to a **principal**, and the principal is the same portal role, now assumed
by the API instead of vended to the browser. Two properties are load-bearing and easy to lose in a
port: **the API never waits, and no route's call count grows with the data**, so every poll and page walk
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

IaC is **OpenTofu** under `infra/`, with S3 remote state. A module is one architectural concept and
the root composes them flat: the eight control planes are eight root calls to one `control-plane`
building block, each in its own `infra/plane-<slug>.tf`, and the five standalone functions are root
calls to `scheduled-function` or `queue-consumer`, each in its own `infra/function-<slug>.tf`. IAM
policies are `.tftpl` templates rendered by `templatefile()` — never inline `jsonencode`. Every module
carries a `README.md` beside its `.tf`, each plane and standalone function one beside its templates, and [`infra/info/INDEX.md`](../infra/info/INDEX.md) is the
router.

**GitHub Actions owns delivery**, through a role assumed by OIDC:

| Workflow | Runs on | Does |
|---|---|---|
| `ci.yml` | pull requests | `tsc -b` build, the VITE_ bundle check, contract regeneration, doc-layout validation, feature-flag validation — lint, format check, both suites, ruff and mypy are disabled here and run in the local pre-push gate instead (`docs/process/ci-and-deploy-traps.md`) |
| `spa-image.yml` | pull requests | builds the container and asserts its behaviour against every criterion the image is built to meet |
| `deploy-infra.yml` | pull requests (`plan`) and push to `main` (`apply`) | `tofu plan` with a Checkov scan of the rendered plan, then `tofu apply`, with a `skip_refresh` break-glass |
| `deploy-spa-image.yml` | push to `main` | builds the image, pushes it to ECR tagged by commit sha, and points the ECS service |
| `deploy-lambda-image.yml` | push to `main` | builds the Lambda fleet's one image, proves it against the behaviour matrix, and pushes it tagged by commit sha — it points nothing, which is `deploy-lambdas.yml`'s job |
| `deploy-lambdas.yml` | push to `main`, or a dispatch carrying an `image_tag` to roll back | points **every** function at the fleet's container image, reconciles by name, then invokes a sample to prove the deployed artefact starts |
| `deploy-config.yml` | push to `main` | publishes the feature-flag document to the user-space bucket |
| `security.yml` | pull requests and a weekly schedule | the scanner suite — Semgrep, pip-audit, gitleaks and Checkov **block**; npm audit and the ZAP baseline report |

**Lambda code and infrastructure are deployed separately** — `tofu apply` never touches code, and CI
owns which image each function runs. That split, and the traps that come with it, are
[`lambdas/info/deployment.md`](../lambdas/info/deployment.md).

**The deploy role self-grants**, which makes adding a new AWS resource type its own small discipline:
the grant lands in **its own PR, applied before the resources that need it**. The trap list is
[`infra/info/deploy-role-iam.md`](../infra/info/deploy-role-iam.md), and it is in-scope work for any
spec that provisions new infra.

**The container platform reaches AWS through endpoints, and the internet through one NAT gateway.**
A task reaches ECR, CloudWatch Logs, S3, DynamoDB and SSM through interface and gateway endpoints, so
starting one never depends on the NAT gateway. The NAT gateway, on the web tier's switch, carries
only what has no endpoint: the portal server's calls to the Cognito domain's token endpoint and to
the API's custom domain. Flow logs record what a task reached. *(Until SPEC-257 there was no NAT
gateway anywhere and a missing endpoint failed as a connect timeout; row 34.)*

## Constraints that shape the system

The durable ones — each is a property of a service rather than of our code, and each has already cost
something.

- **S3 has no move or rename**, so every one is `CopyObject` + `DeleteObject`, folder operations are
  recursive and can partially fail, and there is no transactional rollback.
- **Versioning is off**, so a failure between those two steps is unrecoverable. Deferred
  pre-production; revisit before real user data lands.
- **`ListObjectsV2` returns at most 1,000 keys per call.** The browser paginates with
  `useInfiniteQuery` — a Prev/Next pager over server pages in the file browser, "Load more" in
  the destination picker — never assume one page is a whole folder.
- **The SERVER decides whether an upload is one presigned `PUT` or a multipart plan**, so the
  browser holds no threshold. Either way it caps at 5 GiB — and that ceiling is now a server-side
  refusal, because S3 enforced it unforgeably only for a single `PUT`. A dropped connection retries
  one part, not the file.
- **Lake Formation is in hybrid mode**, and leaving hybrid mode breaks direct-IAM S3 access.
- **Usernames are constrained at signup** because the same string is a prefix, a tag and a database
  name. The pool is case-insensitive.
- **Client-side routing needs the server to answer every app path with the shell**, or a refresh on
  a deep link returns a raw error. The optional catch-all route does it, which is also why a path
  nothing matches answers 200 rather than 404.
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
rejected alternatives live — an entry in [`decisions/`](decisions/index.yaml) for most, a tree page for
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
| 1 | [Cognito User Pool plus Identity Pool, no custom auth](decisions/identity-and-access/auth.md) | A greenfield app with no existing identity estate; the managed pair vends AWS credentials directly, so the browser needs no token-exchange code of ours. | The Hosted UI is [Managed Login v2](decisions/identity-and-access/hosted-ui-managed-login-v2.md) — the classic UI broke the post-signup redirect. Tokens are held per tab, not per browser. **Superseded in part by row 49 (SPEC-202):** the Identity Pool is retired and the browser holds no AWS credentials. The User Pool, the Hosted UI and the token are unchanged — the pair is now a User Pool and the API. |
| 2 | [One shared IAM role, isolation by principal tag](decisions/identity-and-access/auth.md) | Per-user roles need a provisioning step per user and hit account limits; the Identity Pool can stamp a verified claim as a session tag, which scopes one policy to every user. | The tag is stamped server-side, so it cannot be spoofed. A session without the tag matches nothing — the default is an implicit deny. **Amended by row 49 (SPEC-202):** the API stamps the tag now, from the same claim of the same token; the model and every policy are unchanged. |
| 3 | [The username is also the prefix, the tag and the database name](decisions/identity-and-access/usernames.md) | One identifier means one thing to keep consistent; three would need a mapping table nobody could see. | Constrained at signup to `^[a-z][a-z0-9_]{2,62}$` so it is catalog-safe. The client-environment transition re-keys exactly this. |
| 4 | [A user may belong to ten shared spaces](decisions/identity-and-access/bucket-2-shared-space.md) | The Identity Pool maps a claim to exactly one single-valued tag and IAM cannot iterate a list inside an ARN, so a per-user list of memberships is not expressible — ten fixed slots are. | **The bound is per user, not per space** — a space's member count is unlimited. Raising it enlarges the portal-role policy by a statement-pair. Unbounded membership would need a token-vending Lambda, which replaces the whole credential path — recorded, not built. **Amended by row 49 (SPEC-202):** the constraint is the session tag's single value, not the pool's mapping — the API stamps one tag per claim for the same reason, so the ten slots stay. |
| 5 | [The username directory is built from S3, not Cognito](decisions/identity-and-access/the-username-directory-is-built-from-s3-not-cognito.md) | Today Cognito is the complete list and S3 is not; the directory is still built from S3 because that is what the client transition inverts. | Readable by every authenticated user, accepted deliberately: usernames only, never emails. |
| 6 | [A feature flag is presentation, never authorization](decisions/identity-and-access/a-feature-flag-is-presentation-never-authorization-and-it-lives-beside.md) | A flag decides what is offered; IAM decides what is permitted, and conflating them puts an access decision in the browser. | The flag document lives in the **user-space** bucket beside the directory — the admin bucket's grant would not have worked. |
| 7 | [The API is a verifier, not an OIDC client](decisions/identity-and-access/the-api-is-a-verifier-not-an-oidc-client.md) | Sign-in already works in the browser; the API only needs to decide a bearer is genuine. Building a client here duplicates the flow in the one place a mistake fails closed and silently. | Five config fields, no cookie so no CSRF surface, CORS still required. A key-retrieval fault is 5xx, never 401. |
| 8 | [The API assumes the same role with the same tags from the same claims](decisions/identity-and-access/the-api-reads-the-same-claims-and-assumes-the-same-role-with-the-same.md) | One computation over one input means no policy is rewritten and the bucket-policy allowlist stays correct as routes port over. | Role chaining caps `DurationSeconds` at 3600 both ways: shorter caps every presigned link, longer is refused. |
| 9 | [Two credential planes, declared on the route](decisions/identity-and-access/two-credential-planes-declared-per-route-defaulting-to-the-user-plane.md) | A route either acts as the user or as the service. A central registry mapping route to plane was the alternative and is what this replaced: it puts the declaration somewhere other than the thing it describes, and its set-equality guard passes while a route is wrong. A required field on the route cannot be forgotten. | **This failure fails open** — a wrong client succeeds against the wrong identity. Hence one construction site, an AST sweep, and a raise on any third value. |
| 10 | [The credential cache is keyed on the whole tag set](decisions/identity-and-access/the-credential-cache-is-keyed-on-the-whole-tag-set.md) | Keying on the username freezes membership until the next cold start; keying on nothing serves one user another's session. | Its margin is the life of one request. It retries on a **new** client, because boto3 binds credentials at construction. |
| 11 | [Authorization lives in the router, not an API Gateway authorizer](decisions/identity-and-access/authorization-lives-in-the-router-not-in-an-api-gateway-authorizer.md) | An authorizer would verify the same token independently and could disagree with the router about the claim the role scoping depends on, with no arbiter. | One `$default` route means an authorizer would have to duplicate the route table before it could say anything. The verifier is a module with no router dependency, so the gate can move later without the verification moving with it. |

### The browser and the API contract

| # | Decision | Context | Notes |
|---|---|---|---|
| 12 | [TanStack Query for server state, Context and `useReducer` for UI state](decisions/browser/state.md) | Server state has caching, staleness and retries; UI state has none of them. A single store for both means hand-writing the first set, which is what Redux would have been here. | Query keys live in `lib/queryKeys.ts` — a key built at a call site is invisible to every invalidation written against it. |
| 13 | [Services return `ServiceResult<T>` and never throw](../apps/portal/info/component-inventory/foundations.md) | A caller branching on a result handles the failure path visibly; a caller catching an exception mostly does not — and an un-caught one reaches a user as raw AWS text. | The register never got an entry for this; the shape and its adapters are in the inventory. The wording half — never render `error.message` — is [`decisions/browser/`](decisions/browser/) → *User-facing error messaging*. |
| 14 | [The shared layers may not import from `features/`](decisions/browser/components-may-not-import-from-features.md) | Without the rule the dependency graph inverts quietly, and a shared component starts depending on a feature it is used by. | Lint-enforced with two named exemptions. Extract a leaf feature **before** its second consumer, not after. |
| 15 | [Mobile-first, two compiled breakpoints, one tree](decisions/browser/responsive.md) | Tailwind compiles every breakpoint you declare whether or not you use it, and each one is a state every surface can be wrong in. Two is what the layouts actually need. | Only `tablet:` (≥900) and `desktop:` (≥1300) exist — an unprefixed class is mobile. Reaching for a third means the tree is doing something a reflow cannot, which is worth stopping on. |
| 16 | [The wire is declared in Python and the TypeScript is generated](decisions/identity-and-access/the-contract-is-declared-in-python-and-the-typescript-is-generated.md) | Two hand-written halves of one contract drift, and the drift surfaces at runtime in the browser. Python is the declaring half because the server is what actually enforces the shape — generating the other way would make the browser's belief authoritative over the thing validating it. | CI refuses a regeneration diff in both directions. The type vocabulary is closed and **never falls back** — a fallback type agrees with everything. |
| 17 | [`apiRequest` retries nothing, except one forced refresh on 401](decisions/identity-and-access/apirequest-retries-nothing-and-idempotency-is-declared-per-route.md) | A blanket retry replays non-idempotent writes; idempotency is a property of the route, never of the HTTP method. | That single 401 retry is the browser's only refresh path — deleting it signs everyone out at the hour mark with a green suite. |

### Storage and data

| # | Decision | Context | Notes |
|---|---|---|---|
| 18 | [Filesystem UX over a store with no move or rename](decisions/storage/file-ops-filesystem-ux.md) | The alternative is showing users the store as it is — flat keys, no folders, no rename — which is honest and unusable for the file-handling this product exists to do. The gap is bridged in the app, and the cost is that every move is two operations that can half-succeed. | Folder operations are recursive and non-atomic. A per-key failure must never delete its source nor abort the rest. |
| 19 | [S3 versioning stays off](security-baseline.md#iac--checkov-305-failures--25-rules) | Pre-production with no real user data, so the exposure is theoretical today; enabling it has a storage-cost and lifecycle story nobody has written. | This is what makes a failure between copy and delete unrecoverable. **Turning it on is not free elsewhere** — the archive's Object Lock decision and several plane fences read on versioning being off. **Revisit before real user data lands.** |
| 20 | [A multi-file operation belongs on a plane; one file stays synchronous](decisions/storage/a-file-operation-on-more-than-one-file-belongs-on-a-plane-and-the.md) | A single file completes inside a request; a folder tree does not, and holding the browser open for it is the thing that fails. | The boundary is the **selection**, not the byte count. The lock is per space, and its loser waits. |
| 21 | [Per-user catalog isolation by principal tag, not LF-Tags](decisions/analytics/analytics-2.md) | Glue database isolation is the same problem as S3 prefix isolation, and one mechanism is one thing to reason about. | Lake Formation grants the shared role broadly; IAM is the gate. Both buckets stay in LF **hybrid** mode or the file browser loses direct S3 access. |
| 22 | [Control-plane table creation is TBAC](decisions/analytics/control-plane-table-creation-tbac.md) | LF **admin** status does not grant `CREATE_TABLE` on a database the admin did not create — which is not what the console's admin screen suggests. | A `portal-managed` LF-Tag plus one tag-policy grant per execution role, and a static per-bucket data-location grant. |
| 23 | [Every DDL literal goes through an escaper, and there are two axes of them](decisions/analytics/every-ddl-literal-goes-through-literal.md) | Hive/DDL and Trino/DML escape differently, and so do values and identifiers; a shared space's name was held nowhere server-side until the create path took the catalog rule, which refuses a **create only**, so a space named earlier keeps what it was given. | **The wrong escaper fails silently, as a predicate that never matches.** A quoting fix is not done until every statement built from the same value is swept. |
| 39 | [Bytes go to S3 presigned; small text goes through the API](decisions/storage/bytes-go-to-s3-presigned-small-text-goes-through-the-api.md) | Routing file bytes through the API would put a 6 MB response ceiling and a 29-second integration ceiling in front of every upload and download, and would pay compute for a transfer S3 can do itself. Routing *documents* through S3 instead would need a second credential path in the browser for objects a few kilobytes long. | The document route's **byte cap is what holds the split** — without it it is a second upload path that works perfectly to 6 MB. The upload is `XMLHttpRequest`, not `fetch`, or the progress bar silently dies. ~~**No part-level retry** any more.~~ **Superseded on that clause by row 48**; the split itself stands. |
| 40 | [A presigned URL is a bearer token](decisions/identity-and-access/a-presigned-url-is-a-bearer-token.md) | Handing the browser a capability instead of a credential keeps every credential server-side, and S3 evaluates the signer's own scope at redemption — which is what makes the design survive the target environment's move to Access Grants. | Signed by the **caller's** assumed session, never the execution role. Clamped to the credential that signed, read in the **same** call. In no emitted record. |

### The control planes

| # | Decision | Context | Notes |
|---|---|---|---|
| 24 | [Privileged work runs on a control plane, not in the browser](decisions/identity-and-access/no-backend.md) | Cross-user, multi-step work needs permissions no browser session should hold, and durable retry across a closed tab. A synchronous API route would need the same permissions and still lose the work when the request ends. | The browser held one grant, `sqs:SendMessage`, which kept the privileged surface off user credentials; SPEC-200 moved even that behind the API, so the browser now holds none (ADR row 42). The register has no entry of its own for this: the decision lives as the **superseded marker** on the `No backend` entry it reversed, which is what the link lands on. The pattern and its fences are [`decisions/control-planes/`](decisions/control-planes/). |
| 25 | [One execution role and one DLQ per plane](../infra/modules/control-plane/README.md) | Per-verb roles were built and deliberately consolidated: the union policy is readable, and seven roles per plane were not. | The drain names the feature by the DLQ a request dead-lettered on, so a shared DLQ would misattribute it. |
| 26 | [`cpcommon` owns the algorithm; a domain layer owns the wording](decisions/control-planes/the-deliberate-twins-are-discharged-one-implementation-per-cross-plane.md) | The same CAS loop, lock protocol and failure resolver existed three times and had already diverged. | **Do not merge the domain layers wholesale.** ~~Where a layer is packaged by an explicit file list, a test asserts set equality with the directory.~~ **Superseded by SPEC-214:** there is no explicit file list — a shared directory ships what it holds — so that guard retired with the list it checked. The set equality survives against an independent walk of the same directories. The no-merge rule is unchanged, and is now a code decision rather than a packaging one. Full entry: `decisions/control-planes/`. |
| 27 | [Everything unbounded travels by pointer, never on the state](decisions/control-planes/everything-unbounded-on-the-state-travels-by-pointer-including-the.md) | The 256 KB Step Functions state cap raises `States.DataLimitExceeded`, which `States.ALL` does not catch and no `Catch` in the fleet names — so the failure mode is silence. | A cap on the list is not a substitute for a pointer. Every cap that does exist is computed by a test against the budget that sized it. |
| 28 | [Outcomes arrive through the notifications inbox, on a single-writer queue](decisions/control-planes/notifications.md) | The work is asynchronous and may outlive the tab, so the completion channel has to be durable and readable later. | The UI never blocks. Delivery is at-least-once and **a redelivered message is not a re-run** — do not design recovery around it. |
| 29 | [A restore is guarded absolutely, and the guard runs twice](decisions/archive-and-restore/the-destination-guard-runs-twice-because-this-spec-turned-a-guarantee.md) | Archive is the one surface where a mistake is unrecoverable, and the billed retrieval hours are exactly when a user re-creates the file. | Any occupied destination refuses the **whole** restore, and a 403 counts as occupied — at the check AND at every write, since every copy-back line is a conditional write ([what overlap still costs](decisions/archive-and-restore/the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md)). One archive id is one run, by a create-only claim. The source is deleted only when every object is confirmed copied. |

### Infrastructure and delivery

| # | Decision | Context | Notes |
|---|---|---|---|
| 30 | [OpenTofu, bounded-context modules, IAM as `.tftpl` templates](decisions/infrastructure/iac.md) — *module shape superseded by row 54* | OpenTofu over CDK, Pulumi and SST — the infrastructure is the product's security boundary, so a declarative document a reviewer reads beats a program they have to execute in their head. `.tftpl` for the same reason: inline `jsonencode` hides a policy inside HCL. | An IAM policy document must be printable ASCII, so rationale never goes in a `.tftpl` — an em dash is rejected at `CreatePolicy`, invisible to plan and validate. |
| 31 | [Lambda code and infrastructure deploy separately](../lambdas/info/deployment.md) | Terraform applying code means every code change waits on an infra apply, and layer attachment belongs with the build that produced the layer. | `tofu apply` never touches code. ~~`ignore_changes` must name `layers`, or an apply strips a layer back off and the next cold start fails.~~ **Superseded by row 51 (SPEC-213):** every function is container-packaged, `layers` is not declared at all, and what `ignore_changes` names is `image_uri`. The split itself is unchanged. |
| 32 | [Configuration is a runtime document with no production fallback](decisions/infrastructure/configuration-is-a-runtime-document-and-a-production-build-has-no.md) | A `VITE_*` value inlined at build time makes an artifact environment-specific, so promotion becomes a rebuild and rollback becomes a rebuild back. | `no-store`, refused whole on version. A key is wired in five places, asserted across all of them, and the container refuses to start on a missing one. **Updated by row 55 (SPEC-255):** the Next.js server renders the document, the sites are four, and only the test runner has a fallback. |
| 33 | [The SPA ships as a container on Fargate, with CloudFront still production](decisions/infrastructure/the-nginx-configuration-reproduces-cloudfronts-jobs-and-three-are.md) | The target environment needs a runtime it controls; running both paths keeps a rollback that is exercised rather than theoretical. | Three deliberate divergences: `Server: nginx`, no brotli, no HSTS `preload`. Origins are admitted **additively** and narrowed only at the cutover. **Superseded by row 50 (SPEC-202):** CloudFront is destroyed and the container is the only front door; the divergences and the additive-origins rule are unchanged. **Superseded again by row 55 (SPEC-255):** the container runs the Next.js server, not nginx, and the divergences are two, with the `Server` banner gone. |
| 34 | [No NAT gateway; private subnets reach AWS through endpoints alone](decisions/infrastructure/there-is-no-nat-gateway-and-the-endpoints-are-the-whole-outbound-story.md) | "No route to the internet" is a property a reviewer reads off a route table; "a NAT gateway nobody uses" is a claim re-argued every year. | The residual failure is a **connect timeout**, which leaves nothing behind — hence flow logs. Read any successful pull beside `describe-route-tables`. **Superseded in part by row 57 (SPEC-257):** one NAT gateway on the web tier's switch carries the portal server's two internet destinations; AWS services stay on endpoints. |
| 35 | [The image tag is the commit sha and `:latest` does not exist](decisions/infrastructure/the-image-tag-is-the-commit-sha-and-latest-does-not-exist.md) | An immutable tag makes a running task traceable to a commit, and makes a rollback a repoint. | `task_definition` is ignored and `desired_count` is not, so **CI must point the service** — a pipeline that only registers a revision produces a pull error indistinguishable from an endpoint failure. |
| 36 | [The deploy role self-grants, and grants land in their own PR first](../infra/info/deploy-role-iam.md) | The role that creates everything has to be able to create the thing that grants it — so the grant and its first use cannot be in the same apply. | Scopability is **measured** with `simulate-custom-policy`, never assumed. A simulate matches patterns, not the ARN a service actually passes. |
| 37 | [A gate blocks on a narrowed count, never a total](decisions/gates-and-tests/a-scanner-gate-blocks-on-a-narrowed-count-never-a-total.md) | Enforcing what passes is a ratchet; suppressing what fails is a list that grows. A line matching no finding is a hard error. | **"Did not run" is never "clean."** A broken scanner fails the job even in report mode. |
| 38 | [Coverage floors and compiler strictness are declared, never inherited](decisions/gates-and-tests/compiler-and-coverage-defaults-are-declared-never-inherited.md) | An inherited default changes under you when a tool upgrades, and the change is invisible in the diff. | Ratchets at the measured level. Never lower one for a regression — the doc-layout budgets follow the same rule, each sitting just above its measurement with the room it leaves stated beside the number. |
| 41 | [The API makes exactly one AWS call per request, and every loop stays in the browser](decisions/identity-and-access/the-api-makes-exactly-one-aws-call-per-request-and-every-loop-stays-in.md) | "The API waits for the query" is the shape a reader reaches for. A five-minute query is 10× a **non-raisable** 30-second integration ceiling, so the rejected design does not fail at the margin — it fails always, and it holds a Lambda open for the duration of a user's query while doing so. | The count is on the **route's own service client**, never on botocore — the session cache fires `AssumeRole` on some invocations and not others. What is enforced is the shape — no waits, no paginators, no continuation loops — rather than a literal count of one: `objects.move` and the multipart create each make a small fixed number, and free-name's is bounded. A route may now carry **path parameters**, and a value that is not one segment is refused in the browser. |
| 42 | [The browser's queue grants come off with the switchover, not with the trust flip](decisions/identity-and-access/the-browsers-queue-grants-come-off-with-the-switchover-not-with-the.md) | The eight FIFO request queues were the browser's last privileged write and its only remaining AWS grant. Moving the send behind the API is what lets a plane trust an actor the API stamps from a verified bearer rather than a token it verifies itself — and the grant had to come off in the SAME change, because the Identity Pool survives to SPEC-202 and a trusted `actor` field plus a browser credential able to write the queue is impersonation. | The API's execution role is the only principal that may write a request queue; the browser holds no AWS grant at all. The message carried a nested `identity` block ALONGSIDE the token it did not yet replace — SPEC-201 flipped the planes onto it and only then stopped the token being sent (row 43). Supersedes row 24's "the browser's only grant is `sqs:SendMessage`". |
| 43 | [The planes trust a body field because of who may WRITE it, not because of cryptography](decisions/identity-and-access/the-planes-trust-a-body-field-because-of-who-may-write-it-not-because.md) | Eight planes each verified a Cognito ID token out of the queue message. Once the API became the only principal that may write those queues, that was a second answer to a settled question — and the last reason a raw JWT travelled through eight queues, sat in eight execution inputs, and reached CloudWatch on every dead-letter. | The planes read `identity.actor` through one reader that **cannot verify**; `cpcommon.auth` keeps one caller, the API. Dropping a verification is not dropping an authorization — every authorizer has zero diff. Two deploys, the second irreversible. Completes row 42.
| 44 | [The membership index is an authorization input, where the username directory is not](decisions/identity-and-access/the-membership-index-is-an-authorization-input-where-the-username.md) | The session's shared-space tags come from Cognito custom-attribute claims, which do not exist in the successor account under either identity variant. The registry could answer "which spaces is this user in" but not cheaply — one object per space, keyed by space name, so a listing plus a read per space on every credential mint. A new per-user projection in the admin bucket answers it in one `GetObject`. | The source is a **cold-start choice** (`MEMBERSHIP_SOURCE`), default `claims`, wired into no Terraform — nothing here changes what runs today. The index is **user-unreachable, plane-written, CAS-written**, which is what lets it be an authorization input where SPEC-146's directory may not be. The user's own connections cache has the same shape, is one `GetObject` away, and is **user-writable** — reading it is a complete bypass. |
| 49 | [The Identity Pool is retired, and no one's sign-in changed](decisions/identity-and-access/the-identity-pool-is-retired-and-no-ones-sign-in-changed.md) | Two credential paths ran at once through the arc: the pool vending AWS credentials to the browser, and the API assuming the same role from the same claims. The second made the first redundant, and the first made the arc's load-bearing negative — the browser makes no AWS call other than presigned S3 bytes — impossible to observe, because Amplify vends pool credentials whenever the id is configured. | Retiring it changed **nobody's sign-in**: the User Pool, Managed Login v2 and the token are untouched, and reading it as "Cognito is retired" sends the next reader looking for a change that does not exist. The role is **reused**, so no permission policy was rewritten; the trust policy went from two statements to one. `lib/awsCredentials.ts` became `lib/idToken.ts` with one export, named for a JWT because a module called `awsCredentials` invites putting some back. The absence is proved **positively** — `describe-identity-pool` → `ResourceNotFoundException` — and SPEC-196's isolation simulation was re-run row for row afterwards with **no row changed**. Supersedes row 1's "the managed pair vends AWS credentials". |
| 45 | [A shared-space delete removes people, not things](decisions/control-planes/a-delete-removes-people-not-things-and-retention-keys-on-a-durable-fact.md) | Deleting a workspace destroyed every object under its prefix, its Glue database and its registry record, on a bucket with **no versioning** — so a mistaken delete had no recourse at all. It now ends every member's access and destroys nothing, which makes the mistake recoverable by an administrator and removes SPEC-151's whole failure class from the route (nothing frees a name, so a partial teardown cannot). | Retention keys on the durable `everActive`, **never live `status`** — which moves `active → deleting → failed` over intact data. `deleting` is **not** evidence a space was usable: delete is gated on ownership alone, so a never-active create reaches it too. **One predicate**, `is_destroyable`, routes the delete AND refuses the add; complements written twice drift silently in both directions. Two permanent, user-visible costs: a name is never reusable, and deleted data is retained. The residual is the credential window — a removed member's query workspace still reaches the retained database until their token expires. |
| 46 | [A control-plane queue may have a second producer, admitted by SenderId](decisions/control-planes/a-control-plane-queue-may-have-a-second-producer-admitted-by-senderid.md) | A shared space's owner was whoever created it, forever — so an owner who had left could only be worked around by abandoning the space or deleting it, and both are worse than the problem. Transfer fixes the ordinary case; the case the UI cannot serve is an owner who is already gone, which needs a door no signed-in session goes through. | The reader enqueues onto the **existing** queue, so operator and user transfers are one verb, one authorization and one notification pair. That reuse is what forces the fence: with no bearer to present, an operator message declares `origin` and is admitted only by the **`SenderId` role-id half** — the mechanism SPEC-206 established, inverted from a denylist to an allowlist. Two things make it real rather than nominal: the reader holds its **own execution role** (sharing the orchestrator's would admit every verb on the plane, invisibly), and `origin` is **undeclarable through the API**, so a signed-in caller cannot claim it at all. Narrows rows 42 and 43's "the API is the only principal that may write a request queue" to "the writers are enumerated"; the browser still holds no grant. **SPEC-217 widened that door from transfers to adds and removals**, which changes the threat model rather than the mechanism — a row now grants a stranger live access rather than moving ownership between existing members: [`decisions/control-planes/`](decisions/control-planes/the-operator-door-widens-to-member-management-and-that-is-a-threat.md). |
| 47 | [One image for the whole Lambda fleet, and the sweep that pays for it](decisions/infrastructure/one-image-for-the-whole-lambda-fleet-and-the-sweep-that-pays-for-it.md) | Eighty-six functions ship as zips with ten layers attached in a literal order, and what a function can import is decided at deploy time by a join between two JSON tables — observable nowhere else, so a missing layer is a `ModuleNotFoundError` at the next cold start, in production, behind a green suite. That happened and lasted nine days. | A container image replaces the join with an artefact: dependencies installed once, shared code copied once, every function running the same image with a different command. **It runs nothing yet** — no `aws_lambda_function` changed, and the cutover is its own spec. **Superseded in part by row 51 (SPEC-213):** every function now runs it, so read "runs nothing yet" as the state this row was written in. The image is strictly **wider** than a zip and an AST sweep, not the packaging, is what pays for that. Its import check runs through the runtime's **own bootstrap**, because a reconstructed search path that is a superset passes what production fails. |
| 48 | [An upload's shape is the server's decision, and a part is sized so the expiry premise stops mattering](decisions/storage/an-uploads-shape-is-the-servers-decision-and-a-part-is-sized-so-the.md) | One `PUT` gave a dropped connection nothing to retry, and made every upload depend on an unmeasured premise about when S3 evaluates a presigned expiry. Letting the browser choose the path would have put one policy number in two places. | The threshold **is** the part size — one quantity, computed from the slowest supported uplink. Reverses row 39's no-part-level-retry clause. The 5 GiB ceiling is unchanged, but what holds it is now a refusal on the **declared** size — a courtesy, not S3's unforgeable one. |
| 50 | [A cutover is two merges, and only the second one destroys the rollback](decisions/infrastructure/a-cutover-is-two-merges-and-only-the-second-one-destroys-the-rollback.md) | The arc was additive by design, so the retirement was the one subtraction — and nothing goes red when a dead distribution keeps answering, when the browser holds credentials it no longer uses, or when a `connect-src` still names four hosts nothing fetches. A half-finished retirement looks exactly like a finished one. | Merge 1 retires and touches nothing serving the app; the live checks then run **with the rollback intact**; merge 2 narrows the three allowlists and destroys the distribution, after which there is no way back. What the rollback was is worth stating precisely: a CloudFront-served **HEAD** bundle talking to the API, not a restoration of browser-direct AWS. A grant outlives its resource by one apply (the refresh deadlock), which is where the Checkov accept list turned out to be holding that grant's own findings open. Retires `deploy-app.yml`, `infra/modules/app`, the static bucket and the `/*` invalidation with it. |
| 51 | [A ForceNew packaging change is a rename in state plus 86 replacements](decisions/infrastructure/a-forcenew-packaging-change-is-a-rename-in-state-plus-86-replacements.md) | Row 47 built an image that ran nothing. Putting the fleet on it is a `package_type` change, which is ForceNew — so every function is destroyed and recreated, and the danger is not the packaging but everything that quietly does **not** re-plan alongside it. | 172 `moved` blocks make it an ordered replacement rather than a create racing a destroy on one name; Terraform tolerates a `moved` whose `from` is not in state, silently, so the guard checks both halves against a **frozen** population. Every `aws_lambda_permission` binds to the module's `function_arn`, because a name is config-known, plans **no diff**, and lets `DeleteFunction` take the resource policy — an API-wide 500 behind a green apply. Reverting is **not** a rollback; pointing at a previous sha's image is, and it was exercised both ways. One image also makes deploy-narrowing a category error, so CI points every function on every run and then proves a sample **started** — a check that took three designs, two of them measured wrong. Supersedes row 31's `layers` clause. |
| 52 | [A guard is retired by proving its replacement, then deleting](decisions/infrastructure/a-guard-is-retired-by-proving-its-replacement-then-deleting.md) | Rows 47 and 51 built the image and put all 86 functions on it. What was left was the machinery that made layers work — two JSON tables, a build script, an attach loop, and the one test standing between a missing layer and a production `ModuleNotFoundError`. Deleting a guard is the one change a review cannot sample, because it leaves nothing to read. | The join between two hand-maintained tables is replaced by an **import executed inside the artefact** — stronger because it runs the code rather than reasoning about a description of it — and the ordering (prove, then delete) is the whole safety argument. The 923 published versions are destroyed and proved gone **positively**, account-wide. Three fences the destroy earned: Terraform named only eight of the ten layers, so the enumeration could not be derived from it; **absence is zero versions, not an exception**, measured against the live API rather than inferred; and a sweep of the wrong names deletes nothing while looking identical to a completed one, so `apply` carries the count its own report found and refuses a non-positive one. Retires the layer tables, `deploy-lambda.sh`, `test_build_layer.py` and the deploy role's layer grants. `lambda-artifacts` is deliberately **not** retired and no spec owns it. |
| 53 | [CloudFront serves the portal again, because the VPC was the bill](decisions/infrastructure/cloudfront-serves-the-portal-again-because-the-vpc-was-the-bill.md) | The web tier was nearly the whole bill, and the client environment that required a container is shelved. | Exactly one front door exists: the existing switch picks CloudFront over S3 or the container, at one origin, so nothing naming the origin changes. **Superseded by row 55 (SPEC-255):** a Node app has no static fallback, so the CloudFront path is retired and the tier is always the front door; off means the portal is down. |
| 54 | [A module is one concept, and the root composes them flat](decisions/infrastructure/iac.md) | The per-feature modules had become eight copies of the control-plane machine, so a fix to the machine was eight edits that had to agree and a new plane started as a copy. | One `control-plane` building block, called once per plane from the root at the plane's existing address, with each plane's distinct configuration beside its call; its inputs are exactly what varies between planes, found by diffing resolved values. Its proof is the PR's plan showing only moves, plus the one deliberate change: shared spaces' state machine gets its own role. Supersedes row 30's module shape. |
| 55 | [The portal is a Next.js server, and the web tier is the only front door](decisions/infrastructure/cloudfront-serves-the-portal-again-because-the-vpc-was-the-bill.md) | The client environment requires Next.js on a server runtime, and a Node app has no static fallback, so a CloudFront copy of the portal cannot stand in while the tier is off. | One tier, on only while someone is working; with it off the portal is down, which is accepted. The server renders the runtime document, refuses to start without it, and its request proxy stamps each page with a nonce in `script-src`; a request with a body skips the proxy. The certificate renews only while the tier is on. Supersedes row 53, and the nginx half of row 33. |
| 56 | [The App Router owns the shell, and navigation goes through one seam](decisions/browser/react-router-in-the-catch-all-is-a-matcher-the-navigation-seam-feeds.md) | The areas move onto the App Router one at a time, so a signed-in page may be served by either router, and the App Router has no history state, navigation type or per-entry key. | The shell lives in the root layout behind a client-only boot, and the chrome decides by the address through the area records; every feature navigates through `lib/navigation/`, which feeds react-router inside the catch-all and decides by the committed address; while an upload is unfinished the shell asks before the document unloads. The layout half is `decisions/browser/layout-boundaries-reset-by-prop-never-by-key-a-signed-in-pages-sits.md`. |
| 57 | [The portal server holds the session, and only the provider or the clock ends it](decisions/identity-and-access/the-portal-server-holds-the-session-and-only-the-provider-or-the-clock-ends-it.md) | The client environment requires a Next.js server, and the arc moves the session onto it: the browser will hold only an opaque cookie. The server needs Cognito's token endpoint and the API's public domain, which have no VPC endpoint. | A DynamoDB session store outside the web tier's switch, a confidential Cognito client, `/auth/*` routes and an `/api/` pass-through; one NAT gateway on the switch, with AWS services still on endpoints. A refresh is a compare-and-set, expiry is checked on read, and a fault is never a sign-out. Nothing the browser calls uses it until SPEC-262. Supersedes row 34 in part. |
