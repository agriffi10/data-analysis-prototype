# Architecture: S3 File Portal

**Status:** Living doc of durable design decisions + constraints. Read the section you need —
not the whole file. Code/config is the source of truth for *how*; this doc captures *why*.

Pointers (don't duplicate these here):
- Spec index + status → `docs/specs/INDEX.md`
- Env vars → `apps/portal/.env.example`; GitHub Actions vars → `.github/workflows/README.md`
- IAM policies → the `.tftpl` templates under `infra/modules/*/policies/`
- Amplify / S3 client wiring → `apps/portal/src/lib/amplify.ts`, `src/lib/s3Client.ts`

---

## System Overview

A single-page app with **no backend server**. All AWS calls come from the browser using temporary
credentials for **one shared IAM role**, issued by a Cognito **Identity Pool** that federates the
User Pool token (Amplify v6 does the exchange; `fetchAuthSession()` returns the credentials — no STS
SDK). Per-user isolation is enforced by **IAM principal tags**: the Identity Pool's *attributes for
access control* map the username claim to a `username` principal tag **server-side** (unspoofable),
and the role's policy scopes access with `${aws:PrincipalTag/username}`. No per-user roles.

**Two buckets.** Bucket 1 (user-space) is self-contained — IAM enforces per-user prefix isolation by
the Cognito username. Bucket 2 (shared-space) is governed by a **user-managed access-key model that
is not yet designed or built** — do not implement anything for it (the old daily-IAM-pipeline design
is abandoned).

## Authentication Flow (summary)

Amplify checks the session → no session redirects to the Cognito Hosted UI → on login Cognito issues
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

### Bucket 2 — Shared Space
Status: access model **not yet specced or built** (user-managed access keys; likely needs a backend
service). Prefix structure stays the same concept; the enforcement mechanism is TBD. Connection
configs will be stored as JSON in the user's own Bucket-1 prefix
(`{username}/.config/connections.json`) — no separate datastore. A missing config file is an **empty
state, not an error**.

### Analytics (SPEC-032→036)
Per-user Glue-database isolation works exactly like S3 isolation — the **`username` IAM principal
tag** scopes the portal role's Glue ARN to `database/${aws:PrincipalTag/username}` (DB name =
username), **not** LF-Tags. Lake Formation grants the shared role broadly (per-DB grant issued by the
SPEC-033 post-confirmation Lambda); IAM is the per-user gate. The user-space bucket is registered in
LF **hybrid** mode so the file browser keeps direct-IAM S3 access while Athena reads via LF. Detail:
`docs/specs/INDEX.md` (analytics arc) + `docs/specs/SPEC-032`.

---

## Known Constraints

- **No backend / API proxy.** All AWS calls are from the browser. A use case needing elevated
  permissions beyond user-scoped IAM would require adding a Lambda/API layer — a significant change.
- **Move and rename are non-atomic.** S3 has neither; the app does `CopyObject` + `DeleteObject`
  (rename = move within the same parent). For a folder this is *recursive* and can *partially fail* —
  a per-key copy failure must never delete that source and never abort the rest (SPEC-018/019). No
  transactional rollback; the UI reports which keys succeeded/failed.
- **No overwrite protection from S3.** Versioning is off (SPEC-010), so writing an existing key
  destroys the prior object. The app guards in the UI with warn-and-confirm (HEAD-check → Overwrite
  or Rename) on upload and move/rename — there is no server-side safety net.
- **Listing pagination.** `ListObjectsV2` returns ≤1,000 keys/call. The browser paginates with
  `ContinuationToken` via TanStack `useInfiniteQuery` + a "Load more" control; never assume one page
  is the whole folder.
- **File size limits.** Uploads use managed `lib-storage` (auto-multipart above 5 MiB), configurable
  max (default 5 GiB, `VITE_MAX_UPLOAD_BYTES`); files above it are rejected client-side.
- **Lake Formation hybrid mode.** The user-space bucket is registered in *hybrid* access mode (SPEC-032).
  Do **not** flip it to enforced (non-hybrid) without first opting in every principal — it would break
  the file browser's direct-S3 access. Enabling LF enforcement (dropping the `IAMAllowedPrincipals`
  Super grant) is safe only alongside the portal-role Glue scoping + SPEC-033's per-DB grants.
- **Usernames are constrained at signup** (= S3 prefix = principal tag = Glue DB name). Pre-signup
  Lambda enforces the rule; SPEC-033 tightens it to catalog-safe `^[a-z][a-z0-9_]{2,62}$`. Pool is
  case-insensitive.
- **SPA client-side routing.** CloudFront must serve `index.html` for 403/404 or refresh/direct-URL
  navigation returns a raw S3 error.
- **`connections.json` is the user's own data.** Corrupting/deleting it loses their connections; the
  UI treats a missing file as empty, not an error.

## Infrastructure & Deployment

IaC is OpenTofu under `infra/`, organized as bounded-context modules (`app`, `base`, `auth`, `data`,
`analytics`); IAM policies are `.tftpl` templates under each module's `policies/`. The GitHub Actions
**deploy role** (`infra/modules/base`) applies all IaC via `deploy-infra.yml` — **any spec adding new
infra must expand the deploy-role policy** as in-scope work. The SPA deploys as static files to S3 +
CloudFront (OAC origin; custom error responses 403/404 → `/index.html` for SPA routing). Build-time
`VITE_*` vars are GitHub Actions variables (see `.github/workflows/README.md`); resource→spec mapping
and current values come from `tofu -chdir=infra output`.

> **CORS:** both browser-facing buckets need CORS or all SDK calls fail — the most common first-time
> setup issue. Managed in the bucket modules' `.tftpl`/`s3.tf`.

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
  refresh itself needs can never land. Break-glass: temporarily attach the missing read on `*` to the
  role out-of-band (`aws iam put-role-policy`), let the apply reconcile the real policy, then remove
  the temp policy.
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
  CloudWatch logs or by querying as an LF admin (only the deploy role + post-confirmation exec role
  are LF admins).

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
- Adding a Lambda = create `lambdas/<name>/`, add function infra in the owning module
  (placeholder + `ignore_changes`), add a `{ name: <name> }` row to the `deploy-lambdas.yml` matrix,
  and extend the deploy-role policy for any new actions. The first `deploy-infra.yml` apply must
  precede `deploy-lambdas.yml` (function + bucket must exist first).

## Deferred / Future Scope

File preview (PDF/image in-browser) · admin UI (user mgmt, access audit) · audit logging
(CloudTrail/S3 access logs) · staging environment + promotion pipeline · real-time access revocation
(needs a backend) · Bucket 2 shared-space access model.
