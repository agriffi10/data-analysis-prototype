---
type: Spec
id: SPEC-196
title: "The AWS Identity Layer — Role Assumption, the Two Credential Planes"
description: "Lets the API assume the portal role server-side with session tags read from the verified token's claims, so every existing IAM, bucket and Lake Formation policy keeps isolating users unchanged."
spec_status: Completed
depends_on: [SPEC-011, SPEC-013, SPEC-016, SPEC-032, SPEC-056, SPEC-033, SPEC-106, SPEC-127, SPEC-128, SPEC-129, SPEC-130, SPEC-131, SPEC-132, SPEC-133, SPEC-134, SPEC-135, SPEC-136, SPEC-137, SPEC-186, SPEC-193, SPEC-195]
arc: api-layer-and-containerisation
arc_order: 5
---

**Dependency notes:** SPEC-011 (the Identity Pool ABAC model this spec preserves — the `username` principal tag stamped server-side from the verified claim), SPEC-013/016/032/056 (the portal role's prefix-, Glue- and membership-scoped policies that must keep enforcing unchanged), SPEC-033 (the catalog-safe username rule the session name is validated against), SPEC-106 (`toUserMessage` — raw AWS text is never rendered), SPEC-127→137 (`cpcommon.observability`, the one door, and the field rule), SPEC-186 (`env` + `version` on every log record; the deployed-role IAM simulation discipline), SPEC-193 (the API Lambda, its execution role and the placeholder route this spec proves itself with), SPEC-195 (the API's auth boundary — the verified ID token whose claims this layer reads its tag values from)
## Overview

Today the browser holds AWS credentials. Amplify exchanges the Cognito ID token with the Identity
Pool, AWS reads the `cognito:username` claim and stamps it as a `username` principal tag, and the
portal role's policies expand `${aws:PrincipalTag/username}` into every S3 prefix, Glue database and
membership-slot ARN. That one tag is the whole isolation model: a session without it matches nothing.

SPEC-195 gave the API a **verified ID token** — the same token the browser already holds, signature-
checked against the provider's JWKS on every request. This spec is how that token's claims become AWS
credentials **on the server** — the API calls `sts:AssumeRole` on the same portal role with the same
tag set, read from the same claims, so **not one IAM policy, bucket policy or Lake Formation grant is
rewritten**. That preservation is the arc's central claim, and this is the spec that has to prove it
rather than assert it.

The claim reading is not an analogy. `aws_cognito_identity_pool_provider_principal_tag.username`
maps `username → cognito:username` and `shared_space_k → custom:shared_space_k`, and it reads those
claims **out of the ID token the browser presents**. The API is handed that same token and reads the
same claims. Same token, same claims, same tag names, same role — which is why nothing downstream
can tell the two credential paths apart.

The second half of the spec exists because the design has one failure mode and it fails *open*: a
helper that hands back the wrong AWS client makes the call **succeed**, against the wrong identity.
So the API gets two named credential planes, a declaration per call site, a runtime guard that fails
closed, and a sweep that enumerates every site rather than trusting review.

## Scope

### In Scope

- **The user plane**: `sts:AssumeRole` on the existing portal role with the **full** session-tag set
  — `username` plus the ten `shared_space_k` membership slots — built from the claims of SPEC-195's
  **verified** ID token, and from nothing else the request carries.
- **The trust policy** on the portal role: a second statement admitting the API Lambda's execution
  role, with both `sts:AssumeRole` and `sts:TagSession`.
- **The role session name**, validated against `CATALOG_IDENTIFIER_RE`, with a stated refusal for a
  username that cannot be represented.
- **The API plane**: the API Lambda's own execution role — the `sts:AssumeRole` call itself today,
  SPEC-200's queue writes later. Opt-in, per route, by registry.
- **Per-container credential caching** keyed so a warm Lambda cannot serve user B with user A's
  credentials, plus the expiry margin and the single forced re-assume that replace
  `lib/credentialRetry.ts` server-side.
- **Failure semantics** for three distinguishable conditions — assume-role failure, an unusable
  token, Lake Formation / IAM denial — mapped to HTTP statuses and SPEC-106 codes.
- **Observability** through `cpcommon.observability` into `logs/`, with `env` and `version`
  populated, under the field rule, inheriting SPEC-195's `error.stack` treatment.
- **One temporary probe route** (`GET /_identity/self`) making a trivial user-plane call plus its own
  negative control, so the arc's first live proof of isolation exists before any feature is ported.
- Deploy-role IAM: **verified as already sufficient** (FR-003) rather than assumed. No new AWS
  resource type is created by this spec.

### Out of Scope

- **The transport contract** — route shape, response envelope, error wire format, the TS↔Python
  agreement mechanism, the SPA's API client. SPEC-197. This spec defines error *semantics* (which
  condition, which status, which code) and defers how they are serialised.
- **Any ported service.** No `*.service.ts` changes, no `@aws-sdk/*` import removed; the browser
  still calls AWS directly for everything. SPEC-197 → 199.
- **The queue writes and the `{actor, delegated_by, assurance}` contract.** SPEC-200. The portal
  role keeps its `sqs:SendMessage` grants and the browser keeps enqueueing until then.
- **Any change to the control-plane Lambdas** — they keep verifying the ID token and reading
  `cognito:username`. SPEC-201.
- **Retiring the Identity Pool.** Both credential paths run side by side for the whole arc (SPEC-202
  retires the pool), which is what makes every spec between here and there independently revertible.
- **Identity Center identity context.** FR-001's interface is shaped so the later swap is a change of
  *tag source*, not of call site, but nothing IdC-specific is built here.
- **Any browser-visible change.** No `VITE_*` variable is added; the SPA learns nothing about roles.

### What produces the tag today, what produces it after, and why they are equivalent

| | Today (Identity Pool) | After this spec (the API) |
|---|---|---|
| What the browser supplies | The Cognito ID token | **The same Cognito ID token** |
| Who verifies its signature | AWS `cognito-identity`, against the User Pool | The API, against the provider's JWKS, **on every request** (SPEC-195) |
| Where the tag values come from | The `cognito:username` and `custom:shared_space_k` claims of that token | **The same claims of the same token** |
| What performs the mapping | `aws_cognito_identity_pool_provider_principal_tag.username` | `session_tags()` (FR-002), reading the same claim names |
| Who chooses the value | AWS, from the verified claim | The API, from the verified claim — **never from anything else in the request** |
| The STS call | `AssumeRoleWithWebIdentity` + `TagSession` | `AssumeRole` + `TagSession` |
| The role | `aws_iam_role.portal` | `aws_iam_role.portal` — **the same role** |
| The resulting tag set | `username`, plus one `shared_space_k` per occupied slot | Byte-identical |

The equivalence is not an analogy, it is **the same computation over the same input**. The Identity
Pool's principal-tag map is a declaration of *which claim feeds which tag*; `identity-pool.tf` merges
`{username = "cognito:username"}` with `{shared_space_k = "custom:shared_space_k"}` into one map, and
AWS applies it to the ID token the browser presents. The API is handed that same token and applies
the same map in Python. The claim names are the contract, and they are the *only* thing this spec
copies from the Identity Pool.

That is the whole argument that no policy is rewritten: a policy sees a session tag, not who stamped
it, and both stampers read the same claim of the same token.

**A corollary about freshness, and it is not a new defect.** A claim set is exactly as fresh as the
token that carries it. A shared space added after the token was issued is invisible to the API until
that token refreshes — which is precisely SPEC-056's documented behaviour: *"a membership change
updates Cognito attributes; the tag stamps at the next credential vend. Grant/revoke takes effect on
token refresh"* (`architecture.md` → *Shared Spaces*), with SPEC-052's **Refresh connections**
control forcing one. The trigger is unchanged because the carrier is unchanged: today a stale token
vends stale credentials, and after this spec a stale token stamps stale tags. Both are cured by the
same `fetchAuthSession({forceRefresh: true})` the Refresh control already issues, so the control
keeps working **provided the SPA reads the token per request rather than caching one of its own** —
which SPEC-195 owns and this spec depends on (Premise 1). If anything the new path is marginally
fresher: FR-006 keys the credential cache on the tag set, so a refreshed token whose slots changed is
a cache miss on the very next request, where Amplify's own credential cache can hold the old
credentials for the rest of the hour.

**What would break the equivalence**, precisely: taking a tag value from anything other than a claim
of the verified token — a header, a query parameter, a body field, an unverified JWT, or a
username the API re-derives from a path segment. Also: any route that accepts a username or space
name and uses it to *select credentials* rather than to *scope a call made with the caller's own
credentials*. SPEC-200's `delegated_by` is a message field describing who asked; it is never a
credential selector.

### Premises later specs must honour

Stated here because SPEC-195 is written in parallel and the rest are not written at all.

1. **SPEC-195's verification result exposes every claim this layer needs** — `cognito:username`
   *and* `custom:shared_space_1..N` — not the username alone. A verifier that returns only the
   username silently removes every shared space from every user (FR-002). The claims are present in
   the token by construction: the Identity Pool reads them out of it today (`identity-pool.tf`), and
   shared-space isolation demonstrably works — but Phase 5 confirms it directly against a live token
   rather than resting on the inference. The same premise's other half: **the SPA reads the token
   from Amplify per request** rather than caching one of its own, or SPEC-052's Refresh-connections
   control stops propagating membership and the freshness corollary above becomes false.
2. **`GET /_identity/self` is removed by SPEC-197**, when the ported user-directory route makes the
   same proof against a real feature. It is a scaffold, not a diagnostic surface.
3. **A route may not take a credential-selecting parameter.** Space and username parameters scope a
   call; they never choose an identity (FR-001).
4. **No route may construct a boto3 client.** FR-005's sweep is repo-lint, not review advice; a
   ported service that reaches for `boto3.client(...)` reddens CI.
5. **The "no existence oracle" rule (SPEC-113) survives the move.** A route asked about a space this
   user cannot reach must refuse without probing AWS. That is per-route work in SPEC-198/199; it is
   named here because the identity layer's 403 is what a careless route would leak through.

**AMENDED 2026-08-18 — this layer is CORRECT and it is also TEMPORARY, and both halves matter.**
`transition_plan.md` §3.4 collapses the target's two credential planes into one identity-enhanced
session, and §3.9 records the consequence: because
`AWSIAMIdentityCenterAllowListForIdentityContext` denies plain S3, the end state governs storage with
**S3 Access Grants** and has **no principal tags at all**. So the whole tag set this spec builds —
`username` and the ten `shared_space_k` slots — does not survive Phase 5 of the transition.

**Nothing in this spec changes as a result, and the equivalence argument is why.** The claim to
preserve is that *not one IAM policy, bucket policy or Lake Formation grant is rewritten*, and that
is only provable if the API stamps byte-identically what the Identity Pool stamps — from the same
claims of the same token. Sourcing the membership tags from the shared-space registry instead would
be defensible in isolation and would **break the equivalence**, turning a provable preservation into
an argument. Build it from the claims (FR-002), exactly as written.

Three things a later reader should carry, because each is easy to get wrong in the other direction:

- **This layer is what makes the successor account's Phases 1–4 possible at all.** The
  identity-enhanced session needs a trusted token issuer, a customer-managed application, an Access
  Grants instance and an IdC-enabled workgroup — none of which exist before Phase 5. The interim
  plane there *is* this layer, pointed at a different provider, with **no Cognito Identity Pool
  anywhere** (SPEC-202 retires it and it is never recreated).
- **In that interim window the membership tags DO come from the registry**, because there is no
  Cognito attribute to read and no Identity Pool to read it. That is a deliberate later change with
  its own equivalence argument to make; it is not licence to make it here.
- **The ten-slot ceiling and SPEC-056's propagation delay die with the tags**, not with this spec.
  `useSharedSpaceAccessRecovery` stays exactly as it is (FR-002), because claim-sourced tags still
  carry the delay.

---

## Functional Requirements

### FR-001: The user plane — one role, assumed per request, tagged from the verified claims

#### Description:

The API assumes `aws_iam_role.portal` with `sts:AssumeRole`, passing session tags built from the
claims of the request's **verified** ID token. The credentials returned drive every call that must be
isolation-enforced.

#### Acceptance Criteria:

- [ ] The role assumed is **the existing portal role** — `var.portal_role_name`, the same ARN the
      Identity Pool's role attachment names. A new role is not created. (FR-008 is why.)
- [ ] `DurationSeconds` is **3600**, matching the Identity Pool enhanced flow's one-hour credentials
      exactly, and within the role's default `MaxSessionDuration` so no `iam:UpdateRole` is needed.
      **Do not shorten it without reading this:** SPEC-198 mints presigned URLs with these
      credentials, and a presigned URL dies with the credential that signed it — a 15-minute session
      would cap every download link and every multipart upload window at 15 minutes, a user-visible
      regression with no failing test.
- [ ] The `Tags` list is built **only** from the verified claims. A test constructs a request whose
      body, query string and non-`Authorization` headers **all** carry `mallory` while the verified
      token's `cognito:username` claim says `alice`, and asserts the `AssumeRole` call's `Tags` are
      exactly `alice`'s. The fixture must **disagree** — one where the request and the claim agree
      passes over the defect.
- [ ] The claims come from SPEC-195's **verification result**, never from an independent decode. A
      test asserts this layer's modules contain no base64/JWT-decoding call of their own: a second
      decoder is a signature check that silently is not one, and it looks identical when it is wrong.
- [ ] `TransitiveTagKeys` is **absent** from the request. A transitive tag survives role chaining;
      nothing here chains, and a tag that outlives its session is a durable escalation.
- [ ] The tag key carrying the username is read from configuration (`PRINCIPAL_TAG_KEY`), and its
      agreement with the stamper is **asserted, because it cannot be structural**. `var.principal_tag_key`
      does **not** feed the role policies: it reaches only `infra/modules/analytics/`, whose
      `portal-role-analytics.json.tftpl` interpolates it — while `portal-role-permissions.json.tftpl`,
      `portal-role-shared-space.json.tftpl` and `identity-pool.tf`'s
      `{ username = "cognito:username" }` all hard-code the literal `username`. So "one variable feeds
      both, therefore they cannot drift" is false, and **threading the variable through those templates
      to make it true would edit them, which FR-008's no-change guard forbids by design.** The criterion is a
      read-back instead: a test parses the tag name out of `identity-pool.tf`'s `principal_tags` map —
      the declaration AWS actually applies — and asserts the API's configured value equals it. A wrong
      value produces a session whose tags match no policy statement, which reads as `AccessDenied`
      everywhere and names nothing.
- [ ] `sts` is reached through the API plane (FR-005). The identity layer is the one module exempt
      from FR-005's sweep, and the exemption is **by module identity**, never by a name pattern
      (SPEC-165's rule).

### FR-002: The tag set is the WHOLE tag set

#### Description:

`username` is not the only principal tag the Identity Pool stamps. SPEC-056 maps ten
`custom:shared_space_k` claims onto ten `shared_space_k` tags — in the *same* merged
`principal_tags` map, because there is only one such map per (pool, provider) — and the portal
role's shared-space policy templates one statement pair per slot. Stamping `username` alone leaves
every personal feature working and **every shared space broken**.

#### Acceptance Criteria:

- [ ] The tag list is `username` plus `shared_space_1..MAX_SHARED_MEMBERSHIPS`, taken from the
      matching `custom:shared_space_k` claims of the verified token.
- [ ] The claim-name → tag-name mapping this layer implements is **the same one**
      `identity-pool.tf` declares. A test asserts the pairs `("cognito:username", username)` and
      `("custom:shared_space_k", "shared_space_k")` for every k, reading the tag name from
      `PRINCIPAL_TAG_KEY` and the slot count from `MAX_SHARED_MEMBERSHIPS`. A hand-written
      `shared_space_{k}` that drifts from the Tofu map produces a session with plausible-looking
      tags that match no policy statement.
- [ ] **A slot with no claim contributes NO tag** — it is omitted from the list, never sent with an
      empty value. This is load-bearing, not tidiness: an empty-valued tag makes
      `${shared_space_bucket_arn}/${aws:PrincipalTag/shared_space_3}/*` resolve to
      `arn:aws:s3:::dat-prod-shared-space//*`, which is a live grant on every key beginning with `/`
      — a key S3 permits. Today an unstamped slot simply matches nothing. Asserted on the `Tags`
      list itself (the key is absent), not on the value being falsy.
- [ ] `MAX_SHARED_MEMBERSHIPS` comes from the same Tofu variable that sizes the policy templates and
      the Cognito attributes (`var.max_shared_memberships`), delivered as the environment variable
      `shared-space-common` already reads under that name. A test reads the Tofu variable back and
      asserts agreement — a hand-copied 10 is the defect this closes.
- [ ] The tag-count bound is **computed, not asserted** (SPEC-161's rule): a test names STS's
      50-session-tag ceiling and the 128/256-character key/value limits, computes
      `1 + MAX_SHARED_MEMBERSHIPS` against them, and fails if raising the slot count would breach
      one. It must name the schedulable unit — here, one tag per membership slot.
- [ ] **This is the requirement that silently succeeds when it is wrong.** Omit the slot tags and
      personal S3, personal Glue, notifications and the file browser all work; only shared spaces
      return `AccessDenied` on a listing — for which the app already has a "Refresh access" recovery
      built for SPEC-056's known propagation delay, so a missing tag *presents as the documented
      delay*. The distinguishing assertions are (a) a test that reads the `Tags` kwarg off the stubbed
      `AssumeRole` call for a member of ten spaces and asserts **eleven** entries — the call itself,
      not its trace, because this account records no `AssumeRole` event anywhere (Phase 5 item 2) — and
      (b) Phase 5's simulation row that flips `allowed` → `implicitDeny` when the slot tag leaves the
      context.
- [ ] **Membership propagation keeps its current semantics, and the carrier is the reason.** The tag
      values ride the ID token both before and after, so a membership change takes effect on the next
      **token refresh** — SPEC-056's documented delay, unchanged, with SPEC-052's Refresh-connections
      control still forcing one. The cache key (FR-006) is the whole tag set, so the refreshed token
      is a cache miss on the very next request rather than waiting out a cached credential.
      Asserted by a test: two requests whose tokens differ **only** in one `custom:shared_space_k`
      claim issue two `AssumeRole` calls with different tag sets. A test whose two tokens differ in
      the username passes with the slot claims ignored entirely.

### FR-003: The trust policy

#### Description:

The portal role gains a second trust statement. It must admit the API Lambda's execution role and
nothing else.

#### Acceptance Criteria:

- [ ] The new statement's `Principal.AWS` is the **API Lambda execution role's ARN** (SPEC-193's
      role), passed in as a variable. Not the account root, not a wildcard, not the deploy role.
- [ ] `Action` is **both** `sts:AssumeRole` **and** `sts:TagSession`. Either alone renders, plans,
      applies and unit-tests green, then fails at runtime with an `AccessDenied` naming neither the
      tag nor the missing action — it reads as a permissions bug in whichever feature called first.
      A `.tftpl` test asserts both actions are present in the same statement.
- [ ] The existing `AssumeRoleWithWebIdentity` statement is **untouched**. Both credential paths run
      for the whole arc; SPEC-202 removes the first.
- [ ] A `ForAllValues:StringEquals` condition on `sts:TagKeys` bounds the statement to the
      `username` + `shared_space_k` key set, and a `Null` condition on `sts:TransitiveTagKeys`
      requires their absence. **State the limit honestly in the spec and in the template's comment:**
      this constrains tag *keys*, not tag *values*, and IAM has no way to constrain the value. The
      unspoofability argument rests entirely on FR-001's "the value comes from a claim of a
      signature-verified token", never on the trust policy.
- [ ] **This spec supersedes SPEC-195 FR-009 AC2's STS clause, and owns the edit.** That criterion
      sweeps the API execution role for **zero** statements naming STS, and this FR's companion
      statement on that role (Data Model, below) is exactly one. SPEC-195 carries the superseded
      marker; **this spec updates the test in the same commit that adds the statement**, to: zero
      statements naming DynamoDB, KMS, Secrets Manager or Cognito, and **exactly one** naming STS,
      whose actions are `sts:AssumeRole` and `sts:TagSession` and whose `Resource` is
      `${portal_role_arn}` and nothing else. Left as written, SPEC-195's sweep goes red on the day
      this spec lands, and the repair a builder reaches for is to delete the sweep — which also
      removes the DynamoDB, KMS, Secrets Manager and Cognito guards that have nothing to do with this
      change.
- [ ] **Deploy-role IAM is verified, not assumed.** `github-actions-deploy.json.tftpl` already grants
      `iam:UpdateAssumeRolePolicy` on `${portal_role_arn}`; a test asserts that grant exists, so a
      later narrowing reddens here rather than at the next apply. No new resource type is created by
      this spec, so `architecture.md` → *Deploy-role IAM — adding a new resource type* does not
      apply — and saying so is part of the requirement, because "it needed no expansion" and "we
      forgot to check" are indistinguishable in a diff.

### FR-004: The role session name

#### Description:

The session name appears in CloudTrail and in every assumed-role session ARN. It must identify the
user unambiguously.

#### Acceptance Criteria:

- [ ] The session name is the username **verbatim** — no prefix, no suffix, no transformation.
- [ ] The username is **validated, never trusted**, against `cpcommon.config.CATALOG_IDENTIFIER_RE`
      (`^[a-z][a-z0-9_]{2,62}$`) — the constant the rest of the repo already owns — *and* against
      STS's own `RoleSessionName` charset (`[\w+=,.@-]{2,64}`).
- [ ] A test **computes** the containment rather than asserting it: every string the catalog rule
      admits is 3–63 characters drawn from `[a-z0-9_]`, which is a strict subset of `\w` and inside
      2–64, so no valid username needs escaping. The same test computes why **a prefix is not
      available**, and truncating would collapse two usernames onto one CloudTrail identity.

      > **CORRECTED 2026-08-27, during build — this criterion's arithmetic was off by one, and
      > computing it rather than asserting it is what found that.** This spec said "63 + any
      > non-empty prefix exceeds 64". It does not: the longest catalog-safe username is 63 and STS
      > admits 64, so the **prefix budget is exactly one character** and a one-character prefix
      > fits. **The requirement is unchanged** — the session name is the username verbatim — but
      > the reason is not the one written down. The true reason is the budget itself: one
      > character is not a namespace, so any prefix worth having (a service name, an environment,
      > a separator) overflows for the longest usernames, and the only way to make it fit is to
      > truncate, which is the collision this criterion already names. The test computes the
      > budget, fails if it ever grows, and says so in its own docstring.
- [ ] A username that fails either rule is **refused** — never sanitised, never truncated. The
      request fails as `IdentityUnavailable` (FR-007), the refusal is logged with the username (user
      metadata, permitted by the field rule), and no `AssumeRole` is issued. Asserted by a test that
      passes a username with a hyphen and one 64 characters long and counts **zero** STS calls.
- [ ] Refusal rather than repair is deliberate and forward-looking: SPEC-146 records that the
      transition replaces `cognito:username` with a synthetic `identitycenter_<subject>`, whose
      Entra-shaped subject carries hyphens and uppercase and will **not** satisfy this rule. Refusing
      loudly, from one shared constant, makes that a single-constant change with a failing test in
      front of it; sanitising would make it a silent identity collision.

### FR-005: Two credential planes, declared per call site

> **Naming note (2026-08-18).** "Two credential planes" here means **user plane** and **API plane** —
> whose credentials a route uses. `transition_plan.md` §3.4 uses the same phrase for a different
> split (**base plane** and **catalog plane** — which enforcement mechanism governs a resource), and
> supersedes it. They are unrelated; this one is unaffected.

#### Description:

- **User plane** — FR-001's assumed role. Every call that must be isolation-enforced.
- **API plane** — the API Lambda's execution role. Only what the user is not directly authorized
  for: the `sts:AssumeRole` call itself today, SPEC-200's verified queue writes later.

A helper that hands back the wrong client fails *open*. So the plane is declared, the guard is
runtime and fails closed, and the enumeration is mechanical.

#### Acceptance Criteria:

- [ ] Every AWS client in the API comes from exactly one of two constructors — `user_client(service,
      identity)` or `api_client(service)`. There is no third way in.
- [ ] **The default is the user plane.** A route with no declaration may use `user_client` only;
      `api_client` requires the route's entry in `ROUTE_PLANES` to name `Plane.API`. The less
      privileged plane is the default because the dangerous direction is a user-scoped call escaping
      onto the execution role.
- [ ] `api_client` called from a route that did not declare it **raises** `PlaneViolationError`
      before any AWS call. Verified **by deliberate violation in both directions** (SPEC-163's
      precedent, SPEC-176's lesson): a route declared user-only calling `api_client` raises, *and*
      a route declaring `Plane.API` calling it succeeds. One direction alone passes for a guard that
      always raises.
- [ ] A **guard equates the two sets**: every key in `ROUTE_PLANES` is a route the router dispatches,
      and every route the router dispatches has a key. A hand-maintained list rots; the guard is what
      stops it (SPEC-163's `GATED_SURFACES` shape).
- [ ] An **AST sweep** over the API package fails if any module other than the identity layer calls
      `boto3.client`/`boto3.resource`/`boto3.Session`, or imports `cpcommon.clients`. The second half
      matters as much as the first: `cpcommon.clients` is a module-level cache of *default-credential*
      clients — exactly the shape that works perfectly in every single-user test and serves the
      execution role's identity to a user's request in production.
- [ ] The sweep's exemption for the identity layer is by **node/module identity**, not a name or
      filename pattern (SPEC-165's docstring-vs-declaration lesson: a pattern exemption silently
      exempts the next module someone names similarly).
- [ ] `user_client` takes the identity as a **parameter**. It may not reach for a request-scoped
      global, because a module-global "current identity" is FR-006's leak wearing a different hat.

### FR-006: Credential caching, and the leak it invites

#### Description:

A warm Lambda serves many users in sequence. `cpcommon.observability`'s `traced` clears trace baggage
at the start of every invocation precisely so one invocation's identity cannot leak onto the next; a
credential cache deliberately *survives* the invocation, so it must be keyed instead of cleared.

#### Acceptance Criteria:

- [ ] Credentials are cached per container, keyed on the **whole tag set** — the username and the
      ordered membership slots — never on the username alone and never on nothing.
- [ ] A cached entry is used only while `expires_at - now > margin`. The margin is **computed by a
      test** against the budget that sizes it (the API's own timeout plus the longest downstream call
      it makes), not written as a literal.
- [ ] **The assertion that catches a wrongly-keyed cache, stated as a sequence in ONE process:**
      request A carrying `alice`'s token, then request B carrying `bob`'s, then request A again
      inside the margin. **This is the leak the whole design most invites**: nothing about a warm
      container is per-user, and a cache that gets this wrong serves user B a client holding user
      A's credentials — which succeeds, against the wrong identity, with the right-looking data.
      Assert (1) B's client carries `bob`'s credentials, (2) exactly **two** `AssumeRole` calls were
      issued across the three requests, and (3) the second call's tags are `bob`'s. Every clause is
      load-bearing: without (1) a shared cache passes; without (2) a cache keyed on the request id —
      safe but useless — passes; without (3) a cache that re-assumes with the previous tag set
      passes. **None of this is visible to a single-user test**, which is the whole reason the
      criterion is written as a sequence.
- [ ] A fourth request with `alice`'s token **refreshed so one `custom:shared_space_k` claim
      differs** issues a **third** `AssumeRole`. This is FR-002's propagation criterion asserted from
      the cache's side, and it is what a username-only key gets wrong — a username-only key would
      pin a user to whichever membership set their first request of the hour happened to carry,
      turning SPEC-056's refresh-to-propagate contract into refresh-and-nothing-happens.
- [ ] An `ExpiredToken`/`ExpiredTokenException` from a downstream call made with cached credentials
      triggers **one** forced re-assume and **one** retry — the server-side successor to
      `lib/credentialRetry.ts`'s single retry, for the same reason it exists. A second failure is
      not retried; it becomes FR-007's `IdentityUnavailable`.
- [ ] A test-only `reset_credential_cache()` exists and is called by the suite's fixture, so a
      leak between *tests* cannot mask a leak between *requests*.

### FR-007: Failure mapping — three conditions the user must be able to tell apart

#### Description:

An assume-role failure, an unusable token and a Lake Formation / IAM denial are three different
things. Conflating them makes isolation-working-correctly read as a bug, and a bug read as a refusal.
Wording comes from SPEC-106's `toUserMessage` and nowhere else; the wire format is SPEC-197's.

#### Acceptance Criteria:

- [ ] **A missing, malformed, unverifiable or expired ID token → HTTP 401, code `SessionExpired`.**
      **SPEC-195 FR-004 and FR-008 own that contract whole** — the status, the single code, the
      byte-identical bodies, and the one forced refresh and one retry that are the arc's only retry.
      This spec restates none of it and adds no behaviour to it. Its own obligation is a negative one
      and it is what the test asserts: the identity layer **never produces a 401 of its own**, and
      never re-uses `SessionExpired` for an AWS-side failure. A sweep over this layer's modules finds
      no 401 and no `SessionExpired` literal.
- [ ] **A downstream `AccessDenied` / `AccessDeniedException` on the user plane, including every Lake
      Formation denial → HTTP 403**, code `AccessDenied`. This is the isolation model working. It
      must **not** trigger a re-login, and it must not be worded as "your session expired".
- [ ] **`AssumeRole` failure, tag-construction failure, or an unrepresentable username → HTTP 500**,
      code `IdentityUnavailable`. The user did nothing wrong and can do nothing about it; the message
      resolves to SPEC-106's "Contact the Administrator." fallback.
- [ ] A test asserts the three map to **three distinct** statuses and three distinct codes. A mapper
      that collapses two of them passes any test that exercises one at a time.
- [ ] **No raw AWS text crosses the boundary.** A test raises a botocore `ClientError` whose message
      contains a role ARN and an account id and asserts neither string appears in the response body.
      Every code added here has a rule in `lib/errorMessages.ts`; none is `passthrough` (that flag is
      only ever set on messages this repo authored).
- [ ] The **403 must not become an existence oracle.** Premise 5 is per-route work, but the identity
      layer's contract is fixed here: a 403 says "this request was refused", never "that space
      exists and you are not in it".

### FR-008: What stays true — the preservation claim, asserted

#### Description:

The claim is that every existing authorization artefact keeps enforcing unchanged. The claim is only
worth making if each artefact is checked individually.

#### Acceptance Criteria:

- [ ] **The identity policies are unchanged — all NINE of them.** The portal role carries **nine**
      inline permission policies, one per bounded context, and the count is worth stating because a
      reader who names three or four will diff three or four:
      `user-space-access` (`portal-role-permissions.json.tftpl`), `shared-space-membership`,
      `analytics-access`, and six enqueue policies — `archive-enqueue`, `notifications-enqueue`,
      `data-quality-enqueue`, `file-send-enqueue`, `table-share-enqueue`, `table-build-enqueue` —
      each rendered from its own `portal-role-*.json.tftpl`. (Arc A's file-ops plane adds a tenth; the
      guard below is a set, not a count, so it absorbs that without editing.) The **trust** policy,
      `portal-role-trust.json.tftpl`, is the one template this spec does edit (FR-003).
- [ ] **The no-change guard is a NAMED-ABSENCE assertion, not a golden diff.** A test that snapshots
      the rendered templates during the build and diffs them against themselves compares a copy of the
      answer with itself and passes whatever happens. Two assertions that can fail: (a) the set of
      `portal-role-*.json.tftpl` files under `infra/modules/*/policies/` **excluding**
      `portal-role-trust.json.tftpl` is byte-identical to the **pre-change git blob** at this spec's
      base commit, checked with `git show`; and (b) the rendered permission policies name **no** new
      `Resource`, **no** `sts:` action and **no** statement mentioning the API execution role. (a)
      catches a tidy, (b) catches a widening that a re-baselined snapshot would have absorbed.
- [ ] **The user-space bucket-policy allowlist needs NO new entry, and here is why, from the code:**
      the allowlist Denies every principal whose `aws:PrincipalArn` is not in a list that already
      names `${portal_role_arn}`; `s3.tf`'s own comment records that `aws:PrincipalArn` for an
      assumed-role request resolves to the **role's IAM ARN**, not the session ARN, which is why
      Identity-Pool users are already excluded from the Deny. `sts:AssumeRole` produces the same
      resolution, so **assuming the same role keeps the same allowlist entry valid.** This is the
      single strongest reason a new role was not created — the allowlist is hand-maintained and this
      repo has already been bitten by a principal missing from it.
- [ ] **That resolution is the one preservation claim that cannot be proved offline** and is a
      Verification item, not an assertion here: `simulate-principal-policy` does not fetch a bucket
      policy, so a real call through the assumed session is the only proof. **`GET /_identity/self`
      is that call** — the Deny's action list includes `s3:ListBucket` (verified against
      `user-space-bucket-policy.json.tftpl`), so the probe exercises the same resolution a `GetObject`
      would, and no route from SPEC-198 is needed. Phase 5 item 3.
- [ ] **Lake Formation grants are unchanged.** LF resolves an assumed-role principal to the role ARN
      and does not read session tags, so SPEC-033's per-database grants keep applying. LF is not
      modelled by the simulator either, and **this spec ships no route that queries Athena** — so it
      is recorded as **owed** and discharged by SPEC-199's first live query, not claimed here.
- [ ] **The shared-space bucket has no bucket policy** (verified: only user-space, archive, static
      assets and the trail bucket carry one), so its access is identity-policy-only and FR-002's tag
      set is the entire gate. Stated because a reader will look for an allowlist there, and its
      absence is otherwise indistinguishable from an oversight.
- [ ] **The archive bucket stays unreachable.** The portal role holds zero statements naming it and
      the archive bucket policy's allowlist does not include it; nothing here changes that, and a
      test asserts the portal role's rendered policies name the archive bucket nowhere.

### FR-009: Observability

#### Description:

The identity layer's spans go through `cpcommon.observability` — the only door — into
`logs/service=api/`.

#### Acceptance Criteria:

- [ ] A child span (`observability.step`) around the assume call, carrying `username` and the
      **count** of membership slots as fields, and `stamp`ing `username` as baggage so every event in
      the request joins.
- [ ] `env` and `version` are populated on every record (SPEC-186 FR-005): `ENV_NAME` from Tofu's env
      map, the build sha from the `BUILD_VERSION` file **inside the package**. A record with an empty
      `env` or `0.0.0` `version` is a failure.
- [ ] **The field rule binds.** Usernames and space names are user metadata and go in; the ID token,
      any `Authorization` header value, any raw claim blob, the STS
      `SecretAccessKey`/`SessionToken` and any email **never** appear in a field. A test emits from
      every call site in this layer and asserts the union of field values contains no token-shaped
      or credential-shaped string.
- [ ] **SPEC-195's `error.stack` scrub extends to this layer, and it is a CREDENTIALS scrub — nothing
      wider.** SPEC-195 FR-007 settled the mechanism (scrub at the boundary; `log-foundry` 0.6.0
      offers no opt-out), so there is no open fork to restate here. What this layer adds to the
      surface is credential material of its own: `log-foundry`'s `end_event` walks the `__cause__`
      chain, and a failed `AssumeRole` raised inside a request whose frames hold the caller's ID token
      — or an STS response holding a `SecretAccessKey`/`SessionToken` — can pull one in. The test
      raises a synthetic exception whose `__cause__` message carries a token-shaped string and a
      credential-shaped string, and asserts no emitted record contains either.

      > **CORRECTED 2026-08-27, during build — this criterion asked for a mechanism SPEC-195 did
      > not build, and its two halves contradicted each other.** It says the treatment is
      > *inherited* from SPEC-195 FR-007, and separately that a record must not *contain* a
      > credential written into an exception message. SPEC-195 FR-007's mechanism is
      > **preventative, not a redactor**: a sweep forbidding this repo's code from rendering a
      > token into an f-string, a `%`-format, a `.format()` call or a `raise` argument, plus a
      > sentinel test. `log-foundry` 0.6.0 still exposes no way to turn stack capture off and no
      > redactor exists, so a test that deliberately writes a credential into an exception message
      > and then demands its absence asks for something neither spec ships — it is red by
      > construction. **Settled 2026-08-27 (Andrew): prevent, and record the residual.** This
      > layer extends the interpolation sweep to the four session-material names it introduces,
      > and the sentinel test drives a path that genuinely raises through the span while holding a
      > real assumed session — so the absence is asserted where a stack actually exists. The
      > residual — a future route that interpolates a session value despite the sweep — is
      > recorded in `owed.md` rather than implied to be closed.
- [ ] **The scrub does NOT extend to user data, and that boundary is deliberate.** The settled
      2026-07-23 decision **accepts** file contents reaching `error.stack` — `logs/` is admin-only and
      a stack is diagnostic metadata a failed run needs — and pins it with
      `test_ACCEPTED_the_span_error_stack_may_carry_file_contents`, a tripwire whose failure means
      revisit the decision, not delete the test. A scrub written against user-data-shaped strings
      would contradict that decision and redden that tripwire from a spec that never argued the case.
      Credentials were never inside the 2026-07-23 exemption; that is the whole of what SPEC-195 FR-007
      re-opened, and this layer inherits exactly that scope. One `decisions/` entry covers both
      layers.
- [ ] The API function's row in the deploy matrix carries the `cpcommon` layer flag and
      `lambdas/test_deploy_matrix.py` is green for it. SPEC-137 is the precedent: a layer that is
      imported and not attached deploys clean and raises `ModuleNotFoundError` at cold start, and
      every offline gate was blind to it.

### FR-010: The trivial call, and its negative control

#### Description:

The provider is proved against the placeholder API by a route that does the smallest possible
isolation-enforced thing — and, in the same breath, the thing that must fail.

#### Acceptance Criteria:

- [ ] `GET /_identity/self` requires a verified ID token (401 otherwise), makes **two** user-plane
      `ListObjectsV2` calls with `MaxKeys=1` — one on `{username}/`, one on a fixed constant prefix
      that no username can ever be (it fails `CATALOG_IDENTIFIER_RE` by construction) — and returns
      `{username, spaceCount, ownPrefixListable, foreignPrefixListable}`.
- [ ] The pass condition is `ownPrefixListable === true && foreignPrefixListable === false`. **Both
      halves can fail and they fail for different reasons**: an unstamped tag makes the first false
      (the `ListBucket` grant is prefix-conditioned on the tag), and an over-granted or
      wrongly-conditioned policy makes the second true. A route asserting only the first would pass
      with the isolation model deleted.
- [ ] The route takes **no** parameter of any kind. The foreign prefix is a constant in the code, not
      an input — a route that lists a browser-supplied prefix is the credential-selection defect FR-001
      forbids, wearing a probe's clothes.
- [ ] It is removed by SPEC-197 (Premise 2).

---

## Data Model

```python
# lambdas/api/apicommon/identity.py

@dataclasses.dataclass(frozen=True)
class UserIdentity:
    """The verified identity a request acts as.

    Built ONLY from the claims of SPEC-195's verified ID token — the same claims
    `aws_cognito_identity_pool_provider_principal_tag.username` maps today.
    """
    username: str                       # cognito:username
    #: Slot index (1-based) -> space name, from custom:shared_space_k.
    #: A slot with no claim is ABSENT, never "".
    memberships: Mapping[int, str]


@dataclasses.dataclass(frozen=True)
class AssumedCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str
    expires_at: datetime.datetime


class PlaneViolationError(RuntimeError):
    """Raised when a route reaches for a credential plane it did not declare."""


class IdentityUnavailableError(RuntimeError):
    """AssumeRole failed, or the username cannot be represented as a session name."""
```

```python
# lambdas/api/apicommon/planes.py

class Plane(enum.Enum):
    USER = "user"
    API = "api"

#: Route key -> the planes that route may use. USER is implicit; API must be named.
#: Guarded for set-equality against the router's dispatch table (FR-005).
ROUTE_PLANES: Mapping[str, frozenset[Plane]]
```

```python
# lambdas/api/apicommon/config.py  (values computed by tests, never written as literals)

PORTAL_ROLE_ARN: str                  # env, required
PRINCIPAL_TAG_KEY: str                # env, from Tofu var.principal_tag_key
MAX_SHARED_MEMBERSHIPS: int           # env, from Tofu var.max_shared_memberships
ASSUME_ROLE_DURATION_SECONDS: int     # 3600 — FR-001
CREDENTIAL_EXPIRY_MARGIN_SECONDS: int # computed against the API's own timeout budget
```

### The IAM shapes

```jsonc
// infra/modules/data/policies/portal-role-trust.json.tftpl — a SECOND statement.
// The existing AssumeRoleWithWebIdentity statement is untouched.
{
  "Sid": "TheApiMayActAsAUser",
  "Effect": "Allow",
  "Principal": {"AWS": "${api_execution_role_arn}"},
  "Action": ["sts:AssumeRole", "sts:TagSession"],
  "Condition": {
    "ForAllValues:StringEquals": {"sts:TagKeys": ["username", "shared_space_1", "…", "shared_space_N"]},
    "Null": {"sts:TransitiveTagKeys": "true"}
  }
}
```

```jsonc
// The API execution role (SPEC-193) gains exactly one statement.
{
  "Sid": "AssumeThePortalRoleAsTheCaller",
  "Effect": "Allow",
  "Action": ["sts:AssumeRole", "sts:TagSession"],
  "Resource": "${portal_role_arn}"
}
```

---

## API / Interface Contract

```python
# lambdas/api/apicommon/identity.py

def session_tags(identity: UserIdentity) -> list[dict[str, str]]: ...
"""[{"Key": ..., "Value": ...}]. Omits unset slots entirely (FR-002)."""

def role_session_name(username: str) -> str: ...
"""The username verbatim. Raises IdentityUnavailableError on FR-004's refusals."""

def assume_user_role(identity: UserIdentity) -> AssumedCredentials: ...
"""Cached per container on the whole tag set (FR-006)."""

def user_client(service: str, identity: UserIdentity) -> Any: ...
"""A boto3 client on THIS user's assumed credentials — the only isolation-enforced door."""

def api_client(service: str) -> Any: ...
"""A boto3 client on the execution role. Raises PlaneViolationError unless the current
route declared Plane.API."""

def reset_credential_cache() -> None: ...  # test fixtures only
```

## Environment Variables

No `VITE_*` variable is added — this spec changes nothing the browser can see.

New API Lambda environment variables, wired in `infra/modules/<api>/` (SPEC-193's module):

```
PORTAL_ROLE_ARN=arn:aws:iam::<account>:role/<project>-portal-user-role
                                       # = local.portal_role_arn (infra/main.tf). The name carries
                                       # NO environment segment, and var.portal_role_name overrides it
PRINCIPAL_TAG_KEY=username             # var.principal_tag_key
MAX_SHARED_MEMBERSHIPS=10              # var.max_shared_memberships
```

All three are **required** — the accessor raises at first use if unset, never defaults. A defaulted
`PORTAL_ROLE_ARN` would fail far from its cause, and a defaulted `MAX_SHARED_MEMBERSHIPS` would
silently drop membership slots, which is FR-002's silent success.

## File & Folder Structure

```
lambdas/api/                              # SPEC-193's function package
├── apicommon/
│   ├── config.py                         # extended
│   ├── identity.py                       # NEW
│   └── planes.py                         # NEW
├── routes/
│   └── identity_self.py                  # NEW — FR-010, removed by SPEC-197
├── test_identity_apicommon.py            # NEW
├── test_credential_planes.py             # NEW — FR-005's sweep + both-direction violation
└── test_credential_cache_apicommon.py    # NEW — FR-006's three-request sequence

infra/modules/data/policies/
└── portal-role-trust.json.tftpl          # + one statement (FR-003)

infra/modules/<api>/                      # SPEC-193's module
├── iam.tf                                # + the AssumeRole statement on the execution role
└── lambda.tf                             # + the three environment variables
```

## Implementation Phases

### Phase 1: The tag set, the session name and the caps

- `identity.py`'s pure half: `session_tags`, `role_session_name`, the `UserIdentity` shape.
- FR-002's omit-don't-empty rule and the Tofu read-back for `MAX_SHARED_MEMBERSHIPS`.
- FR-004's computed containment proof; the refusal path with zero STS calls.
- FR-002's computed tag-count bound against STS's 50-tag ceiling.

### Phase 2: The planes, the guard and the sweep

- `planes.py`, `ROUTE_PLANES`, the router hook that sets the current route.
- `user_client` / `api_client`; `PlaneViolationError` failing closed.
- The set-equality guard and the AST sweep, each verified by a deliberate violation in **both**
  directions.

### Phase 3: Assumption, caching and failure mapping

- `assume_user_role` over `api_client("sts")`; the per-container cache and its margin.
- FR-006's three-request sequence and the membership-change fourth.
- FR-007's three conditions → three statuses → three codes, plus the `lib/errorMessages.ts` rules.
- FR-009's spans, baggage, field-rule test and the `error.stack` inheritance test.

### Phase 4: The IAM and the probe route

- The trust-policy statement and the execution-role statement; the `.tftpl` tests, including
  FR-003's deploy-grant read-back, FR-008's git-blob baseline plus named-absence guard over the nine
  permission templates, and the SPEC-195 FR-009 AC2 sweep updated in the same commit as the STS
  statement.
- `GET /_identity/self` and its negative control.

### Phase 5: Verification

Real invocations. **Everything in this spec that matters is invisible to the offline suite**, for the
reasons SPEC-137 and SPEC-011 each learned once. Written as a runnable script at
`docs/testing/arc-b-api-container-e2e.md`.

**What only a real assumed-role call can prove:**

0. **The claims this whole spec reads are actually in the ID token.** Sign in as a member of at least
   two shared spaces, capture the ID token from `fetchAuthSession()` and decode its payload: confirm
   `cognito:username` **and** one `custom:shared_space_k` claim per occupied slot are present. The
   inference from `identity-pool.tf` is strong (AWS reads those very claims out of this very token
   to stamp today's tags) but it is an inference, and every offline test in this spec supplies its
   own fixture claims — so a token that turned out not to carry them would pass the entire suite and
   fail on the first real request. Do this **first**: if it fails, nothing else in the phase matters.
1. **The trust policy admits the API's role, with both actions.** A statement granting `sts:AssumeRole`
   without `sts:TagSession` renders, plans, applies and unit-tests green.
2. **The tags are actually stamped — and only the `username` half is observable in this spec.** There
   is **no `AssumeRole` event to read**: the account's only trail
   (`infra/modules/verification/cloudtrail.tf`, SPEC-186 FR-004) is one advanced event selector for
   **data** events on the archive bucket, with `is_multi_region_trail = false` and management events
   recorded for nothing, and no spec in this arc adds a selector — that is unbudgeted infra. A
   criterion phrased against that trail **cannot fail**: it returns nothing whether the call happened
   or not, which is SPEC-186 FR-004's own trap (an empty result from a trail that does not record the
   event reads exactly like a call that never happened). So the `username` tag is proved
   **behaviourally, by the probe's own session**: item 6's `ownPrefixListable === true` is reachable
   only with the tag correctly stamped, because the portal role's `UserPrefixList` statement grants
   `s3:ListBucket` **only** under `"s3:prefix": ["$${aws:PrincipalTag/username}/", …]`. **Verify the
   mechanism before relying on it**, as item 3 does: read `portal-role-permissions.json.tftpl` and
   record that the condition names the tag, or a later reader cannot tell the proof from a
   coincidence. `foreignPrefixListable === false` is what keeps an over-broad grant from reading the
   same way. SPEC-011 FR-002 is the precedent for looking at all: a mapping that looked right stamped
   no principal tags whatever.
   **The slot half is OWED, and this spec cannot discharge it.** Every call this spec ships touches
   the user-space bucket only, and `spaceCount` is counted from the token's claims rather than from
   the session's tags — it reports the same number with the slot tags dropped entirely. The first
   observation that can settle it is a successful user-plane call against a shared space the caller is
   a member of, where the shared-space bucket has no bucket policy and FR-002's tag set is therefore
   the entire gate; that arrives with SPEC-198's routes. Record it as owed and pass it there, as item 4
   passes Lake Formation to SPEC-199. Sign in as a member of at least two shared spaces regardless —
   items 0 and 8 both need it.
3. **The user-space bucket-policy allowlist admits the session — and `GET /_identity/self` is what
   proves it, because no `GetObject` route exists until SPEC-198.** The IAM simulator does not fetch a
   bucket policy, so `aws:PrincipalArn` resolving to the role's IAM ARN under `sts:AssumeRole` (as
   opposed to `AssumeRoleWithWebIdentity`) needs a real call through the assumed session — and the
   probe's is one. **Verify the mechanism before relying on it:**
   `user-space-bucket-policy.json.tftpl`'s `DenyDataAccessExceptPortalRole` lists **`s3:ListBucket`**
   beside `GetObject`/`PutObject`/`DeleteObject`, on `${bucket_arn}` as well as `${bucket_arn}/*`, so
   the probe's `ListObjectsV2` is subject to the same allowlist a `GetObject` would be. A
   principal the allowlist did not admit would be Denied outright, and `ownPrefixListable` would come
   back **false**. Do not read this as discharged by item 6's boolean alone: record explicitly that the
   `ListBucket` action is inside the Deny, or a later reader cannot tell the proof from a coincidence.
4. **Lake Formation still authorizes the session — OWED, not runnable here.** LF is not modelled by
   the simulator at all, and confirming it needs one Athena query on the user plane, for which
   **there is no route until SPEC-199**. Record it as owed and pass it to SPEC-199's first live query
   against the caller's own database; FR-008's LF criterion carries the same disposition. Running it
   by hand from a laptop proves nothing about this layer — the local IAM user is a different
   principal.
5. **The cache does not leak in a real warm container.** Two users' tokens, requests interleaved
   inside one execution environment (confirm the same `logStream`, or the observation is two cold
   starts and proves nothing). The observation is the two **responses**, not a trail (item 2): each
   `_identity/self` body must carry its **own** caller's `username` and `ownPrefixListable: true` —
   a leaked credential makes the second one's `username` wrong, or its `ownPrefixListable` **false**,
   because the cached session's tag no longer matches the prefix it lists. Confirm as well that
   `logs/service=api/` shows the second request carrying the second username.
6. **`GET /_identity/self` returns `ownPrefixListable: true, foreignPrefixListable: false`.** Record
   both booleans; recording only the first proves nothing.
7. **`logs/service=api/` records carry a real `env` and a real build sha**, neither empty nor `0.0.0`,
   and no record contains a token or an email.
8. **The propagation delay is what SPEC-056 documents, not something new.** Add the signed-in user to
   a new shared space, and **without refreshing the token** confirm the API still refuses that space;
   then press **Refresh connections** and confirm the same request now succeeds. Both halves are
   required: the first alone is indistinguishable from a broken grant, and the second alone from a
   grant that was always live.

**The IAM policy simulation, against the DEPLOYED role.** `aws iam simulate-principal-policy` with
`--policy-source-arn` the live portal role and `--context-entries` supplying
`aws:PrincipalTag/username` and the slot tags. **Every denial is paired with an `allowed` control**,
because an `implicitDeny` alone cannot distinguish an ungranted action from a wrong ARN — CLAUDE.md
records this repo learning that on `dat-prod-athena-admin`. At minimum:

| Action | Resource | Context | Expect |
|---|---|---|---|
| `s3:GetObject` | `user-space/alice/x.csv` | `username=alice` | `allowed` (control) |
| `s3:GetObject` | `user-space/bob/x.csv` | `username=alice` | `implicitDeny` |
| `s3:ListBucket` | `user-space` | `username=alice`, `s3:prefix=alice/` | `allowed` (control) |
| `s3:ListBucket` | `user-space` | `username=alice`, `s3:prefix=bob/` | `implicitDeny` |
| `s3:DeleteObject` | `user-space/alice/reports/x.csv` | `username=alice` | `allowed` (control) |
| `s3:DeleteObject` | `user-space/alice/DO_NOT_DELETE.txt` | `username=alice` | `explicitDeny` |
| `s3:PutObject` | `user-space/alice/archive/r.txt` | `username=alice` | `explicitDeny` |
| `glue:GetTable` | `database/alice` | `username=alice` | `allowed` (control) |
| `glue:GetTable` | `database/bob` | `username=alice` | `implicitDeny` |
| `s3:GetObject` | `shared-space/marketing/x` | `shared_space_1=marketing` | `allowed` (control) |
| `s3:GetObject` | `shared-space/marketing/x` | **slot tags absent** | `implicitDeny` |
| `s3:DeleteObject` | `shared-space/marketing/athenaresults/x` | `shared_space_1=marketing` | `explicitDeny` |

The last two rows are the ones worth the trouble: the eleventh is FR-002's silent success made
visible, and the twelfth proves the Deny is matching rather than merely present.

**Not observable, record as owed rather than discharged:** the Lake Formation authorization of the
assumed session (item 4 — no Athena route until SPEC-199, which discharges it); anything about the
Identity Center identity context (nothing IdC ships in this arc); and the behaviour of a username that
fails `CATALOG_IDENTIFIER_RE` against a live pool — the pre-signup Lambda makes one unreachable, so
FR-004's refusal stays unit-tested only.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row (status only); the delivery doc at
  `docs/spec-delivery/SPEC-196-the-aws-identity-layer.md`.
- **`decisions/` entries**, then **one line each** in CLAUDE.md's Key Decisions:
  1. *The API reads the SAME claims the Identity Pool reads, and assumes the SAME role with the SAME
     tag set* — the equivalence argument stated as one computation over one input (the ID token),
     the claim-name pairs as the only thing copied from `identity-pool.tf`, what would break it, the
     freshness corollary (a claim set is as fresh as its token, which is SPEC-056's existing delay
     and not a new one), and why reusing the role rather than minting one is what keeps the
     hand-maintained bucket-policy allowlist correct.
  2. *Two credential planes, declared per route, defaulting to the user plane* — including that the
     failure mode is fail-open and that the enumeration is a sweep plus a set-equality guard, not a
     list.
  3. *The credential cache is keyed on the whole tag set* — why a username-only key silently breaks
     membership propagation, and that a warm Lambda serving user B with user A's credentials is the
     one failure here that succeeds against the wrong identity.
  4. The `error.stack` treatment for this layer, **appended to SPEC-195's entry** rather than filed
     separately, so one entry covers the whole token-handling surface.
- An `ARCS.md` update to the arc entry recording what this spec actually found — in particular that
  the ten membership slot tags are part of the identity, which the arc entry's "a `username` session
  tag now" phrasing understates.
- A `apps/portal/info/component-inventory/` row only if the API area file exists (SPEC-193's ritual creates it);
  the row names `apicommon/identity.py` and `apicommon/planes.py`, in the area file matching their
  path, never the router.
- **The Help sweep: nothing user-facing changes in this spec.** No route is ported, no screen moves,
  no wording changes. Record that explicitly and skip, rather than leaving it ambiguous — SPEC-197
  onward own the user-visible change.
