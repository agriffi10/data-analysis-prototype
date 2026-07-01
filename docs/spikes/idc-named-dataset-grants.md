# Spike: Named per-user dataset grants via IAM Identity Center trusted identity propagation

**Status:** Spike / de-risking — not a committed decision yet. Graduates to an architecture decision doc + spec arc **only after** the linchpin experiment in §10 passes.
**Last Updated:** 2026-07-01
**Related:** `docs/architecture.md` (Authentication Flow, Authorization Model → Analytics), `docs/shared-spaces-architecture.md` (control-plane pattern), `docs/table-builder-architecture.md` (analytics/LF precedent), SPEC-011 (Identity Pool + principal-tag ABAC), SPEC-012/033 (username model), SPEC-032/033 (analytics + per-DB LF model).

> Read this before designing the "shared core datasets" feature. It records the *intended shape* and — most
> importantly — the **one thing we must prove before committing** (§10). Everything downstream of that proof is
> infra + a `useConnections` seam; the proof itself decides whether "no backend" survives.

---

## 1. What we're building

A class of **globally-managed core datasets** (not per-user, not user-created) that individual users are granted
access to **by name and by level**:

- A user can hold **dataset X at `sensitive`** and **dataset Y at `normal`** simultaneously.
- The grants are **independent**: `sensitive` on X does **not** imply `sensitive` on Y.
- `sensitive` vs `normal` is **column/row masking** on the *same* dataset (sensitive sees protected
  columns/rows; normal sees the masked subset).
- Analysts must be able to **JOIN across datasets** they're entitled to, in a **single** query.
- Access is defined as **config** (a desired-state matrix of `principal → {(dataset, level)}`) and projected into
  live permissions by a **reconciler**. No tags.

This is the access model the user already runs in their real environment (SSO logins, IAM Identity Center enabled,
a permissions reconciler that issues Lake Formation grants). The job of this spike is to make that model work
**inside this Cognito-based, browser-direct SPA** without breaking what already ships.

**Explicitly out of this feature (unchanged):** the file browser, the **personal** Glue DB (DB = username), and
**shared spaces** all keep running on Cognito → Identity Pool → the shared portal role + `username` principal tag.
IdC is *additive* and scoped to the **catalog query path** only.

## 2. Why this shape (the reasoning chain that got us here)

Four facts forced the design; each closed a door:

1. **The app has no trusted server in the query path.** The browser holds real AWS credentials and calls AWS
   directly. So the security boundary is the **credential/service layer (IAM/LF)**, never app code. A permissions
   check written in the SPA is **UX, not enforcement** — a user with the underlying credentials can bypass the UI
   with the AWS CLI. (This is why "store permissions as config and check them in the app at query time" cannot be
   the boundary; config can *drive* grants and *shape* UX, but LF must be the checker.)
2. **Lake Formation has no ABAC.** LF grants target a **principal ARN**; you cannot condition an LF grant on a
   session/principal tag. So the `username`-principal-tag trick that isolates personal DBs and shared spaces
   **does not translate** to per-user dataset grants.
3. **One shared IAM role can't be the per-user LF grant target.** If the reconciler grants (dataset, level) to the
   single shared portal role, every user of that role inherits the **union** of everyone's grants — no isolation.
4. **A query-broker backend would have to re-implement the masking.** Routing queries through a Lambda that checks
   config *is* enforceable, but that Lambda now holds the privileged credentials and must itself apply the
   sensitive/normal **column/row masking** — re-implementing, by hand, exactly what LF data cell filters do for
   free. That's a security anti-pattern *and* it reverses "no backend" harder than the option below.

The only mechanism that injects a **per-user identity** into a browser-held query session, so **LF can enforce
per-user named grants** (with real column/row masking) **and** carry a user's *whole* grant set in one session
(→ cross-dataset joins), is **IAM Identity Center trusted identity propagation (TIP)**. Everything else fails one
of the four requirements above.

### 2.1 The payoff — a single shared query role still works

TIP means we **do not** need per-user roles or per-(dataset,level) roles. The identity-enhanced session still
assumes **one shared "catalog query" IAM role**, but LF differentiates by the **propagated IdC user identity**, not
by the role. So:

- No role explosion (per-user roles were the scaling problem).
- No credential swap per dataset — **one** identity-enhanced session carries **all** of a user's LF grants, so a
  single Athena statement can JOIN across every dataset they're entitled to.
- The repo's "one shared role, differentiate inside AWS" philosophy is preserved — we just add a **second** shared
  role for the catalog path, differentiated by IdC identity instead of a principal tag.

## 3. The identity wiring — two Cognito↔IdC connections

These are constantly conflated. They are **two separate connections, in opposite directions, doing different
jobs.** We need both.

### 3a. Login federation — Cognito uses IdC as its upstream SSO IdP  *(IdC → Cognito)*
Configure IdC as a **SAML 2.0 (or OIDC) identity provider on the Cognito User Pool**. Portal login becomes the
user's existing corporate SSO; Cognito stops being a separate identity store and becomes a **facade** over the IdC
user. This handles **authentication** and — because both sides resolve to the same directory — makes the token→user
mapping in §3b **exact**, not a fuzzy cross-directory email match.

*In this environment IdC users already exist (SSO is already the login for other apps), so there is no separate
"provision users into IdC" step — the directory is already populated.*

### 3b. Trusted Token Issuer — IdC trusts Cognito's tokens  *(Cognito → IdC)*
Register the Cognito User Pool as a **Trusted Token Issuer (TTI)** in IdC:

- **Issuer URL** = the pool's OIDC issuer, `https://cognito-idp.{region}.amazonaws.com/{userPoolId}`.
- **Claim mapping** = which Cognito-token claim identifies the user (e.g. `email`) → which IdC identity-store
  attribute it maps to.

Then create an IdC **customer-managed application** with **trusted identity propagation enabled**, whose
**audience** is the Cognito app-client ID, granted the **scopes** the propagated service (Athena/LF) requires, and
assigned to the relevant users/groups. This is what lets the app exchange a **Cognito** token for an **IdC identity
context** at query time (§4). *This* connection is the one strictly required for TIP; §3a just makes it clean and
gives single sign-on.

### 3c. Two credential planes off one login
```
                         ┌─ Identity Pool (GetId → GetCredentialsForIdentity)
                         │     → BASE shared portal role  (principal tag: username)
  Cognito login  ────────┤        used by: file browser, personal DB, shared spaces   [UNCHANGED]
  (federated to IdC)     │
                         └─ CreateTokenWithIAM → AssumeRole(ProvidedContexts)
                               → CATALOG shared query role  (carries IdC user identity)
                                  used by: core-dataset queries                        [NEW]
```
One login, two credential paths. The base plane is exactly today's flow (SPEC-011). The catalog plane is the new
work and is the subject of §4.

## 4. The end-to-end connection — explicit token flow

### One-time setup (infra / control plane)
1. **IdC** enabled with the identity store populated *(already true — SSO)*.
2. **Cognito ← IdC** login federation (§3a).
3. **IdC ← Cognito** Trusted Token Issuer + customer-managed application with TIP enabled (§3b).
4. **Catalog query role** — an IAM role whose trust policy admits the **IdC context provider**
   (`arn:aws:iam::aws:contextProvider/IdentityCenter`) and whose permission policy grants Athena run +
   Glue read + `lakeformation:GetDataAccess` + read/write of the Athena results location. **Shared by all users**;
   LF does the per-user differentiation.
5. **Athena workgroup** configured for IdC / trusted identity propagation, for the catalog query path.
6. **Reconciler** has projected config → LF grants + data cell filters (§7).

### Runtime — per session (the new catalog plane)
```
Preconditions the app already holds after login:
  • Cognito ID token (JWT; issuer = the User Pool, i.e. the registered TTI)
  • BASE Identity Pool credentials (shared role + username tag)

1. sso-oidc:CreateTokenWithIAM                         [SigV4-signed with the BASE creds]
       grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer
       assertion  = <Cognito ID token>
   → IdC validates the JWT against the TTI, matches the mapped claim → an IdC identity-store user
   → returns tokens including the IdC identity context (an sts:identity_context assertion)

2. sts:AssumeRole  (on the CATALOG query role)
       ProvidedContexts = [{ ProviderArn      = arn:aws:iam::aws:contextProvider/IdentityCenter,
                             ContextAssertion = <identity context from step 1> }]
   → identity-enhanced credentials: a session on the shared catalog role that CARRIES the IdC user identity

3. athena:StartQueryExecution  (on the IdC-enabled workgroup)  [with the step-2 creds]
   → Athena propagates the IdC identity to Lake Formation
   → LF resolves THIS user's named grants (+ any group grants) and applies the dataset's data cell filter
     for the granted LEVEL (column/row masking: sensitive vs normal)
   → because the session carries the user's whole grant set, a JOIN across datasets they hold works in one query

4. athena:GetQueryExecution / GetQueryResults; results land in the workgroup output location
   → S3 for the underlying data is read via LF credential vending (GetDataAccess), not direct S3 grants
```

**Caching.** Steps 1–2 are per **session** (cache the identity-enhanced creds until near expiry; refresh silently),
**not** per query. Step 3+ is per query. Token/session lifetimes and the silent-refresh path are a spike output
(§10, G6).

## 5. The catalog query role (carrier, not the boundary)

- **Trust policy:** allows `sts:AssumeRole` with the IdC context provider (`ProvidedContexts`). It does *not* need
  per-user conditions — the identity travels in the context, and LF, not the trust policy, enforces per-user.
- **Permissions:** `athena:StartQueryExecution/GetQueryExecution/GetQueryResults` on the IdC workgroup; Glue
  catalog **read** on the core-dataset databases; `lakeformation:GetDataAccess`; read/write on the Athena results
  prefix. Deliberately **no direct S3 read** on the dataset data — LF vends that.
- **One role for everyone.** Differentiation is 100% in LF via the propagated identity. This is the §2.1 payoff and
  is what keeps the change small.

## 6. How Lake Formation enforces at query time

- **Named grants keyed on the IdC principal.** LF `SELECT` is granted to the **IdC user (or group)** — the same
  principal the reconciler manages (§7). At query time Athena presents the propagated IdC identity; LF evaluates
  that principal's grants (direct + inherited group grants).
- **Levels = data cell filters.** Each dataset defines two **LF data cell filters** — e.g. `{dataset}__normal`
  (drops/masks the protected columns, optionally a row predicate) and `{dataset}__sensitive` (all columns/rows).
  A user's **level** for a dataset = which filter they hold `SELECT` on. `sensitive` on X and `normal` on Y are two
  independent grants → the requirement that levels don't leak across datasets falls out for free.
- **Default deny.** A user with no grant on a dataset gets access-denied — no app gating required, and none
  possible to bypass (the credentials themselves can't reach the data).

## 7. The reconciler — individual per-user permissions through IdC

This is the crux of the user's ask: *how does a reconciler still give each user individual permissions through
IdC?* It projects **config (source of truth)** into **LF grants against IdC principals**. It is a **control-plane**
component that runs **out-of-band** (their existing reconciler, or a scheduled Lambda/CodeBuild in this account) —
**not** in the browser path.

### 7.1 Config — the desired-state matrix (source of truth)
```yaml
# access-config.yaml  — one row per (principal, dataset, level); git-tracked, reviewed like code
grants:
  - principal: { type: user,  ref: alice@corp.com }   # resolved to an IdC user id
    dataset: sales
    level: sensitive
  - principal: { type: user,  ref: alice@corp.com }
    dataset: finance
    level: normal
  - principal: { type: group, ref: data-analysts }    # group grants are supported too
    dataset: marketing
    level: normal
```
Plus a **dataset registry** (also config) that maps each logical `dataset` → its Glue database/table(s) and the
column/row rules that *define* its `__normal` vs `__sensitive` filters. The access matrix references datasets by
logical name; the registry is where "what is sensitive in sales" lives.

### 7.2 Reconcile loop (idempotent; on config change / scheduled)
```
1. RESOLVE PRINCIPALS   email / group-name → IdC IDs
                        identitystore:GetUserId / ListGroups / ListGroupMemberships     (cache)

2. ENSURE FILTERS       for each dataset in the registry, ensure the two LF data cell filters exist
                        lakeformation:CreateDataCellsFilter (from the registry's column/row rules)

3. COMPUTE DESIRED      for each config row → a concrete LF grant:
                          principal → IdC user/group as the LF DataLakePrincipal
                          dataset+level → SELECT on the {dataset}__{level} data cell filter
                        = the exact set of grants that SHOULD exist

4. READ CURRENT         lakeformation:ListPermissions  (per principal, or catalog-wide)

5. CONVERGE             GrantPermissions   for desired − current
                        RevokePermissions  for current − desired      (idempotent; safe to re-run)
```

### 7.3 Why this yields *individual* per-user enforcement
- The grant's **principal is the IdC user** (or a group the user is in). LF stores it per-principal.
- At query time the identity-enhanced session **carries that IdC user identity** (§4 step 2–3), so LF applies
  **exactly that user's** grants and filters. Two users on the *same* shared catalog role see *different* data.
- No per-user IAM roles, no tags, no credential swapping. The reconciler's output is pure LF grants keyed on IdC
  identity — precisely the model the user already runs, now consumed by a Cognito-fronted SPA.

### 7.4 The trade vs. a synchronous broker
The reconciler is **eventually consistent**: a config change isn't live until the next reconcile projects it into
LF (seconds–minutes). A broker would be synchronous but would re-implement masking (§2, door 4). Mitigate by
running the reconciler **on config change** (e.g. on merge to the config repo) plus a periodic sweep. Accepting
reconciler lag to avoid hand-rolled column security is the right trade.

## 8. The ripple: SSO login vs. the username model

Federating login to IdC (§3a) collides with the app's **self-service signup + username model** and must be handled
as in-scope work, because it underpins S3 isolation:

- Today: users self-sign-up; the **pre-signup Lambda** validates a user-chosen username to catalog-safe
  `^[a-z][a-z0-9_]{2,62}$`; **username = S3 prefix = `username` principal tag = personal Glue DB name**
  (SPEC-012/033).
- With IdC federation: users are **JIT-provisioned** from IdC, not self-chosen. Their IdC attributes (email, etc.)
  **won't** satisfy the catalog-safe pattern (`@`, dots, case).
- So we need a **deterministic IdC-attribute → safe-username mapping** in a Cognito trigger (pre-signup /
  pre-token-generation), and the pre-signup Lambda's role flips from *"reject a bad chosen name"* to
  *"derive + validate a stable, collision-free safe name from the verified federated claim."* It must be stable
  (same user → same username every login) because it keys the personal prefix/DB.

## 9. What changes vs. stays

| Area | Verdict |
|---|---|
| Browser → AWS direct | **Stays** (modulo the §10 linchpin — may need one token-exchange Lambda) |
| Cognito as the app's credential broker | **Stays** |
| Base shared role + `username` tag (files, personal DB, shared spaces) | **Stays — untouched** |
| Config-as-source-of-truth + reconciler | **Stays** — now targets IdC users/groups |
| Enforcement at the credential/service layer | **Stays** — LF is the checker (never the SPA) |
| Cognito login | **Federated to IdC** (+ username-derivation ripple, §8) |
| IdC TTI + customer-managed application | **New** |
| Catalog shared query role (identity-enhanced) | **New** |
| `useConnections` catalog connection kind | **New** — runs under the identity-enhanced session |
| Fine-grained LF (data cell filters) on core datasets | **New** — the "level" mechanism |
| Deploy-role IAM + `infra/modules/…` for IdC/federation/query-role | **New** |

## 10. THE SPIKE — de-risk the linchpin first

Everything above is infra + a `useConnections` seam **except one unknown that reshapes the whole story**: can a
**public SPA client** perform the `CreateTokenWithIAM` exchange itself (SigV4-signed with the base Identity Pool
creds, no client secret), or does the IdC customer-managed application require a **confidential client** — forcing a
small token-exchange Lambda and thus a (tiny) backend? Since IdC is already enabled in the client environment, this
is answerable empirically in an afternoon. **Prove it before writing any spec.**

### Goal
End-to-end, in the client account, from a browser-equivalent public client: exchange a Cognito token → identity
context → identity-enhanced session → an Athena query that **LF filters per IdC user** — and record whether a
backend is required.

### Throwaway setup
- 1 small test table + 2 **data cell filters** — `test__normal` (drops one PII column), `test__sensitive` (all).
- 1 test IdC user (or reuse a real SSO user).
- TTI on the Cognito pool + IdC customer-managed application (TIP enabled) + the identity-enhanced **catalog query
  role** + an IdC-enabled Athena workgroup.
- Reconciler stub / manual `GrantPermissions`: grant the test user **`SELECT` on `test__normal`** to start.

### Exercise (from a public client holding only base Identity Pool creds)
1. `sso-oidc:CreateTokenWithIAM` (jwt-bearer, Cognito ID token) → identity context.
2. `sts:AssumeRole` on the query role with `ProvidedContexts` → identity-enhanced creds.
3. `athena:StartQueryExecution` → `SELECT * FROM test`.

### Pass/fail gates
| Gate | Check | If it fails |
|---|---|---|
| **G1 (linchpin)** | Step 1 succeeds from a **public** client (no client secret) | Re-test the exchange from a **Lambda** (confidential client). If only that works → "no backend" needs a **token-exchange Lambda**; redesign the seam around it before the spec. |
| **G2** | Step 3 returns the **normal** view (PII column masked/absent) for the test user | LF fine-grained/data-cell-filter or workgroup config is wrong — fix before proceeding. |
| **G3** | After granting `test__sensitive`, re-run → **full** view (PII present) | Level switching via LF grants doesn't work — the whole "level" model is in question. |
| **G4** | A user with **no** grant → access-denied | Default-deny/propagation broken — blocker. |
| **G5** | A JOIN across two granted datasets in one query → returns | Single-session-spans-grants assumption is wrong — revisit cross-dataset-join requirement. |
| **G6** | Identity-enhanced session lifetime is workable + silent refresh path exists | UX churn (re-auth mid-session) — may need a refresh strategy. |

### Deliverable
A short findings note answering: **backend needed? (G1)**, required IdC app **scopes**, **session lifetimes /
refresh**, and any **Athena JS SDK** friction from the browser. That note decides whether this graduates to a
committed architecture doc + spec arc, and whether the "no backend" Known Constraint gets a caveat.

## 11. New infrastructure (summary; detail in the eventual spec arc)

- **IdC:** Trusted Token Issuer (Cognito pool) + a customer-managed application with TIP enabled + assignments.
- **Cognito:** IdC as an upstream SAML/OIDC IdP on the User Pool; the username-derivation trigger (§8).
- **IAM:** the shared **catalog query role** (IdC-context trust policy; Athena/Glue-read/`GetDataAccess`/results-S3).
- **Athena:** an IdC-enabled workgroup for the catalog path.
- **Lake Formation:** data cell filters per dataset (`__normal`/`__sensitive`); grants to IdC principals (reconciler).
- **Reconciler:** config repo + dataset registry + the reconcile job (scheduled + on-config-change).
- **(Conditional on G1)** a token-exchange **Lambda** if the public-client exchange is disallowed.
- **Deploy-role IAM** expanded for every new resource type (IdC/TTI/app admin, the query role incl. scoped
  `iam:PassRole`, Athena workgroup, LF grant/filter admin, Identity Store read for the reconciler) — per the
  CLAUDE.md infra rule and architecture.md "adding a new resource type" traps.

## 12. Open questions (resolve in / around the spike)

- **G1 — public vs confidential client for `CreateTokenWithIAM`.** The single biggest unknown; decides "no backend".
- **IdC application scopes** required to propagate identity to Athena/LF.
- **Session lifetime & silent refresh** of the identity-enhanced credentials (browser UX).
- **Cross-*plane* joins.** JOINing a core dataset (IdC/LF plane) against the **personal** `username` DB (base-role
  plane) in one statement almost certainly won't work — different enforcement planes. Confirm this is acceptable
  (expected: yes; keep them separate connections).
- **Reconciler home & cadence.** Their existing reconciler vs. a job in this account; on-merge + periodic sweep.
- **Dataset registry ownership.** Who defines each dataset's `__normal`/`__sensitive` column/row rules, and where.

## 13. Proposed next steps

1. **Run the §10 spike** in the client account; produce the findings note (esp. G1).
2. If G1 passes as a public client → this graduates to `docs/named-dataset-grants-architecture.md` (decision doc,
   `table-builder-architecture.md` format) + a spec arc: **IdC/TTI + federation → username derivation →
   catalog query role + token exchange → `useConnections` catalog kind → LF data cell filters + reconciler grants**.
3. If G1 needs a Lambda → same arc, plus a token-exchange Lambda, and a one-line caveat on the "No backend" Known
   Constraint in `architecture.md`.
</content>
</invoke>
