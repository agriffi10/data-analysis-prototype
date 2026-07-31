# Transition Plan — Client Environment

**Status:** Single source of truth for the client transition. Living document; update it in place
rather than writing a competing one.
**Last updated:** 2026-07-31
**Supersedes and replaces:** `docs/client-migration-plan.md` and
`docs/spikes/idc-named-dataset-grants.md`, both deleted. Everything of value from the spike —
the reasoning chain behind trusted identity propagation, the two-connection identity model, the
credential-plane split, the reconciler design and the surviving spike gates — is absorbed into
§3 and §7 below.

---

## Contents

1. [What is changing](#1-what-is-changing)
2. [Settled decisions](#2-settled-decisions)
3. [Target architecture — the identity and authorization model](#3-target-architecture--the-identity-and-authorization-model)
4. [Deployment topology](#4-deployment-topology)
5. [The open fork — the permission-set path](#5-the-open-fork--the-permission-set-path)
6. [Risk register — the five hard problems](#6-risk-register--the-five-hard-problems)
7. [Phases](#7-phases)
8. [Open questions by gating phase](#8-open-questions-by-gating-phase)
9. [What this leaves behind](#9-what-this-leaves-behind)
10. [Sources](#10-sources)

---

## 1. What is changing

Today this portal is a **closed system**. It owns the identity store, it provisions each user's
resources, and it owns the Lake Formation configuration of its whole account. In the client
environment it becomes an **access portal over resources it does not own**. That single sentence
explains every change in this document.

| Concern | Today (this repo) | Client environment |
|---|---|---|
| Who authenticates | Cognito User Pool, self-service signup | IAM Identity Center, already the org's SSO |
| Who can sign in | Anyone who registers | Everyone in the organization |
| Who creates the user's S3 prefix | The browser, via `ensurePrefixMarker` | Already exists, provisioned by the other repo |
| Who creates the user's Glue database | `post_confirmation.py` | Already exists, provisioned by the other repo |
| Per-user IAM identity | One shared role plus a `username` principal tag | Bespoke per-user roles today, to be retired |
| Lake Formation grants | Issued by this app, keyed on the shared role | Issued by the client's reconciler, keyed on the bespoke role today, to be re-keyed on Identity Center principals |
| Shared workspaces | Created and managed by this app's control plane | Provisioned by client IaC today; **to be adopted by this app and removed from their IaC** |

---

## 2. Settled decisions

Treated as inputs. Do not re-litigate without new information.

1. **Cognito survives as a facade.** Identity Center becomes the upstream SAML/OIDC identity
   provider on the User Pool. The portal stays open to everyone in the organization, using the
   login screens they already trust.
2. **A token-exchange backend is required.** AWS documentation confirms this is *mandatory*, not
   conditional, and that it must hold session state rather than being a pure function (§3.5).
   The "no backend" constraint is formally broken; record that honestly in `architecture.md`.
3. **The per-user identifier is already catalog-safe and consistent.** The client's convention
   satisfies `^[a-z][a-z0-9_]{2,62}$` and is the same string for the S3 prefix and the Glue
   database name. The core invariant of SPEC-012 and SPEC-033 survives.
4. **Every organization user is provisioned.** A signed-in user without a workspace is a defect,
   not a supported state. Build a defensive empty state; do not design around it.
5. **Shared workspaces transfer ownership to this app.** Seed a manifest from the workspaces the
   client's IaC has already built, then this app's control plane owns their lifecycle and the
   client's IaC stops managing them.
6. **Analytics is feature-flagged off for Phase 1.** File browser, notifications and shared
   workspace browsing ship first.
7. **Deploy into the existing data account.** A separate account was evaluated and rejected;
   reasoning in §4. This makes §6.2's IaC ownership surgery mandatory rather than optional.
8. **Hosting is ECS Fargate, not CloudFront.** The SPA is served from a container. The task role
   supplies AWS credentials, which is what makes the token-exchange backend straightforward (§4.6).
9. **The token-exchange backend runs in the same container as the SPA.** Same origin, so no CORS
   for the backend, `httpOnly` session cookies work naturally, one artifact and one certificate
   (§4.7).

---

## 3. Target architecture — the identity and authorization model

This section absorbs the retired spike. It is the *why* behind the phases.

### 3.1 What the end state has to support

Beyond the file browser and personal workspaces, the client runs a class of **globally-managed
core datasets** that users are granted access to **by name and by level**:

- A user can hold dataset X at `sensitive` and dataset Y at `normal` simultaneously, and the
  grants are **independent** — `sensitive` on X does not imply `sensitive` on Y.
- `sensitive` versus `normal` is **column and row masking on the same dataset**.
- Analysts must be able to **JOIN across every dataset they are entitled to, in one query**.
- Access is defined as **config** — a desired-state matrix of `principal → {(dataset, level)}` —
  and projected into live permissions by a **reconciler**.

This is the model the client already runs. The job is to make it work from this app.

### 3.2 Why trusted identity propagation is the only mechanism

Four facts closed every other door. This chain is the load-bearing argument; understand it
before proposing an alternative.

1. **There is no trusted server in the query path.** The browser holds real AWS credentials and
   calls AWS directly, so the security boundary is the credential and service layer, never app
   code. A permission check written in the SPA is UX, not enforcement — a user with those
   credentials can bypass the UI with the AWS CLI.
2. **Lake Formation has no ABAC.** Grants target a principal ARN; you cannot condition a Lake
   Formation grant on a session or principal tag. The `username`-principal-tag trick that
   isolates personal databases and shared workspaces **does not translate** to per-user dataset
   grants.
3. **One shared IAM role cannot be the per-user grant target.** If the reconciler grants
   (dataset, level) to the single shared portal role, every user of that role inherits the
   **union** of everyone's grants. No isolation.
4. **A query-broker backend would have to re-implement the masking.** Routing queries through a
   Lambda that checks config is enforceable, but that Lambda holds the privileged credentials
   and must itself apply the column and row masking — hand-rolling exactly what Lake Formation
   data cell filters do for free.

The only mechanism that injects a **per-user identity** into a browser-held query session — so
Lake Formation can enforce per-user named grants with real masking, while carrying the user's
*whole* grant set in one session so cross-dataset joins work — is **trusted identity
propagation**.

**The payoff:** a single shared query role still works. The identity-enhanced session assumes one
shared carrier role, and Lake Formation differentiates by the propagated Identity Center
identity rather than by the role. No per-user roles, no role explosion, no credential swap per
dataset, and one statement can join across everything the user holds.

### 3.3 Two Cognito–Identity Center connections, in opposite directions

These are constantly conflated. They are separate connections doing different jobs, and both are
needed.

**Login federation — Identity Center is Cognito's upstream IdP.** Configure Identity Center as a
SAML 2.0 identity provider on the User Pool. Portal login becomes the user's existing corporate
SSO, and Cognito becomes a facade over the Identity Center user. This handles authentication,
and because both sides resolve to the same directory it makes the token-to-user mapping below
exact rather than a fuzzy cross-directory email match.

**Trusted Token Issuer — Identity Center trusts Cognito's tokens.** Register the Cognito User
Pool as a Trusted Token Issuer in Identity Center. Issuer URL is the pool's OIDC issuer,
`https://cognito-idp.{region}.amazonaws.com/{userPoolId}`; claim mapping determines which Cognito
claim identifies the user. Then create a customer-managed application with trusted identity
propagation enabled, whose audience is the Cognito app-client ID.

Cognito ID tokens already satisfy the format requirements — RS256-signed JWTs carrying `iss`,
`sub`, `aud` and `exp`. Identity Center supports up to ten trusted token issuers.

### 3.4 Two credential planes off one login

```
                         ┌─ BASE plane
                         │     Identity Pool → shared portal role (principal tag: username)
  Cognito login  ────────┤     used by: file browser, personal DB, shared workspaces
  (federated to IdC)     │     NOTE: §5 may replace this plane entirely — test before building
                         │
                         └─ CATALOG plane
                               CreateTokenWithIAM → AssumeRole(ProvidedContexts)
                               → shared carrier role carrying the IdC user identity
                               used by: core-dataset queries
```

The two planes stay separate. A query joining a personal database (base plane) against a core
dataset (catalog plane) in one statement almost certainly will not work — different enforcement
planes. Confirm this is acceptable; the expectation is yes, and they remain separate connections.

### 3.5 The catalog-plane token flow, and why the backend holds state

```
1. sso-oidc:CreateTokenWithIAM                    [SigV4-signed, from the backend]
       grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer
       assertion  = <Cognito ID token>
   → IdC validates against the TTI, maps the claim to an IdC user
   → returns the identity context (and a refresh token, if that grant is enabled)

2. sts:AssumeRole on the CATALOG carrier role
       ProvidedContexts = [{ ProviderArn     = arn:aws:iam::aws:contextProvider/IdentityCenter,
                             ContextAssertion = <identity context from step 1> }]
   → identity-enhanced credentials, returned to the browser

3. athena:StartQueryExecution on the IdC-enabled workgroup   [browser-direct]
   → Athena propagates the identity to Lake Formation
   → LF resolves THIS user's grants and applies the data cell filter for their level
```

**Steps 1 and 2 run in a backend. This is not optional.** AWS states that the application "must
have a backend server component that can securely store credentials. Browser-based applications,
such as single page applications (SPAs), and other public clients are not supported." (That quote
sits on the *account-access for customer-managed applications* page — the §5 Path A feature — but
the conclusion holds for this flow too: `CreateTokenWithIAM` requires SigV4 signing, and the
accompanying guidance is unconditional: keep Identity Center access and refresh tokens on the
backend, never expose them to client-side code.)

This does not make the app a backend app. The SPA is not the OAuth client — the Lambda is, and
the SPA is a front end to it. This is the backend-for-frontend pattern. What crosses to the
browser is AWS temporary credentials, exactly what the Identity Pool sends today, so the posture
is unchanged. What must never cross is the Identity Center token.

**The backend needs session state.** Identity Center refuses to exchange a token it has already
exchanged, using the JWT `jti` claim for replay detection, and Cognito ID tokens carry a `jti` —
**but only because token revocation is enabled on the app client.** Cognito adds `jti` /
`origin_jti` only when `enable_token_revocation` is on; the current IaC does not set it and relies
on the Terraform provider default of `true`. Pin it explicitly when the client pool is built,
because this replay behaviour is what the session-state design rests on.
Each Cognito ID token can therefore be exchanged **exactly once**, which rules out the stateless
design where the browser re-presents its token and the backend re-exchanges it. Hold the refresh
token server-side (encrypted, keyed by session, with a TTL) and use the `refresh_token` grant
thereafter.

Two further consequences worth designing for:

- This is a **new kind of component for this repo.** Every existing backend piece is asynchronous
  (SQS → Pipe → Step Functions → Lambda). This is a synchronous HTTP endpoint needing a Function
  URL or API Gateway, CORS, throttling and its own token verification. New surface, new failure
  mode.
- You take on an **availability-critical dependency**. Today, if credential minting breaks it is
  AWS's problem. Afterwards it is yours.

### 3.6 The carrier role

- **Trust policy:** allows `sts:AssumeRole` with the Identity Center context provider. It needs
  no per-user conditions — the identity travels in the context and Lake Formation, not the trust
  policy, enforces per-user.
- **Permissions:** Athena start/get/results on the Identity Center workgroup, Glue catalog read
  on the core-dataset databases, `lakeformation:GetDataAccess`, and read/write on the Athena
  results prefix. Deliberately **no direct S3 read** on dataset data — Lake Formation vends it.
- **One role for everyone.** All differentiation is in Lake Formation via the propagated identity.

Note that the identity-enhanced session is restricted by the
`AWSIAMIdentityCenterAllowListForIdentityContext` managed policy, which STS attaches
automatically and which denies everything not on its list — regardless of account, and regardless
of what the carrier role's own policies allow. **Answered (2026-07-31, policy v12):** Athena and
the Glue catalog read actions are on it; the **only S3 actions on it are the three S3 Access
Grants operations** (`s3:GetDataAccess`, `s3:GetAccessGrantsInstanceForPrefix`,
`s3:ListCallerAccessGrants`). Plain `GetObject` / `PutObject` / `ListObjectsV2` are denied, so
**the file browser can never run on this plane via direct S3 calls.** The two-plane split already
routes around this; it also motivates gate P3 in §5.4.

### 3.7 How Lake Formation enforces

- **Named grants keyed on the Identity Center principal.** `SELECT` is granted to the Identity
  Center user or group. At query time Athena presents the propagated identity and Lake Formation
  evaluates that principal's direct and inherited group grants.
- **Levels are data cell filters.** Each dataset defines two filters — `{dataset}__normal`
  (masks protected columns, optionally with a row predicate) and `{dataset}__sensitive` (all
  columns and rows). A user's level for a dataset is whichever filter they hold `SELECT` on, so
  independent levels across datasets fall out for free.
- **Default deny.** No grant means access denied, with no app gating required and none possible
  to bypass.

Two constraints on this model, both confirmed:

- **Cell-level security is not supported on resource links**, nested columns or views, and array
  and map types are not supported in filter expressions.
- **Identity Center users and groups cannot be Lake Formation data lake administrators.**

### 3.8 The reconciler

Config is the source of truth; the reconciler projects it into Lake Formation grants against
Identity Center principals. It runs **out of band** — the client's existing reconciler, or a
scheduled job — and never in the browser path.

```yaml
# access-config.yaml — git-tracked, reviewed like code
grants:
  - principal: { type: user,  ref: alice@corp.com }
    dataset: sales
    level: sensitive
  - principal: { type: group, ref: data-analysts }
    dataset: marketing
    level: normal
```

Plus a **dataset registry**, also config, mapping each logical dataset to its Glue database and
tables and to the column and row rules that define its `__normal` and `__sensitive` filters.

The reconcile loop is idempotent and safe to re-run:

1. **Resolve principals** — email or group name to Identity Center IDs, via
   `identitystore:GetUserId` / `ListGroups` / `ListGroupMemberships`. Cache.
2. **Ensure filters** — `lakeformation:CreateDataCellsFilter` from the registry's rules.
3. **Compute desired** — each config row becomes `SELECT` on the `{dataset}__{level}` filter for
   the resolved principal.
4. **Read current** — `lakeformation:ListPermissions`.
5. **Converge** — grant the difference, revoke the surplus.

**The trade:** this is eventually consistent. A config change is not live until the next
reconcile. Run it on config merge plus a periodic sweep. Accepting reconciler lag to avoid
hand-rolled column security is the right trade.

---

## 4. Deployment topology

**Decision: deploy into the existing data account.** A separate account was seriously evaluated
and rejected. The reasoning is below because it will be asked about.

### 4.1 The constraint that settles it

Lake Formation **cannot grant permissions to an Identity Center user or group on a Data Catalog
resource in another account.** The attempt returns `Cross-account grants are not supported for
the principal`. Grants to Identity Center principals may only be made in the account that owns
the catalog resource.

What *is* permitted is the mirror image: an IAM role in an external account may act as the
**carrier role**. So the session can be minted against a role anywhere, as long as the grants are
issued in the account owning the catalog.

**Therefore the Glue catalog must live with the data.** Any design that moves per-user or
per-workspace databases into a separate account forfeits §3 entirely, because those databases
could never be governed by Identity Center identity.

Once that is true, the split stops paying for itself. What would remain in a separate account is
the SPA, Cognito and the control-plane compute — all of which exist to touch data in the data
account. The boundary would sit in the middle of every data path rather than around a
self-contained subsystem: coordination cost without isolation.

The org-wide Identity Center rollout strengthens this. If other accounts are adopting trusted
identity propagation, the data account will have Lake Formation connected to Identity Center
regardless. Deploying there makes the portal **one more consumer of a pattern the organization
already runs** rather than a special case, which is a materially easier security review.

### 4.2 Recovering what the separate account would have bought

Its real advantage was reversibility — abandoning the work by closing an account. Recover most of
that by obtaining a **non-production account in the same organization, sharing the same Identity
Center organization instance**, and running every phase there before it touches production.

### 4.3 What this makes mandatory

Everything in §6.2 was avoidable in a fresh account. Here it is required work, and it comes first:

- Remove `aws_lakeformation_data_lake_settings` from the portal's IaC.
- Remove or convert `aws_lakeformation_resource` — the account already registered its buckets.
- Remove the portal's ownership of the user-space bucket policy
  (`infra/modules/data/policies/user-space-bucket-policy.json.tftpl`).
- Treat the Lake Formation Identity Center configuration as a third account-wide singleton (§4.4).

### 4.4 A third account-wide singleton

An account has **one** Lake Formation Identity Center configuration. It is not created per
consumer. It carries a list of AWS account IDs and organization or OU ARNs permitted to access
the data it governs, and it is maintained through
`UpdateLakeFormationIdentityCenterConfiguration`.

If the account already has one — or acquires one when another team adopts trusted identity
propagation — the portal must be **added to the existing configuration's allow-list**. Creating a
second is not possible; replacing the existing one would break every other consumer. Call
`DescribeLakeFormationIdentityCenterConfiguration` early and find out whether one exists and who
owns it.

### 4.5 A third counterparty

The customer-managed application cannot be created from the data account. An organization
instance of Identity Center lives in the AWS Organizations **management account**, and only
management-account administrators or a registered **delegated administrator** can create a
customer-managed application and enable AWS account access for it.

Phase 5 therefore depends on three parties: this repo, the provisioning repo's team, and whoever
administers the organization's Identity Center. Establish that third relationship in Phase 0 —
it is the one most likely to be discovered late.

### 4.6 Hosting moves from CloudFront to a container

The SPA will be served from Docker rather than CloudFront over an S3 origin. Producing the image
is trivial — a Vite build served by nginx — but CloudFront was doing more than serving files, and
each of those jobs now needs an owner. This is a **parallel workstream**, independent of the auth
phases, with one hard coupling noted below.

#### Configuration: build-time versus runtime

**Vite environment variables are build-time, not runtime.** Every `VITE_*` variable (documented in
`apps/portal/.env.example`) is baked into the bundle. With CloudFront that was fine — you built
per environment and deployed the artifact. With Docker, promoting **one image** across
environments is impossible with build-time variables, because the image would carry one
environment's configuration everywhere.

**The real scope, measured.** `import.meta.env` appears 50 times (on 47 lines) across 22 files
under `apps/portal/src`, but that overstates it considerably:

- Roughly 11 are **comments**, several of them explaining the call-time-read pattern below.
- Four are `import.meta.env.DEV`, a build-mode flag that stays exactly as it is.
- Several more are dev-only (`VITE_AWS_ACCESS_KEY_ID`, `VITE_AWS_SECRET_ACCESS_KEY`,
  `VITE_S3_DEV_UNAUTH`, `VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`) and are compiled out of
  client builds anyway.

That leaves roughly **30 genuine production config reads across ~18 files**.

**Most of the pattern already exists.** The repo already reads config at *call* time rather than
module load in many places, because module-level `import.meta.env` constants broke `vi.stubEnv` in
tests — see the explicit comments in `lib/userSpace.ts`, `features/data-quality/useDataQualityRuns.ts`,
`useDataQualityReport.ts`, and the `queueUrl:` reads inside `sharedSpaces.service.ts`,
`tableBuild.service.ts`, `tableShare.service.ts`, `notifications.service.ts` and
`dataQuality.service.ts`. Those are already accessor-shaped. The refactor extends an existing
convention rather than inventing one.

**The one genuinely fiddly piece is `lib/amplify.ts`.** It holds five reads at *module load*, and
`main.tsx` imports it first specifically so `Amplify.configure()` runs before anything else. Moving
that behind a fetched config means an async bootstrap: fetch config, configure Amplify, then
render. That is the only architecturally interesting part of the change; everything else is
mechanical.

#### Recommendation: one image, config served by the co-located backend

The decision is close, and building per environment is defensible. But two things tip it:

1. **The backend must read runtime configuration regardless.** The DynamoDB table name, the KMS
   key ARN, the Identity Center application ARN and the session cookie secret all arrive as ECS
   task-definition environment variables. There is no version of this where the server half uses
   build-time config.
2. **Given (1), per-environment builds leave you maintaining two config mechanisms inside one
   image** — build-time for the frontend, runtime for the backend. That is the real, non-obvious
   cost of the simpler-looking option.

Since the backend is co-located and already serving HTTP, having it serve `GET /config.json` from
those same task-definition variables is roughly twenty lines and unifies both halves onto one
mechanism. Promotion becomes a tag repoint, and so does rollback.

**You do not have to decide now.** Do the accessor refactor first and keep feeding the accessors
from `import.meta.env`. It is worth doing on its own merits — it is half-done already, and it is
what makes the tests stop fighting `vi.stubEnv`. With accessors in place, switching to
`/config.json` later is a one-file change. That decouples the decision from the migration
timeline entirely.

The rest of what CloudFront was doing, each of which needs explicit configuration now:

| Job | What it needs in the container |
|---|---|
| SPA routing fallback | CloudFront mapped 404 to `index.html` for client-side routes. nginx needs `try_files $uri $uri/ /index.html`, or every deep link 404s. |
| Cache headers and busting | Long immutable cache on hashed assets, `no-store` on `index.html`. Get this wrong and users silently run stale bundles after a deploy — intermittent and very hard to diagnose. |
| Compression | CloudFront gzipped and brotli'd automatically. nginx must be told to. |
| TLS and certificate | An ALB with ACM, or ingress TLS. **Cognito requires HTTPS callback URLs.** |
| Security headers | Any CloudFront response headers policy moves into the nginx config. |
| Health check | The load balancer or orchestrator needs an endpoint to probe. |

**Two coupling points that reach outside this workstream:**

- **The Cognito app client's callback and logout URLs must match the new origin exactly**, and
  `VITE_APP_URL` feeds the same value. So the final origin has to be known before Phase 1's auth
  configuration is finalised. This is the hosting workstream's one hard dependency on the auth
  phases.
- **S3 bucket CORS must allow the new origin.** The browser calls S3, Athena, Glue and SQS
  directly, so the bucket's CORS configuration needs the new origin added — and **the client owns
  that bucket**, making this a change request to the provisioning repo. Easy to miss until the
  first upload fails with an opaque browser error.

**The deploy pipeline changes shape.** Build, push to a registry, update the service, replacing
build, sync to S3, invalidate the distribution. New resource types mean the deploy role's
`.tftpl` policies expand as in-scope work, per the `CLAUDE.md` infra rule — read
`architecture.md` → *Deploy-role IAM — adding a new resource type* before starting.

**The availability model changes, and not in your favour.** CloudFront was a globally distributed
CDN with essentially no operational burden. A container behind a load balancer has instances,
scaling behaviour and a real failure mode. Combined with §3.5's availability-critical token
backend, the portal acquires genuine uptime work it did not have before. Budget for it.

### 4.7 The backend, and where its state lives

§3.5 established that a token-exchange backend is mandatory and must hold session state. The move
to Docker changes the best answer to *where it runs*, and makes it **simpler**, not harder.

**Settled: it co-locates with the SPA in the same container.** Serving the app and the token
endpoints from one image behind one origin buys no CORS configuration for the backend,
`httpOnly` session cookies that work naturally, one deploy artifact, one TLS certificate, and one
thing to keep running. It also makes the runtime-config story in §4.6 nearly free.

**The state design, either way:**

- The browser holds an **opaque session identifier** in an `httpOnly`, `Secure`, `SameSite`
  cookie. Nothing else.
- The **Identity Center refresh token** lives in DynamoDB, encrypted with a customer-managed KMS
  key, with a TTL matching the token's lifetime. It never traverses the browser, which is what
  AWS's guidance requires.
- **Keep the container itself stateless.** State belongs in DynamoDB, not in process memory —
  otherwise horizontal scaling breaks sessions and every restart logs everyone out.

**Credentials come from the ECS task role.** Running on Fargate means the container gets rotating
AWS credentials automatically, with no static secrets and no IAM Roles Anywhere trust anchor to
stand up. This is the single biggest reason Fargate is the right call here: the token-exchange
backend needs SigV4 credentials to call `CreateTokenWithIAM`, and the task role supplies them for
free. Scope that role narrowly — it is a privileged identity that mints sessions on behalf of
users.

**Three clocks now govern a session:** the Cognito session, the Identity Center refresh token, and
the browser session cookie. Decide deliberately what the user experiences when each expires,
rather than letting the shortest one produce a confusing failure.

**A new portal-owned state store.** The DynamoDB table joins the admin bucket as app-owned state.
Unlike the admin bucket, it holds credentials that grant access to client data, so it needs the
customer-managed key, tightly scoped access, and its own line in the client's security review.

#### A sharp interaction with the settled `error.stack` decision

This one is easy to miss and worth acting on before the backend is written.

`log-foundry`'s `end_event` attaches `traceback.format_exception` to every failed span, walking
the `__cause__` chain. That behaviour was examined and **accepted** on the reasoning that `logs/`
is admin-only and a stack is diagnostic metadata an admin needs — but that decision was reasoned
about for **file contents**, not for secrets.

A token-exchange service is a different class of caller. A failed `CreateTokenWithIAM` or a
failed refresh could put an Identity Center access or refresh token into a stack trace, and from
there into `logs/`. Tokens are already "always out" under the field rule, but the stack exemption
was not written with a token-handling service in mind, and it would carry them straight past it.

**Either exempt this service from stack attachment, or scrub its exception paths explicitly**, and
record the decision in `decisions.md` alongside the original. Do not assume the existing
exemption covers this — it does not.

---

## 5. The open fork — the permission-set path

**This must be tested before Phase 1 is built.** It is the single highest-value experiment in the
plan, and running it late means throwing Phase 1 work away.

The longer-term goal is one identity across every internal tool, with seamless movement between
several small services. That ambition points at a second credential path that AWS introduced in
June 2026, and it may be better than what Phase 1 currently specifies.

### 5.1 The two paths

| | Path A — `sso:account:access` | Path B — identity-enhanced session |
|---|---|---|
| Mechanism | Portal APIs `ListAccounts`, `ListAccountRoles`, `GetRoleCredentials` | `sts:AssumeRole` with `ProvidedContexts` |
| Yields | Credentials for the user's **permission-set** roles | A session on **one named carrier role** |
| Scoping | **None at the application level.** Grants access to *every* account and role the user holds; AWS states you cannot restrict it. | Exactly one role, chosen by the application |
| Carries identity context to Lake Formation? | **Unverified — this is gate P1** | Yes, by construction |

**Path B remains the safe default for the catalog plane** (§3), because it targets one role and
its identity propagation is not in question.

**Path A is not a competitor to Path B.** It is a candidate replacement for the **Cognito
Identity Pool** — the base plane that mints credentials for the file browser, the personal
database and shared workspaces.

Address the scoping objection by registering **two separate Identity Center applications**: a
narrow one for the catalog plane, and a separate one for any broader identity-brokering
capability. The scope is granted per application, so enabling it on one does not widen the other.

### 5.2 Why Path A is attractive

- **It deletes §6.1 entirely.** No `custom:portal_username` attribute means no writable-attribute
  privilege-escalation trap, currently the most dangerous detail in Phase 1. Session tags would
  come from Identity Center's *attributes for access control*, sourced from the directory and
  passed as session tags referenced by `${aws:PrincipalTag/...}` — the same ABAC model the repo
  already relies on, fed from a source the user cannot write to.
- **It removes the ten-slot ceiling.** Shared workspace membership would no longer live in
  Cognito custom attributes (`custom:shared_space_1..10`), which cannot be deleted or renamed
  once created. Confirm Identity Center's own attribute limits before relying on this.
- **It fixes audit legibility.** The permission-set role's session name is the user, rather than
  the opaque Cognito identity ID the enhanced flow produces today.
- **It shrinks Cognito to a login facade and trusted token issuer**, which directly serves the
  one-identity goal.
- **The backend is already mandatory** (§3.5), so this adds no new class of component.

### 5.3 What Path A costs

- **The backend moves into the file path.** Credential minting for *everything* would run through
  a component you own. If it is down, nobody browses files. A real availability regression.
- **Permission-set assignment becomes a prerequisite** for every portal user, managed in Identity
  Center. For an "everyone in the organization" portal that is one group assignment, but it is a
  hard dependency on the Identity Center administrators.
- **The un-scopable scope**, mitigated by a dedicated application but still a conversation.

### 5.4 The experiment

In a non-production account:

1. Enable identity-enhanced sessions in Identity Center; grant `sts:SetContext` in a test
   permission set's identity-based policy.
2. Enable `sso:account:access` on a test customer-managed application with the Cognito pool as its
   trusted token issuer.
3. From a Lambda, exchange a Cognito ID token and call `GetRoleCredentials`.
4. **Gate P1:** do the returned credentials carry Identity Center identity context? Check whether
   Lake Formation resolves a grant made to the Identity Center *user* rather than to the
   permission-set role ARN.
5. **Gate P2:** do Identity Center attributes for access control arrive as session tags, such that
   a policy conditioned on `${aws:PrincipalTag/username}` resolves?
6. **Gate P3:** do plain S3 operations (`GetObject`, `PutObject`, `ListObjectsV2`) succeed on the
   returned credentials? If the session turns out to be identity-enhanced, STS may attach
   `AWSIAMIdentityCenterAllowListForIdentityContext` (§3.6), whose only S3 actions are the three
   S3 Access Grants operations — which would deny the file browser's calls outright. A P1 *pass*
   could therefore imply a P3 *failure*.

**P2 and P3 are the ones that matter for Phase 1**, and they are independent of P1. If both pass,
the base plane moves off the Identity Pool and §6.1's trap disappears. If P1 also passes, both
paths collapse into one credential story — as close to the one-identity goal as this architecture
gets. If P3 fails, Path A cannot serve the base plane regardless of P2.

If a gate fails, nothing is lost: Phase 1 proceeds as written and Path B still carries Phase 5.

### 5.5 Gates inherited from the retired spike

Independent of P1 and P2, these belong to Phase 5 and are still worth proving:

| Gate | Check | If it fails |
|---|---|---|
| ~~G1~~ | ~~Can a public client perform `CreateTokenWithIAM`?~~ | **Settled — no.** Backend mandatory (§3.5). Do not run. |
| G2 | A user granted `__normal` sees the masked view | Filter or workgroup config is wrong |
| G3 | After granting `__sensitive`, the full view returns | The level model is in question |
| G4 | A user with no grant is denied | Default-deny or propagation broken — blocker |
| G5 | A JOIN across two granted datasets returns in one query | The single-session-spans-grants assumption is wrong |
| G6 | Session lifetime is workable and silent refresh exists | UX churn; needs a refresh strategy |

---

## 6. Risk register — the five hard problems

Everything else is mechanical. These are where the work and the risk live.

### 6.1 The federated username claim is not `cognito:username`

The highest-consequence detail in the migration, and easy to miss. **If §5's gates P2 and P3 both
pass, this problem disappears — which is why that experiment comes first.**

When a user signs in through a federated identity provider, Cognito does **not** set
`cognito:username` to the user's real username. It sets a provider-prefixed synthetic value of
the form `identitycenter_<subject>`. **Five** places read that claim and would silently start
operating on the wrong identifier:

- `infra/modules/auth/identity-pool.tf` line 85 maps the `username` principal tag to
  `cognito:username`. That tag scopes `${aws:PrincipalTag/username}` in every S3 and Glue policy
  in the repo.
- `lambdas/control-plane-common/cpcommon/auth.py` reads it in **three** places, not one:
  `verified_username` (line 95), `verified_username_ignoring_expiry` (line 108, the relaxed entry
  point the DLQ drain uses), and the **hard rejection of a token missing the claim** at lines
  55-56 — which sits inside `_verify` (line 26), *not* inside the `verify_id_token` wrapper at
  line 60. Change the private helper, not the wrapper — though note the wrapper's *docstring*
  does mention the claim, so a naive grep-and-replace will still touch it.
- `lambdas/notifications-writer/notifications_writer.py` line 105 reads the claim through its
  **own, independent verification path** — it is not routed through `cpcommon`, and it raises its
  own error when the claim is missing (line 107). This read is the **anti-spoofing control for
  the notifications inbox**; miss it and notification identity silently keys on the wrong value.
- `lambdas/shared-space-common/auth.py` line 34 reads the claim directly from the token dict
  returned by `cpauth.verify_id_token` — verification is delegated, the claim read is not.
- `apps/portal/src/features/auth/auth.service.ts` reads `getCurrentUser().username` and publishes
  it as `AuthUser.username`, which fans out to roughly twenty call sites building S3 prefixes and
  Glue database names.

**The fix has two halves, and the second is a security control.**

First, map the Identity Center attribute carrying the catalog-safe username into a dedicated
claim — a custom attribute (`custom:portal_username`) populated by SAML attribute mapping, or a
claim injected by a Pre-Token-Generation V2 trigger. Then change the principal-tag mapping, all
three `cpcommon/auth.py` readers, the two readers outside `cpcommon` (`notifications_writer.py`
and `shared-space-common/auth.py`), and the SPA's username source.

Second, **the app client must not have write permission on that attribute.** Cognito custom
attributes are writable by the user through `UpdateUserAttributes` if the app client grants write
access. If a user can write the attribute that becomes their principal tag, they can assume
another user's S3 prefix and Glue database.

This is **not** a one-line change. `infra/modules/auth/cognito.tf` lines 129-153 sets neither
`read_attributes` nor `write_attributes` on `aws_cognito_user_pool_client.spa`, and Cognito's
default in that case is that **everything is writable**. Locking one attribute means enumerating
the entire writable set explicitly.

A related trap: **Cognito custom attributes can never be renamed or deleted.** Getting the schema
right before the client User Pool is created matters, because fixing it later means a new pool,
which means every user's `sub` changes.

### 6.2 The Lake Formation IaC is account-wide and will overwrite the client's configuration

`infra/modules/analytics/lakeformation.tf` line 14 declares
`aws_lakeformation_data_lake_settings`. This resource is a **singleton for the entire AWS account
and region**. It is not additive. Applying this module in the client account would:

- Replace the client's data-lake administrator list with this repo's six ARNs.
- Empty the `IAM_ALLOWED_PRINCIPALS` default permissions for newly created databases and tables.

In an account running a populated data lake, that blast radius covers every consumer in the
environment. **This resource must be removed before any apply touches the client account.** The
portal's control-plane roles are added to the admin list by the client's own IaC.

The same reasoning applies with lower severity to `aws_lakeformation_resource.user_space` (line
67). If the client has already registered that bucket, re-registering it with a different role is
disruptive. Convert to a data source or drop it.

**Hybrid mode is load-bearing for Phase 1.** If the client registered their bucket in enforced
(non-hybrid) mode, direct S3 IAM access is blocked and the file browser cannot read anything with
plain `ListObjectsV2` and `GetObject` calls. Confirm this before writing any code — it determines
whether Phase 1 is a configuration exercise or a rewrite of the file browser's credential path.

### 6.3 Destructive code paths pointed at client-owned data

The app deletes things because it created them. Several of those paths now point at data it did
not create and must never destroy.

| Path | File | What it destroys | Guard |
|---|---|---|---|
| Shared-space `delete` verb | `lambdas/shared-space-delete/delete_space.py` | Calls the three teardown helpers below, in sequence | **Disable entirely until Phase 5.** During adoption this is the single highest-consequence code path in the repo. Re-enable only behind an allow-list of app-created workspaces. |
| Teardown helpers | `lambdas/shared-space-common/teardown.py` — `delete_shared_prefix` (line 18), `revoke_portal_role`, `drop_database` | `delete_shared_prefix` **deletes every S3 object** under `{name}/`. The other two revoke LF grants and drop the Glue database with all its tables. | Gate all **three**. Gating only the two grant/catalog functions leaves the object deletion live. |
| `forget` verb teardown branch | `lambdas/shared-space-forget/forget_space.py` line 48 | Full teardown when `owner == actor and status != "active"` — **any** non-active status, not only failed | Restrict to the cache-only branch during adoption. An adopted workspace mid-reconciliation could present as non-active. |
| Data-quality temp tables | `lambdas/data-quality-create-temp-tables/`, `.../drop-temp-tables/` | Creates and drops `dq_tmp_*` tables in the user's or shared workspace's Glue database | Confirm **both** prefixes — `dq_tmp_` *and* `dq_tmp_raw_` (`dqcommon/sql.py` lines 40-41) — cannot collide with a client naming convention. |
| Prefix marker write | `ensurePrefixMarker` (`features/file-browser/fileBrowser.service.ts` line 153), constants in `fileBrowser.constants.ts` (`PREFIX_MARKER_FILENAME` line 7, plus `prefixMarkerKey` and `PREFIX_MARKER_BODY`), sole app caller `routes/FilesPage.tsx` line 65 | Writes `{username}/DO_NOT_DELETE.txt` into a client-owned prefix | **Remove all of it** — the function, the three constants, the call site, the barrel re-export in `features/file-browser/index.ts` line 30, and the coverage in `fileBrowser.service.test.ts`, `FilesPage.test.tsx` and `FilesPage.a11y.test.tsx`. Deleting the function alone leaves a dangling call site. |
| Table Share object copy | `lambdas/table-share-copy-objects/table_share_copy_objects.py` | Writes into `{recipient}/shared_tables/{tableName}/` | Confirm no collision with existing client data under a recipient's prefix. |
| Table Share DDL | `lambdas/table-share-create-table/table_share_create_table.py` line 35 | Athena output to `s3://{destBucket}/{database}/athenaresults/{actor}/` — a different shape from the SPA's | Include in the Phase 4 workgroup audit. |

**Reserved prefixes are defined in three divergent places.** An audit checking only one will miss
data:

| Location | Contents |
|---|---|
| `lambdas/data-quality-common/dqcommon/config.py` line 27 (`RESERVED_PREFIXES`) | `user_settings`, `athenaresults`, `_data-quality-reports`, `shared_tables`, `_fc-work` |
| The file-converter arc's blocklist (SPEC-116) | Kept in sync by comment only — locate and audit it |
| `apps/portal/src/features/file-browser/protectedFolders.ts` line 24 (`PICKER_LOCKED_FOLDERS`) | `athenaresults`, `user_settings`, `_data-quality-reports` — missing `shared_tables` and `_fc-work` |

Each name now sits inside a prefix that may already contain client data using the same name.
Reconciling the three lists is worth doing on its own merits and gates the Phase 2 audit.

### 6.4 Shared workspace adoption without data loss

The client's workspaces are real, tag-provisioned and hold real data. Transferring ownership from
their IaC to this app's registry is the most delicate sequence in the plan.

The app's source of truth is `s3://{admin-bucket}/shared-spaces/{name}.json`, written under ETag
compare-and-swap by `lambdas/shared-space-common/registry.py`. Adoption means creating one
registry object per existing workspace, populated from current tags and membership, **without
touching the underlying S3 prefix, Glue database or data**.

The critical property: **removing a resource from OpenTofu management is not the same as
destroying it.** The client's repo must use `tofu state rm` (or a `removed` block) so resources
are forgotten by state, not deleted. A `tofu destroy` or plain resource deletion takes the data
with it. Write this into the runbook and confirm it on a plan output before any apply.

Adoption must also answer what membership physically *is* in the client environment. Today it is
a Cognito custom attribute (`custom:shared_space_1..10`) that becomes a principal tag unlocking an
ABAC statement. If the client grants access another way — an Identity Center group, a resource
tag, an entitlement record — the control plane's write path changes even though its verbs and UI
do not. **This is the largest remaining unknown.**

### 6.5 Retiring bespoke roles without an access gap

Users hold live Lake Formation grants against per-user IAM roles. The only safe sequence:

1. **Dual-grant.** The reconciler issues grants to the new principal — the shared portal role for
   the base plane, or the Identity Center user for the catalog plane — **in addition to** the
   existing bespoke-role grants. Nothing is revoked.
2. **Verify.** Confirm through the portal *and* through direct AWS CLI access that every user
   reaches everything they could before, using only the new principal. This wants a scripted
   comparison of effective permissions per user, not spot checks.
3. **Revoke.** Remove the bespoke-role grants in batches, with the reconciler able to re-grant.
4. **Delete the roles.** Last, after a quiet period with no access failures.

The window between steps 1 and 3 is where both models are live. Plan for weeks, not days, and
make sure nothing in either repo assumes exclusivity.

---

## 7. Phases

Each phase is independently shippable and independently reversible. Boundaries are chosen so that
a failure never leaves the client environment needing forward-only recovery.

### Phase 0 — Discovery, contract and experiments (no product code)

**Goal:** eliminate the unknowns in §8 and write down the interface between this repo and the
provisioning repo.

- **Run the §5.4 permission-set experiment.** Highest-value item in the phase: gates P2 and P3
  together decide whether Phase 1 needs the Cognito Identity Pool and the custom username
  attribute at all. Running it after Phase 1 is built means throwing that work away.
- Do **not** run the retired spike's G1 experiment. It is settled (§3.5).
- Inventory the client environment: bucket names, prefix convention, Glue database naming, Lake
  Formation registration mode, existing data-lake admins, workspace tags, the reconciler's
  location and cadence.
- Confirm the Lake Formation registration is hybrid. Go/no-go for Phase 2's shape.
- Call `DescribeLakeFormationIdentityCenterConfiguration` (§4.4).
- Identify the Identity Center administrators and their process for creating a customer-managed
  application (§4.5).
- Confirm the exact Identity Center attribute carrying the catalog-safe username.
- Enumerate existing shared workspaces and their membership — input to the adoption manifest.
- Write the coordination contract with the provisioning repo: what they add (portal role and
  control-plane roles to the bucket policy, Lake Formation admin list, data location grants), and
  what they stop doing (shared workspace provisioning, eventually per-user roles).

**Exit criteria:** every question in §8 has an answer; P1 and P2 findings are written down and
Phase 1's credential design is confirmed or revised in light of them.

### Phase 1 — Federated login

**Goal:** an organization user signs in with their existing SSO and lands in the portal with a
correct `username` principal tag. Nothing else works yet, and that is fine.

*Revise this phase if gates P2 and P3 both passed — the Identity Pool and custom attribute items
drop out.*

- Add Identity Center as a SAML identity provider on the User Pool (`infra/modules/auth/cognito.tf`).
- Add the `custom:portal_username` attribute (or the Pre-Token-Generation trigger), map it from
  the Identity Center attribute, and **remove write permission from the app client** (§6.1).
- Change the Identity Pool principal-tag mapping (`identity-pool.tf` line 85) to the new claim.
  Heed the existing comment on that resource: it churns on every apply if the provider name
  becomes unknown at plan time. Do not reintroduce a data source there.
- Change all three `cpcommon/auth.py` readers: `verified_username` (line 95),
  `verified_username_ignoring_expiry` (line 108), and the claim rejection inside `_verify`
  (lines 55-56) — the `verify_id_token` wrapper needs only its docstring updated.
- Change the two readers **outside** `cpcommon` (§6.1): `notifications_writer.py` line 105 (its
  own verification path — the notifications anti-spoof control) and
  `shared-space-common/auth.py` line 34.
- Change `auth.service.ts` to read the claim from the ID token rather than
  `getCurrentUser().username`.
- Change `supported_identity_providers` (`cognito.tf` line 142, currently `["COGNITO"]`) to
  Identity Center only, and pass the provider to `signInWithRedirect` so Managed Login skips the
  picker.
- Turn off self-signup Cognito-side, then delete the sign-up UI surface. This is **cosmetic**:
  `startSignUp` in `auth.service.ts` lines 64-66 is literally `return startSignIn();`, so there is
  no distinct code path. The surface is `startSignUp` in `auth.service.ts`, `signUp` in
  `AuthProvider.tsx` and `auth.types.ts`, the "Create account" / "Create your account" handlers in
  `routes/LandingPage.tsx` (lines 470, 509, 607), copy in `lib/returnPath.ts`, and the "automatic
  right after sign-up" empty state in `features/query/DatabaseNode.tsx`.
- Remove the `pre-signup` and `post-confirmation` triggers and delete their provisioning logic.
- Compile out the `VITE_S3_DEV_UNAUTH` path for client builds.
- Feature-flag off Query workspace, Table Builder, Table Share and Data Quality.
- **Coordinate with the hosting workstream (§4.6):** the app client's callback and logout URLs
  must match the container's final origin, so that origin has to be settled before this phase's
  auth configuration is finalised.

**Verification:** sign in as two real Identity Center users; confirm from CloudTrail that the
expected `username` principal tag is stamped for each, and that neither can obtain the other's tag
via `UpdateUserAttributes`.

**Rollback:** revert the identity provider and app client configuration. No client data touched.

### Phase 2 — Attach to existing S3 resources

**Goal:** the file browser and notifications work against the client's existing per-user prefixes.

- Strip `aws_lakeformation_data_lake_settings`, the bucket registration and the bucket-policy
  ownership from the portal's IaC (§4.3). **Do this first.**
- The client's repo adds the shared portal role and the notifications writer role to the bucket
  policy and, if the bucket is Lake Formation registered, to the data location grants. Bespoke
  per-user roles keep working untouched.
- Remove `ensurePrefixMarker` and every other write the portal makes to establish a prefix.
- Audit the reserved prefixes (§6.3) against real client data and resolve collisions.
- Point the admin bucket (registry, logs) at a **portal-owned** bucket — app-internal state, not
  client data.

**Verification:** a real user uploads, downloads, renames and deletes within their own prefix, and
is denied on another user's. Run the denial check with raw AWS CLI credentials pulled from the
session, not through the UI — the UI is not the boundary.

**Rollback:** the client removes the portal role from the bucket policy. Nothing they own changed.

### Phase 3 — Shared workspace adoption

**Goal:** the app's registry becomes the source of truth for workspaces the client's IaC built,
with zero data movement.

- Ship the delete-verb kill switch (§6.3) **before anything else in this phase**.
- Build the adoption tool: read the tag-provisioned workspaces, emit one
  `shared-spaces/{name}.json` registry object each, members resolved from current membership.
  Idempotent, re-runnable, read-only against everything except the registry.
- Decide and implement the membership write path (§6.4). The verbs and UI stay; the mechanism
  underneath changes.
- Drop `create` and `delete` from the user-facing verb set for adopted workspaces.
- The client's repo removes the workspaces from state with `tofu state rm`, verified against a
  plan output showing no destroys.

**Verification:** compare a full inventory of workspace prefixes, objects and Glue databases
before and after the state removal. They must be byte-identical.

**Rollback:** delete the registry objects; the client re-imports into state. Because nothing was
destroyed, this is genuinely reversible.

### Phase 4 — Analytics on the existing model

**Goal:** re-enable the Query workspace and table arcs against the client's existing Glue
databases, still on the shared role and principal tag.

- Re-enable Query workspace first (read-only), then Table Builder, Table Share and Data Quality
  one arc at a time.
- The client's reconciler grants the shared portal role and each control-plane execution role what
  they need — their `portal-managed` LF-Tag equivalent, or explicit named grants.
- Confirm the Athena workgroup and its enforced output location. The app writes results in
  **three shapes**: the SPA uses `s3://{bucket}/{username}/athenaresults/` (`query.service.ts`
  line 22), table-share uses `s3://{destBucket}/{database}/athenaresults/{actor}/`, and
  data-quality uses `{space_root}/athenaresults/data-quality/{requestId}`
  (`dq_start_profile_query.py` line 56). A workgroup enforcing an output location overrides all
  three, and any code reading results back from the path it requested will break.

**Verification:** per-arc, the original spec's acceptance criteria, against client data in a
non-production workspace.

### Phase 5 — Identity Center identities in Lake Formation

**Goal:** Lake Formation grants keyed on the Identity Center user, not on any IAM role. The design
is §3; the work items are here.

- Register the Cognito User Pool as a Trusted Token Issuer. Confirm the `aud` claim configuration
  and which claim maps uniquely to the Identity Center user (`email` is the usual choice).
- Create the customer-managed application — **requires the management account or a delegated
  administrator** (§4.5). Register a second, separate application if the broader
  identity-brokering capability is being pursued (§5.1).
- Build the token-exchange backend with its session store (§3.5).
- Create the catalog carrier role (§3.6).
- Create an Identity Center enabled Athena workgroup.
- Add a connection kind in `useConnections` running under the identity-enhanced session.
- The client's reconciler dual-grants Identity Center principals alongside the bespoke roles.
- Prove gates G2 through G6 (§5.5).

**Verification:** two users on the same carrier role see different data; a user with no grant is
denied. Confirm with raw credentials, not through the UI. Separately, confirm no Identity Center
token ever reaches the browser — inspect the network trace, not just the code.

### Phase 6 — Retire bespoke roles

**Goal:** the per-user IAM roles are deleted. Follow §6.5. Mostly waiting and verifying; do not
rush it to hit a date.

---

## 8. Open questions by gating phase

**Gating Phase 0 to 1:**

- Gates P1, P2 and P3 (§5.4). Everything about Phase 1's credential design depends on P2 and P3.
- Which Identity Center attribute carries the catalog-safe username, and is it stable for the life
  of a user? It keys the S3 prefix, so a change strands data.
- Does the client permit a Cognito User Pool at all, and is Managed Login v2 branding acceptable
  to their security review?
- Session lifetime: Cognito refresh tokens can outlive an Identity Center session revocation, so a
  deprovisioned employee could hold a valid portal session. What window is acceptable, and does
  sign-out need single logout?
- Who owns the provisioning repo, and what is the turnaround on a change request? Every phase from
  2 onward depends on them.

**Gating Phase 2:**

- Is the Lake Formation registration hybrid or enforced? Enforced blocks direct S3 access and
  reshapes the file browser.
- How many **user-space** buckets are there? `CLAUDE.md` line 137 says "no multi-bucket support
  (initial)", but that is a stale scope note rather than a live fence — the repo already runs
  several buckets. The real constraint is exactly one *user-space* bucket.
- Do the reserved prefixes collide with existing client data (§6.3)?
- Is Object Ownership set to *Bucket owner enforced*, and does bucket encryption use a customer
  managed KMS key? AWS managed keys do not support trusted identity propagation at all, which
  would block Phase 5.

**Gating Phase 3:**

- **What physically grants shared workspace membership in the client environment?** The strongest
  candidate for the biggest surprise in this migration.
- **How many workspaces can one user belong to?** The app hard-caps at ten
  (`custom:shared_space_1..10`, `var.max_shared_memberships`). A tag-provisioned environment could
  put a user in dozens. Cognito allows fifty custom attributes and **they cannot be deleted once
  created**. If the real number exceeds ten, redesign before the client pool is created, not after.
  Note that passing gates P2 and P3 (§5.4) remove this ceiling entirely.
- Are workspace names catalog-safe under the same regex? They become Glue database names.

**Gating the hosting workstream (§4.6, §4.7):**

- ~~Where does the container run?~~ **Settled — ECS Fargate**, task role supplies credentials.
- ~~Does the backend co-locate or stay a Lambda?~~ **Settled — co-located** in the same container.
- **One image promoted across environments, or a build per environment?** Still open, and
  deliberately deferred: do the accessor refactor first (§4.6) and the decision becomes a
  one-file change made later, on evidence rather than up front.
- Who owns TLS and DNS for the new origin, and what is the turnaround on getting a certificate?
  The origin must be settled before Phase 1's Cognito callback URLs are finalised.
- Who updates the client bucket's CORS configuration to allow the new origin (§4.6)? The client
  owns that bucket, so this is a change request to the provisioning repo.
- What is the session cookie's lifetime relative to the Cognito session and the Identity Center
  refresh token — the three clocks in §4.7?

**Gating Phase 5:**

- Does the account already have a Lake Formation Identity Center configuration, and who owns it
  (§4.4)?
- Who administers the organization's Identity Center, and what is their process (§4.5)?
- Is the refresh-token grant available on the customer-managed application? The session-state
  design (§3.5) depends on it.
- Can the portal's control-plane roles be Lake Formation data-lake admins, or will the client's
  security posture refuse? Table Builder, Table Share and Data Quality depend on admin status.
  Identity Center users and groups **cannot** be data lake administrators, so this stays an
  IAM-role question regardless.
- Cross-plane joins: a query joining a personal database against a core dataset almost certainly
  will not work (§3.4). Confirm this is acceptable.

---

## 9. What this leaves behind

Code that becomes dead and should be deleted rather than left to rot:

- `lambdas/pre-signup/` entirely.
- `lambdas/post-confirmation/` provisioning logic, `backfill.py`, and
  `scripts/backfill-portal-managed-tag.sh`.
- `startSignUp` / `signUp` across `auth.service.ts`, `AuthProvider.tsx`, `auth.types.ts`,
  `test/authFixtures.ts`, and their tests.
- Sign-up copy in `routes/LandingPage.tsx`, `lib/returnPath.ts` and
  `features/query/DatabaseNode.tsx`.
- `ensurePrefixMarker`, its constants in `fileBrowser.constants.ts`, its call site in
  `routes/FilesPage.tsx`, the barrel re-export in `features/file-browser/index.ts`, and its
  tests (§6.3 has the full list).
- The `create` verb in the shared-space control plane, once adoption completes.
- `aws_lakeformation_data_lake_settings` and the bucket registration in
  `infra/modules/analytics/lakeformation.tf`.
- If gates P2 and P3 pass: the Cognito Identity Pool, its principal-tag mapping, and the
  `custom:shared_space_*` attribute schema.
- The CloudFront distribution, its origin access configuration, the static-hosting bucket, any
  response headers policy, and the cache-invalidation step in CI (§4.6).

Documentation to rewrite when this lands: `docs/architecture.md` (Authentication Flow,
Authorization Model, and the "No backend" Known Constraint, which §3.5 breaks), `docs/decisions.md`
(auth, shared-space and Lake Formation material, plus a new entry for the federated claim — the
file is one flat heading with no `##` sections, so locating passages means reading it),
`docs/shared-spaces-architecture.md` (ownership model), and the in-app help content per the
SPEC-074 rule.

---

## 10. Sources

Lake Formation:
[IAM Identity Center integration limitations](https://docs.aws.amazon.com/lake-formation/latest/dg/identity-center-lf-notes.html) ·
[Data filtering limitations](https://docs.aws.amazon.com/lake-formation/latest/dg/data-filtering-notes.html) ·
[Registering an S3 location in another AWS account](https://docs.aws.amazon.com/lake-formation/latest/dg/register-cross-account.html) ·
[Prerequisites for Identity Center integration](https://docs.aws.amazon.com/lake-formation/latest/dg/prerequisites-identity-center.html) ·
[CreateLakeFormationIdentityCenterConfiguration](https://docs.aws.amazon.com/lake-formation/latest/APIReference/API_CreateLakeFormationIdentityCenterConfiguration.html)

IAM Identity Center:
[Enable AWS account access for customer managed applications](https://docs.aws.amazon.com/singlesignon/latest/userguide/enable-account-access-customer-managed-apps.html) ·
[Using applications with a trusted token issuer](https://docs.aws.amazon.com/singlesignon/latest/userguide/using-apps-with-trusted-token-issuer.html) ·
[Identity-enhanced IAM role sessions](https://docs.aws.amazon.com/singlesignon/latest/userguide/trustedidentitypropagation-identity-enhanced-iam-role-sessions.html) ·
[Enabling identity-enhanced console sessions](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-enhanced-sessions.html) ·
[Attributes for access control](https://docs.aws.amazon.com/singlesignon/latest/userguide/attributesforaccesscontrol.html) ·
[Delegated administration](https://docs.aws.amazon.com/singlesignon/latest/userguide/delegated-admin.html) ·
[Announcement, 30 June 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-iam-identity-center-account-access-customer-managed-apps/)

IAM and STS:
[Granting permissions to use identity-enhanced console sessions (`sts:SetContext`)](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_control-access_sts-setcontext.html) ·
[AWSIAMIdentityCenterAllowListForIdentityContext](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSIAMIdentityCenterAllowListForIdentityContext.html)
