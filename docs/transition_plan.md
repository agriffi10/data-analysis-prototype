# Transition Plan — Client Environment

**Status:** Single source of truth for the client transition — moving this portal into the client's
**successor AWS account**, with **Entra ID** as who authenticates and **IAM Identity Center** as
what propagates that identity into AWS. **Living document: update it in place rather than writing a
competing one.** Dated revision notes live in §11; every correction they announce is recorded in the
section it belongs to, so read the section rather than the log.

**Supersedes and replaces** `docs/client-migration-plan.md` and `docs/spikes/idc-named-dataset-grants.md`,
both deleted. Everything of value from the spike — the reasoning chain behind trusted identity
propagation, the credential-plane argument, the reconciler design and the surviving gates — is
absorbed into §3, §5.5 and §7. **Do not resurrect either file:** add here instead.

## Where we stand (2026-09-04)

**No phase in §7 has started.** The successor account's tenancy, the Identity Center relationship
and every gate in §5.5 are still Phase 0 questions.

**What has moved is on this side, and it deleted work this plan used to carry.** Arc B
(SPEC-192 → 202) put every AWS call behind an API, retired the Cognito Identity Pool and the
CloudFront distribution, and left the product complete on Cognito. SPEC-203 built the membership
index, SPEC-205 made a shared-space delete empty a space rather than destroy it, and SPEC-212 → 215
moved the Lambda fleet onto one container image with its configuration read from Terraform state.
So the browser holds no AWS credentials, the SPA is a container behind an ALB, and the identity work
below starts from an API that already verifies a bearer and assumes a role from the verified claim.

## Two variants of the identity plane

The corporate identity provider is **Microsoft Entra ID**. Which mechanism it can offer is not ours
to decide, so the plan carries two variants and builds whichever the answer permits:

- **[A] — the baseline.** Entra issues OIDC/OAuth2 JWTs directly and is registered as the Identity
  Center **trusted token issuer**. **There is no Cognito anywhere** — no User Pool, no Identity
  Pool, no Managed Login, no custom attributes.
- **[B] — the fallback**, used only if the Entra tenant turns out to be hard SAML-only. Cognito is
  reduced to a **SAML→OIDC bridge**: it federates to Entra, issues the JWT the exchange consumes,
  and is the trusted token issuer. It is infrastructure, not the app's identity provider — nothing
  app-level may depend on it.

**Everything downstream of the JWT is identical in both**, which is why this is one plan and not
two. The deliberately tagged passages are §3.3, the assertion in §3.5's step 1 and its replay
paragraph, §6.1, and the Phase 1 and Phase 5 items that name a provider. The deciding fact is
**gate G8** (§5.5), answered in Phase 0.

> **An untagged passage is NOT a promise of variant-neutrality.** This document predates the
> variants and still names Cognito in passages neither revision rewrote — chiefly the whole of §5,
> whose experiment is written around a Cognito pool as the trusted token issuer. Read a bare
> "Cognito" in an untagged passage as **[B]**, and as *"under [A] the same job exists and Entra does
> it"*. (§4.6's callback URLs and §4.7's session clocks were the other two examples; both now carry
> explicit **[A]**/**[B]** tags.)

**Nothing in Arc B was gated on a transition gate, and nothing here may degrade the current
environment** (§2 item 14).

## Contents

1. [What is changing](#1-what-is-changing)
2. [Settled decisions](#2-settled-decisions)
3. [Target architecture — the identity and authorization model](#3-target-architecture--the-identity-and-authorization-model)
   - [3.1 What the end state has to support](#31-what-the-end-state-has-to-support)
   - [3.2 Why trusted identity propagation is the only mechanism](#32-why-trusted-identity-propagation-is-the-only-mechanism)
   - [3.3 The identity plane — two mechanisms, two variants](#33-the-identity-plane--two-mechanisms-two-variants)
   - [3.4 ~~Two credential planes off one login~~ — superseded, there is one](#34-two-credential-planes-off-one-login--superseded-there-is-one)
   - [3.5 The token flow, and why the backend holds state](#35-the-token-flow-and-why-the-backend-holds-state)
   - [3.6 The carrier role](#36-the-carrier-role)
   - [3.7 How Lake Formation enforces](#37-how-lake-formation-enforces)
   - [3.8 The reconciler](#38-the-reconciler)
   - [3.9 The storage plane — S3 Access Grants](#39-the-storage-plane--s3-access-grants)
   - [3.10 Third-party driver access — Excel, Access, Power BI and anything else on ODBC/JDBC](#310-third-party-driver-access--excel-access-power-bi-and-anything-else-on-odbcjdbc)
   - [3.11 Shared-space entitlements — the projection that replaces the tag](#311-shared-space-entitlements--the-projection-that-replaces-the-tag)
   - [3.12 Provisioning a user without a signup](#312-provisioning-a-user-without-a-signup)
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
   - [6.1 The username claim is not `cognito:username`](#61-the-username-claim-is-not-cognitousername)
   - [6.2 First-tenant singleton ownership (was: the Lake Formation IaC overwrite)](#62-first-tenant-singleton-ownership-was-the-lake-formation-iac-overwrite)
   - [6.3 Destructive code paths during the sync-and-seed window](#63-destructive-code-paths-during-the-sync-and-seed-window)
   - [6.4 Shared workspace seeding (was: adoption — nothing is adopted anymore)](#64-shared-workspace-seeding-was-adoption--nothing-is-adopted-anymore)
   - [6.5 The sync and the cutover (was: retiring bespoke roles — deleted; they are never created)](#65-the-sync-and-the-cutover-was-retiring-bespoke-roles--deleted-they-are-never-created)
7. [Phases](#7-phases)
   - [Phase 0 — Discovery, contract and experiments (no product code)](#phase-0--discovery-contract-and-experiments-no-product-code)
   - [Phase 1 — Stand up the portal in the successor account](#phase-1--stand-up-the-portal-in-the-successor-account)
   - [Phase 2 — Provision every known user, then sync personal spaces](#phase-2--provision-every-known-user-then-sync-personal-spaces)
   - [Phase 3 — Shared workspaces](#phase-3--shared-workspaces)
   - [Phase 4 — Analytics on the synced model](#phase-4--analytics-on-the-synced-model)
   - [Phase 5 — Identity Center identities in Lake Formation](#phase-5--identity-center-identities-in-lake-formation)
   - [Phase 6 — Cutover and decommission](#phase-6--cutover-and-decommission)
8. [Open questions by gating phase](#8-open-questions-by-gating-phase)
9. [What this leaves behind](#9-what-this-leaves-behind)
10. [Sources](#10-sources)
11. [Revision history](#11-revision-history)

**[The order of work](#the-order-of-work)** — the phases in sequence, what is waiting on somebody
outside this project, and the four orderings that have a wrong answer in both directions.

**Read map** — `CLAUDE.md` says "read before touching auth, provisioning or LF"; in practice:

- **Touching auth** (tokens, sign-in, anything reading the username claim) → §3 (especially
  §3.3–3.5) plus §6.1 — the username claim is **not** `cognito:username` in either variant, and it
  is the highest-consequence detail in the migration. §3.3 is where the **[A]** / **[B]** variant
  split lives; an untagged passage applies to both.
- **Touching provisioning / de-provisioning** (creating or deleting user/space resources, the
  account-wide LF singletons) → **§3.12 first** — a user's space is created by a portal-owned
  provisioner from a known username list, before anyone signs in, and that section carries what has
  to be true for it and what de-provisioning still does not answer. Then §4.4 and §6.2
  (portal-created singletons and their ownership), and §6.3 (destructive paths during the
  sync-and-seed window).
- **Touching Lake Formation re-keying** (grants moving to Identity Center principals) → §3.7 (how
  LF enforces) and Phase 5 (the work items); §3.8 for the reconciler that projects the grants,
  §3.11 for the shared-space entitlements, which are registry-driven and per-member rather than
  config-driven, and whose cutover ordering has a wrong answer in both directions.
- **Wanting the end state as a picture** → `docs/target-architecture-variants.md`, a subordinate
  companion: both variants drawn, the two credential lanes below the API made explicit, and the
  **ALB-native-OIDC fork rejected on evidence**. It also carries the **live-docs validation log**
  (2026-08-19) behind the corrections since applied in place here: §3.5's action prefix, its replay
  claim, the assertion's permitted token type, and the `${user_id}` half-answer. Three things live
  **only** there and would be lost if it were ever deleted as "just the pictures": the ALB fork's full
  four-leg argument (§3.3 below carries a precis, not a substitute), the two-lane framing, and the
  `AWSIAMIdentityCenterAllowListForIdentityContext` v12 evidence. This document stays authoritative;
  where they disagree, read here.

---

## The order of work

**§7 owns the sequence. This is a router over it, not a second plan** — it carries the three things
§7 scatters: *what a phase cannot start without*, *what undoes it*, and *whose work each item is*.
Every one of those is stated in §7 as well; nothing here is the only home of a fact. Where the two
disagree, §7 is right and this table is stale.

| # | Phase | Cannot start until | Rollback |
|---|---|---|---|
| 0 | Discovery, contract and experiments — no product code | Nothing. Start it now; six of its items have lead times that belong to other people (the table below) | n/a |
| 1 | Stand up the portal in the successor account | G8 has settled the variant **in writing**, the account exists in the same AWS Organization, the container's final origin is fixed (the callback URLs are registered against it), and the Access Grants **prefix identity** is decided — §8 files that one as gating Phase 0 to 1, because it decides whether the username survives as the prefix | Tear the stack down; the account was empty |
| 2 | Provision every known user, then sync personal spaces | Phase 1 signs a real user in; the provisioning contract and the username list exist (§3.12) | Delete the synced copy and re-run |
| 3 | Shared workspaces — seed, then parity-check | Phase 2's prefixes exist; the Phase 0 membership inventory is in hand | Delete the seeded registry objects and data |
| 4 | Analytics on the synced model | Phase 3's databases exist, and the `portal-managed` tag the provisioner stamps is the one the TBAC tag-policy grants expect — without it no arc can create a table (§3.12) | Feature-flag the arcs back off |
| 5 | Identity Center identities in Lake Formation | G7 and G9 have passed and SCIM is live; the **relationship** with the Identity Center administrators is established (Phase 0) — the customer-managed application is this phase's own first work item, not a precondition | The interim plane, kept running alongside until the last step |
| 6 | Cutover and decommission | Nothing, for the delta syncs — but **the freeze cannot be called** until the driver desktop fleet has migrated off the old account's SAML path (§6.5) | Point users back at the old account and lift the freeze — until decommission, and no further |

**Five items are not this project's to execute, and every one of them has a lead time.** They are
listed here because a plan that only tracks its own work discovers these late.

| What | Whose | Needed by | If it is late |
|---|---|---|---|
| **G8** — can the Entra tenant issue OIDC for this application, on the default signing key? | The Entra tenant owner | Phase 1's whole auth configuration | Variant B gets built, and under B the **desktop fleet** points at the Cognito bridge too (§3.10) |
| **SCIM** provisioning from Entra into Identity Center | The client's platform team | Phase 5 — grants target Identity Center principals, and there is no just-in-time provisioning | Nobody can be granted anything, and §3.12's identity-shaped pass cannot run |
| A **customer-managed application** in Identity Center (at least two — the portal's and the driver path's) | Management-account or delegated administrators | Phase 5 | Phase 5 does not start; this is the relationship most often discovered late (§4.5) |
| The **successor account's** existence, organization membership and tenancy order | The client's platform team | Phase 1 | Every identity assumption in §3 is re-opened (§4.5), and §6.2's surgery reactivates |
| The **desktop migration** — DSN shape, the ODBC 2.1.0.0 / JDBC 3.7.0 floor, the rollout | The client's endpoint owners | Phase 6's write freeze | The freeze strands them, or the dual-key fallback has to be costed first (§3.10) |
| The **username list** — every catalog-safe username, ideally with the Identity Store attribute beside it | Ours to specify, **theirs to produce** | Phase 2, which is a run over it | Nothing is provisioned, so Phase 2 has nowhere to sync into (§3.12) |

**Four orderings have a wrong answer in both directions.** Each is stated where it lives; they are
collected here because all four look like housekeeping.

1. **Shared-space entitlements at Phase 5 (§3.11):** entitle every member and verify → retire the
   tags and the interim plane → revoke the role-level Lake Formation grants, rewriting the
   tag-scoped Glue statement in the *same* change. Reversed, every member is locked out at once;
   step 3 skipped, every user is entitled to every space.
2. **Deploy-role IAM before the resources it grants** (`CLAUDE.md`'s infra rule, §7 Phase 1). A
   grants-only PR lands first; the reverse is an apply that fails halfway.
3. **The driver fleet migrates before the freeze** (§3.10, §6.5), not before Phase 5 — it has
   nowhere to land until the TIP path is up, and nowhere to read from once the freeze falls.
4. **G8 before Phase 1's auth configuration** (§5.5). Building Variant B when A was available is
   the expensive mistake, and it is unrecoverable only in the sense that the bridge then has users.

---

## 1. What is changing

Today this portal is a **closed system**. It owns the identity store, it provisions each user's
resources, and it owns the Lake Formation configuration of its whole account. Two moves are now
happening at once: the client environment is transitioning to a **successor account**, and the
portal is **stood up in that account first**, before the data arrives. The portal therefore
remains the **resident, owning system of its account** — much closer to what this repo already is
than the "access portal over resources it does not own" posture the previous strategy required.
What changes instead is identity — **Entra ID replaces self-service Cognito as who authenticates, and
Identity Center is added as what propagates that identity into AWS**; they are not alternatives and
reading them as one is the mistake §3.3 exists to prevent — and the arrival of the client's data via a
**one-time sync and cutover** from the old account.

| Concern | Today (this repo) | Successor account |
|---|---|---|
| Who authenticates | Cognito User Pool, self-service signup | **Entra ID**, the org's existing SSO — directly **[A]**, or through a Cognito SAML→OIDC bridge **[B]** (§3.3) |
| Who can sign in | Anyone who registers | Everyone in the organization |
| Who propagates identity into AWS | Nothing — one shared role, differentiated by a principal tag | **IAM Identity Center**, via the token exchange (§3.5). Entra authenticates; IdC propagates — they are not alternatives |
| Who creates the user's S3 prefix | The browser, via `ensurePrefixMarker` | A **portal-owned provisioner**, over the client's known username list, **before anyone signs in** (§3.12). **Sign-in provisions nothing** |
| Who creates the user's Glue database | `post_confirmation.py` | The same provisioner, running `provision_user`'s existing sequence on a new trigger — database, portal-role grant, `portal-managed` tag (§3.12) |
| Per-user IAM identity | One shared role plus a `username` principal tag, stamped by the API from the verified claim (the Identity Pool did this until SPEC-202 retired it, 2026-08-31) | **Interim (Phases 1–4):** the same shared role and tag, assumed by the API from the verified claim — no Identity Pool. **End state (Phase 5):** one identity-enhanced session, no principal tags, storage on S3 Access Grants (§3.4, §3.9). **Bespoke per-user roles are never created** |
| Per-user storage isolation | `${aws:PrincipalTag/username}` in the bucket and Glue policies | Same in the interim; **S3 Access Grants** in the end state — plain S3 is denied on an identity-enhanced session (§3.6) |
| Third-party BI / ODBC clients (Excel, Access, Power BI) | Not consumers of this repo at all — they reach Athena directly from the **client's** environment, over SAML federation with Lake Formation, under a **parallel** grant set keyed on SAML principals | The **same** grants that govern the portal, keyed on the same Identity Center principals, carried by the drivers' own trusted-identity-propagation plugins. One entitlement model instead of two (§3.10) |
| Lake Formation grants | Issued by this app, keyed on the shared role | Same for personal and workspace scopes; core datasets keyed on Identity Center principals (§3), issued by a config-driven reconciler |
| Shared workspaces | Created and managed by this app's control plane | Same — created by this app in the successor account, contents synced from the old account's workspaces |
| The data itself | Created in place by users | **Synced from the old account**, re-encrypted under the successor account's KMS key, then cut over (§6.5) |

---

## 2. Settled decisions

Treated as inputs. Do not re-litigate without new information.

1. **~~Cognito survives as a facade.~~ SUPERSEDED 2026-08-18 — the identity plane has two
   variants, and the baseline has no Cognito at all.** The corporate identity provider is
   **Entra ID**, and the portal stays open to everyone in the organization using the login screens
   they already trust either way. **[A — baseline]** Entra issues OIDC directly and is the Identity
   Center trusted token issuer; there is no Cognito. **[B — fallback]** Entra is SAML-only, so
   Cognito federates to it and issues the OIDC JWT the exchange consumes, and is the trusted token
   issuer. Under **both**, nothing app-level depends on Cognito: no custom attributes, no
   `cognito:username`, no Managed Login as the app's own login surface. §3.3 carries the mechanism;
   the choice is gate G8 (§5.5), in Phase 0. *The old wording — Identity Center as the upstream SAML
   provider on a surviving User Pool — described Variant B with the bridge pointed at Identity
   Center rather than at Entra; §3.3 records why the Entra-facing shape is preferred if B is used at
   all.*
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
7. **Sign-in no longer provisions, and the portal provisions instead — AMENDED 2026-09-04.**
   *This item used to give provisioning to the client's automated process, with a separate
   permissions control plane issuing the grants, and it left three questions in §8 for someone else
   to answer.* **The portal owns it**: a control-plane provisioner, fed by the client's external
   username list, creates every user's space **ahead of use** — the design is **§3.12**. What
   carries over unchanged is the half that matters most: **sign-in provisions nothing**, so
   `ensurePrefixMarker` and the Cognito triggers still go, and the defensive empty state still
   stays, because a user can sign in before the provisioner has run for them. What changes is the
   fate of the code: `provision_user` is **kept and re-triggered**, not deleted (§9), and the tag
   taxonomy is ours to align rather than someone else's to confirm.
8. **Existing shared workspaces arrive via the sync, with the manifest written manually**; from
   cutover the app **fully manages all shared spaces** — new ones through the `create` verb as
   today. The seeding parity check in §6.4 is what makes that handover safe.
9. **Analytics is feature-flagged off for Phase 1.** File browser, notifications and shared
   workspace browsing ship first.
10. **Hosting is ECS Fargate, not CloudFront.** The SPA is served from a container. The task role
    supplies AWS credentials, which is what makes the token-exchange backend straightforward (§4.6).
11. **~~The token-exchange backend runs in the same container as the SPA.~~ REVERSED — Arc B
    landed.** The API is a **Lambda behind API Gateway**, its own origin, and the SPA is a container
    behind an ALB; the co-location argument was made when the backend existed only to exchange
    tokens. What survives is everything §4.7 says about **state** — the opaque `httpOnly` cookie,
    the refresh token in DynamoDB under a customer-managed key, and the three clocks.
12. **Users and groups must exist in Identity Center BEFORE use, and nothing in this architecture
    creates them.** The token exchange maps a claim to an existing Identity Center user and populates
    nothing; **Identity Center performs no just-in-time provisioning**, so an unprovisioned user's
    exchange simply fails. AWS permits two ways to satisfy this — SCIM synchronisation from the IdP,
    **or** creating users directly in Identity Center — and at organization scale SCIM from Entra is
    the only tractable one. It is also what gives Lake Formation **groups** to grant to. Two
    constraints that ride with it: the claim mapped to an Identity Center user must resolve to
    **user name, email or external ID** (so "typically `email`" is a constraint rather than a
    convention), and it must be unique. Variant-independent, and a hard dependency on the Identity
    Center administrators either way.
13. **There is ONE credential plane in the end state, not two.** Supersedes §3.4. The
    identity-enhanced session is the only plane, and because
    `AWSIAMIdentityCenterAllowListForIdentityContext` denies plain S3, **S3 Access Grants** governs
    storage — personal prefixes included. `${aws:PrincipalTag/username}` and the
    `custom:shared_space_k` slots **do not survive Phase 5** — they carry through the interim plane
    (Phase 1) and retire with it. New §3.9 carries what replaces them, and
    the largest downstream consequence lands on **shared spaces**, not on the file browser.
14. **The app must be fully functional on Cognito until the successor account is live.** Arc B
    (SPEC-192 → 202) moves every AWS call behind an API without touching sign-in, and the product is
    complete on Cognito when it lands. Nothing in this plan may create a window where the current
    environment is degraded, and **no Arc B spec may be gated on a transition gate** — the three
    forward-compatibility obligations the 2026-08-18 revision added to its drafts are each
    independently shippable today (§11 names them; `docs/specs/ARCS.md` carries each in full).
15. **The client's third-party driver users are on the SAML path today, and they must be migrated**
    (confirmed by the client, 2026-08-24). Their Excel, Access and Power BI clients reach Athena
    through SAML-2.0 federation with Lake Formation — the very feature AWS documents as *"not
    compatible with the IAM Identity Center trusted identity propagation feature"*. So this is a
    **cutover for every one of those desktops**, not a version bump, and §3.10's migration subsection
    is the shape of it. Treated as an input: do not re-plan on the assumption of a straight swap.

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

### 3.3 The identity plane — two mechanisms, two variants

**Two mechanisms are constantly conflated, and keeping them apart is what makes the variants
legible.** They are separate connections doing different jobs, and both are needed.

1. **Sign-in / SSO** — how a human authenticates. Identity Center accepts SAML 2.0 **or** OIDC here,
   and Entra SAML is fully supported.
2. **The token exchange (trusted identity propagation)** — how that identity reaches AWS services.
   This requires **OAuth 2.0 / JWT**. AWS documents that TIP **does not support SAML 2.0
   integrations**: the trusted token issuer must be an OAuth 2.0 authorization server issuing signed
   JWTs, because `CreateTokenWithIAM` uses a `jwt-bearer` grant with the JWT as the assertion.

**That single asymmetry is the whole basis for the two variants.** Identity Center accepting SAML for
*sign-in* does not remove the OAuth requirement for the *exchange*. So if Entra can issue OIDC JWTs,
it is the trusted token issuer directly; if it cannot, something has to convert a SAML-authenticated
session into an OIDC JWT, and that something is Cognito.

| | **[A] — baseline** | **[B] — fallback** |
|---|---|---|
| Use when | The Entra tenant/app registration can issue OIDC/OAuth2 JWTs | Entra is hard SAML-only for this application |
| Sign-in | Browser → **Entra** (OIDC) | Browser → **Cognito** → SAML → Entra |
| Trusted token issuer in IdC | **Entra** (issuer URL + JWKS) | **Cognito** (`https://cognito-idp.{region}.amazonaws.com/{userPoolId}`) |
| Assertion exchanged in §3.5 step 1 | The **Entra** ID token | The **Cognito** ID token |
| Cognito | **Absent entirely** | Present as a SAML→OIDC bridge and nothing else |
| Everything downstream of the JWT | Identical | Identical |

**A third shape exists and is rejected: Identity Center as the login provider.** AWS's own
**Important** on the customer-managed-applications page settles it — such an application *"must
obtain a token from a trusted token issuer, **which is external to IAM Identity Center**."* It
assumes your application authenticates users elsewhere. **Entra authenticates the users; Identity Center propagates their identity into AWS.**
They are not alternatives, and anyone who reads "tie the portal to an Identity Center login" as a
sign-in flow will build something that cannot work.

**Provisioning into Identity Center is required in both variants and is not part of either one.**
The claim in step 1 must resolve to a user who already exists in Identity Center — there is no
just-in-time provisioning — and the mapped claim must be **user name, email or external ID**. SCIM
from Entra is the practical way to satisfy that at organization scale, and it is also what gives Lake
Formation groups to grant to (§2 item 12). The exchange populates nothing by itself.

#### If Variant B is used, point the bridge at Entra

An earlier version of this plan had Cognito federating to **Identity Center** as its upstream SAML
provider, on the argument that both sides then resolve to the same directory and the token-to-user
mapping is exact rather than a fuzzy cross-directory email match. That argument is real, but it is
weaker than it looks and the Entra-facing shape is preferred:

- With SCIM live (§2 item 12), Identity Center's directory **is** Entra's — so the "same directory"
  property holds either way, and the mapping is exact in both.
- Authentication, MFA and conditional access stay in Entra in both shapes. Pointing the bridge at
  Identity Center adds a hop that authenticates nobody.
- Variant B exists to be **deleted**. The migration from B to A is *"re-point the trusted token
  issuer registration and the claim mapping at Entra, store Entra tokens instead of Cognito tokens,
  delete Cognito"* — and that is a smaller diff when Cognito was already federating to Entra.

**Guardrail, and it is load-bearing:** in Variant B, Cognito **must not permit self-asserted local
identities**. Authentication must delegate to Entra. If a user can sign up locally and assert an
arbitrary email, they can obtain a token that maps to another person's Identity Center user, and with
it that person's Lake Formation grants and Access Grants. The pool auto-creates users on successful
SAML federation; the user must already exist in Identity Center for the exchange to succeed.

**Variant B's other cost is §6.1's trap**, which Variant A deletes outright — see there.

**Both variants are drawn in `docs/target-architecture-variants.md`**, which also records why the
Application Load Balancer is not a place to put the sign-in redirect for this flow. The evidential
leg — the only header it signs is signed by *itself*, and the access token it forwards sits under
*"Legacy unsigned headers"*, is one AWS says the load balancer creates, and *"cannot be independently
verified by your application"* — is strong but not airtight, so the rejection does **not** rest on
it: it also protects the wrong origin (the API is a separate front door), it is a second reader of
the same identity able to disagree, and its 11 KB / 15-minute / expired-session-redirect limits bite
this app specifically. Do not re-open it without reading all four.

### 3.4 ~~Two credential planes off one login~~ — superseded, there is one

> **SUPERSEDED 2026-08-18.** This section described a **base plane** (Identity Pool → shared portal
> role → `${aws:PrincipalTag/username}`, serving the file browser, the personal database and shared
> workspaces) running alongside a **catalog plane** (identity-enhanced session, serving core-dataset
> queries). The end state has **one plane**: the identity-enhanced session. What follows is the
> reasoning; §3.9 is what replaces the base plane's job.

```
  Entra login  ──── §3.5 ────►  identity-enhanced session on the carrier role
  [A] OIDC direct               ├─ Athena + Lake Formation  → core datasets, personal DB,
  [B] via Cognito bridge        │                             shared-workspace DBs
                                └─ S3 Access Grants (§3.9)  → personal prefixes, shared-workspace
                                                              prefixes, query results
```

**Why the base plane cannot survive, and it is not a preference.** STS attaches
`AWSIAMIdentityCenterAllowListForIdentityContext` to every identity-enhanced session automatically,
and it denies everything not on its list regardless of what the carrier role's own policies allow.
The **only** S3 actions on that list are the three S3 Access Grants operations (`s3:GetDataAccess`,
`s3:GetAccessGrantsInstanceForPrefix`, `s3:ListCallerAccessGrants`) — plain `GetObject`, `PutObject`
and `ListObjectsV2` are denied (§3.6). A file browser cannot run on that plane by calling S3
directly, so storage moves to Access Grants, and once it has there is no second plane left to keep.

Running both anyway was the previous design, and it was the more expensive answer to the same
problem: two credential paths, two isolation mechanisms for one product, and a hard wall between them.

**Three things this collapse buys, and one it costs.**

- **`${aws:PrincipalTag/username}` and `custom:shared_space_1..10` cease to exist.** With them go
  §6.1's writable-attribute privilege-escalation trap in its Variant-B form, the ten-slot membership
  ceiling, and the propagation delay `useSharedSpaceAccessRecovery` exists to paper over.
- **The cross-plane join question dissolves.** It was open — a statement joining a personal database
  against a core dataset "almost certainly will not work", because the two sat in different
  enforcement planes. On one plane both are Lake Formation grants against the same propagated
  identity, so the join is an ordinary query. Confirm it rather than assume it (§5.5 covers the
  cross-dataset case as G5); do not carry the old expectation forward.
- **Audit legibility improves** — every data access, storage included, is attributable to an
  Identity Center user rather than to a shared role with a tag.
- **The cost is a hard dependency on S3 Access Grants**, which appears nowhere in this architecture
  today. It is new infrastructure and a new account-wide singleton to own (§3.9, §4.4).

**The largest downstream consequence lands on shared spaces, not on the file browser.** Membership
is a principal tag today; on one plane there are no principal tags, so a member's access to a shared
space becomes **an Access Grant on its prefix plus a Lake Formation grant on its database**, issued
per (user, space) by the shared-space control plane rather than written as an attribute. That is a
new verb on an existing plane and it is **not** scoped anywhere yet — §3.9 states the obligation;
Phase 3 and Phase 5 are where it lands.

**What is unaffected:** the control-plane execution roles are ordinary IAM roles and are *not*
identity-enhanced, so their direct S3 and Glue grants keep working untouched. Every asynchronous
plane in this repo — file operations, table builder, table share, send-files, archive, data quality,
shared spaces — crosses this revision unchanged. That is what makes them safe to keep building now.

### 3.5 The token flow, and why the backend holds state

```
1. CreateTokenWithIAM                             [SigV4-signed, from the backend]
       IAM action = sso-oauth:CreateTokenWithIAM  (the ENDPOINT and CLI are sso-oidc;
                                                   the action prefix is NOT. Verified 2026-08-19)
       grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer
       assertion  = [A] <Entra ID token>  |  [B] <Cognito ID token>
                    (AWS permits an ID token OR an access token — "the token can be an
                     identity token or an access token". This plan assumes the ID token,
                     the shape AWS's own Entra walkthrough uses. Verified 2026-08-19)
   → IdC validates the signature against the TTI's JWKS, checks the audience,
     maps the configured claim (typically `email`) to exactly ONE IdC user
   → returns the identity context (and a refresh token, if that grant is enabled)

2. sts:AssumeRole on the carrier role
       ProvidedContexts = [{ ProviderArn     = arn:aws:iam::aws:contextProvider/IdentityCenter,
                             ContextAssertion = <identity context from step 1> }]
   → identity-enhanced credentials, held by the BACKEND (~1 hour), cached and reused

3a. athena:StartQueryExecution on the IdC-enabled workgroup   [from the backend]
   → Athena propagates the identity to Lake Formation
   → LF resolves THIS user's grants and applies the data cell filter for their level

3b. s3:GetDataAccess on the S3 Access Grants instance          [from the backend, §3.9]
   → prefix-scoped temporary credentials for THIS user's storage
```

**Steps 1 and 2 are the same in both variants; only the assertion differs.** That is the whole reason
this is one plan: the trusted token issuer registration and the claim mapping point at Entra **[A]**
or at Cognito **[B]**, and nothing downstream of the identity context can tell which.

**Step 3 runs in the backend, not the browser.** An earlier version of this section returned the
identity-enhanced credentials to the browser and had it call Athena directly. Arc B (SPEC-192 → 202)
settles the opposite for the current environment — the API assumes the role and makes the call — and
the same conclusion holds here for a stronger reason: the identity-enhanced session is the one
credential in this architecture that carries a **person's** whole Lake Formation grant set, and
handing it to a tab makes every browser-side exfiltration path a data-lake path. What crosses to the
browser is what crosses today: the results of a call, and presigned URLs for bytes (§3.9).

**Step 3 is AMBIGUOUS in the documentation, and the whole flow rests on it (2026-08-18).** The Athena
documentation for IAM Identity Center enabled workgroups lists *"Federated access to the Athena API"*
among the features trusted identity propagation is **not compatible with**. It also says queries in a
TIP workgroup *"cannot be run directly from the Athena console. They must be run from the Athena
interface in an EMR Studio that has IAM Identity Center enabled"*, and states that Athena SQL support
for TIP is available *"in both EMR Studio and SageMaker Unified Studio"* — both studio products. Read
one way, a plain `StartQueryExecution` from our own identity-enhanced session is exactly what that
bullet excludes.

**Read the other way it is not, and the second reading has the better evidence.** AWS uses *"federated
access to Athena"* elsewhere as a narrow, named feature: the page *Use Lake Formation and JDBC or ODBC
drivers for federated access to Athena* defines it as *"SAML 2.0-based federation with Athena using
Okta and Microsoft Active Directory Federation Services (AD FS) identity providers"*. The sibling
bullet in the same incompatibility list names that driver feature, so the two plausibly read as the API
half and the driver half of one SAML feature. Trusted identity propagation's own mechanism —
`AssumeRole` with `ProvidedContexts` — exists so that a caller *can* make AWS API calls carrying an
identity context, and the console exclusion is explicable by the console's session not being
identity-enhanced rather than by a prohibition on API callers.

**So: materially at risk, unsettled, and settle it by experiment — gate G7 (§5.5), in Phase 0.** It is
cheap, and if it comes back negative Phase 5 needs a different query surface: a studio product, or a
broker that re-implements masking (§3.2 point 4), and §3's design is reopened.

**Evidence added 2026-08-24 — the odds moved, the gate did not.** AWS's own JDBC/ODBC
trusted-identity-propagation plugins are ordinary client code exchanging a JWT, assuming an
identity-enhanced session and calling the Athena API with no studio product in the path, and AWS
documents them for use *"either as standalone drivers or with any BI or SQL tool"*. Expect G7 to
pass; run it anyway. §3.10 carries it.

> **Two supersessions on this passage, both 2026-08-18, and the second is a correction of the first.**
> It first read *"it is not documented as unsupported either; it is simply unaddressed"* — wrong,
> because the incompatibility list does name federated API access. It was then rewritten as
> *"documented as OUT OF SCOPE... expect G7 to fail"* — also wrong, and in the more expensive
> direction, because AWS defines that term narrowly on another page and the strong reading would have
> budgeted Phase 5 for a masking broker on the strength of it. Neither confident reading is supported.
> Do not install a third one without re-reading both live pages.

The same page carries five more facts to design around regardless, and one of them is nearly as
consequential as G7:

- **An IdC-enabled workgroup cannot be modified to support resource-level IAM permissions or
  identity-based IAM policies.** That constrains what is possible **inside such a workgroup**, and
  reading it as "the portal's isolation model is unworkable" is the mistake to avoid — through Phase 4
  the interim plane (Phase 1) keeps `${aws:PrincipalTag/username}` governing S3 and the personal Glue
  database, untouched by anything a workgroup does. *This bullet used to say the two planes were
  separate by design; §3.4 is superseded and they are separate only in TIME — the interim plane retires
  in Phase 5.* What it does reach is the query-results location: the workgroup's **user-identity-based
  S3 prefix** feature appends **`${user_id}`** to the results path and requires *Override client-side
  settings*, displacing the per-user result routing this app derives today. **PARTLY ANSWERED
  2026-08-19 against the live page — and only partly, so read the split carefully.** The
  **`${user_id}` prefix itself is OPTIONAL**: it is a checkbox at workgroup creation, *"(Optional)
  Choose **Create user identity based S3 prefix**"*, and selecting it *"automatically enables the
  override client-side settings option"*. What is **NOT** established is whether *Override
  client-side settings* can be left off for an IdC workgroup that declines the prefix — the console
  procedure's next step is *"confirm that **Override client-side settings** is selected"* and is
  **not** marked optional. That override is the half that actually bites, because it *"enforces
  [workgroup settings] at the workgroup level for all clients"*. **The surviving sub-question is the
  override, not the prefix.**
- **Queries time out after 30 minutes by default, one hour maximum**, in a TIP workgroup. The limit is
  not raisable past an hour.
- **Users must be assigned to the `IdentityCenterApplicationArn`** returned by `GetWorkGroup`, not
  merely to the account or the Lake Formation application.
- TIP with Athena is available in a **fixed Region list** (`us-east-1` is on it).
- `aws:CalledVia` context keys and Athena for Spark workgroups are incompatible with TIP as well. So
  is *"Federated access to Athena using **Lake Formation and** the Athena JDBC and ODBC drivers"* —
  and **that qualifier is load-bearing. CORRECTED 2026-08-24.** This bullet used to read *"federated
  access through the Athena JDBC/ODBC drivers"*, which states, to anyone reading the plan for an
  answer, that the client's Excel, Access and Power BI users lose their connection at Phase 5. **They
  do not.** The bullet names the **SAML-2.0 Okta/AD FS** driver feature — the same narrow feature
  this section invokes earlier when it declines the pessimistic reading of G7 —
  and AWS shipped **native TIP support in the drivers themselves** (JDBC 3.6.0 / ODBC 2.0.5.0,
  released 2025-09-10) after this plan was first written. **§3.10 carries it.**

- An IdC-enabled workgroup requires Lake Formation configured for IdC identities **and**
  *"Amazon S3 Access Grants must be configured to use Trusted identity propagation identities."*
  **S3 Access Grants appears nowhere in this architecture today** — it is new infrastructure, not a
  configuration flip, and it is the reason §3.6's allowlist policy carries only the three Access
  Grants operations and no plain `GetObject`.
- A workgroup's **authentication method cannot be changed after creation**, and an existing workgroup
  cannot be converted to an IdC-enabled one. The choice is made once, at create time.
- **Entitlement changes can take up to an hour to take effect**, which sets a floor under the
  reconciler's lag (§3.8) that no amount of running it more often will lower.

**Steps 1 and 2 run in a backend. This is not optional.** AWS states that the application "must
have a backend server component that can securely store credentials. Browser-based applications,
such as single page applications (SPAs), and other public clients are not supported." (That quote
sits on the *account-access for customer-managed applications* page — the §5 Path A feature — but
the conclusion holds for this flow too: `CreateTokenWithIAM` requires SigV4 signing, and the
accompanying guidance is unconditional: keep Identity Center access and refresh tokens on the
backend, never expose them to client-side code.)

This does not make the app a backend app. The SPA is not the OAuth client — the Lambda is, and
the SPA is a front end to it. This is the backend-for-frontend pattern. What crosses to the
browser is AWS temporary credentials, which is what the Identity Pool sent until SPEC-202 retired
it — so the posture would be a return to it rather than a new exposure, and today's browser holds
no AWS credentials at all. What must never cross is the Identity Center token.

**The backend needs session state in both variants — but for DIFFERENT reasons, and the difference is
a security property the baseline does not get.** The design conclusion is the same either way:
exchange once at login, hold the refresh token server-side (encrypted, keyed by session, with a TTL)
and use the `refresh_token` grant thereafter. Do not read that shared conclusion as a shared guarantee.

Identity Center refuses a token it has **already exchanged**, and documents **`jti`** as the claim
that makes reuse detectable. It states the `jti` half conditionally — *"this claim, **when present**,
prevents tokens that have the same JTI from being reused for token exchanges"* — while warning that
some authorization servers do not emit one. *This paragraph read "replay protection **is keyed on**
the `jti` claim … it does **not** document what happens to a replayed token carrying none" until
2026-08-19; both halves were wrong, and the [A] bullet carries the correction.*

- **[B]** Cognito emits `jti` / `origin_jti`, but **only when `enable_token_revocation` is on**. The
  current IaC does not set it and relies on the Terraform provider default of `true`. Pin it
  explicitly when the bridge pool is built, or the protection is silently absent.
- **[A] — Entra does NOT emit `jti`, and it cannot be made to.** It emits **`uti`**, which Microsoft
  describes as *"equivalent to `jti` in the JWT specification"* — a different claim name, in v1.0 and
  v2.0, ID tokens and access tokens alike. `jti` is **not in the optional-claims reference**, so it
  cannot be requested, and nothing in AWS's documentation says Identity Center reads `uti` as a
  substitute. **AMENDED 2026-08-19 — the old conclusion was too strong, and do not overcorrect
  either.** The trusted-token-issuer page states *"If IAM Identity Center receives a request to
  exchange a token that IAM Identity Center has already exchanged, the request fails"*, and that
  *"IAM Identity Center protects against the replay of tokens **based on the claims in the token**"*.
  So this bullet's old closing claim — that an Entra ID token captured before its `exp` is *"on the
  evidence available, **re-exchangeable**"* — is **withdrawn**: a second exchange of the *same* token
  is refused with or without a `jti`. What stays undocumented is how strong the dedup key is without
  one. Settling that needs a **two-exchange test on a real Entra assertion** — which is *not* what G8
  is (§5.5 calls G8 a conversation with the tenant owner, not an experiment); run it alongside,
  whenever the exchange is first standing up. Record this as a property that is **weaker** in the
  baseline variant, not one the baseline lacks.
- **The compensating control, stated rather than assumed:** the assertion never reaches the browser
  and is exchanged exactly once, server-side, in the login handler — so the exposure is a token
  stolen from the backend or from the IdP round trip inside its own validity window, not a token
  replayed from a tab. That is the same exposure the OIDC code exchange already carries. It is
  narrow, and it is **not zero**, and it is the reason session state here is a design requirement
  rather than a consequence of replay protection.
- **Settle it with G8's own experiment.** The exchange is already being stood up to answer G8; while
  it is up, exchange one Entra assertion twice and record what Identity Center does. That is the only
  evidence that would move this.

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
  on the core-dataset databases, `lakeformation:GetDataAccess`, and the three S3 Access Grants
  operations (§3.9). Deliberately **no direct S3 read** on dataset data — Lake Formation vends it,
  and the allow-list below denies it anyway.
- **One role for everyone.** All differentiation is in Lake Formation via the propagated identity.

Note that the identity-enhanced session is restricted by the
`AWSIAMIdentityCenterAllowListForIdentityContext` managed policy, which STS attaches
automatically and which denies everything not on its list — regardless of account, and regardless
of what the carrier role's own policies allow. **Answered (2026-07-31, policy v12):** Athena and
the Glue catalog read actions are on it; the **only S3 actions on it are the three S3 Access
Grants operations** (`s3:GetDataAccess`, `s3:GetAccessGrantsInstanceForPrefix`,
`s3:ListCallerAccessGrants`). Plain `GetObject` / `PutObject` / `ListObjectsV2` are denied, so
**the file browser can never run on this plane via direct S3 calls.**

> **AMENDED 2026-08-18.** This paragraph used to end *"the two-plane split already routes around
> this"*. There is no two-plane split (§3.4): this constraint is not routed around, it is **obeyed** —
> storage moves onto S3 Access Grants (§3.9). It still motivates gate P3 in §5.4, and P3 now decides
> whether the permission-set path can serve any storage access at all rather than whether it can
> serve a second plane.

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

### 3.9 The storage plane — S3 Access Grants

§3.4 collapsed the two credential planes into one, and the allow-list in §3.6 is why: on an
identity-enhanced session, plain S3 is denied. **S3 Access Grants is what replaces
`${aws:PrincipalTag/username}`**, and it is new infrastructure — it appears nowhere in this
architecture today, and it is an account-wide singleton to own in the coordination contract (§4.4).

**How it is configured** (all in the central account):

1. Create an **S3 Access Grants instance** — one per account and Region — and associate it with
   Identity Center so it accepts trusted-identity-propagation identities. That association is also a
   **prerequisite of the IdC-enabled Athena workgroup**, not an optional extra.
2. **Register a location**: the bucket or prefix, plus an IAM role Access Grants uses to vend
   credentials for it, whose **permission** policy is where per-user narrowing lives (below). Its
   **trust** policy needs a **second statement** granting **`sts:SetContext`** — beside the
   `sts:AssumeRole` one, not folded into it — conditioned on
   `ForAllValues:ArnEquals` over `sts:RequestContextProviders` =
   `arn:aws:iam::aws:contextProvider/IdentityCenter`, plus `aws:SourceAccount` and an `aws:SourceArn`
   naming the **location**.
3. **Create grants**: bind an **Identity Center user or group** to a **prefix** with
   `READ` / `WRITE` / `READWRITE`.

**The backend calls `GetDataAccess` on the user's identity-enhanced session and gets back
prefix-scoped temporary credentials.** From there the bytes reach the browser the way Arc B already
settles it — the backend presigns and the browser redeems the URL directly against S3, so large
transfers stay off compute without the browser ever holding credentials. **That presigning step is
unproven against Access-Grants-vended credentials and is gate G9** (§5.5); if it fails, the fallback
is handing the scoped credentials to the browser, which is what the target design assumed, and
SPEC-202's load-bearing negative has to be re-worded before it is run.

**Isolation is expressed in TWO places, and confusing them is the mistake to avoid.** A grant's scope
is **literal path text** plus a trailing `*` — `CreateAccessGrant` documents no variable substitution
in `S3SubPrefix`, so *there is no such thing as one variable grant covering every user*. The
per-user narrowing that looks like a variable lives in the **location role's permission policy**,
where `${identitystore:UserId}` is an ordinary IAM policy variable — AWS's own sample role policy for
an IdC-enabled Athena workgroup resolves `arn:aws:s3:::.../${identitystore:UserId}/*` exactly that
way. So the shape is *one broad grant narrowed by a role policy*, or *one literal grant per user*,
and the choice is real either way. **For the shared-space bucket it is already settled — §3.11 —
and the two buckets may differ**: membership is a relation in our registry, and no policy variable
can consult it, so that bucket forces the literal form whatever this one decides.

> **CORRECTED 2026-08-18, at review.** An earlier version of this section offered
> `${identitystore:UserId}` as a **grant scope** and called it "one standing grant and no provisioning
> at all — the strongest practical argument for the variable form". That option does not exist as
> described. It is also **not** the same token Athena uses: Athena's user-identity result prefix
> appends **`${user_id}`**, substituted by Athena when it writes results, where
> `${identitystore:UserId}` appears in an **IAM policy**. Two mechanisms, two spellings, one easy
> conflation.

**Three things this plane must answer that no section answers yet.**

- **Does the per-user prefix stay the username?** The core invariant — username = S3 prefix = Glue
  database name (§2 item 3; the principal tag is this plan's own addition to it) — has survived every
  revision so far, and a literal per-user grant preserves it. Narrowing by
  `${identitystore:UserId}` in the location role's policy does not: the prefix becomes an Identity
  Store id. **Query results are the part most likely to move** — if *Override client-side settings*
  turns out to be unavoidable on an IdC workgroup (§3.5's workgroup bullet, narrowed 2026-08-19) —
  so the invariant may hold for the file browser and break for results. Decide it deliberately; it
  strands data if it changes afterwards.
- **Who creates a user's grant, and how many are there?** A literal per-user grant is a provisioning
  step and belongs beside database creation and tagging in the provisioning contract (§2 item 7),
  with the same latency question. A role-policy-narrowed grant is standing and provisions nothing —
  which is the genuine argument for that shape, now that the imaginary one is gone. **Either way the
  instance has a ceiling**: one Access Grants instance per account and Region, **1,000 locations**
  and **100,000 grants** on it, shared with every other tenant of the account (§4.4).
- **Shared spaces need a grant per (member, space), and nothing issues one today.** Membership is a
  Cognito attribute write today; here it is an Access Grant on the space's prefix **plus** a Lake
  Formation grant on the space's database. Both are per-user and registry-driven — the shared-space
  control plane already knows the membership and is already the privileged writer, so this is a new
  verb on an existing plane rather than a new plane. **The shared-space control plane owns both
  halves, and they are one spec**: they are written and revoked at the same moments (add member,
  remove member, leave, delete space), and splitting them across two owners is how a member ends up
  holding one and not the other. §3.8's reconciler is the **pattern** to follow — desired state,
  read current, converge — not a second owner. **That design is §3.11.** Phase 3's
  inventory sizes it; Phase 5 executes it. Read its cutover ordering before planning Phase 5 — it
  found a standing role-level Lake Formation grant that becomes a union grant on every space the
  moment the tags retire.

**What does not change:** the control-plane execution roles keep their direct S3 grants and are
untouched by any of this (§3.4).

### 3.10 Third-party driver access — Excel, Access, Power BI and anything else on ODBC/JDBC

**This section exists because the plan previously implied the wrong answer**, and the wrong answer
here is expensive: read one way, §3.5's incompatibility bullet says every Excel, Access and Power BI
user in the organization loses their connection at Phase 5. It does not say that (§3.5's correction
of 2026-08-24). **Driver users survive the transition.**

**What they gain is ONE entitlement model where there are currently two** — and stating it any
more strongly than that would be false. *(**CORRECTED 2026-08-24, at review.** This paragraph first
claimed they "arrive better governed than they are today" and that an ODBC client gets "no per-user,
per-level masking at all". Both were wrong, for the reason the rest of this paragraph gives.)* These users are *not* ungoverned today: they reach Athena
through SAML federation **with Lake Formation** (§2 item 15), so they already get per-user,
column-level enforcement — just from a parallel grant set keyed on SAML principals, maintained
beside the portal's. After Phase 5 both surfaces are governed by the same grants keyed on the same
Identity Center principals, projected by one reconciler (§3.8). That is a real gain in
maintainability and audit legibility. It is **not** a gain in whether masking exists.

AWS shipped native trusted-identity-propagation support in the drivers on **2025-09-10** (announced
the 11th), in **JDBC 3.6.0** and **ODBC 2.0.5.0** — after this plan was first drafted — and gave it
its own page:
*"When you access Athena from tools like PowerBI, Tableau, or DBeaver, your identity and permissions
automatically propagate to Athena through IAM Identity Center."*

**Two plugins, and which one a user gets is decided by the machine they sit at.**

| Plugin | Value | ODBC floor | JDBC floor | Shape | For |
|---|---|---|---|---|---|
| Browser TIP | `BrowserOidcTip` | **2.0.6.0** (2025-11-21) | **3.7.0** (2025-11-21) | Runs the whole OAuth 2.0 code flow in the user's default browser and fetches the JWT itself | Excel, Access, Power BI **Desktop** — a person at their own machine |
| JWT TIP | `JWT_TIP` | 2.0.5.0 (2025-09-10) | 3.6.0 (2025-09-10) | Takes an already-obtained JWT as a **connection parameter**; something else must supply it | Power BI **Server**/gateway, Windows Terminal Server, **Remote Desktop Services** — anywhere the loopback port is shared. Also what AWS's own DBeaver walkthrough uses |

**The two floors are not the same release, and the JDBC one is the trap:** 3.6.0 and 2.0.5.0 shipped
JWT TIP on 2025-09-10 (announced 2025-09-11); the **browser** plugin arrived two months later in
3.7.0 and 2.0.6.0. A JDBC rollout planned against "3.6.0, the version the announcement names" gets
no browser flow at all.

The split is AWS's own recommendation, not this plan's invention: Browser TIP *"is specifically
designed for single-user desktop environments"*, and in shared environments the default loopback port
**7890** is shared between users — *"If these security controls cannot be implemented, we recommend
using the JWT trusted identity propagation plugin instead."*

**Power BI needs no separate answer because it is ODBC underneath.** The Microsoft Power BI connector
for Athena takes an **ODBC DSN** as its input; Excel (*Get Data → From ODBC*) and Access (linked
tables) take one the same way. One driver, one DSN shape, three clients — which is also why the
version floor and the rollout below are a single piece of work rather than three.

**What the connection needs that this account does not have today:**

- An **Entra app registration for the driver flow**: `client_id`, the
  `.well-known/openid-configuration` URL, and `http://localhost:7890/athena` allowlisted as a
  redirect URI. `Scope` must carry `openid` plus whatever claims the Identity Center trusted token
  issuer mapping reads — **the same claim §3.5 step 1 maps and §2 item 12 constrains** (user name,
  email or external ID). That coupling is worth stating plainly: get that claim wrong and both
  surfaces fail together. *It is a different claim from §6.1's catalog-safe username, which keys the
  S3 prefix and which drivers never touch — the plan keeps the two apart everywhere else and this
  section must too.*
- An **Application Role** (performs the JWT exchange, reads the workgroup tags, resolves the access
  role) and an **Access Role** (the identity-enhanced session that reaches downstream services).
  These are the driver path's analogue of §3.6's carrier role and they are **separate roles** — the
  portal's carrier role is not reusable here.
- A **customer-managed Identity Center application**, needing the management account or a delegated
  administrator (§4.5). Distinct from the portal's own (§4.5, Phase 5).
- **One tag key on TWO resources, with different values** — and missing either breaks the same
  resolution chain. Both are `AthenaDriverOidcAppArn`: on the **Identity Center customer-managed
  application** its value is the **Access Role ARN**, and on the **Athena workgroup** its value is the
  **Identity Center application ARN**. The Application Role walks that chain, which is why it needs
  `athena:ListTags*` and `sso:ListTags*`. Tagging both is not optional polish: AWS's setup page notes
  it is what *"eliminate[s] the need for users to provide `AccessRoleArn` and
  `CustomerIdcApplicationArn`"* in every desktop's connection string. An IaC obligation on **both**
  resources, easy to miss because nothing else in this plan tags either.
- **`WorkgroupArn` and `Workgroup` are two separate parameters** — the ARN names the workgroup
  **carrying the tags**, `Workgroup` names where queries run, and *"both parameters must be set
  explicitly"* even when they are the same workgroup. Stated on **both** browser plugin pages, ODBC
  and JDBC; the JWT plugin reference pages omit it (though the setup page's DBeaver walkthrough does
  tell `JWT_TIP` users the two must match), and JDBC's `WorkGroupArn` defaults to `primary` on both
  its plugins — which is its own way to fail quietly.
- AWS publishes a **CloudFormation template** for the driver-side setup. Read it before writing the
  OpenTofu; it is the closest thing to a reference implementation.

**Six operational facts to plan the rollout around:**

- **The practical version floor is higher than the feature floor.** 2.0.6.0 gets Browser TIP, but
  **2.1.0.0** (2026-03-20) is a security release AWS says to take *"as soon as possible"* and it
  carries breaking changes — SSL verification on by default, TLS 1.2 minimum, and Browser SSO OIDC
  moved from Device Code to Authorization Code with PKCE. Plan the desktop rollout against 2.1.0.0 or
  later, not 2.0.6.0.
- **2.3.0.0 (2026-08-21) fixes Power BI specifically** — empty-string filter patterns from ADO.NET
  clients returning zero rows, and `SQLTables`/`SQLColumns` omitting tables beyond the first 200 in a
  schema **when a metadata results page was empty** (a conditional bug, not a flat 200-table
  ceiling — dropping that qualifier would be the same mistake §3.5 exists to correct). It also
  **changes the driver's `User-Agent`** to match `*lib/AmazonAthenaODBC#*`, which AWS flags **action
  required** for any `aws:UserAgent` IAM condition, log filter or IdP sign-on rule matching the old
  value; nothing in this repo matches on it today, so re-check rather than assume in the successor
  account. Same release, relevant to a managed desktop fleet: on Windows the driver now verifies TLS
  against the **Windows system certificate store and ignores `TrustedCerts`**, and on Linux it finds
  the CA bundle at runtime honouring `CURL_CA_BUNDLE` / `SSL_CERT_FILE`.
- **Token caching is ODBC-specific advice, and the security caveat does NOT transfer to JDBC.** On
  ODBC, turn `JwtTipFileCache` on for BI tools — Power BI opens multiple processes and
  re-authenticates in each without it — and off on shared hosts, where the cache can leak a token
  between users with similar connection strings; since 2.1.0.0 it is plaintext JSON under
  `user-profile/.athena-odbc/`, owner-only. **JDBC has no file cache at all:** `JWT_TIP` caches
  in-memory by default with no parameter, and `BrowserOidcTip` takes `EnableTokenCaching` (default
  `FALSE`). Nothing is written to disk, so the plaintext-on-disk concern is ODBC's alone.
- **The two drivers spell the same parameters differently**, which matters now that this section sets
  a floor for both. ODBC's `client_id` / `client_secret` / `listen_port` / `role_session_name` /
  `JwtTipFileCache` are JDBC's `OidcClientId` / `OidcClientSecret` / `IdpPortNumber` /
  `JwtRoleSessionName` / `EnableTokenCaching`. The redirect URI, the 7890 default and the `Scope`
  default are identical on both — do not build a JDBC connection string from an ODBC example.
- **The 30-minute default / one-hour maximum query timeout is documented for *Identity Center
  enabled* workgroups**, so it reaches driver users **if** the driver path lands on one — which the
  migration subsection below shows is a choice, not a given. Decide the workgroup first — but do not
  read that as an escape hatch: AWS words the **one-hour maximum** against *"Trusted identity
  propagation workgroups"* rather than Identity-Center-enabled ones, so the ceiling may well bite on
  an IAM-enabled workgroup running TIP too. A large Excel or Access pull is likelier to meet it than
  a portal query is.
- **Entitlement changes take up to an hour** (§3.5). "I was granted access and Excel still says
  denied" is expected behaviour and needs saying out loud before it becomes a ticket.
- **Query results are Access Grants territory** — again only on an IdC-enabled workgroup, where
  results land in the workgroup's location governed by S3 Access Grants. The narrowing AWS samples
  for that case is the `${identitystore:UserId}` form in the **location role's policy**, not a grant
  (§3.9 draws that distinction; keep it). This is **the same pull §3.9 already records** toward query
  results resolving differently from the file browser — not new evidence, but now reaching a second
  population of users, which strengthens the case for deciding both surfaces at once.

**What driver users do NOT get, and it is not a regression.** The Access Grants entitlements §3.9 and
§3.11 issue for personal prefixes and shared-space prefixes serve the **portal's file browser**. A
driver user queries the **catalog**: reaching their personal database or a shared space's database
from Excel needs the matching Lake Formation grant, which this app already issues. Nothing here gives
Excel a file browser and nothing in this plan proposes one.

#### The migration — confirmed necessary, 2026-08-24

**The client's driver users are on the SAML path today** (§2 item 15), which is the one answer that
turns this section from a compatibility note into a work item. AWS states the incompatibility from
the SAML side too, and unambiguously: *"Federated access using the JDBC and ODBC drivers is **not
compatible** with the IAM Identity Center trusted identity propagation feature."* There is no
session that is both. Every one of those desktops is a cutover.

**What is actually changing, laid out so the size of it is legible:**

| | Today (SAML) | After (TIP) |
|---|---|---|
| Driver | ODBC **1.1.3+** / JDBC 2.0.14+ | ODBC **2.1.0.0+** / JDBC **3.7.0+** — a major-version jump on ODBC, not an upgrade |
| Auth plugin | `BrowserAzureAD` / ADFS / Okta, with `LakeformationEnabled` | `BrowserOidcTip` (desktop) or `JWT_TIP` (shared host) |
| IdP protocol | SAML 2.0 | **OIDC** — a different app registration, not a re-pointing of the old one |
| AWS principal | An IAM role reached by `AssumeRoleWithSAML` | An identity-enhanced session on the Access Role |
| LF grants keyed on | SAML users and groups | **Identity Center principals** |
| Workgroup | A regular workgroup | **Either kind — this is a choice we make** (see below), not something the platform forces |

**Three consequences. The first was stated wrongly in this section's first draft and is corrected
here — read it rather than remembering it.**

- **The coexistence window is real, but it comes from the ACCOUNTS, not from the workgroups — and
  the workgroup topology is a choice this project must make and enforce, not a platform guarantee.**

  > **CORRECTED 2026-08-24, at review.** This bullet first claimed the two paths *"necessarily live
  > on different workgroups"* because an IdC-enabled workgroup cannot be converted in either
  > direction, and concluded *"no flag day"*. Both halves were wrong, and the first would have led
  > an implementer straight into the configuration it promised was impossible.

  **The driver TIP path does not require an Identity Center enabled workgroup.** AWS documents it on
  both kinds, with different access-scope sets — *"select `lakeformation:query` for IAM-enabled
  workgroups, or `lakeformation:query`, `athena:workgroup:read_write`, and `s3:access_grants:read_write`
  for Identity Center-enabled workgroups"* — and states that *"Existing Athena SQL workgroups can
  propagate identity to downstream services."* Non-convertibility only says one workgroup cannot be
  **both auth methods**; it says nothing about where the driver path has to live. **And AWS's
  documented setup path tags an EXISTING workgroup** (`AthenaDriverOidcAppArn`), creating none — so
  an implementer following the quickest documented route would tag the workgroup the SAML fleet is
  already on. Putting TIP on its own workgroup is the right call here, but it is **our decision, to
  be enforced in IaC**, and the plan must not describe it as structural.

  **What genuinely permits a phased migration is that the two environments are different accounts.**
  The SAML path lives in the old account and keeps working there through Phases 1–5; the successor
  account brings up the TIP path beside it. A desktop migrates by being re-pointed at the new
  account, one at a time, at the endpoint owners' pace.

  **So there IS a deadline, and it is §6.5's write freeze.** The successor account has no SAML
  identity provider, no `AssumeRoleWithSAML` role and no SAML-keyed Lake Formation grants, and no
  phase creates any. When Phase 6 freezes the old account, an unmigrated desktop reads frozen data;
  when it is decommissioned, that desktop reads nothing. **The fleet must be migrated by the freeze**
  — which is a soft, dated deadline rather than a flag day, but it is not "at whatever pace".

  **One thing remains undocumented and should be treated as unknown:** whether the SAML feature and
  a TIP workgroup can both be live in a *single* account. AWS states the incompatibility in a
  considerations list without ever naming its granularity, and Lake Formation's Identity Center
  integration notes list no SAML-coexistence limitation. It does not matter while the two paths sit
  in two accounts. It matters entirely for the dual-key fallback below, which is the one plan that
  needs both in the successor account.
- **Re-keying the grants is free here, and it would not be in an in-place upgrade.** Their existing
  Lake Formation grants are keyed on SAML principals and none of them survive. But §2 item 5 already
  rebuilds catalog and grants in the successor account rather than copying them, and §3.8's
  reconciler already projects the grant matrix onto Identity Center principals — so the re-key *is*
  the rebuild. Nothing extra is owed. This is the single largest reason the SAML answer is less
  expensive than it first sounds.
- **G8 now gates the desktop fleet, not just the portal, and that raises its stakes.** `BrowserOidcTip`
  needs an OIDC IdP: an `IdpWellKnownConfigurationUrl` and a `client_id`. Under **Variant A** that is
  Entra directly and the drivers point where the portal points. Under **Variant B** — Entra SAML-only
  — the portal gets a Cognito bridge, and the drivers would have to authenticate against **that
  bridge** too, or fall back to `JWT_TIP` with something else minting the JWT for each desktop. So a
  G8 failure is materially worse than §5.5's row implies: it is not only a Cognito bridge to build
  and delete, it is a Cognito bridge the whole desktop fleet points at. **Ask G8 with the driver
  fleet in the question.**

**Weak evidence on G8, in both directions, recorded so it is not overread.** That the client uses
SAML for Athena today says little. The drivers have carried non-SAML Identity Center authentication
(`BrowserSSOOIDC`) since ODBC 2.0.1.0 in 2023 — what was **SAML-only until 2025-09-10** is
Lake-Formation-governed *fine-grained* access under a corporate identity, which is exactly what these
users need. So their being on SAML is evidence about the calendar, not about the tenant. Pointing the other way, AWS's own `BrowserOidcTip`
documentation names *Microsoft Entra ID* when describing which claims the ID token must carry, which
is AWS treating Entra as an expected OIDC issuer for this exact plugin. Neither settles G8; it stays
a conversation with the tenant owner.

**The fallback if the desktop migration cannot finish before the freeze: dual-key the grants — and
price it honestly.** The reconciler can project the same matrix onto *both* SAML principals and
Identity Center principals, so unmigrated desktops keep querying while the portal runs on the
identity-enhanced session. The cost is not "a second isolation model and double the grants": it is
**rebuilding the SAML stack in the successor account** — a SAML identity provider, an
`AssumeRoleWithSAML` role, a regular workgroup and Lake Formation configured for SAML principals,
none of which appears in any phase and all of which cuts against §2 item 1 and §3.3's OIDC posture.
It also depends on the single-account coexistence question above, which is unanswered. **Keep it as a
named option with a mandatory end date, not as a comfortable plan B** — but have it costed before the
freeze date is set, rather than discovering the need late.

**Two things this section does NOT claim, stated so nobody reads it as settled.**

- **AWS names Power BI, Tableau and DBeaver. It never names Excel or Access.** Both are ordinary ODBC
  DSN consumers and the Power BI connector's own documentation proves the DSN path works, so the
  architecture supports them — but *"an ODBC client should work"* is a deduction, not a vendor
  statement. **Test Excel and Access explicitly, Access first:** linked tables reconnect often, and a
  browser prompt per reconnection is the failure mode that would make it unusable in practice while
  passing every architectural test.
- **This is strong evidence for gate G7, not a substitute for running it.** The driver plugins do
  precisely what §3.5's **steps 1 → 3** do — exchange a JWT, `AssumeRole` into an identity-enhanced
  session, then call the Athena API from ordinary client code, with no studio product anywhere in the
  path. AWS says it outright: *"You can use both JDBC and ODBC either as standalone drivers or with
  any BI or SQL tool with trusted identity propagation using this authentication plugin."* That makes
  the pessimistic reading of *"federated access to the Athena API"* very hard to sustain. **The
  counter-evidence, stated so a reader does not hit it cold and think this section overclaimed:** the
  workgroups page still scopes Athena TIP to EMR Studio and SageMaker Unified Studio and says TIP
  queries *"cannot be run directly from the Athena console"*. The console exclusion is explicable —
  the console's own session is not identity-enhanced — but the studio framing is not fully reconciled.
  **Expect G7 to pass. Still run it**: a vendor driver may hold a privileged path our own code does
  not.

---

### 3.11 Shared-space entitlements — the projection that replaces the tag

A member's access to a shared space is a **principal tag** today. `shared-space-add-members` writes
`custom:shared_space_k` on the member, the Identity Pool stamps it, and the portal role's policy
expands `$${aws:PrincipalTag/shared_space_k}` into the S3 prefix, the `ListBucket` condition and the
Glue ARNs. One attribute write grants everything.

On an identity-enhanced session there are no principal tags, and §3.6's allow-list denies plain S3
outright. So a membership becomes **two grants** — an S3 Access Grant on the space prefix and a Lake
Formation grant on the space database, per (member, space) — and something has to issue and revoke
them at the six moments a membership changes. This section is that design. It was specified as
SPEC-204 and moved here on 2026-09-01: it cannot be built or tested until the Access Grants instance
exists, and a spec that cannot be built is a spec that silently rots (which it had begun to do — see
*What the code already does*, below).

**The registry stays the source of truth and the verbs stay unchanged in what they decide.** What
changes is that a membership decision now has to be *projected* into two external systems that can
drift from it.

**The entitlement is a pair, and it is one operation.** A member holding one half and not the other
is a support ticket that reads as a product bug: files but no tables, or tables that return
`AccessDenied` on their own data. A partial projection therefore fails the whole operation and
reports one outcome. Within the pair the order is **S3 Access Grant first, Lake Formation second** —
least privileged first. With the space's data location registered with Lake Formation in hybrid mode
(§6.2), an LF grant alone is enough for Athena to read the whole space through LF credential vending,
while the Access Grant is what the file browser needs; LF-first therefore hands a member the ability
to query everything while the UI still looks empty. The Access Grant is issued at **`READWRITE`** on
the space prefix, mirroring the `s3:PutObject`/`s3:DeleteObject` the tag-scoped statement grants a
member today — a member writes to a shared space, so a read-only grant would be a regression.

**The pair is expressed once, in `shared-space-common`, and every trigger calls it** — not in
`cpcommon`, which owns algorithms rather than a domain's wording. A test asserts no verb issues a
`grant_permissions` or a `CreateAccessGrant` of its own, and the reason it matters here is that
revocation must mirror the grant exactly. **That test needs a carve-out between cutover steps 1 and
3**, because `create_space` issues the role-level grant until step 3 removes it — the two
requirements are opposite for exactly as long as the interim plane runs. **The space prefix is derived by the existing path builder,
never reconstructed:** a grant scoped one segment wrong is a grant on somebody else's data.

**The member's Lake Formation set is DERIVED, and reusing the role's constants is a privilege
escalation.** `shared-space-common/config.py` holds `DATABASE_PERMISSIONS`
(`DESCRIBE`, `CREATE_TABLE`, `ALTER`, `DROP`) and `TABLE_PERMISSIONS` (`SELECT`, `INSERT`,
`DESCRIBE`, `ALTER`, `DROP`). Those were sized for the **shared portal role**, whose effective rights
are then narrowed by IAM: `portal-role-shared-space.json.tftpl` grants ten Glue actions and **not
`glue:DeleteDatabase`, not `glue:UpdateDatabase`**, so today a member cannot drop or alter a shared
space's catalog. Grant the role's LF set straight to a member's principal with that narrowing gone
and `DROP`/`ALTER` on the **Database** become live. The member set is the intersection: **Database —
`DESCRIBE`, `CREATE_TABLE`; Tables — `SELECT`, `INSERT`, `DESCRIBE`, `ALTER`, `DROP`**.

**Shared spaces force the literal per-member grant, and that settles half of §3.9's fork.** A
location-role policy variable narrows by properties of the *caller*; membership is a relation in our
registry, and no IAM variable expands to "the spaces alice belongs to". The two buckets may therefore
use different forms, and the personal-prefix decision does not have to wait for this one. Each grant
names exactly one space prefix — no wildcard, no grant covering two spaces.

**Principal resolution is the one place this touches a directory we do not own.** The portal username
resolves through `identitystore:GetUserId` on the configured attribute, cached per container. The
TTL is bounded by how quickly a directory change must be honoured, not by cost: the mapping is stable
for the life of a user, so the bound exists to stop a warm container serving a stale principal after
a rename, and it is stated where it is built. An **unresolvable member is a refusal, not a skip** — skipping produces a member the
registry lists with no entitlement and no error anywhere. A member absent from Identity Center and a
resolution *fault* get different reason tokens: the first means provisioning has not run for them,
the second means the directory is unhealthy, and they look identical in a generic error. The resolved
principal id may be logged; the claim value it was resolved from may not.

> **This is the one genuinely load-bearing dependency on Phase 0, and it is a requirement on that
> decision rather than an assumption.** The registry holds the **portal** username, which is
> catalog-safe `^[a-z][a-z0-9_]{2,62}$` and can never be an email address, so this design requires
> that the portal username equals exactly one Identity Store attribute value — most plausibly
> `UserName` or `ExternalId`. §6.1 leaves open whether the portal username is *derived* rather than
> stored; **if Phase 0 decides derived, this design needs a stored username → principal map** it
> currently refuses on purpose. **§3.12's username list is the candidate answer** — if a row carries
> the Identity Store attribute beside the username, that list *is* the map, supplied rather than
> invented.

**Six triggers, and one that deliberately is not.** Projection runs on **create** (the owner),
**add-members**, **remove-members**, **leave**, **delete** and **`shared-space-forget`**.
`acknowledge-membership` is **not** a trigger: acknowledgement is display-only and access is granted
at add time, so making it one would deny an added member until they signed in. Create's projection
runs **after** `reg.finalize(..., "active")`, not among the provisioning steps — `reserve` writes
`status: "provisioning"`, for which `is_active_member` is false, so a projection placed with the
other create steps entitles nobody. Projection always runs **after** the registry write commits.
Revocation belongs beside **`membership.clear_slot`** — the one call every membership-ending path
already makes, in `delete`'s `_revoke`, in `forget` on both its paths, in `leave` and in
`remove-members` — and **not** in `teardown.py`, which only the *destroying* branch of a delete
reaches. Placed there it would never run on the ordinary emptying delete, and every member of an
emptied space would keep live grants on live data until the sweep noticed. `_revoke`'s own docstring
already calls the Cognito slot "the S3 and Glue grant", which is the seam this replaces. It is a verb on the existing shared-space state machine under the
existing execution role, reusing the plane's FIFO queue, its DLQ and the DLQ drain — no new plane —
and it does **not** inherit the roster fan-out's best-effort posture: a stale roster is cosmetic, a
missing entitlement is total loss of access.

**Decided 2026-09-06 — a seventh trigger is asked for, and is deliberately not built yet.** An
operator break-glass transfer should be able to reach somebody who is not a member, the UI staying
members-only. It waits for this projection: on the interim plane it would contradict the transfer
verb's own stated premise that membership does not change, and would be rebuilt against grants
straight after. The threat model is not open — `docs/decisions/control-planes.md`'s SPEC-217 entry
already records that an operator row grants a stranger live access, which is the objection SPEC-208
raised in putting a non-member transfer out of scope. What the work carries is a rule still stated
as absolute in the API contract, the browser types, the refusal copy and the Help, and this
section's writer set, which is pinned by equality. Reachable today as an `add` file and a
`transfer` file — one space takes one action per file, but one sweep processes both.

**Convergence is the event plus a sweep, and the sweep must revoke.** Events drift silently — a
failed run, a dead-lettered message, a manual registry edit — and a sweep alone is too slow for a
member added at 09:00. §3.8's reconciler is the pattern, with the registry as this one's config. Per
space: compute the desired set with `is_active_member` (never by reading `members` directly, which
differs on a non-active space), read the current set, grant the difference, **revoke the surplus**. A
revocation lost by a failed event is a member who still reaches a space they left, and a grant-only
reconcile never repairs it. A space whose `status` is not `active` has no desired entitlements. The
sweep reports corrected drift at `warn` with per-space counts — silent correction hides a broken
event path indefinitely — and it reconciles the SPEC-203 membership index on the same pass, under the
same re-read rule: for each space it compares the index's member list against the registry's, writes
the registry's version where they differ, and reports the correction as drift. That is what closes
that index's stated staleness residual, and it is the reason two other documents defer here.

**The sweep re-reads each registry record immediately before acting and abandons that space if the
ETag moved.** Without it its authority runs backwards: it reads `finance_space`, computes a desired
set including `alice`, `remove-members` commits and revokes her, and the sweep — still holding the
stale set — grants the difference and **puts her back**. A re-read plus an ETag comparison is enough
because the sweep is idempotent and can simply skip.

**Cadence is hourly, and the number is derived rather than round:** Identity Center entitlement
changes take up to an hour to take effect (§3.5), which floors the end-to-end latency no sweep can
beat, so a faster sweep spends API quota to beat a floor it cannot beat. The event path delivers the
fast case; the sweep bounds how long a lost event can hide.

**Idempotency in both directions, and the revoke direction carries the traps.** Granting what exists
succeeds and creates no duplicate; revoking what does not exist succeeds. Revocation matches by
**(principal, scope)**, never by an id this system stored — a stored id is a second source of truth
that strands grants nothing can find. `DeleteAccessGrant` takes an `AccessGrantId`, so matching by
scope means a paginated `ListAccessGrants` then a delete, and `lakeformation:ListPermissions` is the
same shape: a sweep is O(spaces × members) list calls, not O(1). `identitystore:GetUserId`, the Lake
Formation grant/revoke/list calls and `s3control:ListAccessGrants` are all low-TPS, so the sweep's
pacing is **computed** against the tightest of them from the Phase 3 pair count. Two runs projecting
the same pair must produce neither two grants nor a spurious failure, and that is asserted against
genuinely concurrent runs rather than inferred from the queue — FIFO orders **delivery**, not
executions.

> **Every idempotency claim above is a claim about the behaviour of the S3 Access Grants and Lake
> Formation APIs, and offline it can only be asserted against a stub we wrote.** A double-run test
> against a fake programmed to be idempotent cannot fail. Offline tests are therefore **shape
> assertions that state what they do not prove**, and each property is a **live check in this
> phase**: grant twice, revoke twice, revoke what is absent, and two concurrent projections of one
> pair, against the real APIs in the non-production account.

**A member with no access must never be silent.** The registry commits first, so a projection failure
leaves a durable state: the app says alice is a member, the roster shows her, and she cannot open the
space. The run fails and notifies through the plane's existing failure path; the **actor** is told the
change did not fully apply, naming the member and the space, in `toUserMessage` wording. The
**affected member is told nothing** — they can do nothing about it, the actor can, and the sweep
repairs it within the cadence; *if the repair window ever exceeds the cadence, revisit this.* The
registry is **not** rolled back: it is correct, and the grant systems are what is behind.
`logs/service=shared-spaces/` carries one record per failed pair: the member, the space, the half
that failed and a stable reason token.

**The grant budget.** Literal grants consume an account-wide pool of **100,000 grants** and **1,000
locations** per instance (§3.9, §4.4), and consumption is members × spaces, which grows faster than
either. The sweep reports the total this application holds on every run so consumption is a trend
rather than a surprise. The threshold is **50% of the ceiling**: the instance is shared account-wide,
this application cannot see a co-tenant's consumption and cannot shed load, so half is the only
defensible split absent a contractual budget — **if §4.4's coordination contract ever states one, it
replaces this number.** The arithmetic waits on the Phase 3 inventory; until then the formula is
`pairs = Σ(members per space)`, consumption = `pairs` grants, headroom = `50,000 − pairs`. Hitting
the ceiling is a refusal with a named reason, never an opaque AWS error.

**What it needs and what it emits.** Three settings it does not have today: the Access Grants
instance ARN, the Identity Store id, and which Identity Store attribute the portal username matches.
One span per projection and one per sweep, through `cpcommon.observability` and no other door,
carrying the space, the member, the operation and the outcome; the sweep's corrected-drift counts and
the budget figure are **fields**, never interpolations into a message. The fleet-wide rules apply
unchanged — `env` and `version` on every record, messages are literals, `echo=` prohibited.

#### The cutover order, and the role grant that must not be left behind

**The most consequential decision here, and it has a wrong answer in both directions.**
`shared-space-create` grants Lake Formation `Database` and `Table` permissions to the **shared portal
role** for every space; per-user isolation is supplied entirely by the tag conditions in
`portal-role-shared-space.json.tftpl`. Those role-level grants appear nowhere else in this plan and
are the thing most likely to be left in place.

**The objection to answer first, because a reader will raise it to skip step 3.** On the
identity-enhanced plane Lake Formation authorizes the **propagated identity**, so a role-level grant
is not what governs a TIP query — which reads as a reason to leave it alone. It is not: the grant
stays live for any **non-TIP** assumption of that role, and once the tags are gone there is nothing
narrowing it. Left behind it is a standing union grant on every shared space.

1. **Issue per-member entitlements for every space, and verify them.** Additive; nothing is removed.
2. **Retire the principal tags and the interim plane.**
3. **Revoke the role-level Lake Formation grants**, and stop `shared-space-create` issuing them for
   new spaces — otherwise every space created after the cutover reintroduces the union grant one
   space at a time.

**Reversing (1) and (3) locks every member out of every shared space at once. Skipping (3) leaves
every user entitled to every space.** Both are stated because the ordering looks like housekeeping.

**The hazard's actual trigger is the POLICY REWRITE, not the tags going quiet.** The role-level LF
grants become a union only if the role also keeps **IAM** Glue permissions on those databases, and
the only such grant is the tag-scoped statement above. If tags simply stop being stamped and that
policy is untouched, the ARNs resolve to nothing and the outcome is a **lockout**, not a union. The
union materialises when this phase rewrites that statement tag-free, which it must — so step 3
revokes the grants **and** rewrites or removes that statement **in the same change**.

**Verification between (1) and (2) must exercise an identity-enhanced session.** Proving a non-owner
reaches a space while the tags still work proves nothing, and **the tags cannot be made inert for one
member**: under the interim plane the tag and the entitlement both derive from the same registry
record, so removing the member removes both. Drive it with raw credentials on a session where
principal tags do not exist by construction — not through the UI.

#### What the code already does, measured 2026-09-01

Four things are already true in the current account, and they change what this phase has to build.

- **The six trigger points exist and are swept.** They are exactly the six verbs that write the
  SPEC-203 membership index, and `lambdas/test_membership_index.py` already walks the verb tree and
  fails when a seventh membership-moving verb appears — whether or not it writes the index, since
  the writer set is pinned by equality. The projection hooks the same six sites, and that
  enumeration is the guard this design asked for.
- **The current-account half of the cutover hazard is now guarded.**
  `lambdas/test_shared_space_isolation_coupling.py` fails if `shared-space-create` stops granting to
  the portal role, if any Glue resource in the shared-space policy loses its tag scoping, or if any
  portal-role template gains `glue:DeleteDatabase` or `glue:UpdateDatabase`. It is a tripwire on
  today's coupling, not a design: when this phase deliberately replaces it, rewrite those assertions
  with the change rather than deleting a red test.
- **A delete has two routes, and the destroying one lives in `delete` as well as in `forget`.**
  `delete_space.py` branches on `reg.is_destroyable(fresh)` — true only for a space that never
  reached `active` — and on that branch it still calls `delete_shared_prefix`, `revoke_portal_role`,
  `drop_database` and `reg.delete`, and `TeardownIncompleteError` is reachable. On the ordinary
  (ever-active) route nothing is destroyed: the space is emptied, `owner` is cleared, and the record
  survives `active` with no members. Both routes must revoke entitlements; only the destroying one
  has a name to free, and SPEC-151's ordering still governs that one.
- **`revoke_portal_role` is not called on the emptying route, deliberately.** With every member's
  slot cleared the role-level grant reaches no user, and revoking it would leave a restored space's
  catalog unusable for no benefit. It is still called on the destroying route, and these grants are
  retired wholesale by step 3 above.

**An emptied space is permanently `active` with no members, no owner, live data and a live catalog,
and that state is legitimate.** Nothing here may infer membership from status: the desired set stays
computed from `is_active_member`, so an emptied space converges to **zero** entitlements rather than
being skipped as "not deleted".

### 3.12 Provisioning a user without a signup

**Decided 2026-09-04, and it amends §2 item 7.** Every username exists in the client's own system
before the portal ever sees it, so provisioning does not wait for a person: a **portal-owned
provisioner** — a control-plane Lambda, fed by that list — creates every user's space **up front**,
ahead of any sign-in. The half of item 7 that carries over is the one that matters: **sign-in still
provisions nothing**, and this is what makes that safe rather than aspirational. With no signup and
no first-visit write, a user whose space does not exist has nothing that would create it.

**What a provisioned space is.** Four things, and only the first is new work:

1. **The prefix marker**, `{username}/DO_NOT_DELETE.txt`. **S3 has no empty prefixes** — until an
   object exists under `{username}/`, the space does not exist for anything that lists, including
   the username directory, which is built from the bucket's top-level common prefixes and from no
   directory service. `ensurePrefixMarker` writes it from the browser today and is deleted at
   cutover (§6.3, §9), so the provisioner inherits the write **and should not inherit its mechanism
   unexamined**: the route behind `overwrite: false` is a `head_object` followed by an unconditional
   `put_object`, so "write if absent" is check-then-write rather than an atomic guarantee. That is
   adequate here only because the body is a **constant**, so a lost race writes identical bytes —
   which holds only while *every* writer of that key writes the same constant, and is why §6.3's
   prefix-marker row moves the constants' values rather than leaving them to be re-derived. If a stronger guarantee is ever wanted,
   the name for it is `PutObject` with `If-None-Match: *`.
2. **The Glue database**, named exactly the username.
3. **The Lake Formation grant** giving the shared portal role use of that database and its tables.
4. **The `portal-managed` LF-Tag** on the database, **last** — so a tagging failure costs
   control-plane table-creation rights, which a sweep reconciles, rather than the user's own grant.

Steps 2–4 are `provision_user` in `lambdas/post-confirmation/post_confirmation.py` today, already
idempotent and already reused verbatim by `backfill.py`. **This is not a new algorithm; it is the
existing one with a new trigger and one added step** — which is why §9 no longer deletes that
module, only its Cognito trigger.

**A fifth item exists and cannot run in the same pass** — see *the two passes*, below.

#### What must be true

> **Read every boundary claim below as CONDITIONAL, because three review frames each found one that
> was not.** Each says what holds *in the current account, as configured today* — and this document
> exists because that account is being rebuilt somewhere else. Where a claim rests on a
> configuration rather than on a mechanism, the condition is named inline; the standing instruction
> is that **Phase 1 re-establishes those conditions and Phase 0 re-verifies the claim**, rather than
> inheriting it from this page. The two that recurred are worth naming here: what Lake Formation
> vends depends on the **registration mode** and on who is opted in, and what a hand-maintained
> allowlist covers depends on **which lists exist**, of which this section has already
> under-counted one.

1. **Every name on the list is catalog-safe, and the check MOVES rather than disappearing.**
   `^[a-z][a-z0-9_]{2,62}$` is enforced today by `pre_signup.py`, at the one moment a human could
   type one. With no signup nothing enforces it — and the rule is not cosmetic: it is what makes
   **one string** safe as the S3 prefix, the principal tag and the Glue database name at once (§2
   item 3), and its **leading-lowercase-letter** clause is the only reason a username can never
   collide with the bucket's reserved roots — `_directory/` and `_config/` — by construction. A name
   that violates it does not bounce; it produces a space whose three names stop agreeing, and that
   surfaces later as a denial nobody can diagnose. The rule already exists as
   `cpcommon.config.CATALOG_IDENTIFIER_RE`, and `pre_signup.py` holds a second copy of the literal
   (the browser holds a third, in `lib/catalogIdentifier.ts`) — the provisioner takes the `cpcommon`
   one rather than adding a fourth. A row that fails is a **refusal naming the row**, never a
   skipped line.
2. **The name on the list is the name the token will produce.** One username, one claim value,
   stable for the life of the user (§6.1, and the Phase 0 question it leaves open). Provisioning a
   name no claim ever resolves to creates an orphan prefix and a user who signs in to an empty
   portal with an error nowhere. **The list is also a candidate answer to §3.11's open dependency:**
   if Phase 0 decides the portal username is *derived* rather than carried by a claim, §3.11 needs a
   stored username → principal map it currently refuses to invent — and a list that carries the
   identity attribute beside the username *is* that map.
3. **A name already registered as a shared space is REFUSED, not adopted — and the refusal is a
   detector, not the fence.** Usernames and shared-space names share one Glue namespace;
   `provision_user` and `shared-space-create` both call `create_database` and both swallow
   `AlreadyExists`. **The provisioning run itself changes nothing** — every call it makes on a
   colliding name is already satisfied, byte for byte, by what `shared-space-create` did: same
   database, same four database permissions and five table permissions to the same portal role, same
   `portal-managed` tag. That is exactly why the refusal denies nothing. **The hazard exists before
   it and without it:** a session tagged with that username holds the personal-database Glue rights
   — `CreateTable`, `UpdateTable`, `DeleteTable` on `database/${aws:PrincipalTag/username}` — over a
   shared space's catalog. A shared space's name is format-checked **nowhere** server-side, so the
   collision is reachable, and a run over a whole list is what removes the one bound it has today —
   that a colliding name arrives one signup at a time.
   **The data is a separate question, and its answer is CONDITIONAL rather than structural.** Today
   the collision reaches the catalog and not the objects, because Lake Formation is registered in
   **hybrid** mode with **no principal opted in**, so Athena falls back to direct S3 IAM and the
   `shared_space_k` tag scoping is what bites. Under enforced mode, or with the portal role opted
   in, LF vends the credentials instead — and the shared space's LF grants are **role-level with no
   tag condition**, over a data location registered for the *whole* bucket. So the same collision
   reaches the data. Phase 1 re-registers these buckets in a new account, which is precisely when
   that condition is chosen again.
   **State the residual plainly, because item 4 forbids the comfortable reading.** The API stamps
   the tag from the **verified claim**, consulting no registry and no provisioning record, so a user
   whose claim resolves to a colliding name holds those Glue rights *whether or not the provisioner
   ever ran for them*. Refusing the row therefore denies nothing — it is the place the collision
   becomes **visible**, and nothing more. **A fence has four candidate homes, and the two obvious
   ones only stop NEW collisions:** validating a username where it enters the system, and validating
   a shared-space name. The two that would actually deny an existing one are (a) the **tag-minting
   path** — `identity.py` refusing to stamp a username that resolves to a registered space, which is
   the only choke point every request passes and which already refuses on the catalog rule there,
   though the API plane would need a registry read it does not hold today; and (b) making the two
   namespaces **disjoint by construction**, the technique item 1 already relies on for the reserved
   roots and the only one an out-of-band write cannot bypass. **None exists today.** Choose one in
   Phase 0; do not read this refusal as the mitigation.
   The check is a registry read and it **fails closed** — a read that errors refuses the row, because
   `AccessDenied` is not absence: a role that cannot `ListBucket` is never told a key is missing
   (`infra/info/deploy-role-iam.md`).
4. **Provisioning is not authorization, in either direction.** A provisioned space entitles nobody:
   Identity Center performs no just-in-time provisioning, so a user absent from it cannot sign in at
   all (§2 item 12), and through Phases 1–4 access is the `username` principal tag the API stamps
   from the verified claim. The converse is the trap this project has already been bitten by —
   **absence must not read as denial**, so anything asking "has this user been provisioned?" needs
   the `s3:prefix`-conditioned list grant or its absence branch fails as a fault.
5. **THREE hand-maintained allowlists have to gain the provisioner's role, in the PR that creates
   it — and the third is the one whose absence ships green.**
   The first is `infra/modules/data/policies/user-space-bucket-policy.json.tftpl`, a `Deny` on
   `s3:PutObject`/`GetObject`/`DeleteObject`/`ListBucket` for every principal not named in it — and
   **an explicit resource-policy deny beats an identity-policy allow**, so a provisioner holding a
   correct identity grant and missing from that list is denied at runtime with nothing in the plan to
   warn. It reads as a code bug, because the shared-space bucket has no such policy: every
   shared-space path keeps working while every personal one fails.
   The second is the **Lake Formation data-lake administrator list**, which the post-confirmation
   role is in — wired through `infra/main.tf` into `infra/modules/analytics/lakeformation.tf`'s
   `admins`, a constructed ARN inside a `compact()` this repo has already watched swallow a bad
   value and drop a grant silently. **Whether that membership is what makes `provision_user`'s grant
   work is NOT established**: Lake Formation also confers grantable rights on the *creator* of a
   resource, and this function creates the database immediately before granting on it. Measure which
   it is before granting a new role admin — because joining that list makes the provisioner a
   **data-lake administrator**, able to grant any permission on any resource to any principal, which
   is enormously larger than "creates a database and grants a role". If the creator route suffices,
   `CREATE_DATABASE` on the catalog plus the third grant below replaces it.
   The third is `aws_lakeformation_permissions.provisioner_tag_associate` — **`ASSOCIATE` on the
   `portal-managed` tag**, its own `for_each` list, and **admin status does not confer it**: that is
   recorded live in `lakeformation.tf`, where an admin role got *"Required ASSOCIATE on
   portal-managed"* from `AddLFTagsToResource`. A provisioner in the first two lists and not this one
   creates the database, grants the portal role, and **fails at the tag** — which is item 9's partial
   state exactly. The resource carries `ignore_changes` on its permissions, so **Terraform will not
   show you the drift**.
6. **Idempotent, re-runnable, and incapable of overwriting.** Every step tolerates already-exists;
   the marker is written only when absent (see item 1 for what that condition actually is); and
   nothing in the pass writes a document the user or the sync may already own. In particular it does **not** pre-write `user_settings` — that reader quarantines
   what it cannot parse and refuses a newer schema untouched, and a provisioner writing a settings
   document is how a user meets a quarantine on their first visit.
7. **It runs in either order against the sync, and survives both.** The sync copies **objects**;
   per-user databases are this pass's job and no longer the catalog rebuild's (§6.5 layer 2), so the
   two touch one shared thing: the bytes under `{username}/`. Provision-then-sync leaves a marker
   the sync must not delete; sync-then-provision meets a populated prefix the marker write must not
   disturb. Both hold **because of (6)** — the marker is written only when absent, and nothing else
   in the pass writes user data. What is not fine is a pass that assumes an empty
   prefix. Phase 2's reserved-prefix audit (§6.3)
   covers what the provisioner creates as well as what the sync lands.
8. **One code path for the bulk run and for every user afterwards.** The list is re-read, not
   replayed: a new name provisions, a name already provisioned is a no-op. `backfill.py` is the
   precedent to copy rather than the mistake to avoid — it imports `provision_user` from the handler
   *specifically* so the two can never drift, and its docstring says so. What must not happen is a
   second implementation growing beside it for the bulk case.
9. **A partial failure is reported, and a sweep converges what the report names.** The reason is
   not that anything swallows errors — `provision_user` raises, and only the Cognito *handler*
   swallows so a failure never blocks a signup. It is that the sequence is **three non-transactional
   steps**: a raise at the tagging step leaves a database and a portal-role grant with **no tag**, so
   the user's own space keeps working — the portal role holds a named per-database grant and is
   deliberately not tag-granted — while the three tag-granted roles behind Table Builder, Table
   Share and Data Quality can neither create a table there nor describe one. That failure is loud at
   the point of use and silent at provisioning time, which is the half that needs the sweep.
   Today an operator re-running `backfill.py` is the convergence mechanism — a person noticing —
   which is what a bulk run cannot rely on. §3.11 already settled the pattern for
   this class: **the event plus a sweep**, desired state computed, current state read, difference
   applied. Without one, a user with a database, no tag and no error is invisible. Note that
   `_tag_database` already turns Lake Formation's per-item `Failures` array into a raise — a 200 is
   not success — and that behaviour is preserved rather than reimplemented.
10. **The bulk run does not fit one invocation, and its bound is computed.** "Every known username"
    at organisation scale is orders of magnitude past what the operator-CSV path handles, and that
    path is the model for *how* to bound it rather than for the numbers. Read that module carefully
    before copying it, because it holds three different kinds of cap: `MAX_SPACES_PER_FILE` and
    `MAX_ADD_ROWS_PER_FILE` say of themselves that they are **blast-radius controls, not resource
    budgets**; `MAX_FILE_BYTES` **is** a resource control, sized against the memory the parse needs;
    and **two** caps are computed — `MAX_ROWS_PER_INVOCATION` and `MAX_MEMBERS_PER_MESSAGE`, the
    second the better model here because it carries an O(N) fan-out term. Note also that its
    per-send cost is **deliberately conservative and unmeasured**, and says so — a copier should
    preserve that rather than "improve" it. Copy the shape: a resumable Map with per-item tolerance
    and a report, and a cap **computed** against the tightest of Glue's create-database rate, Lake
    Formation's `GrantPermissions` rate, **`AddLFTagsToResource`'s own separate throttle** (step 4
    is a different API from step 3, and it is the one item 9 is about), the two S3 calls the marker
    costs, and the invocation ceiling — named, in a test, against the budget that sized it. **A rate
    cap does not address a hard ceiling:** Glue's databases-per-catalog quota bounds the whole
    population, not the run, and a per-organisation list is the first thing that could reach it.
11. **The list is an authorization-shaped input and must be unreachable by the people it
    authorizes.** Admin bucket, never the user-space bucket, and never a document any user can
    write — the property that makes `memberships/{username}.json` safe and that the user's own
    `shared-connections.json` conspicuously lacks. **SPEC-217's `operator-requests/` prefix is the
    nearest existing shape, and it differs in exactly the way that matters:** that CSV is written by
    a *human operator*, not by a plane, which is precisely why the plane fences it with a `SenderId`
    comparison downstream rather than trusting the document. A username list is the same kind of
    object — out-of-band, privileged, human-supplied — so it inherits the fence as well as the
    shape, and "plane-written" is not a property it can claim.
12. **It is a fleet function, with the fleet's obligations.** A `docker-lambda` module call in
    Terraform — which is what `fleet.py` reads, so a function declared anywhere else is not in the
    fleet — a module flat at the task root defining a top-level `handler`, its own execution role,
    and **deploy-role IAM in its own PR before** the resources that need it.

#### The two passes, and why they cannot be one

A grant binds an **Identity Center user**, not a string. So the work splits by what it needs to know:

- **The name-shaped pass** (items 1–4 above) needs only a catalog-safe username. It can run as soon
  as the bucket and the catalog exist — Phase 2, before SCIM has necessarily finished.
- **The identity-shaped pass** — the S3 Access Grant on the user's prefix, if Phase 0 chooses the
  literal per-user form (§3.9), plus the per-(member, space) pairs of §3.11 — needs a resolvable
  Identity Store principal, so it cannot run until SCIM has created that user. It belongs to
  **Phase 5**, and it follows §3.11's rule that an unresolvable user is a **refusal, not a skip**,
  with distinct reasons for "not provisioned yet" and "the directory is unhealthy".

Reading the second as a continuation of the first is the mistake: the first pass can complete for a
user the second cannot even address.

#### Two consequences accepted, and one gap left open

**The username directory becomes a full organisation roster, and that is the decision, not a side
effect.** It is built from S3 prefixes, so today it lists only people who have used the portal;
after a bulk run it lists everyone the client has. The disclosure is the same *kind* the directory
already makes — usernames only, never emails, readable by every authenticated user — but it is now
complete, and its payload grows with the organisation rather than with usage, on a document with no
pagination. If completeness ever becomes unacceptable, the fix is a liveness rule in the builder,
not a change here.

**The quota is consumed per known user, not per active user.** A Glue database each, and from Phase
5 an Access Grant each against the instance's 100,000 account-wide ceiling (§4.4) — so the Phase 0
headcount is an input to §3.11's grant-budget arithmetic and not only to the sync's sizing.
Provisioning ahead of use spends that budget on people who may never sign in.

**De-provisioning is the mirror image and nothing owns it yet.** The external system is the source of
who exists, so it is also the source of who has left — and nothing in this repo deletes a user's
space. A leaver keeps a prefix, a database, a directory entry and, after Phase 5, a live Access
Grant; what actually cuts their access is losing the Identity Center user, which is SCIM's doing and
leaves every one of those artifacts behind. **Name an owner in the coordination contract (§4.4) or
accept the residue explicitly.** What is not acceptable is discovering at the client's security
review that "provisioned from the list" was never paired with anything.

#### What it does not do

It creates no Identity Center users — SCIM does (§2 item 12) — it touches Cognito in neither
variant, it mints no per-user IAM, and it does not decide who may sign in.

#### What Phase 0 must answer for it

Where the username list comes from and in what shape; whether it carries the identity attribute
beside the username (which would settle §3.11's stored-map question); how often it is refreshed and
what a re-run does with a name that has disappeared from it; whether the identity-shaped pass is a
second mode of this function or a separate verb; **which door the list arrives through — its own
fenced reader, on SPEC-217's model, or an existing one** (item 11); **where the username /
shared-space name collision is actually fenced**, since item 3's refusal detects it rather than
preventing it and no fence exists today; and who owns de-provisioning.

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

**The list gained a third member on 2026-08-18: the S3 Access Grants instance** (§3.9). It is one
per account and Region, its association with Identity Center is a prerequisite of the IdC-enabled
Athena workgroup, and every consuming application in the account shares it. Name it in the
coordination contract on the same terms as the other two — the portal creates it as first tenant,
and later tenants register locations through this repo's IaC rather than by a competing apply.

**It is the first singleton with a CONSUMABLE budget, and that is a different kind of coordination
problem.** The data-lake settings and the Identity Center configuration are shapes a later tenant can
overwrite; this one is a pool a later tenant can **exhaust**: **1,000 locations** and **100,000
grants** per instance. With one literal grant per user per space (§3.9), the portal's own consumption
grows with users × spaces, and a co-tenant granting per object prefix could take the rest. The
contract needs a **budget** alongside the ownership line, and the Region constraint with it — the
Identity Center instance, the Access Grants instance, the Athena workgroup and Lake Formation must
all be in the same Region.

### 4.5 A third counterparty — unchanged

> **Note added 2026-08-24.** Where this section says *"the customer-managed application"*, read it as
> **at least two**: the portal's own, and the driver path's (§3.10). §5.1's brokering capability would
> be a third. Each needs the management account or a delegated administrator, so the counterparty
> relationship below is exercised once per application, not once overall.

The customer-managed application still cannot be created from the data account. An organization
instance of Identity Center lives in the AWS Organizations **management account**, and only
management-account administrators or a registered **delegated administrator** can create a
customer-managed application and enable AWS account access for it. Phase 5 therefore still
depends on that relationship — establish it in Phase 0; it is the one most likely to be
discovered late.

One new item joins it: **confirm the successor account joins the same organization** (and so the
same Identity Center organization instance). If it does not, every identity assumption in §3
needs re-examination before anything else in this document is acted on.

**Sharpened 2026-08-18 — organization instance versus account instance is a decision with teeth, and
it belongs to the client's platform team.** AWS's prerequisite is explicit: with an **account
instance**, *"all AWS services that you want users to access with trusted identity propagation must
reside in the same AWS account where you enable IAM Identity Center"*, and AWS recommends the
organization instance for exactly this reason. The consequence worth carrying into that conversation
is concrete: an account instance **forecloses cross-account data sharing with other teams outright**,
because Lake Formation's RAM sharing carries trusted identity propagation only when grantor and
grantee are in the same **Region**, the same **AWS Organization**, and the same **organization
instance**. Lake Formation also refuses to grant to IdC principals on Data Catalog resources in an
external account — *"Cross-account grants are not supported for the principal"* — so the grants stay
in the owning account and an external-account IAM role acts as a **carrier role**. Together those
settle where a future team-level integration can live, and the choice has a long lead time.

The fuller treatment of what that integration would look like — the two shapes it can take, and why
neither routes through this application's API — is in `docs/specs/ARCS.md` under the API-layer arc,
*Other applications acting on behalf of users*. Pull it back here if that arc entry is ever pruned.

### 4.6 Hosting moves from CloudFront to a container

> **LANDED 2026-09-02 (SPEC-193 → 202), and this section is a record rather than a plan.** The SPA
> is a container on ECS Fargate behind an ALB; the distribution and the static bucket are destroyed.
> The table below is what nginx reproduces, with three deliberate divergences — `Server: nginx`, no
> brotli, no HSTS `preload`. **Two things in this section are still ahead of the successor account:**
> the availability work the arc deferred (autoscaling, capacity providers, a WAF, the multi-AZ
> obligations) and the two coupling points at the end, which bite at Phase 1.

**The shape that landed, because this section was written before it.** The SPA is the container
behind the ALB; the **API is a Lambda behind API Gateway**, not the ALB — viable because the bulk
data work moved to a control plane first, leaving the API thin enough that the 29-second integration
ceiling never binds, and compatible with §3.5 because `CreateTokenWithIAM` needs SigV4 credentials
the execution role supplies and the session state the single-use assertion forces lives in DynamoDB.
**Two origins**, so the SPA and the API are subdomains of one registrable domain — same-site, so the
`httpOnly` session cookie reaches both under `SameSite=Lax`, with CORS and `credentials: 'include'`
on the API. **The browser no longer calls AWS directly**, so `connect-src` is the API host plus the
S3 endpoint for presigned bytes, not an enumeration of AWS service hosts.

CloudFront was doing more than serving files, and each of those jobs needed an owner. (nginx here
means the **web server**, actively maintained by F5 — not Kubernetes' community *Ingress NGINX*
controller, which retired March 2026 and is easily confused with it. No Kubernetes is involved in
this plan; confirmed 2026-08-03.)

#### Configuration: build-time versus runtime — SETTLED, and it is the superseded marker SPEC-192 asked for

**Vite environment variables are build-time**, so promoting one image across environments is
impossible with them: the image would carry one environment's configuration everywhere. SPEC-192
built the answer — a runtime `/config.json`, same-origin and `no-store`, read through accessors, with
`lib/env.ts`'s literal table kept as the dev fallback and a dynamic import in `main.tsx` because a
module's static imports evaluate before its first statement runs. The contract is
`apps/portal/info/runtime-configuration.md` and the reasoning is in
`docs/decisions/infrastructure.md`; SPEC-215 later moved the values themselves out of repository
variables and into Terraform state.

**The superseded marker SPEC-192 asked this section for, stated once so nobody hunts it:** this
section used to carry a pre-implementation estimate of *"roughly 30 genuine production config reads
across ~18 files"*. Measured, it was **40** reads, of which **25** lines moved onto the accessor and
the rest stayed as `lib/env.ts`'s dev fallback. Take the figure from SPEC-192's **delivery** doc —
the spec itself says 23, which its delivery corrected.

**The one argument worth carrying forward**, because it is the non-obvious half and it decided the
call: building per environment would have left **two configuration mechanisms inside one image** —
build-time for the frontend, runtime for the server half, which needs runtime configuration
regardless. That cost is invisible until you are maintaining both.

The rest of what CloudFront was doing, each of which needs explicit configuration now:

| Job | What it needs in the container |
|---|---|
| SPA routing fallback | CloudFront mapped 404 to `index.html` for client-side routes. nginx needs `try_files $uri $uri/ /index.html`, or every deep link 404s. |
| Cache headers and busting | Long immutable cache on hashed assets, revalidate-always (`no-cache`) on `index.html` — the exact per-class scheme is **SPEC-141**, and nginx must reproduce it (SPEC-141 also records *why*: heuristic browser caching plus `--delete` produces a white screen, not stale content). Get this wrong and users silently run stale bundles after a deploy — intermittent and very hard to diagnose. |
| Compression | CloudFront gzipped and brotli'd automatically. nginx must be told to. |
| TLS and certificate | An ALB with ACM, or ingress TLS. **The OIDC provider requires HTTPS callback URLs** — Cognito does under **[B]**, Entra does under **[A]**. |
| Security headers | The **shipped** response-headers policy (SPEC-140: enforcing CSP + HSTS + framing/nosniff/referrer/Permissions-Policy/COOP/CORP, `Server` stripped — `architecture.md` → *How the SPA reaches a user*) moves into the nginx config. The CSP's `connect-src` is derived from Terraform variables; the nginx copy needs the same derivation, not a frozen string. HSTS currently carries `preload` (inert on `*.cloudfront.net`, never submitted) — re-decide `preload` deliberately for the new domain before emitting it there. |
| Health check | The load balancer or orchestrator needs an endpoint to probe. |

> **Delivered by SPEC-194 (2026-08-27); this table now records what was decided, not what is
> open.** Every row above has an owner and an answer. The fallback, the per-class cache scheme and
> the full header set are reproduced; the health endpoint is an exact-match `location` deliberately
> outside the fallback, because a probe that falls through to the shell reads a broken container as
> healthy. Three rows are **divergences, not parity**: `Server: nginx` remains (`server_tokens off`;
> removing it needs a third-party module the official images do not ship), there is **no brotli**
> (same compile stage, refused once), and HSTS drops `preload` — re-decided, as this row asked,
> because emitting it claims a submission this deployment has not made against a registrable domain
> it does not own. `connect-src` is derived from Terraform and supplied per environment by the task
> definition, never frozen into the image.

**Two coupling points that reach outside this workstream:**

- **The OIDC provider's callback and logout URLs must match the new origin exactly** — the Cognito app client under **[B]**, the Entra app registration under **[A]** — and
  `VITE_APP_URL` feeds the same value. So the final origin has to be known before Phase 1's auth
  configuration is finalised. This is the hosting workstream's one hard dependency on the auth
  phases.
- **S3 bucket CORS must allow the new origin.** *This bullet predates Arc B: the browser no longer
  calls Athena, Glue or SQS at all — every AWS call moves behind the API (SPEC-197 → 201), and the
  Identity Pool retires (SPEC-202).* What survives is the part that matters here: the browser still
  redeems **presigned S3 URLs** for file bytes, so the bucket's CORS configuration needs the new
  origin. Under the successor strategy the portal owns the bucket, so this is this repo's own IaC
  rather than a change request — but it is still easy to miss until the first upload fails with an
  opaque browser error.

**The deploy pipeline changes shape.** Build, push to a registry, update the service, replacing
build, sync to S3, invalidate the distribution. New resource types mean the deploy role's
`.tftpl` policies expand as in-scope work, per the `CLAUDE.md` infra rule — read
`infra/info/deploy-role-iam.md` before starting.

**The availability model changes, and not in your favour.** CloudFront was a globally distributed
CDN with essentially no operational burden. A container behind a load balancer has instances,
scaling behaviour and a real failure mode. Combined with §3.5's availability-critical token
backend, the portal acquires genuine uptime work it did not have before. Budget for it.

### 4.7 The backend, and where its state lives

§3.5 established that a token-exchange backend is mandatory and must hold session state. **Where it
runs is settled and is not where this section originally said:** the BFF is a **Lambda behind API
Gateway**, not a process co-located with the SPA in one container. The co-location argument — one
origin, no CORS, one artifact, one certificate — was made when the backend existed only to exchange
tokens; it now serves the whole application's AWS surface, and API Gateway is the target
environment's established pattern.

**Everything this section says about STATE is unchanged, and is more load-bearing rather than
less.** A Lambda satisfies the container-is-stateless rule by construction, and its execution role
supplies the SigV4 credentials `CreateTokenWithIAM` needs, exactly as a task role would have.

**The state design, either way:**

- The browser holds an **opaque session identifier** in an `httpOnly`, `Secure`, `SameSite`
  cookie. Nothing else.
- The **Identity Center refresh token** lives in DynamoDB, encrypted with a customer-managed KMS
  key, with a TTL matching the token's lifetime. It never traverses the browser, which is what
  AWS's guidance requires.
- **TTL is storage hygiene, never the security boundary.** DynamoDB deletes an expired item on its
  own schedule rather than at the moment it expires, and an expired-but-undeleted item **is still
  returned by reads** —
  so session expiry is checked on read, and a design that leans on the TTL to end a session does not
  end it.
- **Keep the compute stateless.** State belongs in DynamoDB, not in process memory — otherwise
  scaling breaks sessions and every restart logs everyone out. A Lambda gives this by construction;
  it was a rule to enforce when the backend was a container.

**Credentials come from the execution role**, rotating, with no static secrets and no IAM Roles
Anywhere trust anchor to stand up: the token-exchange backend needs SigV4 credentials to call
`CreateTokenWithIAM`, and the role supplies them for free. Scope it narrowly — it is a privileged
identity that mints sessions on behalf of users.

**Three clocks now govern a session:** the provider session (Cognito **[B]**, Entra **[A]**), the Identity Center refresh token, and
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
record the decision in `decisions/` alongside the original. Do not assume the existing
exemption covers this — it does not.

---

## 5. The open fork — the permission-set path

**This must be tested before Phase 1 is built.** It is the single highest-value experiment in the
plan, and running it late means throwing Phase 1 work away.

**What Path A is an alternative to, since §3.4 collapsed.** This section was written when §3.4 had
a **base plane** for storage and Path A was a candidate replacement for the Cognito Identity Pool
that fed it. The base plane is gone, so Path A's role changes rather than disappearing: it is now
the alternative to **§3.9's S3 Access Grants** for the storage plane, and **gate P3 decides it**.
§5.4 records the tension that makes it interesting — a P1 *pass* implies the session is
identity-enhanced, which implies a P3 *failure*, because the allow-list denies plain S3 (§3.6):

- **P3 passes** (plain S3 works, the session is not identity-enhanced): a base plane survives after
  all, fed by permission sets rather than the Identity Pool, and §3.9 is not needed for user storage
  — though it is **still needed for the IdC-enabled Athena workgroup**, which requires the Access
  Grants association regardless.
- **P3 fails:** §3.9 stands as written and this section is history.

Either way §3.9's Access Grants instance gets built, so nothing in Phase 5 waits on this. And
§5.4's procedure is written around a **Cognito pool as the trusted token issuer** — read it as
**[B]**, and substitute Entra under **[A]**; the experiment is unchanged, only the issuer moves.
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

> **Two of these are no longer reasons to prefer Path A, and are kept because the mechanism is
> still worth understanding.** The variant revision delivers both on its own: **Variant A** has no
> Cognito, so there is no writable custom attribute and no `custom:shared_space_k`, and **Phase 5
> retires the tags regardless**. What remains genuinely Path A's is the audit-legible session name
> and the single-identity story.

- **~~It deletes §6.1 entirely.~~** No `custom:portal_username` attribute means no
  writable-attribute privilege-escalation trap. Session tags would come from Identity Center's
  *attributes for access control*, sourced from the directory and passed as session tags referenced
  by `${aws:PrincipalTag/...}` — the same ABAC model the repo already relies on, fed from a source
  the user cannot write to. **Variant A already deletes that trap.**
- **~~It removes the ten-slot ceiling.~~** Shared workspace membership would no longer live in
  Cognito custom attributes (`custom:shared_space_1..10`), which cannot be deleted or renamed
  once created. **The ceiling is in the IAM policy, not in Cognito** (§6.4), so what actually lifts
  it is Phase 5 retiring the tags — not this path.
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

Independent of P1 and P2, and still worth proving. **G7, G8 and G9 run in Phase 0** — each can
invalidate design rather than merely confirm it; the rest belong to Phase 5:

| Gate | Check | If it fails |
|---|---|---|
| ~~G1~~ | ~~Can a public client perform `CreateTokenWithIAM`?~~ | **Settled — no.** Backend mandatory (§3.5). Do not run. |
| G2 | A user granted `__normal` sees the masked view | Filter or workgroup config is wrong |
| G3 | After granting `__sensitive`, the full view returns | The level model is in question |
| G4 | A user with no grant is denied | Default-deny or propagation broken — blocker |
| G5 | A JOIN across two granted datasets returns in one query | The single-session-spans-grants assumption is wrong |
| G6 | Session lifetime is workable and silent refresh exists | UX churn; needs a refresh strategy |
| G7 | A plain `StartQueryExecution` on an IdC-enabled workgroup, issued with identity-enhanced credentials from our own code, runs and is enforced per user (§3.5) | **Blocker, and genuinely uncertain** — the docs list *federated access to the Athena API* as incompatible with TIP, but define that term narrowly elsewhere as SAML-via-JDBC/ODBC, so neither reading is safe to assume. If it fails, Phase 5 needs a different query surface: a studio product, or a broker that re-implements masking (§3.2 point 4). **Run it in Phase 0, not Phase 5**. **Evidence added 2026-08-24 (§3.10):** AWS's own JDBC/ODBC driver TIP plugins do exactly this — exchange a JWT, assume an identity-enhanced session, then call the Athena API from ordinary client code with no studio product in the path. Expect a pass; run it anyway, since a vendor driver may hold a privileged path our own code does not |
| **G8** | **Can the Entra tenant issue OIDC/OAuth2 JWTs for this application** — an app registration on the **default signing key** (a custom signing key is unsupported for the Entra trusted-token-issuer path), with an audience and an `email`-to-IdC-attribute claim mapping that align? | **This is the variant decider (§3.3), not a blocker.** Pass → **Variant A**, and Cognito is never built. Fail → **Variant B**, and a Cognito bridge is built to be deleted later. Often a per-app-registration or tenant-policy matter rather than a product limitation, so **ask the Entra tenant owner before assuming**. Answer it in **Phase 0**: it decides work in Phase 1 and Phase 5, and building B when A was available is the expensive mistake. **Stakes raised 2026-08-24 (§3.10):** the client's driver users are on SAML and must migrate to an OIDC-based TIP plugin, so a G8 failure points the **whole desktop fleet** at the Cognito bridge as well as the portal — ask G8 with the drivers in the question |
| **G9** | **Presign an S3 `GET` and a `PUT` from `GetDataAccess`-vended credentials and redeem both from a browser origin** (§3.9) | Presigning is a local SigV4 operation and the session token rides in the query string, so this *should* work and S3 should evaluate the grant's scope at redemption — but it is **unproven**, and the whole "AWS credentials never reach the browser" posture rests on it. If it fails, the fallback is vending the scoped credentials to the browser directly, and **SPEC-202's load-bearing negative live check must be re-worded before it is run**. Cheap; run it in Phase 0 beside G7, on the same throwaway instance |

---

## 6. Risk register — the five hard problems

Everything else is mechanical. These are where the work and the risk live.

### 6.1 The username claim is not `cognito:username`

The highest-consequence detail in the migration, and easy to miss. **It changed shape twice and did
not go away.**

**[A — baseline]** There is no Cognito, so there is no `cognito:username` and **no custom attribute
to lock down** — the writable-attribute privilege escalation below disappears, and with it the
"attributes can never be renamed or deleted" trap. What survives is the first half, in a new form:
**which Entra claim carries the catalog-safe username**, is it stable for the life of a user, and
does every reader take it from there. You cannot write to Entra, so if no existing claim carries it
the username must be **derived or mapped** rather than stored — decide it in Phase 0, because it
keys the S3 prefix and a change strands data. (§3.12's username list is a candidate answer to the
mapped form.)

**[B — fallback]** Cognito does **not** set `cognito:username` to the user's real username under
federation: it sets a synthetic `{providerName}_<subject>` value, prefixed with the **provider name
configured on the pool** — so with the bridge pointed at Entra it is not literally
`identitycenter_<subject>`, and nothing may pattern-match the prefix.

**So under [B] the catalog-safe username needs a claim the pool does not natively carry, and the
obvious route to one is closed.** A **custom attribute** populated by SAML attribute mapping is what
this would ordinarily use, and Phase 1's **[B]** items forbid it — no custom attribute schema at
all. Three candidates remain, and Phase 0 chooses between them rather than this page: a claim
injected by a **Pre-Token-Generation V2 trigger** (recorded here because nothing else in this repo
records it), a mapping onto a **standard** attribute such as `preferred_username`, or **deriving**
the username server-side, which is the same answer §6.1 gives under [A] and which §3.12 item 2
already contemplates. **Whichever is chosen becomes a Phase 1 [B] build item, and today that phase
has none** — a trigger in particular is a Lambda, with everything a fleet function owes.

The reason the attribute route is closed is also the reason to get the pool right first time: **a
Cognito custom attribute can never be renamed or deleted**, so fixing a schema mistake means a new
pool, which changes every user's `sub`.

**Arc B collapsed the readers, and that is why this is now configuration rather than surgery.**
Before SPEC-201 five places read the claim independently. The API now verifies the bearer once at
the edge, derives the actor from it, and every control plane reads a field it cannot forge — so
what remains is **one configured claim name in one verifier** (`oidc_username_claim` in
`infra/main.tf`), plus the SPA's own `getCurrentUser().username`, which is not the claim string at
all but **fans out to roughly twenty call sites building S3 prefixes and Glue database names**. A
fleet sweep fails if any shipped Lambda module writes a provider's claim name as a literal, so the
list cannot silently regrow. The full record of what moved and where: `docs/decisions/identity-and-access.md`.

**The [B] guardrail is a security control, not hygiene.** The app client must **not** have write
permission on whatever attribute carries the username. Cognito custom attributes are writable by
the user through `UpdateUserAttributes` if the client grants write access, and a user who can write
the attribute that becomes their principal tag can assume another user's S3 prefix and Glue
database. This repo's app client sets neither `read_attributes` nor `write_attributes` — measured:
neither appears anywhere under `infra/` — and Cognito's default in that case is that **everything is
writable**, so locking one attribute means enumerating the entire writable set explicitly. This is why §2 item 1 ships the
bridge pool with **no custom attribute schema at all**: an attribute that does not exist cannot be
written, and a Cognito custom attribute can never be renamed or deleted once created.

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
must choose **hybrid** mode, so the file browser's `ListObjectsV2` / `GetObject` path keeps working
— listing through the API under the caller's assumed portal-role session, and bytes on URLs that
same session presigned. The old risk — inheriting an enforced-mode registration that blocks direct S3 —
returns only if sequencing changes.

**If the portal turns out not to be first into the account**, the previous strategy's surgery
reactivates in full: strip the data-lake settings, convert the bucket registration to a data
source, surrender the bucket policy, and join the incumbent's Identity Center configuration
allow-list. Keep this paragraph until the account's tenancy order is contractual.

### 6.3 Destructive code paths during the sync-and-seed window

> **AMENDED 2026-08-18, and SPEC-205 has now SHIPPED (2026-09-01) — the delete row is NARROWED, not
> struck.** A shared-space delete now removes every member and the owner and destroys nothing *on
> the ordinary route*: the objects under `{name}/`, the Glue database and the registry record all
> survive, and the record stays `active` with an empty roster. Retention keys on **`everActive`**, a
> durable field — not on live `status`, which a failed delete moves out of `active` while the data
> is intact.
>
> **What the 2026-08-18 amendment got wrong, corrected here:** it instructed a later reader to
> *strike* the `delete` row once SPEC-205 landed, on the premise that a never-active space is
> destroyed only by `shared-space-forget`'s owner path. It is not. `delete_space.py` branches on
> `reg.is_destroyable(fresh)` — true exactly when a space never reached `active` — and on that
> branch it still deletes the prefix, revokes the portal-role grant, drops the database and deletes
> the registry record. **A workspace mid-seed is precisely a space that has not reached `active`**,
> which is the state the guard exists for, so the row stays and its scope narrows to that branch.
> §3.11's *What the code already does* records the same measurement.

The app deletes things because it created them — and in the successor account that becomes true
again, which retires most of the previous strategy's permanent guards. What remains is a
**window**: between the first sync and a verified cutover, prefixes and workspaces hold the only
in-account copy of the synced client data. A destructive path firing mid-seed destroys work that
must be re-synced; the same path firing after cutover destroys the authoritative copy while the
old account is already read-only. The guards below are scoped to that window rather than
permanent.

| Path | File | What it destroys | Guard |
|---|---|---|---|
| Shared-space `delete` verb, **never-active branch only** | `lambdas/shared-space-delete/delete_space.py`, on `reg.is_destroyable` — `not everActive and status != "active"`, which is "never reached `active`" only because `finalize` stamps `everActive` at the same moment | On that branch it calls all three teardown helpers below **and** `reg.delete`, which frees the name. On the ordinary ever-active route it destroys nothing — the space is emptied and the record survives | **Disable through the seeding window (Phase 3)**; re-enable at cutover, once the per-workspace inventory and the §6.4 parity check verify. A seeded workspace mid-sync can present as never-active, which is exactly the branch that destroys. From cutover the app fully manages all shared spaces, so delete is legitimate again. |
| Teardown helpers, and the registry delete beside them | `lambdas/shared-space-common/teardown.py` — `delete_shared_prefix`, `revoke_portal_role`, `drop_database` — plus `registry.delete` in `lambdas/shared-space-common/registry.py` | `delete_shared_prefix` **deletes every S3 object** under `{name}/`. The other two revoke LF grants and drop the Glue database with all its tables. `registry.delete` removes the record, and the record *is* the name lock — freeing a name a seeded space still holds. | Gate all **four** during the window. Gating only the two grant/catalog functions leaves the object deletion live; gating only the three helpers leaves the name reusable. |
| `forget` verb teardown branch | `lambdas/shared-space-forget/forget_space.py` | Full teardown when `owner == actor and status != "active"` — **any** non-active status, not only failed — and it calls `reg.delete` too, so it frees the name as well | Restrict to the cache-only branch through the seeding window. A seeded workspace mid-sync could present as non-active. |
| Data-quality temp tables | `lambdas/data-quality-create-temp-tables/`, `.../drop-temp-tables/` | Creates and drops `dq_tmp_*` tables in the user's or shared workspace's Glue database | Confirm **both** prefixes — `dq_tmp_` *and* `dq_tmp_raw_` (`dqcommon/sql.py` lines 40-41) — cannot collide with a client naming convention. |
| Prefix marker write | `ensurePrefixMarker` in `features/file-browser/fileBrowser.service.ts`, the constants in `fileBrowser.constants.ts` (`PREFIX_MARKER_FILENAME`, `prefixMarkerKey`, `PREFIX_MARKER_BODY`), sole app caller `routes/FilesPage.tsx` | Writes `{username}/DO_NOT_DELETE.txt` into the user's prefix | **Remove the BROWSER's copy of it — the marker object itself stays (§3.12).** The function, the call site, the barrel re-export in `features/file-browser/index.ts` line 30, and the coverage in `fileBrowser.service.test.ts`, `FilesPage.test.tsx` and `FilesPage.a11y.test.tsx` all go; deleting the function alone leaves a dangling call site. **The three constants' VALUES move to the provisioner** — the filename and body are what make a provisioned prefix visible to the username directory and undeletable to its owner, so deleting the marker with its writer is the one reading of this row that breaks the file browser for every user. *This row said "remove all of it" until 2026-09-04, when §2 item 7's amendment moved the write rather than retiring it.* |
| Table Share object copy | `lambdas/table-share-copy-objects/table_share_copy_objects.py` | Writes into `{recipient}/shared_tables/{tableName}/` | Confirm no collision with existing client data under a recipient's prefix. |
| Table Share DDL | `lambdas/table-share-create-table/table_share_create_table.py` line 35 | Athena output to `s3://{destBucket}/{database}/athenaresults/{actor}/` — a different shape from the SPA's | Include in the Phase 4 workgroup audit. |

**Reserved prefixes are defined in three divergent places.** An audit checking only one will miss
data:

| Location | Contents |
|---|---|
| `lambdas/data-quality-common/dqcommon/config.py` line 27 (`RESERVED_PREFIXES`) | `user_settings`, `athenaresults`, `_data-quality-reports`, `shared_tables`, `_fc-work`, `_directory` |
| `apps/portal/src/features/file-browser/protectedFolders.ts` (`HIDDEN_BROWSER_FOLDERS`) | `user_settings`, `_data-quality-reports`, `_directory` — the SPA's listing filter; diverges from both other lists |
| `apps/portal/src/features/file-browser/protectedFolders.ts` (`PICKER_LOCKED_FOLDERS`) | `athenaresults`, `user_settings`, `_data-quality-reports`, `_directory`, `shared_tables` |

(A fourth list this table previously named — the SPEC-116 file-converter blocklist — **never
existed in code**; that arc was cancelled 2026-08-03 with nothing built, and its architecture
record was removed.)

**`_directory` is different in kind from every other name here, and the sync must respect it.**
The rest are prefixes *inside a user's own space*; `_directory/` is at the **bucket root** and
holds the published username directory (SPEC-146). It is the user-space bucket's one deliberate
exception to "every top-level prefix is a username", and it is safe because
`CATALOG_IDENTIFIER_RE` requires a leading lowercase letter, so no username can ever collide
with it. **The sync must not land client data at `s3://{user-space-bucket}/_directory/`** — not
because a user could reach it (the portal role's `ListBucket` is prefix-conditioned and its only
grant there is `GetObject`), but because the daily builder overwrites that object wholesale.

Each name may collide with data arriving from the old account via the sync.

**Reviewed 2026-08-05, and "reconcile the three lists" turned out to be the wrong instruction.**
They answer three different questions — may a data-quality *check* treat this as source; does the
user *see* it; may the user *paste* into it — so unioning them would break the case that proves
it: `athenaresults/` is deliberately visible (you want your query results) and deliberately not a
paste target. Divergence is only a defect where it is **accidental**, and one such gap was found
and closed: `shared_tables/` was a valid move/copy destination, so a user could drop files beside
the files of a table shared with them. `_fc-work` stays `dqcommon`-only — the SPEC-116 arc was
cancelled with nothing built, so nothing creates that folder and listing it in the SPA would be
dead config. The reasoning now lives in `protectedFolders.ts` beside the lists.

What the **Phase 2 audit** still needs from this table is unchanged: every name here may collide
with synced data.

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

What does **not** disappear is the membership question, though the revision changes its shape.

> **RESHAPED 2026-08-18, then CORRECTED at review the same day. The ceiling survives the interim
> plane, and the correction is the load-bearing half.** This paragraph first said the ten-slot cap
> carries over as a *Cognito* limit; the reshape then said it dissolves. Both were wrong.
>
> **The cap is not in Cognito. It is in the IAM policy.**
> `infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl` loops over
> `max_shared_memberships` (default 10) and emits `${aws:PrincipalTag/shared_space_${k}}` into the S3
> object resources, the `ListBucket` prefix condition and the Glue database and table ARNs. An
> eleventh session tag matches **no resource** and is an implicit deny — so it does not matter where
> the tag came from. Through **Phases 1–4** the interim plane keeps that policy, which means it keeps
> the ceiling: raising it means re-rendering the policy, which is the "no IAM policy changes at all"
> the interim window otherwise promises (and IAM's 6,144-character inline-policy limit bounds how far
> the loop can grow). *STS accepting up to 50 session tags is true and irrelevant — enforcement is
> the policy, not the tag set.*
>
> **The ceiling dissolves at Phase 5, not before**, when the tags retire and membership becomes an
> **S3 Access Grant on the space's prefix plus a Lake Formation grant on its database**, per (member,
> space) — §3.9. Those have no per-user slot limit, but the Access Grants instance has its own
> ceilings (1,000 locations, 100,000 grants) and is shared account-wide.
>
> **So keep the Phase 0 inventory and keep checking it against ten**, for Phases 1–4. It has a second
> purpose now: every (member, space) pair is a grant something has to issue at Phase 5 seeding, and
> the count sizes that work. **[B]** adds nothing here — the bridge pool ships with no custom
> attribute schema at all (§2 item 1), so the cap has no Cognito half in either variant.

### 6.5 The sync and the cutover (was: retiring bespoke roles — deleted; they are never created)

The data sync is three layers, and only the first one copies:

1. **Objects.** S3 sync from the old account's buckets into the portal-created buckets,
   re-encrypted under the successor account's **customer-managed KMS key** — required by Phase 5
   regardless, since AWS managed keys do not support trusted identity propagation. DataSync or
   S3 batch operations; per-prefix, resumable, verified by inventory comparison.
2. **Catalog.** Glue databases and tables are rebuilt, never copied: per-user databases by the
   **portal-owned provisioner**, over the whole known username list — in either order against the
   object copy, since neither pass may assume an empty prefix (§3.12); workspace databases through seeding (§6.4); core-dataset tables from the dataset
   registry config (§3.8) pointed at the new account.
3. **Grants.** Re-issued, never copied. Core-dataset grants are a config re-run against
   unchanged Identity Center identities (§4.1); the personal-database grant to the shared portal
   role is step 3 of the same provisioner pass (§3.12); workspace grants arise in §6.4's seeding.
   Anything still keyed on an IAM role ARN would have been stale anyway — the ARNs embed the old
   account ID.

**The freeze has a second precondition besides the delta size, and it is not ours.** The client's
third-party driver desktops query the **old** account over SAML (§2 item 15), and the successor
account has no SAML stack for them to land on — so an unmigrated desktop reads frozen data after the
freeze and nothing after decommission. **The driver fleet must be migrated before the freeze is
called** (§3.10), or the dual-key fallback costed first. Phase 0 inventories the fleet precisely so
this date can be set against a known number.

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

- **Ask G8 with the driver fleet in the question (§3.10).** A G8 failure no longer means only "build
  a Cognito bridge for the portal": the client's Excel/Access/Power BI users are on SAML and must
  migrate to an OIDC-based TIP plugin, so under Variant B the **whole desktop fleet** authenticates
  against that bridge too, or falls back to `JWT_TIP` with something else minting each user's JWT.
  Same gate, larger blast radius.
- **Settle the variant — gate G8 (§5.5), and it is a conversation, not an experiment.** Ask the
  Entra tenant owner whether an OIDC/OAuth2 app registration is available for this application, on
  the **default signing key**. Pass → **Variant A** and no Cognito is ever built; fail → **Variant
  B** and a bridge pool is built to be deleted later. It gates Phase 1's whole auth configuration
  and part of Phase 5, it has a long lead time, and **building B when A was available is the
  expensive mistake** — so start this on day one of the phase, ahead of the experiments below.
- **Inventory the driver desktop fleet** (§3.10, §2 item 15): how many desktops, on which ODBC/JDBC
  versions, and who can push an upgrade to them. It sizes a migration this project does not run but
  does depend on, and it is the input Phase 6's freeze date has to respect. Client-side work, asked
  for in Phase 0 because the lead time is theirs, not ours.
- **Confirm SCIM provisioning from Entra into Identity Center is live** (§2 item 12) — the exchange
  maps a claim to an Identity Center user and grants target Identity Center groups; neither works
  without it, in either variant. It is somebody else's system, so confirm it rather than assume it.
- **Run the §5.4 permission-set experiment.** Unchanged and still first among the experiments: gate
  P3 now decides whether §3.9's Access Grants or a permission-set-fed base plane serves user storage
  (§5), and P2 decides whether session tags can come from Identity Center attributes.
- **Run gate G7 (§5.5) alongside it.** It is a single query against a throwaway IdC-enabled
  workgroup, and it is the one experiment that can invalidate §3 outright — the documentation is
  ambiguous (§3.5) and no amount of further reading will settle it. Standing the workgroup up also
  surfaces the S3 Access Grants prerequisite while it is still cheap, and the workgroup's
  authentication method cannot be changed afterwards, so throwaway means throwaway.
- **Settle single-account coexistence on the same throwaway instance** (§3.10, §8): with the IdC
  workgroup up, confirm whether a SAML-federated driver session can still query a *different*,
  regular workgroup in that account. Undocumented either way, and irrelevant while the two paths sit
  in two accounts — but it is the precondition of the dual-key fallback, and it is nearly free once
  G7's workgroup exists.
- **Run gate G9 (§5.5) on the same throwaway instance** — presign an S3 `GET` and a `PUT` from
  `GetDataAccess`-vended credentials and redeem both from a browser origin. Cheap, and the
  "AWS credentials never reach the browser" posture rests on it (§3.9).
- **Check the Region against the list, before anything else is stood up.** Trusted identity
  propagation with Athena is available in an **enumerated set of Regions** — `us-east-1` is on it;
  `eu-south-2`, `ap-south-2`, `il-central-1`, `me-central-1` and `ca-west-1` are not. The Identity
  Center instance, the Access Grants instance, the Athena workgroup and Lake Formation must all sit
  in that **same** Region. §4.1 asks whether the account is in the same organization and never asks
  this.
- **Size the `CreateTokenWithIAM` quota against the user base.** JWT-bearer token generation is
  limited to **10 requests per second, instance-wide across every application on the Identity Center
  instance**, and it is raisable only by support request. Every sign-in performs exactly one
  exchange (§3.5), so this is a *login-storm* limit — a Monday-morning cohort, or a deploy that
  invalidates sessions — and the instance is shared with whatever else the organization runs on it.
- Do **not** run the retired spike's G1 experiment. It is settled (§3.5).
- Confirm the successor account: does it exist yet, is it in the **same organization** (same
  Identity Center organization instance — load-bearing, §4.5), who else is scheduled to land in
  it and when, and is the portal's first-tenant ownership of the account singletons (§4.4)
  agreed and written into the contract.
- Call `DescribeLakeFormationIdentityCenterConfiguration` in the successor account (§4.4).
- Identify the Identity Center administrators and their process for creating a customer-managed
  application (§4.5).
- Confirm the exact **claim** carrying the catalog-safe username, and that it is stable for the life
  of a user — **[A]** an Entra claim, which you cannot write to, so if none carries it the username
  must be derived or mapped rather than stored; **[B]** the same, mapped through the bridge pool
  (§6.1). It keys the S3 prefix, so a change strands data.
- **Decide the Access Grants prefix identity** (§3.9): one **literal grant per user**, keeping the
  username as the prefix and making a grant a provisioning step — or **one broad grant narrowed by
  `${identitystore:UserId}` in the location role's own policy**, which is standing but replaces the
  username with an Identity Store id. There is no variable grant scope; the two mechanisms are a
  grant and a policy. It may split, because the workgroup's user-identity result prefix (`${user_id}`)
  may move **results** regardless. §3.5 now records that the **prefix** is optional; what is still
  open — and what to establish here — is whether *Override client-side settings* can be left off on an
  IdC workgroup that declines it.
- Inventory the old account: buckets and data volumes, prefix conventions, per-user Glue
  databases, shared workspaces and per-user membership counts (§6.4's ceiling check), core
  datasets and the existing grant matrix.
- **Get the username list, and settle its shape** (§3.12): where it comes from, what a row carries,
  how it is refreshed, and — the question that decides how much §3.11 has to invent — whether a row
  carries the Identity Store attribute beside the catalog-safe username. **Ours to specify, theirs
  to produce**, so ask early even though nothing is built from it until Phase 1.
- **Write the provisioning contract** (§3.12): the per-user checklist, extracted from
  `provision_user` and extended with the prefix marker the browser writes today, plus the two
  passes and what each needs to know. It is the specification the provisioner is built from and the
  thing the sync is checked against, and it names the acceptable latency between a user existing in
  Identity Center and being provisioned. **The tag alignment is now ours on both sides**
  (`portal-managed`, granted by the portal's own TBAC tag-policy grants), so it is a consistency
  check rather than a negotiation.
- **Decide who owns de-provisioning** (§3.12) — nothing does today, and a leaver keeps a prefix, a
  database, a directory entry and, after Phase 5, a live Access Grant.
- Choose the sync tooling and rehearse one real prefix end-to-end in non-production, including
  re-encryption under a customer-managed key (§6.5).

**Exit criteria:** every question in §8 has an answer; **G8 has settled the variant in writing**;
G7 and G9 have run; P1–P3 findings are written down and Phase 1's credential design is confirmed or
revised in light of them.

### Phase 1 — Stand up the portal in the successor account

**Goal:** the portal runs in the successor account with corporate SSO: an organization user signs in
with Entra and lands in an empty portal whose file browser is correctly scoped to them. No data yet,
and that is fine.

> **The credential model in this phase is the INTERIM one, and naming it is what keeps the phase
> tractable.** §3.4's end state — one identity-enhanced plane with storage on S3 Access Grants — is
> **Phase 5** machinery: it needs the trusted token issuer, the customer-managed application, the
> Access Grants instance and the IdC-enabled workgroup, none of which exist yet. Phase 1 instead
> runs the plane **Arc B already built**: the API verifies the OIDC ID token and calls
> `sts:AssumeRole` on the shared portal role with a `username` session tag taken from the verified
> claim, and `${aws:PrincipalTag/username}` keeps scoping every S3 and Glue policy exactly as it
> does today (SPEC-196).
>
> Three things follow, and all three are improvements on the previous plan:
>
> - **The Cognito Identity Pool is never created in the successor account, in either variant.** Arc
>   B retires it (SPEC-202) before the move, and nothing here brings it back. Every Phase 1 item the
>   previous version of this section had about the pool, its principal-tag mapping and the
>   `custom:portal_username` attribute is **deleted**, not rewritten.
> - **The interim plane is provider-agnostic.** It needs a verified ID token and nothing else, so it
>   works identically under **[A]** and **[B]** and needs no Identity Center integration at all.
> - **Shared-space membership tags come from the registry**, computed by the API at `AssumeRole`
>   time rather than read from a directory attribute — which removes the SPEC-056 propagation delay
>   for the whole interim window. It does **not** remove the ten-slot ceiling: see below. Phase 5 then
>   replaces tags altogether (§3.9), so this is a way station, not a destination. **SPEC-203 owns it**
>   and ships before this phase, in the current environment, where the two sources can be proved to
>   agree — an assertion that is unwritable once this account is live. Its mechanism is a **per-user
>   membership index in the admin bucket**, not a registry scan: enumerating a user's spaces from the
>   registry costs a listing plus a read per space on every credential mint, and the request cannot
>   name its own spaces (a fully-qualified `SELECT` names none).

**Both variants:**

- Apply the portal's IaC into the successor account — **including** the Lake Formation settings
  and bucket registration it now legitimately owns (§4.2). Register the user-space bucket in
  **hybrid** mode (§6.2).
- Point the API's token verifier at the new provider: issuer, audience, JWKS URI and the **username
  claim** are configuration (SPEC-195 FR-002). **That half is configuration; the next item is not.**
  Confirm the claim against Phase 0's finding (§6.1).
- **Wire `MEMBERSHIP_SOURCE` to the index, and discharge the live check that goes with it.**
  SPEC-203 **shipped** the membership index and both sources, so the code is proved against each —
  but the variable is in **no Terraform**, and `docs/testing/owed.md` records that the index path has
  never been exercised against a real sign-in. So this is a wiring change plus the one owed check,
  not "configuration": the index path is an authorization input that has never run live, and
  flattening it to a config flip is how it reaches production untested. It also re-sources
  SPEC-198's route-level membership check, which would otherwise refuse every shared space once the
  claims are gone.
  *The paragraph below is why that spec exists; it is retained because it is the argument, not the
  work.*
  SPEC-196 deliberately builds the `shared_space_k` tags from the **token's claims**, and says so as
  a requirement — that is what makes its "not one IAM policy is rewritten" claim provable rather than
  arguable. In the successor account there are no such claims to read (no Cognito attribute in
  **[B]** by decision, no writable directory in **[A]**), so the tags must come from the shared-space
  registry, computed at `AssumeRole` time. It is a real change to the identity layer with real
  consequences to spec: a registry read on the credential-minting path, new API-plane IAM on the
  admin bucket, a per-mint latency cost, an availability coupling, and a defined behaviour when the
  read fails (**fail closed** — a missing tag denies, which is the safe direction, but it must be
  chosen rather than inherited). It needs its own equivalence argument, exactly as SPEC-196 says.
  **Write the spec before this phase, not during it.**
- Confirm `${aws:PrincipalTag/username}` resolves in a real request — the whole isolation model is
  that one tag, and a session without it matches nothing.
- **Land the provisioner's deploy-role IAM and its entry in the user-space bucket policy first, in
  their own PR** — an explicit resource-policy deny beats an identity-policy allow, so a role
  missing from `user-space-bucket-policy.json.tftpl` is denied at runtime with a green plan
  (§3.12).
- **Build and deploy the provisioner** (§3.12): `provision_user`'s existing sequence plus the prefix
  marker write, behind a new trigger, reading the username list from the admin bucket. It provisions
  nobody yet — Phase 2 runs it — but it ships here so the run is not the first time it executes.
- Remove the `pre-signup` and `post-confirmation` **triggers** — sign-in provisions nothing (§2
  item 7). **[A]** they go with the User Pool. **`provision_user` itself is kept** and moves to the
  provisioner, and `pre_signup.py`'s username rule is not deleted either: it moves, as the
  provisioner's refusal, taking `cpcommon`'s `CATALOG_IDENTIFIER_RE` rather than making a third copy.
- Remove `ensurePrefixMarker` and every other write the portal makes to establish a prefix (full
  removal list in §6.3). **The marker itself is not retired — its writer moves** to the provisioner
  (§3.12).
- Delete the sign-up UI surface. This is **cosmetic**: `startSignUp` in `auth.service.ts` lines
  64-66 is literally `return startSignIn();`, so there is no distinct code path. The surface is
  `startSignUp` in `auth.service.ts`, `signUp` in `AuthProvider.tsx` and `auth.types.ts`, the
  "Create account" / "Create your account" handlers in `routes/LandingPage.tsx` (lines 470, 509,
  607), copy in `lib/returnPath.ts`, and the "automatic right after sign-up" empty state in
  `features/query/DatabaseNode.tsx`.
- Feature-flag off Query workspace, Table Builder, Table Share and Data Quality.
- **Coordinate with the hosting workstream (§4.6):** the container's final origin has to be settled
  before this phase's redirect URIs are registered, in either variant.

**[A] — baseline, no Cognito:**

- Register the portal as an **OIDC application in Entra**, on the **default signing key** (a custom
  signing key is unsupported for the trusted-token-issuer path in Phase 5 — get it right now, not
  then). Confidential client; the redirect URI is the API's callback route.
- The API performs the code exchange and holds the tokens; the browser gets the `httpOnly` session
  cookie and nothing else (§3.5, §4.7).
- **Do not apply `infra/modules/auth`.** No User Pool, no Identity Pool, no Managed Login, no custom
  attributes, no `supported_identity_providers`, no self-signup to turn off.

**[B] — fallback, Cognito as a bridge:**

- Create the bridge User Pool and configure **SAML federation to Entra** (§3.3), with
  `supported_identity_providers` set to that provider only and the provider passed to the login
  redirect so no picker appears.
- **Self-signup off, and local identities impossible** — this is the §3.3 guardrail, not hygiene: a
  self-asserted email is another person's grants.
- **Ship no custom attribute schema at all.** Not `custom:portal_username`, not
  `custom:shared_space_*`. Nothing app-level depends on Cognito (§2 item 1), the username comes from
  the verifier's configured claim and membership from the registry — and Cognito custom attributes
  can never be renamed or deleted, so an attribute created "just in case" is permanent.
- Everything else is identical to **[A]**; the API's verifier configuration points at the pool's
  issuer instead of Entra's.

**Verification:** sign in as two real users; confirm from CloudTrail that the expected `username`
session tag is stamped for each on the assumed role, that neither can reach the other's prefix with
raw credentials pulled from the session, and that no browser request carries AWS credentials.

**Rollback:** tear the stack down; the account was empty. Nothing in the old account changed.

### Phase 2 — Provision every known user, then sync personal spaces

**Goal:** the file browser and notifications work in the successor account against synced copies
of each user's data — in spaces the portal created rather than the sync.

- **Run the provisioner over the whole username list** (§3.12), in the non-production account
  first. Every row ends provisioned, already-provisioned, or **refused and named**; a run that
  reports only a count has not been read. Refusals to expect: a name that fails the catalog rule,
  and a name already registered as a shared space.
- Run the object sync (§6.5 layer 1) for personal prefixes, re-encrypting under the successor
  account's customer-managed key. **Either order is safe, run sequentially** — the marker is
  written only when absent and the database create tolerates already-exists — but check-then-write
  is not concurrency control, so do not overlap the two runs; a pass that assumes an empty prefix is
  wrong either way, and the sync must not treat the marker as stray data (§3.12).
- Audit the reserved prefixes (§6.3) against **both** the synced data and what the provisioner
  creates, **before** users arrive, and resolve collisions while the copy is still disposable.
- **Verify a provisioned space against the checklist**, not against a count: database present,
  `portal-managed` tag present, portal-role grant present, marker object present — and a user whose
  provisioning *partially* failed is found by the sweep rather than by a support ticket.
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
  create its Glue database and grants, and populate the roster caches from the Phase 0 membership
  inventory. Idempotent and re-runnable. **There are no member attribute slots to populate** — the
  interim plane computes membership session tags from the registry at `AssumeRole` time (Phase 1),
  so a correct registry object *is* the membership. The §6.4 parity check drops that item and gains
  one: the registry object must carry every member the manifest names, because nothing else does.
- **Inventory the (member, space) pairs and record them as Phase 5 work.** In the end state each one
  becomes an S3 Access Grant on the space's prefix plus a Lake Formation grant on its database
  (§3.9), issued by the shared-space control plane — **§3.11**. This phase is where the size of
  that job becomes known, and the count is a direct input to that section's grant budget: the Access
  Grants instance holds 100,000 grants and is shared account-wide.
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

**Rollback:** feature-flag the arcs back off, one at a time. Nothing else in this phase is
destructive, and the interim plane still carries the file browser.

### Phase 5 — Identity Center identities in Lake Formation

**Goal:** core datasets governed by Lake Formation grants keyed on the Identity Center user, not
on any IAM role. The design is §3; the work items are here.

- Register the trusted token issuer in Identity Center — **[A]** Entra (issuer URL + JWKS, default
  signing key), **[B]** the bridge User Pool
  (`https://cognito-idp.{region}.amazonaws.com/{userPoolId}`). Confirm the `aud` configuration and
  which claim maps uniquely to the Identity Center user (`email` is the usual choice). Identity
  Center supports up to ten trusted token issuers, so registering both during a B→A migration is
  possible.
- Create the customer-managed application — **requires the management account or a delegated
  administrator** (§4.5). Register a second, separate application if the broader
  identity-brokering capability is being pursued (§5.1).
- Build the token-exchange backend with its session store (§3.5).
- Create the catalog carrier role (§3.6).
- Create the Lake Formation Identity Center configuration (§4.4) — under this strategy most
  likely a create, not a join.
- Create an Identity Center enabled Athena workgroup **for the portal**, and — having decided its
  kind (§3.10; AWS supports the driver path on either) — a **second** workgroup for the driver path.
  Two workgroups, because a workgroup's authentication method is fixed at creation (§3.5) and
  because the documented driver setup otherwise tags whichever one already exists.
- Add a connection kind in `useConnections` running under the identity-enhanced session.
- **Stand up the driver path** (§3.10) — **ours**: the OIDC app registration and its
  `localhost:7890/athena` redirect URI, the customer-managed Identity Center application, the
  Application and Access roles, the `AthenaDriverOidcAppArn` tag on **both** that application and the
  workgroup, and the decision of **which workgroup** the driver path lands on (AWS supports either
  kind; put it on its own and enforce that in IaC, because the documented quick path tags an existing
  one).
- **Hand the desktop migration to the client's endpoint owners** — **theirs**: the DSN shape, the
  ODBC 2.1.0.0 / JDBC 3.7.0 floor, and the rollout itself. It does not block the portal's cutover,
  because the SAML path keeps running in the **old account** while this comes up in the successor
  one — **but its deadline is §6.5's write freeze**, not "whenever". If it runs long, the dual-key
  fallback (§3.10) has to be costed *before* the freeze date is set.
- Stand up the core datasets: dataset registry config, data cell filters, and the reconciler
  (§3.8) pointed at the successor account — a re-run of the existing grant matrix against
  unchanged Identity Center principals (§4.1). No dual-granting: there are no bespoke roles to
  grant alongside.
- **Stand up S3 Access Grants (§3.9) and migrate storage onto it.** This is more than the workgroup
  prerequisite it was previously described as: it is what replaces `${aws:PrincipalTag/username}`
  when the interim plane retires. Instance, Identity Center association, registered locations,
  `sts:SetContext` on the location role, and the per-user grants in whichever prefix form Phase 0
  decided. **Gate G9 (§5.5) must have passed** before the API presigns from these credentials.
- **Run the provisioner's identity-shaped pass** (§3.12) — the per-user Access Grant, if Phase 0
  chose the literal form. It could not run in Phase 2 because a grant binds an Identity Center user
  rather than a string, so it waits on SCIM. An unresolvable user is a **refusal naming the user**,
  never a skip, and "not in Identity Center yet" and "the directory is unhealthy" get different
  reasons.
- **Issue the shared-space grants** the Phase 3 inventory produced — one Access Grant per (member,
  space) prefix plus the matching Lake Formation grant on the space's database, issued by the
  shared-space control plane. **The design is §3.11**, and its cutover ordering is what this phase
  must follow: entitle every member and verify, *then* retire the tags, *then* revoke the standing
  role-level Lake Formation grants `shared-space-create` issues today — and rewrite the tag-scoped
  Glue statement in the same change as that revocation, because the rewrite is the hazard's actual
  trigger. Reversed, every member is locked out; skipped, every user is entitled to every space.
- **Retire the interim plane** last, and only once storage and catalog both run on the
  identity-enhanced session: the portal role's session-tag assumption, the `username` and
  `shared_space_k` tags, and the `${aws:PrincipalTag/username}` conditions in the policies that no
  longer gate anything. Keep it running alongside until then — it is the rollback.
- Prove gates G2 through G6 (§5.5). G7 and G9 should already be settled from Phase 0.
- **Re-test the cross-plane join.** §3.4 records that the two-plane wall is gone and a personal
  database should now join a core dataset in one statement. Confirm it; do not carry the old
  "almost certainly will not work" expectation forward, and do not assume it either.

**Verification:** two users on the same carrier role see different data; a user with no grant is
denied. Confirm with raw credentials, not through the UI. Separately, confirm no Identity Center
token ever reaches the browser — inspect the network trace, not just the code.

**Rollback:** the interim plane, which is why the last work item retires it rather than the first.
Until that step every user still reaches storage and catalog through the shared role and its
principal tag, so an entitlement that fails to project is a defect rather than an outage.

### Phase 6 — Cutover and decommission

**Goal:** the successor account becomes authoritative; the old account is retired. Follow §6.5.
Mostly verification and patience — do not rush the freeze or the decommission to hit a date.

- Delta syncs until the final delta is small. **Before calling the freeze, confirm the driver
  desktop fleet has migrated off the old account's SAML path** (§3.10, §6.5) — the freeze strands
  whatever has not. Then call the freeze; run the final delta; run the full verification inventory.
- Flip users to the new origin; the old account goes read-only.
- Hold through a quiet period with no access failures and no missing-data reports; then
  decommission the old account.

**Rollback (before decommission only):** point users back at the old account and lift the
freeze. This is the whole reason the old account survives the quiet period.

---

## 8. Open questions by gating phase

**Gating Phase 0 to 1:**

- **Gate G8 (§5.5) — can Entra issue OIDC for this application?** It decides the variant (§3.3), it
  is a conversation with the tenant owner rather than an experiment, and it has the longest lead
  time of anything in this list. Ask first — and **ask it with the driver fleet in the question**
  (§3.10): under Variant B the client's desktops authenticate against the Cognito bridge too, so the
  gate's blast radius is larger than §5.5's row alone suggests.
- **Is SCIM provisioning from Entra into Identity Center live** (§2 item 12), and who operates it?
- ~~What do the client's Excel, Access and Power BI users connect with today?~~ **ANSWERED
  2026-08-24 — they are on the SAML path and must be migrated** (§2 item 15, §3.10's migration
  subsection). Its successor is **how many desktops, on which ODBC/JDBC versions, and who can push an
  upgrade**, which Phase 0 now inventories and which §6.5's freeze date must respect.
- **Can the SAML feature and a TIP workgroup be live in the SAME account** (§3.10)? Undocumented
  either way, so it is settled by experiment, not by reading — Phase 0 now runs it on G7's throwaway
  workgroup. Irrelevant while the two paths sit in two accounts; decisive for the dual-key fallback,
  which is the only plan that needs both in the successor account.
- **The Access Grants prefix identity** (§3.9): one literal grant per user, or one broad grant
  narrowed by `${identitystore:UserId}` in the **location role's policy**? It decides whether a grant
  is a provisioning step and whether the username survives as the prefix, and it may split between
  the file browser and query results. **Sub-question — narrowed 2026-08-19, because §3.5 answers half of it:** the `${user_id}` prefix is
  optional; what is still open is whether *Override client-side settings* can be left off. The old
  wording asked whether the user-identity result
  prefix be turned off (§3.5)?
- Gates P1, P2 and P3 (§5.4). P3 now decides whether §3.9's Access Grants or a permission-set-fed
  base plane serves user storage (§5).
- Does the successor account exist yet, and is it in the **same organization** — the same
  Identity Center organization instance? §3 and §4.1 assume yes (§4.5).
- Who else lands in the successor account, when, and is the portal's first-tenant ownership of
  the account singletons (§4.4) contractual?
- Which Identity Center attribute carries the catalog-safe username, and is it stable for the life
  of a user? It keys the S3 prefix, so a change strands data.
- **The username list** (§3.12): where it comes from, what a row carries, how often it is
  refreshed, what a re-run does with a name that has disappeared from it, and — the question that
  decides how much §3.11 has to invent — whether a row carries the **Identity Store attribute**
  beside the catalog-safe username. *~~The tag alignment and the permissions control plane's
  coverage~~ were questions for somebody else's automation; §2 item 7's amendment makes both ours,
  so the tag is a consistency check against our own `.tftpl` grants and the grants are step 3 of
  the provisioner's own pass.*
- **Provisioning latency:** how long between a user appearing in Identity Center and the
  provisioner having run for them, and is the defensive empty state acceptable for that window?
  Queries against a not-yet-created database must fail soft. Up-front provisioning shrinks this to
  the gap between a **new joiner** and the next run, rather than every user's first visit — but it
  does not close it.
- **Who owns de-provisioning** (§3.12), and what is meant to happen to a leaver's prefix, database,
  directory entry and Access Grant. Nothing owns it today.
- **[B] only** — does the client permit a Cognito User Pool at all, even as a bridge that
  authenticates nobody? If the answer is no *and* G8 fails, neither variant is available and §3.3
  needs a third OAuth issuer, which is unscoped infrastructure.
- Session lifetime: a refresh token can outlive an Identity Center session revocation, so a
  deprovisioned employee could hold a valid portal session. What window is acceptable, and does
  sign-out need single logout? Unchanged by the variant — the API holds the tokens either way.

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

- **How many workspaces can one user belong to, and how many (member, workspace) pairs are there?**
  Both, and the first is still a hard gate. **The ten-slot cap survives Phases 1–4** — it lives in
  `portal-role-shared-space.json.tftpl`'s per-slot loop, not in Cognito, so sourcing the tags from
  the registry does not lift it (§6.4 as corrected). If any user exceeds ten, either raise
  `max_shared_memberships` and re-render the policy — the one IAM change the interim window
  otherwise promises not to make — or accept a truncated membership until Phase 5. The pair **count**
  matters separately: every pair is a grant Phase 5 has to issue.
- ~~Who issues the per-(member, space) grants, and under which spec?~~ **Answered 2026-08-18, and
  it is no longer a spec: §3.11**, a new verb plus a reconciling sweep on the existing shared-space
  control plane. What remains open is an *input* to it, not a question about it: the Phase 3 pair
  count, which sizes its grant budget against the instance's 100,000-grant ceiling.
- Are all old-account workspace names catalog-safe under `^[a-z][a-z0-9_]{2,62}$`? They become
  Glue database names in the successor account.

**Gating the hosting workstream (§4.6, §4.7):**

- ~~Where does the container run?~~ **Settled — ECS Fargate**, task role supplies credentials.
- ~~Does the backend co-locate or stay a Lambda?~~ **Settled — a Lambda behind API Gateway** (§4.7). *The earlier answer here was "co-located in the same container"; Arc B reversed it.*
- ~~**One image promoted across environments, or a build per environment?**~~ **Settled and built —
  one image**, with configuration fetched at runtime from `/config.json` (SPEC-192) and its values
  read from Terraform state (SPEC-215). §4.6 carries the one argument worth keeping.
- Who owns TLS and DNS for the new origin, and what is the turnaround on getting a certificate?
  The origin must be settled before Phase 1's provider callback URLs are finalised.
- What is the session cookie's lifetime relative to the provider session and the Identity Center
  refresh token — the three clocks in §4.7? (Bucket CORS is now this repo's own configuration —
  §4.6 — so the old change-request dependency is gone.)

**Gating Phase 5:**

- **Gate G7 (§3.5, §5.5) — settled in Phase 0 or not?** If a plain `StartQueryExecution` on an
  identity-enhanced session turns out to be unsupported, everything below is moot and §3 is reopened.
- Who owns **S3 Access Grants** in the successor account — another account-wide singleton to name in
  the coordination contract (§4.4), and one this repo does not touch today.
- **Who owns the driver path's Identity Center application, its Application Role and its Access Role**
  (§3.10) — they are separate from the portal's, and the customer-managed application needs the
  management account or a delegated administrator. Does the Athena workgroup carry the TIP
  configuration tags the plugins read?
- **Do Excel and Access actually work on the Browser TIP plugin** (§3.10)? AWS names Power BI,
  Tableau and DBeaver and never names either. Test Access first — its linked tables reconnect often,
  and a browser prompt per reconnection would make it unusable while passing every other check.

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
- ~~Cross-plane joins: a query joining a personal database against a core dataset almost certainly
  will not work.~~ **Reversed by §3.4's collapse** — on one plane both are Lake Formation grants
  against the same propagated identity, so the join should be ordinary. Confirm it in Phase 5
  rather than assuming it in either direction.
- **Gate G9 (§5.5)** — can the API presign from `GetDataAccess`-vended credentials? If not, the
  browser holds scoped credentials after all and SPEC-202's live-check wording is wrong.

**Gating Phase 6:**

- How long a write-freeze window is tolerable, and in which calendar window does it land (§6.5)?
  **The driver desktop fleet's migration is a precondition of that date** (§3.10) — has it finished,
  or is the dual-key fallback being costed instead?
- How long must the old account survive read-only before decommission?

---

## 9. What this leaves behind

Code that becomes dead and should be deleted rather than left to rot:

**"Leaves behind" means at cutover, not now.** Everything below is load-bearing in this repo until
the successor account is live, and one of these has already been broken *because* it was mentally
retired: `pre-signup` shipped for nine days unable to import its own Lambda layer, failing real
sign-ups, and nothing noticed (2026-08-01, PR #317 — the Correction section of SPEC-137's delivery
doc). Deleting this code is a **cutover** task; keeping it working is a **today** task.

- **The Cognito TRIGGERS, not the provisioning they call — AMENDED 2026-09-04.** The
  `pre-signup` and `post-confirmation` entry points go, because sign-in provisions nothing (§2 item
  7), and `scripts/backfill-portal-managed-tag.sh` goes with them. But `provision_user` **moves to
  the provisioner** (§3.12) rather than being deleted, `pre_signup.py`'s username rule **moves to
  the provisioner's refusal** — taking `cpcommon`'s `CATALOG_IDENTIFIER_RE` rather than making a
  third copy of the same literal — and `backfill.py`'s job is replaced by §3.12's sweep rather than
  simply dropped. *This item used to delete both modules whole, because the client's automation was
  going to own provisioning; the portal owns it now.*
- `ensurePrefixMarker`, its constants in `fileBrowser.constants.ts`, its call site in
  `routes/FilesPage.tsx`, the barrel re-export in `features/file-browser/index.ts`, and its
  tests (§6.3 has the full list). **The marker object itself stays** — what goes is the browser
  writing it; the provisioner writes it instead (§3.12). Deleting the marker with its writer would
  make every provisioned prefix invisible to the username directory.
- `startSignUp` / `signUp` across `auth.service.ts`, `AuthProvider.tsx`, `auth.types.ts`,
  `test/authFixtures.ts`, and their tests.
- Sign-up copy in `routes/LandingPage.tsx`, `lib/returnPath.ts` and
  `features/query/DatabaseNode.tsx`.
- ~~**The Cognito Identity Pool, its principal-tag mapping and `lib/awsCredentials.ts`**~~ —
  **DONE (SPEC-202, 2026-08-31).** Retired before the move rather than at cutover, and never
  recreated in the successor account in either variant (Phase 1).
- **[A] — all of Cognito.** `infra/modules/auth` in full: the User Pool, Managed Login v2 and its
  branding re-ensure step in CI, the app client, the hosted-UI domain, `lib/amplify.ts` and the
  `aws-amplify` dependency, and every runtime-configuration key naming a pool. **[B]** keeps the
  pool as a bridge and deletes the same list when the tenant gains OIDC — which is the whole reason
  §3.3 keeps the bridge thin.
- **The `custom:shared_space_*` attribute schema** and `var.max_shared_memberships` — membership is
  the registry from Phase 1 onward, and per-(member, space) grants from Phase 5 (§3.9).
- ~~The CloudFront distribution, its origin access configuration, the static-hosting bucket, the
  **SPEC-140 response headers policy**, and the deploy-app sync and cache-invalidation CI steps~~ —
  **DONE (SPEC-193 → 202, 2026-09-02).** The header set and SPEC-141's per-class `Cache-Control`
  scheme live in the container's nginx configuration; §4.6 records the three divergences.

**No longer removed** — reversals from the previous strategy: `aws_lakeformation_data_lake_settings`,
the bucket registration, the user-space bucket policy template, and the shared-space `create`
verb all **stay**. The portal owns them in the successor account (§4.2).

Documentation to rewrite when this lands: `docs/architecture.md` (*Identity*, *Authorization*, and
the ADR rows for both, which §3.5 breaks), `docs/decisions/identity-and-access.md` (auth and
shared-space material) and `docs/decisions/analytics.md` (Lake Formation), plus a new entry for the
federated claim — the register is one file per area with a Contents at the top of each, so find the
entry by its heading rather than reading the file,
`lambdas/info/planes/shared-spaces.md` (ownership model), and the in-app help content per the
SPEC-074 rule.

---

## 10. Sources

Lake Formation:
[IAM Identity Center integration limitations](https://docs.aws.amazon.com/lake-formation/latest/dg/identity-center-lf-notes.html) ·
[Data filtering limitations](https://docs.aws.amazon.com/lake-formation/latest/dg/data-filtering-notes.html) ·
[Registering an S3 location in another AWS account](https://docs.aws.amazon.com/lake-formation/latest/dg/register-cross-account.html) ·
[Prerequisites for Identity Center integration](https://docs.aws.amazon.com/lake-formation/latest/dg/prerequisites-identity-center.html) ·
[CreateLakeFormationIdentityCenterConfiguration](https://docs.aws.amazon.com/lake-formation/latest/APIReference/API_CreateLakeFormationIdentityCenterConfiguration.html)

Athena:
[Use IAM Identity Center enabled Athena workgroups](https://docs.aws.amazon.com/athena/latest/ug/workgroups-identity-center.html) ·
[Use Lake Formation and JDBC or ODBC drivers for federated access to Athena](https://docs.aws.amazon.com/athena/latest/ug/security-athena-lake-formation-jdbc.html)

Athena drivers and trusted identity propagation (§3.10):
[Use Trusted identity propagation with Amazon Athena drivers](https://docs.aws.amazon.com/athena/latest/ug/using-trusted-identity-propagation.html) ·
[Browser trusted identity propagation credentials (ODBC)](https://docs.aws.amazon.com/athena/latest/ug/odbc-v2-driver-browser-oidc-tip.html) ·
[JWT trusted identity propagation credentials provider (ODBC)](https://docs.aws.amazon.com/athena/latest/ug/odbc-v2-driver-jwt-tip.html) ·
[JWT trusted identity propagation credentials (JDBC)](https://docs.aws.amazon.com/athena/latest/ug/jdbc-v3-driver-jwt-tip-credentials.html) ·
[Amazon Athena ODBC 2.x release notes](https://docs.aws.amazon.com/athena/latest/ug/odbc-v2-driver-release-notes.html) ·
[Use the Amazon Athena Power BI connector](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc-and-power-bi.html) ·
[Athena launches single sign-on support for drivers, 11 September 2025](https://aws.amazon.com/about-aws/whats-new/2025/09/amazon-athena-sso-drivers/)

IAM Identity Center:
[Enable AWS account access for customer managed applications](https://docs.aws.amazon.com/singlesignon/latest/userguide/enable-account-access-customer-managed-apps.html) ·
[Using applications with a trusted token issuer](https://docs.aws.amazon.com/singlesignon/latest/userguide/using-apps-with-trusted-token-issuer.html) ·
[Identity-enhanced IAM role sessions](https://docs.aws.amazon.com/singlesignon/latest/userguide/trustedidentitypropagation-identity-enhanced-iam-role-sessions.html) ·
[Enabling identity-enhanced console sessions](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-enhanced-sessions.html) ·
[Attributes for access control](https://docs.aws.amazon.com/singlesignon/latest/userguide/attributesforaccesscontrol.html) ·
[Delegated administration](https://docs.aws.amazon.com/singlesignon/latest/userguide/delegated-admin.html) ·
[Announcement, 30 June 2026](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-iam-identity-center-account-access-customer-managed-apps/)

S3 Access Grants and Entra:
[S3 Access Grants — working with instances, locations and grants](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-grants.html) ·
[Using S3 Access Grants with IAM Identity Center identities](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-grants-directory-idc.html) ·
[GetDataAccess](https://docs.aws.amazon.com/AmazonS3Control/latest/API/API_control_GetDataAccess.html) ·
[Automatic provisioning (SCIM) from Microsoft Entra ID to IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/idp-microsoft-entra.html)

IAM and STS:
[Granting permissions to use identity-enhanced console sessions (`sts:SetContext`)](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_temp_control-access_sts-setcontext.html) ·
[AWSIAMIdentityCenterAllowListForIdentityContext](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSIAMIdentityCenterAllowListForIdentityContext.html)

---

## 11. Revision history

**One line per revision, pointing at where its substance went.** Every correction these announce is
recorded *in place* in the section it belongs to, which is where a reader should meet it — this list
exists so the chronology is recoverable, not so anyone works from it.

- **2026-09-06 — operator break-glass transfer.** Recorded in **§3.11** as a seventh projection
  trigger, deferred to it, routing to SPEC-217's recorded threat model rather than restating
  SPEC-208's objection. §3.11's index-guard sentence corrected in place: the guard fires on a
  seventh verb whether or not it writes the index.
- **2026-09-04 — provisioning and ordering pass.** The portal takes ownership of provisioning:
  new **§3.12**, amending §2 item 7 and reaching §1's table, §6.5's layers, Phases 0/1/2/5, §8 and
  §9. Added **The order of work** as a router over §7. Pruned to what has landed: §4.6's
  configuration fork, §4.7's co-location banner, §5's amendment block (with §5.2's two bullets
  corrected in place) and §6.1's pre-Arc-B claim-reader inventory. **§6.3's `delete` row was
  narrowed rather than struck, and the 2026-08-18 instruction to strike it was withdrawn** — the
  never-active branch still destroys, which is exactly the state a mid-seed workspace presents.
- **2026-08-24 — third-party driver pass.** New **§3.10**: the client's Excel, Access and Power BI
  users are on the SAML path and must migrate (§2 item 15), which puts a deadline on §6.5's freeze
  and raises G8's stakes to the whole desktop fleet. Three claims in that section's first draft were
  corrected at review the same day and are marked where they sit.
- **2026-08-19 — live-docs validation pass.** §3.5's IAM action prefix, its replay paragraph, the
  assertion's permitted token type and the `${user_id}` half-answer, each corrected against the live
  page. The validation log is in `docs/target-architecture-variants.md`.
- **2026-08-18, second of two that day — the identity-variant revision.** Entra ID is named; the
  plan gains variants **[A]** and **[B]** (§3.3). §3.4's two credential planes collapse into one,
  which creates **§3.9**'s storage plane and reshapes §6.1's trap rather than deleting it. Gate
  **G8** joins §5.5. It also added three **forward-compatibility obligations** to Arc B's drafts —
  each small, each with a test, none of them gating that arc: SPEC-195 keeping the verifier free of
  router dependencies, SPEC-198's presigned-URL clamp reading the credential rather than a
  configured duration, and SPEC-199 keeping the results-location derivation in one function.
- **2026-08-18, first of the two** — §3.5 gains its step-3 caveat and gate **G7**: whether a plain
  `StartQueryExecution` on an identity-enhanced session is supported at all.
- **2026-08-03 — reconciled against the folded `architecture.md`**: control-plane records moved
  there; §4.6, §6.3 and §9 updated with the header and caching facts.
- **2026-08-01 — the strategy revision.** Build in the **successor account as its first tenant**,
  with the client's data arriving by **sync and cutover**, superseding the 2026-07-31 decision to
  deploy in place into the populated existing account. §4, §6 and §7 are reworked around it; §3 and
  §5 are account-agnostic and unchanged.
