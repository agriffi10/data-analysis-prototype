# Transition Plan — Client Environment

**Status:** Single source of truth for the client transition. Living document; update it in place
rather than writing a competing one.
**Last updated:** 2026-08-03 (reconciled against the folded `architecture.md` — control-plane
records now live there; SPEC-140/141 header and caching facts updated in §4.6, §6.3, §9)
**Strategy revision (2026-08-01):** the client environment is itself moving to a **successor
account** this year. The portal will be **built fresh in that account as its first tenant**, and
the client's data will be **synced over** with a freeze-and-cutover — rather than the portal
deploying in place into the populated existing account (the 2026-07-31 decision, now superseded).
§4 carries the reasoning; §6 and §7 are reworked around it. The identity model in §3 and the open
fork in §5 are unchanged — they are account-agnostic, and the account move strengthens them:
Identity Center principals survive an account change, IAM role ARNs do not.
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
   - [3.1 What the end state has to support](#31-what-the-end-state-has-to-support)
   - [3.2 Why trusted identity propagation is the only mechanism](#32-why-trusted-identity-propagation-is-the-only-mechanism)
   - [3.3 Two Cognito–Identity Center connections, in opposite directions](#33-two-cognitoidentity-center-connections-in-opposite-directions)
   - [3.4 Two credential planes off one login](#34-two-credential-planes-off-one-login)
   - [3.5 The catalog-plane token flow, and why the backend holds state](#35-the-catalog-plane-token-flow-and-why-the-backend-holds-state)
   - [3.6 The carrier role](#36-the-carrier-role)
   - [3.7 How Lake Formation enforces](#37-how-lake-formation-enforces)
   - [3.8 The reconciler](#38-the-reconciler)
4. [Deployment topology](#4-deployment-topology)
   - [4.1 The constraint that still settles it](#41-the-constraint-that-still-settles-it)
   - [4.2 What first tenancy buys, and what it obliges](#42-what-first-tenancy-buys-and-what-it-obliges)
   - [4.3 Reversibility](#43-reversibility)
   - [4.4 The account-wide singletons are now portal-created](#44-the-account-wide-singletons-are-now-portal-created)
   - [4.5 A third counterparty — unchanged](#45-a-third-counterparty--unchanged)
   - [4.6 Hosting moves from CloudFront to a container](#46-hosting-moves-from-cloudfront-to-a-container)
   - [4.7 The backend, and where its state lives](#47-the-backend-and-where-its-state-lives)
5. [The open fork — the permission-set path](#5-the-open-fork--the-permission-set-path)
   - [5.1 The two paths](#51-the-two-paths)
   - [5.2 Why Path A is attractive](#52-why-path-a-is-attractive)
   - [5.3 What Path A costs](#53-what-path-a-costs)
   - [5.4 The experiment](#54-the-experiment)
   - [5.5 Gates inherited from the retired spike](#55-gates-inherited-from-the-retired-spike)
6. [Risk register — the five hard problems](#6-risk-register--the-five-hard-problems)
   - [6.1 The federated username claim is not `cognito:username`](#61-the-federated-username-claim-is-not-cognitousername)
   - [6.2 First-tenant singleton ownership (was: the Lake Formation IaC overwrite)](#62-first-tenant-singleton-ownership-was-the-lake-formation-iac-overwrite)
   - [6.3 Destructive code paths during the sync-and-seed window](#63-destructive-code-paths-during-the-sync-and-seed-window)
   - [6.4 Shared workspace seeding (was: adoption — nothing is adopted anymore)](#64-shared-workspace-seeding-was-adoption--nothing-is-adopted-anymore)
   - [6.5 The sync and the cutover (was: retiring bespoke roles — deleted; they are never created)](#65-the-sync-and-the-cutover-was-retiring-bespoke-roles--deleted-they-are-never-created)
7. [Phases](#7-phases)
   - [Phase 0 — Discovery, contract and experiments (no product code)](#phase-0--discovery-contract-and-experiments-no-product-code)
   - [Phase 1 — Stand up the portal in the successor account](#phase-1--stand-up-the-portal-in-the-successor-account)
   - [Phase 2 — First data sync: personal spaces](#phase-2--first-data-sync-personal-spaces)
   - [Phase 3 — Shared workspaces](#phase-3--shared-workspaces)
   - [Phase 4 — Analytics on the synced model](#phase-4--analytics-on-the-synced-model)
   - [Phase 5 — Identity Center identities in Lake Formation](#phase-5--identity-center-identities-in-lake-formation)
   - [Phase 6 — Cutover and decommission](#phase-6--cutover-and-decommission)
8. [Open questions by gating phase](#8-open-questions-by-gating-phase)
9. [What this leaves behind](#9-what-this-leaves-behind)
10. [Sources](#10-sources)

**Read map** — `CLAUDE.md` says "read before touching auth, provisioning or LF"; in practice:

- **Touching auth** (Cognito, tokens, sign-in, anything reading the username claim) → §3
  (especially §3.3–3.5) plus §6.1 — the federated claim is **not** `cognito:username`, the
  highest-consequence detail in the migration.
- **Touching provisioning / de-provisioning** (creating or deleting user/space resources, the
  account-wide LF singletons) → §4.4 and §6.2 (portal-created singletons and their ownership),
  §6.3 (destructive paths during the sync-and-seed window).
- **Touching Lake Formation re-keying** (grants moving to Identity Center principals) → §3.7 (how
  LF enforces) and Phase 5 (the work items); §3.8 for the reconciler that projects the grants.

---

## 1. What is changing

Today this portal is a **closed system**. It owns the identity store, it provisions each user's
resources, and it owns the Lake Formation configuration of its whole account. Two moves are now
happening at once: the client environment is transitioning to a **successor account**, and the
portal is **stood up in that account first**, before the data arrives. The portal therefore
remains the **resident, owning system of its account** — much closer to what this repo already is
than the "access portal over resources it does not own" posture the previous strategy required.
What changes instead is identity (Identity Center replaces self-service Cognito) and the arrival
of the client's data via a **one-time sync and cutover** from the old account.

| Concern | Today (this repo) | Successor account |
|---|---|---|
| Who authenticates | Cognito User Pool, self-service signup | IAM Identity Center, already the org's SSO |
| Who can sign in | Anyone who registers | Everyone in the organization |
| Who creates the user's S3 prefix | The browser, via `ensurePrefixMarker` | The sync (initial population), then the client's automated process for new users. **Sign-in provisions nothing** |
| Who creates the user's Glue database | `post_confirmation.py` | Sync initially, user automation thereafter (it already handles tagging); grants come from a separate permissions control plane (§8) |
| Per-user IAM identity | One shared role plus a `username` principal tag | Same model, carried over. **Bespoke per-user roles are never created** |
| Lake Formation grants | Issued by this app, keyed on the shared role | Same for personal and workspace scopes; core datasets keyed on Identity Center principals (§3), issued by a config-driven reconciler |
| Shared workspaces | Created and managed by this app's control plane | Same — created by this app in the successor account, contents synced from the old account's workspaces |
| The data itself | Created in place by users | **Synced from the old account**, re-encrypted under the successor account's KMS key, then cut over (§6.5) |

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
   database name. The core invariant of SPEC-012 and SPEC-033 survives the sync unchanged.
4. **Build in the successor account, as its first tenant.** Supersedes the 2026-07-31 decision to
   deploy into the existing data account (§4). Data, catalog and portal co-locate there, which is
   exactly what §4.1 requires.
5. **The old account's data arrives by sync and cutover, not adoption.** Objects are copied and
   re-encrypted; catalog and grants are rebuilt, never copied; the old account stays authoritative
   until a freeze-and-cutover and survives afterwards as the rollback (§6.5).
6. **Bespoke per-user roles are never recreated.** The previous strategy's retirement sequence
   (dual-grant, verify, revoke, delete) is deleted along with them.
7. **Sign-in no longer provisions.** The sync pre-creates every existing user's space and
   database; the client's automated process creates them for new users thereafter — and that
   automation **already handles tagging user databases**, while a **separate permissions control
   plane manages the grants**. The Cognito triggers' provisioning logic is **deleted, not
   reworked**, and `ensurePrefixMarker` goes with it. The contract items that remain: the
   automation's tag taxonomy must line up with the portal's TBAC tag-policy grants, and the
   permissions control plane must cover the grants `post_confirmation.py` issues today (§8). The
   defensive empty state stays, because a new user can sign in during the gap before the process
   has run for them.
8. **Existing shared workspaces arrive via the sync, with the manifest written manually**; from
   cutover the app **fully manages all shared spaces** — new ones through the `create` verb as
   today. The seeding parity check in §6.4 is what makes that handover safe.
9. **Analytics is feature-flagged off for Phase 1.** File browser, notifications and shared
   workspace browsing ship first.
10. **Hosting is ECS Fargate, not CloudFront.** The SPA is served from a container. The task role
    supplies AWS credentials, which is what makes the token-exchange backend straightforward (§4.6).
11. **The token-exchange backend runs in the same container as the SPA.** Same origin, so no CORS
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

**Decision: build in the successor account, as its first tenant.** This supersedes the
2026-07-31 decision to deploy into the existing data account. The constraint that drove that
decision has not moved — the new strategy satisfies it differently.

### 4.1 The constraint that still settles it

Lake Formation **cannot grant permissions to an Identity Center user or group on a Data Catalog
resource in another account.** The attempt returns `Cross-account grants are not supported for
the principal`. Grants to Identity Center principals may only be made in the account that owns
the catalog resource; an IAM role in an external account may act as the **carrier role**, but the
grants themselves are local.

**Therefore the portal, the Glue catalog and the data must all land in the same successor
account.** That is confirmed as the intent. If the successor environment ever splits into
multiple accounts, the portal follows the catalog — re-open this section before agreeing to any
such split.

The account move also quietly strengthens §3: Identity Center is an **organization-level**
service, so users and groups keep their identifiers across the move, and a grant matrix keyed on
Identity Center principals is **re-runnable against the new account unchanged**. Grants keyed on
IAM role ARNs would all have gone stale, because role ARNs embed the account ID — one more reason
the bespoke roles are not worth recreating.

### 4.2 What first tenancy buys, and what it obliges

Building where nothing yet exists deletes most of the coexistence work the previous strategy
required:

- The portal's IaC **keeps** `aws_lakeformation_data_lake_settings`, the bucket registration and
  the user-space bucket policy — there is no incumbent configuration to trample. The previous
  strategy's removal surgery is dead; §6.2 records its ghost in case sequencing changes.
- Shared workspaces are **created by this app's control plane from day one** — no ownership
  transfer, no `tofu state rm`, no adoption tooling. Their contents arrive by sync (§6.4).
- Bespoke per-user roles are **never created**, so the dual-grant/verify/revoke retirement
  sequence (the previous §6.5 and Phase 6) disappears entirely.

The obligation in exchange: **the portal becomes the incumbent.** Whoever lands in the account
later inherits the portal's account-wide Lake Formation settings, its Identity Center
configuration and its bucket topology. Every singleton the portal creates must be recorded in the
coordination contract as portal-owned, with a change process — otherwise a later tenant's IaC
does to the portal exactly what §6.2 once feared this repo would do to the client.

### 4.3 Reversibility

The old account **is** the rollback. It stays authoritative until cutover, and it survives
read-only through a quiet period afterwards; abandoning the strategy at any point before
decommission means pointing users back at it. Do not decommission early to hit a date.

A separate **non-production account in the same organization, sharing the same Identity Center
organization instance**, is still wanted for rehearsing every phase — including a full rehearsal
of the sync and cutover (§6.5) on a real prefix.

### 4.4 The account-wide singletons are now portal-created

An account has **one** Lake Formation Identity Center configuration, maintained through
`UpdateLakeFormationIdentityCenterConfiguration`. Under this strategy the portal most likely
**creates** it rather than joining an existing one. Still call
`DescribeLakeFormationIdentityCenterConfiguration` first — another team may land earlier than
planned — and record ownership in the contract either way: creating a second is not possible, and
replacing an existing one breaks every other consumer.

The same posture applies to `aws_lakeformation_data_lake_settings`: the portal now legitimately
owns the account's data-lake administrator list, and later tenants are added through this repo's
IaC, never by a competing apply.

### 4.5 A third counterparty — unchanged

The customer-managed application still cannot be created from the data account. An organization
instance of Identity Center lives in the AWS Organizations **management account**, and only
management-account administrators or a registered **delegated administrator** can create a
customer-managed application and enable AWS account access for it. Phase 5 therefore still
depends on that relationship — establish it in Phase 0; it is the one most likely to be
discovered late.

One new item joins it: **confirm the successor account joins the same organization** (and so the
same Identity Center organization instance). If it does not, every identity assumption in §3
needs re-examination before anything else in this document is acted on.

### 4.6 Hosting moves from CloudFront to a container

The SPA will be served from Docker rather than CloudFront over an S3 origin. Producing the image
is trivial — a Vite build served by nginx — but CloudFront was doing more than serving files, and
each of those jobs now needs an owner. (nginx here means the **web server**, actively maintained
by F5 — not Kubernetes' community *Ingress NGINX* controller, which retired March 2026 and is
easily confused with it. No Kubernetes is involved in this plan; confirmed 2026-08-03.) This is a **parallel workstream**, independent of the auth
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
| Cache headers and busting | Long immutable cache on hashed assets, revalidate-always (`no-cache`) on `index.html` — the exact per-class scheme is **SPEC-141**, and nginx must reproduce it (SPEC-141 also records *why*: heuristic browser caching plus `--delete` produces a white screen, not stale content). Get this wrong and users silently run stale bundles after a deploy — intermittent and very hard to diagnose. |
| Compression | CloudFront gzipped and brotli'd automatically. nginx must be told to. |
| TLS and certificate | An ALB with ACM, or ingress TLS. **Cognito requires HTTPS callback URLs.** |
| Security headers | The **shipped** response-headers policy (SPEC-140: enforcing CSP + HSTS + framing/nosniff/referrer/Permissions-Policy/COOP/CORP, `Server` stripped — `architecture.md` → *Infrastructure & Deployment*) moves into the nginx config. The CSP's `connect-src` is derived from Terraform variables; the nginx copy needs the same derivation, not a frozen string. HSTS currently carries `preload` (inert on `*.cloudfront.net`, never submitted) — re-decide `preload` deliberately for the new domain before emitting it there. |
| Health check | The load balancer or orchestrator needs an endpoint to probe. |

**Two coupling points that reach outside this workstream:**

- **The Cognito app client's callback and logout URLs must match the new origin exactly**, and
  `VITE_APP_URL` feeds the same value. So the final origin has to be known before Phase 1's auth
  configuration is finalised. This is the hosting workstream's one hard dependency on the auth
  phases.
- **S3 bucket CORS must allow the new origin.** The browser calls S3, Athena, Glue and SQS
  directly, so the bucket's CORS configuration needs the new origin added. Under the successor
  strategy the portal owns the bucket, so this is this repo's own IaC rather than a change
  request — but it is still easy to miss until the first upload fails with an opaque browser
  error.

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

### 6.2 First-tenant singleton ownership (was: the Lake Formation IaC overwrite)

Under the previous strategy this section required stripping `aws_lakeformation_data_lake_settings`
(`infra/modules/analytics/lakeformation.tf` line 14) and the bucket registration (line 67) before
any apply, because the client's account already owned them. In a fresh account the danger
**reverses**: the portal now creates those singletons, and later tenants threaten *it*.
`aws_lakeformation_data_lake_settings` is still a singleton for the entire account and region,
and still not additive — a later team applying their own copy replaces the portal's six-ARN admin
list exactly as this repo once threatened to replace the client's.

Guards: the coordination contract names the portal as owner of the data-lake settings, the Lake
Formation Identity Center configuration (§4.4) and the user-space bucket policy, with all later
additions made through this repo's IaC.

**Hybrid mode is now a choice, not a discovery.** The portal registers the bucket itself and
must choose **hybrid** mode, so the file browser's direct `ListObjectsV2` / `GetObject` path
keeps working. The old risk — inheriting an enforced-mode registration that blocks direct S3 —
returns only if sequencing changes.

**If the portal turns out not to be first into the account**, the previous strategy's surgery
reactivates in full: strip the data-lake settings, convert the bucket registration to a data
source, surrender the bucket policy, and join the incumbent's Identity Center configuration
allow-list. Keep this paragraph until the account's tenancy order is contractual.

### 6.3 Destructive code paths during the sync-and-seed window

The app deletes things because it created them — and in the successor account that becomes true
again, which retires most of the previous strategy's permanent guards. What remains is a
**window**: between the first sync and a verified cutover, prefixes and workspaces hold the only
in-account copy of the synced client data. A destructive path firing mid-seed destroys work that
must be re-synced; the same path firing after cutover destroys the authoritative copy while the
old account is already read-only. The guards below are scoped to that window rather than
permanent.

| Path | File | What it destroys | Guard |
|---|---|---|---|
| Shared-space `delete` verb | `lambdas/shared-space-delete/delete_space.py` | Calls the three teardown helpers below, in sequence | **Disable through the seeding window (Phase 3)**; re-enable at cutover, once the per-workspace inventory and the §6.4 parity check verify. From cutover the app fully manages all shared spaces, so delete is legitimate again. |
| Teardown helpers | `lambdas/shared-space-common/teardown.py` — `delete_shared_prefix` (line 18), `revoke_portal_role`, `drop_database` | `delete_shared_prefix` **deletes every S3 object** under `{name}/`. The other two revoke LF grants and drop the Glue database with all its tables. | Gate all **three** during the window. Gating only the two grant/catalog functions leaves the object deletion live. |
| `forget` verb teardown branch | `lambdas/shared-space-forget/forget_space.py` line 48 | Full teardown when `owner == actor and status != "active"` — **any** non-active status, not only failed | Restrict to the cache-only branch through the seeding window. A seeded workspace mid-sync could present as non-active. |
| Data-quality temp tables | `lambdas/data-quality-create-temp-tables/`, `.../drop-temp-tables/` | Creates and drops `dq_tmp_*` tables in the user's or shared workspace's Glue database | Confirm **both** prefixes — `dq_tmp_` *and* `dq_tmp_raw_` (`dqcommon/sql.py` lines 40-41) — cannot collide with a client naming convention. |
| Prefix marker write | `ensurePrefixMarker` (`features/file-browser/fileBrowser.service.ts` line 153), constants in `fileBrowser.constants.ts` (`PREFIX_MARKER_FILENAME` line 7, plus `prefixMarkerKey` and `PREFIX_MARKER_BODY`), sole app caller `routes/FilesPage.tsx` line 65 | Writes `{username}/DO_NOT_DELETE.txt` into the user's prefix | **Remove all of it** (settled — sign-in provisions nothing, §2 item 7): the function, the three constants, the call site, the barrel re-export in `features/file-browser/index.ts` line 30, and the coverage in `fileBrowser.service.test.ts`, `FilesPage.test.tsx` and `FilesPage.a11y.test.tsx`. Deleting the function alone leaves a dangling call site. |
| Table Share object copy | `lambdas/table-share-copy-objects/table_share_copy_objects.py` | Writes into `{recipient}/shared_tables/{tableName}/` | Confirm no collision with existing client data under a recipient's prefix. |
| Table Share DDL | `lambdas/table-share-create-table/table_share_create_table.py` line 35 | Athena output to `s3://{destBucket}/{database}/athenaresults/{actor}/` — a different shape from the SPA's | Include in the Phase 4 workgroup audit. |

**Reserved prefixes are defined in three divergent places.** An audit checking only one will miss
data:

| Location | Contents |
|---|---|
| `lambdas/data-quality-common/dqcommon/config.py` line 27 (`RESERVED_PREFIXES`) | `user_settings`, `athenaresults`, `_data-quality-reports`, `shared_tables`, `_fc-work` |
| `apps/portal/src/features/file-browser/protectedFolders.ts` line 21 (`HIDDEN_BROWSER_FOLDERS`) | `user_settings`, `_data-quality-reports` — the SPA's listing filter; diverges from both other lists |
| `apps/portal/src/features/file-browser/protectedFolders.ts` line 24 (`PICKER_LOCKED_FOLDERS`) | `athenaresults`, `user_settings`, `_data-quality-reports` — missing `shared_tables` and `_fc-work` |

(A fourth list this table previously named — the SPEC-116 file-converter blocklist — **never
existed in code**; that arc was cancelled 2026-08-03 with nothing built, and its architecture
record was removed.)

Each name may collide with data arriving from the old account via the sync. Reconciling the
three lists is worth doing on its own merits and gates the Phase 2 audit.

### 6.4 Shared workspace seeding (was: adoption — nothing is adopted anymore)

The registry (`s3://{admin-bucket}/shared-spaces/{name}.json`, written under ETag
compare-and-swap by `lambdas/shared-space-common/registry.py`) is the source of truth, and from
**cutover onwards the app fully manages all shared spaces** — `create` and the other verbs
user-facing exactly as today. The already-existing spaces are seeded differently: **the sync
creates them, and the manifest is written manually** — one registry object per old-account
workspace, authored by hand rather than by the `create` verb.

The risk that replaces adoption's: **a seeded workspace must be indistinguishable from one the
control plane created**, or the verbs misbehave on it after cutover. The `create` verb normally
produces four things at once — the registry entry, the workspace Glue database with its Lake
Formation grants, the members' attribute slots, and the roster caches
(`cache.write_roster_to_all`). Manual seeding must produce all four, not just the registry
object. Before any verb is enabled on a seeded space, validate each one: the registry object
parses against the schema the verbs expect, the Glue database and grants exist, every member's
attribute slot and roster cache is populated, and a read-only roster fetch succeeds. The
`tofu state rm` choreography, the ownership-transfer inventory and the "what physically grants
membership" unknown are gone; this **parity check** is what stands in their place.

What does **not** disappear is the ceiling. Membership remains the Cognito custom attributes
(`custom:shared_space_1..10`), and the ten-slot cap carries over. Enumerate old-account workspace
membership in Phase 0: **if any user belongs to more than ten workspaces, redesign before the
successor User Pool is created** — custom attributes can never be deleted or renamed, and fixing
the schema later means a new pool and new `sub` values for every user. Passing gates P2 and P3
(§5.4) replaces the attributes with Identity Center-sourced session tags and removes the ceiling
entirely — one more reason the experiment runs first.

### 6.5 The sync and the cutover (was: retiring bespoke roles — deleted; they are never created)

The data sync is three layers, and only the first one copies:

1. **Objects.** S3 sync from the old account's buckets into the portal-created buckets,
   re-encrypted under the successor account's **customer-managed KMS key** — required by Phase 5
   regardless, since AWS managed keys do not support trusted identity propagation. DataSync or
   S3 batch operations; per-prefix, resumable, verified by inventory comparison.
2. **Catalog.** Glue databases and tables are rebuilt, never copied: per-user databases by the
   sync initially and the client's automated process thereafter (§2 item 7), workspace databases
   through seeding (§6.4), core-dataset tables from the dataset registry config (§3.8) pointed
   at the new account.
3. **Grants.** Re-issued, never copied. Core-dataset grants are a config re-run against
   unchanged Identity Center identities (§4.1); personal-database grants come from the client's
   separate permissions control plane (§2 item 7); workspace grants arise in §6.4's seeding.
   Anything still keyed on an IAM role ARN would have been stale anyway — the ARNs embed the old
   account ID.

The sequence: repeated delta syncs while the portal is built and verified → a **freeze window**
on the old account (writes stop) → final delta → verification inventory (object counts and
checksums per prefix, catalog diff, per-user spot queries) → users flip to the new origin → old
account read-only through a quiet period → decommission.

Plan the freeze honestly: it is write downtime, and its length is set by the size of the final
delta — so keep deltas small by syncing often. The stretch between first sync and cutover is
where **drift** lives: every day of it, users write to the old account and the copy ages.
Nothing on either side may assume the other is frozen until the freeze is actually called.
Rehearse the entire sequence in the non-production account before doing it for real (§4.3).

---

## 7. Phases

Each phase is independently shippable and independently reversible. Until Phase 6's cutover the
old account remains authoritative and untouched, so a failure anywhere leaves users exactly where
they already were.

### Phase 0 — Discovery, contract and experiments (no product code)

**Goal:** eliminate the unknowns in §8 and write down the successor-account contract.

- **Run the §5.4 permission-set experiment.** Unchanged and still first: gates P2 and P3
  together decide whether Phase 1 needs the Cognito Identity Pool and the custom username
  attribute at all, and §6.4's membership ceiling turns on the same result.
- Do **not** run the retired spike's G1 experiment. It is settled (§3.5).
- Confirm the successor account: does it exist yet, is it in the **same organization** (same
  Identity Center organization instance — load-bearing, §4.5), who else is scheduled to land in
  it and when, and is the portal's first-tenant ownership of the account singletons (§4.4)
  agreed and written into the contract.
- Call `DescribeLakeFormationIdentityCenterConfiguration` in the successor account (§4.4).
- Identify the Identity Center administrators and their process for creating a customer-managed
  application (§4.5).
- Confirm the exact Identity Center attribute carrying the catalog-safe username.
- Inventory the old account: buckets and data volumes, prefix conventions, per-user Glue
  databases, shared workspaces and per-user membership counts (§6.4's ceiling check), core
  datasets and the existing grant matrix.
- **Write the provisioning contract** (settled mechanism, §2 item 7): extract the per-user
  checklist from `post_confirmation.py` and map each item to its new owner — database creation
  and tagging to the user automation (which already tags), grants to the separate permissions
  control plane. Confirm the automation's tag key and values against what the portal's TBAC
  tag-policy grants expect (`portal-managed` today — align one side or the other), and agree the
  acceptable latency between a user existing in Identity Center and being provisioned.
- Choose the sync tooling and rehearse one real prefix end-to-end in non-production, including
  re-encryption under a customer-managed key (§6.5).

**Exit criteria:** every question in §8 has an answer; P1–P3 findings are written down and
Phase 1's credential design is confirmed or revised in light of them.

### Phase 1 — Stand up the portal in the successor account

**Goal:** the portal runs in the successor account with federated login: an organization user
signs in with their existing SSO and lands in an empty portal with a correct `username` principal
tag. No data yet, and that is fine.

*Revise this phase if gates P2 and P3 both passed — the Identity Pool and custom attribute items
drop out.*

- Apply the portal's IaC into the successor account — **including** the Lake Formation settings
  and bucket registration it now legitimately owns (§4.2). Register the user-space bucket in
  **hybrid** mode (§6.2).
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
- Remove the `pre-signup` and `post-confirmation` triggers and delete their provisioning logic —
  sign-in provisions nothing (settled, §2 item 7).
- Remove `ensurePrefixMarker` and every other write the portal makes to establish a prefix (full
  removal list in §6.3).
- Compile out the `VITE_S3_DEV_UNAUTH` path for client builds.
- Feature-flag off Query workspace, Table Builder, Table Share and Data Quality.
- **Coordinate with the hosting workstream (§4.6):** the app client's callback and logout URLs
  must match the container's final origin, so that origin has to be settled before this phase's
  auth configuration is finalised.

**Verification:** sign in as two real Identity Center users; confirm from CloudTrail that the
expected `username` principal tag is stamped for each, and that neither can obtain the other's tag
via `UpdateUserAttributes`.

**Rollback:** tear the stack down; the account was empty. Nothing in the old account changed.

### Phase 2 — First data sync: personal spaces

**Goal:** the file browser and notifications work in the successor account against synced copies
of each user's data.

- Run the object sync (§6.5 layer 1) for personal prefixes, re-encrypting under the successor
  account's customer-managed key.
- Audit the reserved prefixes (§6.3) against the synced data **before** users arrive, and
  resolve collisions while the copy is still disposable.
- Verify the provisioning handoff: the sync's pre-created spaces pass the `post_confirmation.py`
  checklist (database and tag from the user automation, grants from the permissions control
  plane), and one user provisioned end-to-end by the ongoing machinery — or a rehearsal of it —
  arrives identically.
- Point the admin bucket (registry, logs) at the portal-owned bucket as usual; it is
  app-internal state and takes no part in the sync.

**Verification:** a real user uploads, downloads, renames and deletes within their own prefix,
and is denied on another user's — run the denial check with raw AWS CLI credentials pulled from
the session, not through the UI, because the UI is not the boundary. Inventory comparison (object
counts and checksums per prefix) confirms the sync.

**Rollback:** delete the synced copy and re-run. The old account remains authoritative.

### Phase 3 — Shared workspaces

**Goal:** every old-account workspace exists in the successor account — created by the sync,
manifest written manually — and passes the §6.4 parity check, so the app can fully manage all
shared spaces from cutover.

- Keep the destructive verbs disabled on seeded workspaces through this phase (§6.3); the app
  takes over full management at cutover, after the parity check passes.
- Seed per §6.4: sync each workspace's objects, author its registry object from the manifest,
  create its Glue database and grants, and populate the members' attribute slots and roster
  caches from the Phase 0 membership inventory (or Identity Center groups, if gates P2 and P3
  passed and the mechanism moved). Idempotent and re-runnable.
- Run the parity check (§6.4) against every seeded workspace before enabling any verb on it.

**Verification:** per-workspace inventory comparison, old account versus new; members see their
workspaces, non-members are denied — raw-credential check again; parity check green on every
seeded space.

**Rollback:** delete the seeded registry objects and synced data and re-run. The old account is
untouched.

### Phase 4 — Analytics on the synced model

**Goal:** re-enable the Query workspace and table arcs against the successor account's Glue
databases, still on the shared role and principal tag.

- Re-enable Query workspace first (read-only), then Table Builder, Table Share and Data Quality
  one arc at a time — each against its original spec's acceptance criteria.
- The grant plumbing is this repo's existing model — the portal's IaC owns the LF admin list and
  the `portal-managed` LF-Tag machinery (§4.2) — rather than a change request to another team.
- Confirm the Athena workgroup and its enforced output location. The app writes results in
  **three shapes**: the SPA uses `s3://{bucket}/{username}/athenaresults/` (`query.service.ts`
  line 22), table-share uses `s3://{destBucket}/{database}/athenaresults/{actor}/`, and
  data-quality uses `{space_root}/athenaresults/data-quality/{requestId}`
  (`dq_start_profile_query.py` line 56). A workgroup enforcing an output location overrides all
  three, and any code reading results back from the path it requested will break.

**Verification:** per-arc, the original spec's acceptance criteria, against synced data in a
non-production workspace.

### Phase 5 — Identity Center identities in Lake Formation

**Goal:** core datasets governed by Lake Formation grants keyed on the Identity Center user, not
on any IAM role. The design is §3; the work items are here.

- Register the Cognito User Pool as a Trusted Token Issuer. Confirm the `aud` claim configuration
  and which claim maps uniquely to the Identity Center user (`email` is the usual choice).
- Create the customer-managed application — **requires the management account or a delegated
  administrator** (§4.5). Register a second, separate application if the broader
  identity-brokering capability is being pursued (§5.1).
- Build the token-exchange backend with its session store (§3.5).
- Create the catalog carrier role (§3.6).
- Create the Lake Formation Identity Center configuration (§4.4) — under this strategy most
  likely a create, not a join.
- Create an Identity Center enabled Athena workgroup.
- Add a connection kind in `useConnections` running under the identity-enhanced session.
- Stand up the core datasets: dataset registry config, data cell filters, and the reconciler
  (§3.8) pointed at the successor account — a re-run of the existing grant matrix against
  unchanged Identity Center principals (§4.1). No dual-granting: there are no bespoke roles to
  grant alongside.
- Prove gates G2 through G6 (§5.5).

**Verification:** two users on the same carrier role see different data; a user with no grant is
denied. Confirm with raw credentials, not through the UI. Separately, confirm no Identity Center
token ever reaches the browser — inspect the network trace, not just the code.

### Phase 6 — Cutover and decommission

**Goal:** the successor account becomes authoritative; the old account is retired. Follow §6.5.
Mostly verification and patience — do not rush the freeze or the decommission to hit a date.

- Delta syncs until the final delta is small; call the freeze; run the final delta; run the full
  verification inventory.
- Flip users to the new origin; the old account goes read-only.
- Hold through a quiet period with no access failures and no missing-data reports; then
  decommission the old account.

**Rollback (before decommission only):** point users back at the old account and lift the
freeze. This is the whole reason the old account survives the quiet period.

---

## 8. Open questions by gating phase

**Gating Phase 0 to 1:**

- Gates P1, P2 and P3 (§5.4). Everything about Phase 1's credential design depends on P2 and P3.
- Does the successor account exist yet, and is it in the **same organization** — the same
  Identity Center organization instance? §3 and §4.1 assume yes (§4.5).
- Who else lands in the successor account, when, and is the portal's first-tenant ownership of
  the account singletons (§4.4) contractual?
- Which Identity Center attribute carries the catalog-safe username, and is it stable for the life
  of a user? It keys the S3 prefix, so a change strands data.
- **The tag alignment** (mechanism settled, §2 item 7): the user automation already tags
  databases — does its tag taxonomy match what the portal's TBAC tag-policy grants expect
  (`portal-managed` today), or do the portal's `.tftpl` grants re-key to the client's existing
  tag? Without an aligned tag, Table Builder, Table Share and Data Quality cannot create tables
  in a user's database.
- **The permissions control plane's coverage:** does it issue every grant `post_confirmation.py`
  issues today, on what trigger and cadence, and does the portal consume its output anywhere or
  simply trust that it has run?
- **Provisioning latency:** how long between a new user existing in Identity Center and the
  automated process provisioning them, and is the defensive empty state acceptable for that
  window? Queries against a not-yet-created database must fail soft.
- Does the client permit a Cognito User Pool at all, and is Managed Login v2 branding acceptable
  to their security review?
- Session lifetime: Cognito refresh tokens can outlive an Identity Center session revocation, so a
  deprovisioned employee could hold a valid portal session. What window is acceptable, and does
  sign-out need single logout?

**Gating Phase 2:**

- Sync tooling and cadence (§6.5): what runs it, who operates it, and how a delta is verified.
- How is the old account's user list enumerated for the sync's pre-creation pass?
- Do the reserved prefixes — including both `dq_tmp_` and `dq_tmp_raw_` table prefixes (§6.3) —
  collide with data arriving from the old account?
- Bucket topology in the successor account: names, exactly one *user-space* bucket (the live
  constraint — several other buckets exist; `CLAUDE.md`'s Out-of-Scope note now states it this
  way), Object Ownership set to
  *Bucket owner enforced*, and a **customer-managed KMS key** for re-encryption — AWS managed
  keys do not support trusted identity propagation at all, which would block Phase 5.

**Gating Phase 3:**

- **How many workspaces can one user belong to in the old account?** The app hard-caps at ten
  (`custom:shared_space_1..10`, `var.max_shared_memberships`), Cognito allows fifty custom
  attributes and **they cannot be deleted once created**. If the real number exceeds ten,
  redesign before the successor pool is created, not after. Passing gates P2 and P3 (§5.4)
  removes this ceiling entirely.
- Are all old-account workspace names catalog-safe under `^[a-z][a-z0-9_]{2,62}$`? They become
  Glue database names in the successor account.

**Gating the hosting workstream (§4.6, §4.7):**

- ~~Where does the container run?~~ **Settled — ECS Fargate**, task role supplies credentials.
- ~~Does the backend co-locate or stay a Lambda?~~ **Settled — co-located** in the same container.
- **One image promoted across environments, or a build per environment?** Still open, and
  deliberately deferred: do the accessor refactor first (§4.6) and the decision becomes a
  one-file change made later, on evidence rather than up front.
- Who owns TLS and DNS for the new origin, and what is the turnaround on getting a certificate?
  The origin must be settled before Phase 1's Cognito callback URLs are finalised.
- What is the session cookie's lifetime relative to the Cognito session and the Identity Center
  refresh token — the three clocks in §4.7? (Bucket CORS is now this repo's own configuration —
  §4.6 — so the old change-request dependency is gone.)

**Gating Phase 5:**

- Does the successor account already have a Lake Formation Identity Center configuration by the
  time Phase 5 starts, and if so who created it (§4.4)?
- Who administers the organization's Identity Center, and what is their process (§4.5)?
- Is the refresh-token grant available on the customer-managed application? The session-state
  design (§3.5) depends on it.
- Where does the core-dataset grant matrix live after the move, and who reviews changes to it
  (§3.8)? The reconciler is now portal-adjacent rather than a client system.
- Control-plane roles as Lake Formation data-lake admins is now the portal's own design choice
  as first tenant — but Identity Center users and groups **cannot** be data lake administrators,
  so it stays an IAM-role question regardless.
- Cross-plane joins: a query joining a personal database against a core dataset almost certainly
  will not work (§3.4). Confirm this is acceptable.

**Gating Phase 6:**

- How long a write-freeze window is tolerable, and in which calendar window does it land (§6.5)?
- How long must the old account survive read-only before decommission?

---

## 9. What this leaves behind

Code that becomes dead and should be deleted rather than left to rot:

**"Leaves behind" means at cutover, not now.** Everything below is load-bearing in this repo until
the successor account is live, and one of these has already been broken *because* it was mentally
retired: `pre-signup` shipped for nine days unable to import its own Lambda layer, failing real
sign-ups, and nothing noticed (2026-08-01, PR #317 — the Correction section of SPEC-137's delivery
doc). Deleting this code is a **cutover** task; keeping it working is a **today** task.

- `lambdas/pre-signup/` entirely, and `lambdas/post-confirmation/` with its provisioning logic —
  sign-in provisions nothing (§2 item 7). `backfill.py` and
  `scripts/backfill-portal-managed-tag.sh` go with them. Extract the provisioning checklist from
  `post_confirmation.py` into the coordination contract **before** deleting it — it is the
  specification the user automation and the permissions control plane must jointly satisfy.
- `ensurePrefixMarker`, its constants in `fileBrowser.constants.ts`, its call site in
  `routes/FilesPage.tsx`, the barrel re-export in `features/file-browser/index.ts`, and its
  tests (§6.3 has the full list).
- `startSignUp` / `signUp` across `auth.service.ts`, `AuthProvider.tsx`, `auth.types.ts`,
  `test/authFixtures.ts`, and their tests.
- Sign-up copy in `routes/LandingPage.tsx`, `lib/returnPath.ts` and
  `features/query/DatabaseNode.tsx`.
- If gates P2 and P3 pass: the Cognito Identity Pool, its principal-tag mapping, and the
  `custom:shared_space_*` attribute schema.
- The CloudFront distribution, its origin access configuration, the static-hosting bucket, the
  **SPEC-140 response headers policy** (its header set moves into nginx — §4.6), and the
  deploy-app sync and cache-invalidation CI steps — including SPEC-141's per-class
  `Cache-Control` passes, once landed (§4.6).

**No longer removed** — reversals from the previous strategy: `aws_lakeformation_data_lake_settings`,
the bucket registration, the user-space bucket policy template, and the shared-space `create`
verb all **stay**. The portal owns them in the successor account (§4.2).

Documentation to rewrite when this lands: `docs/architecture.md` (Authentication Flow,
Authorization Model, and the "No backend" Known Constraint, which §3.5 breaks), `docs/decisions.md`
(auth, shared-space and Lake Formation material, plus a new entry for the federated claim — the
file is one flat heading with no `##` sections, so locating passages means reading it),
`docs/architecture.md` → *Control Planes → Shared Spaces* (ownership model), and the in-app help content per the
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
