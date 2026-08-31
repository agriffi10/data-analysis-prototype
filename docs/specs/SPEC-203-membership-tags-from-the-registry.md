# Spec: The Membership Index — Where the Tags Come From Without a Claim

**ID:** SPEC-203
**Status:** In Progress
**Last Updated:** 2026-08-18
**Depends On:** SPEC-196 (the AWS identity layer — the tag set, the per-container credential cache keyed on the whole tag set, and the claim-sourced implementation this spec makes one of two), SPEC-195 (the verified bearer and `Principal.username`), SPEC-197 (the transport contract), SPEC-198 (`apicommon/spaces.py` — the route-level membership check this spec must also re-source, FR-004), SPEC-199 (the query route, whose body names no space — the reason FR-002 is an index and not a request scan), SPEC-011 (the identity is a verified claim, never a caller assertion), SPEC-051/053/056/073/075 (the shared-space registry, the slots, the propagation contract, and `cache.write_roster_to_all` — the fan-out this spec rides), SPEC-113 (no existence oracle), SPEC-123 (an admin-bucket index under ETag CAS — **the precedent this spec follows**), SPEC-146 (a published directory that is advisory and never an authorization input — the rule this spec's index deliberately breaks, and says so), SPEC-151 (a partial teardown never frees the name), SPEC-106 (`toUserMessage`), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

## Overview

SPEC-196 builds a user's AWS session tags from the claims of their verified ID token: `username` from
`cognito:username`, and ten `shared_space_k` tags from ten `custom:shared_space_k` Cognito custom
attributes. That is correct, and it is what makes SPEC-196's central claim provable — the API stamps
byte-identically what the Identity Pool stamps, so not one IAM policy is rewritten.

In the successor account those claims do not exist. Under the transition's baseline variant there is
no Cognito at all, and under the fallback the bridge pool ships with no custom attribute schema by
decision (`transition_plan.md` §2 item 1, §3.3). Something else has to answer *which shared spaces is
this caller a member of*, on the credential-minting path, on every request.

**The registry cannot answer it.** It is one object per space, keyed by space name, so the question
costs a full listing plus a read per space. This spec builds the index that can: one object per
user, in the admin bucket, written by the same fan-out that already writes the roster at exactly the
moments membership changes.

**It ships against Cognito, while both sources exist, and that is the point.** The index could be
built during the transition, but it could not be *proved* there: with no claims to compare against, a
wrong implementation is indistinguishable from a right one, and the failure mode is a session
silently carrying the wrong spaces. Built here, the same user's membership is knowable two ways and
FR-007 asserts they agree — an assertion that expires the moment the environment moves. This repo's
most expensive outage was instrumented code whose layer attachment was missing while every gate was
blind to it (SPEC-137).

### The decision this spec reversed during review, and why it is recorded

The first draft scoped the tags to **the spaces a request names**, on the reasoning that a session
needs no tag for a space it does not touch — bounded cost, least privilege, and no new artifact.

**It does not work, and the reason is worth carrying.** SPEC-199's query route takes `{sql,
database?}` and SPEC-077 makes every base table fully qualified, so `SELECT * FROM
finance_space.sales` is an ordinary statement naming **no space and no database** anywhere the API
can see — and SPEC-199 Premise 2 makes the SQL string opaque to the API by design, so the API may not
go looking. A per-request rule mints `username` alone for that request and every shared-space query
fails. SPEC-198's `POST /v1/objects/copy` names *two* spaces, which the rule also mishandled.

So enumeration is required, the index is required, and the cost argument that motivated the
alternative is answered by making enumeration **one `GetObject`** rather than a listing.

## Scope

### In Scope

- **The per-user membership index** — its key, its shape, its writers and its consistency point
  (FR-001).
- **The membership source as a declared choice** — `claims` (today, the default) or `index` —
  resolved once from configuration, with an unknown value refused at cold start (FR-002).
- **The index source**, and what an absent, stale or unreadable index means (FR-003).
- **The route-level membership check moves with it** — `apicommon/spaces.py` re-sourced, because a
  tag the identity layer stamps and a refusal SPEC-198 issues must not disagree (FR-004).
- **Why the connections cache is not the index**, asserted rather than assumed (FR-005).
- **The index is an authorization input, which SPEC-146's directory deliberately is not** — what that
  costs and what makes it safe (FR-006).
- **The parity assertion**, offline and live, while both sources exist (FR-007).
- **The API-plane grant** the index read needs, and its scope (FR-008).
- **The slot ceiling, restated correctly** (FR-009).
- **Observability** (FR-010), and **what does not change** (FR-011).

### Out of Scope

- **Changing the default.** `claims` stays the default through this spec and every spec in Arc B.
  Flipping it is a transition Phase 1 configuration change. Nothing here ships a behaviour change to
  the current product.
- **Retiring the Cognito membership slots**, `assign_or_find_slot`, `clear_slot` or the attribute
  schema. They stay live and authoritative for the `claims` source, and FR-009 states what that means
  for the ceiling.
- **Per-user Lake Formation and S3 Access Grants entitlements** — SPEC-204, which replaces tags
  altogether at transition Phase 5. This spec keeps the tags and changes only where their values come
  from. **SPEC-204's sweep also reconciles this index** (its FR-005); until then the writers are the
  only path and FR-001 makes them fail loudly rather than best-effort.
- **Any browser change.** No service signature moves and the SPA cannot tell which source is
  configured.

### Where this lands in the build order

**Not before Arc B — after most of it.** It depends on SPEC-195/196/197 for the boundary, the
identity layer and the transport, and on SPEC-198/199 for the route surface FR-004 re-sources. Build
it after SPEC-199 and before SPEC-202.

**The parity window survives that ordering**, and the reason is worth stating rather than inferring:
SPEC-202 retires the Cognito **Identity Pool**, not the **User Pool**. The ID token and its
`custom:shared_space_k` claims persist through the whole arc and up to the environment move, so
FR-007's comparison is available at every point after this spec lands.

### Premises later specs must honour

1. **The registry record is the source of truth; the index is a projection of it.** The index answers
   *which spaces*, cheaply. It is never the authority on whether a space exists or what its status is.
2. **The index is user-unreachable, and that property is its whole safety** (FR-005, FR-006). A later
   spec that moves it, copies it into a user's prefix, or serves it to the browser has removed the
   only thing separating it from the connections cache.
3. **The identity layer and `apicommon/spaces.py` read the same source** (FR-004). Two membership
   answers in one request is a defect whichever one is right.
4. **A space name reaching a key builder has been through `CATALOG_IDENTIFIER_RE`.**

---

## Functional Requirements

### FR-001: The membership index, and the fan-out it rides

#### Description:

One object per user, in the admin bucket, listing the spaces that user belongs to. It is written at
the moments membership changes — and those moments already have a fan-out: `cache.write_roster_to_all`
runs on add, remove and leave, after the registry write, which its own docstring names as the
consistency point.

**It does not inherit that fan-out's best-effort posture.** A stale roster is cosmetic — one member
sees an out-of-date member list. A stale index is an authorization input that is wrong, in the
grant direction on a removal.

#### Acceptance Criteria:

- [ ] The index is `s3://{admin-bucket}/memberships/{username}.json`, holding `{version, username,
      spaces: [{name, status}], updatedAt}`. Admin bucket, so it is unreachable by any user (FR-005).
- [ ] It is written under **ETag compare-and-swap** through `cpcommon`'s existing CAS loop
      (SPEC-156's one implementation, cap 6), on SPEC-123's precedent.
- [ ] Writers are **every** verb that changes membership, and there are **six**, not five:
      `shared-space-create` (the owner, from `reserve`), `add-members`, `remove-members`, `leave`,
      `delete`, and **`shared-space-forget`** — which calls `membership.clear_slot` on *both* its
      paths and is a second space-deletion route. A test enumerates the verb directory and fails on
      a membership-affecting verb with no index write, so a seventh cannot be added silently.
- [ ] The write happens **after** the registry write commits — the same consistency point
      `write_roster_to_all` already uses — and **before** the run reports success.
- [ ] **An index write failure fails the run**, and is notified through SPEC-152's `NotifyFailure`.
      It is not swallowed the way a roster write is. The AC states the divergence and its reason so
      an implementer reusing the fan-out does not inherit its `except: log and continue`.
- [ ] `create`'s write is placed **after `reg.finalize(..., "active")`**, not inside the provisioning
      steps: `reserve` writes `status: "provisioning"` and FR-003 stamps no tag for a non-active
      space, so an index written mid-create entitles nobody and is immediately wrong. A test asserts
      the ordering against the real `create_space` call sequence.
- [ ] **STRENGTHENED DURING BUILD: it is also placed INSIDE the provisioning guard.** After it, a
      failed index write leaves an `active` space whose owner holds no entry — and once membership
      is sourced from the index that owner can neither reach the space nor delete it, because delete
      is gated on membership. Inside, the existing rollback runs and the owner gets a failed card
      they can retry or forget. A separate test discriminates the two placements, since the
      ordering test alone passes under both.
- [ ] **CORRECTED DURING BUILD: SPEC-151's name-lock ordering DOES apply, until SPEC-205 lands.**
      This AC reasons from the target environment, where a delete removes every member and destroys
      nothing, so the record is never released. Today `delete_space` still calls `reg.delete`, which
      frees the name — so the index drops ride the existing member loop, which runs **before** that
      call. An index still naming a space whose name is free is an entitlement to whatever is
      created next. The same correction applies to **`shared-space-forget`'s teardown path**, which
      also calls `reg.delete`: it drops the **whole roster's** entries, not only the actor's, because
      a delete that fails partway writes `failed` on a record that keeps its members and that record
      reaches this branch too. When SPEC-205 lands, the drops are already where they belong.
- [ ] **`active` with zero members is a legitimate, permanent state**, so nothing here infers
      membership from status. FR-003 filters on status *and* the index's own entries; a test asserts
      that a user whose index still named an emptied space would get no tag — because the entry is
      removed, not because the space stopped being `active`.
- [ ] The per-member write count is bounded by the membership cap, so the fan-out's
      per-item-event exemption (`write_roster_to_all`'s docstring) applies unchanged.

### FR-002: The membership source is a declared choice, resolved once

#### Description:

Two implementations, one selected at cold start. Not a per-request choice, not a fallback chain, and
not a silent default when the value is unrecognised — a misconfigured source that degrades to the
other produces a working application with the wrong authorization model.

#### Acceptance Criteria:

- [ ] `MEMBERSHIP_SOURCE` takes exactly `claims` or `index`, is read **once** at module import, and
      resolves to one implementation.
- [ ] **An unset value resolves to `claims`.** Every deployed environment today omits it.
- [ ] **An unrecognised value raises at import**, failing cold start. It does not warn and does not
      fall back. A typo must be a dead container, not a running one on the default — the two sources
      disagree about what a user may reach, and the wrong one is invisible in every response.
- [ ] Both implementations satisfy one interface taking the verified principal and returning the
      user's spaces, so a call site cannot tell them apart — and neither can FR-004's route check or
      FR-007's parity test.
- [ ] The resolved source is recorded once per container (FR-010).

### FR-003: The index source, and what absence means

#### Description:

Read the caller's index, filter to spaces that are `active`, stamp a tag for each. The interesting
cases are all failures.

#### Acceptance Criteria:

- [ ] One `GetObject` per credential mint, cached with the credentials under SPEC-196 FR-006's
      existing key.
- [ ] Only entries whose status is `active` produce a tag — SPEC-073's rule (`is_active_member`
      requires an active space), applied to the projection. A test drives `provisioning`, `failed`
      and `deleting` and asserts no tag for each.
- [ ] **An absent index means the user is a member of no space**, and is not an error. It is the
      correct answer for every user who has never been added to one, and FR-001 guarantees the object
      exists whenever a membership does, because the write that creates a membership fails the run if
      it cannot write the index.
- [ ] **Any other failure — throttle, timeout, 5xx, parse failure, denied read — fails the request.**
      No credential is minted and no partial tag set is used. The tempting alternative is to stamp
      what was resolved and continue: it fails *closed* in the permissions sense, which reads as
      safe, and it is the worst option available — a session missing a tag produces `AccessDenied` on
      a space the user genuinely belongs to, indistinguishable from a real refusal, unactionable, and
      invisible to every gate. SPEC-196's second half exists because a wrong credential *succeeds*;
      this is the same defect with the sign flipped.
- [ ] The failure maps to SPEC-196 FR-007's `IdentityUnavailable` and a SPEC-106 code — **not** to a
      permission denial, which is what a partial mint would tell the user.
- [ ] Nothing is cached on the failure path. A partial tag set must not outlive the fault that caused
      it.
- [ ] A **malformed** index is a failure, not an absence. An unparseable document is not evidence
      that the caller is a member of nothing.
- [ ] Retry is the caller's under SPEC-197's declared policy; this layer retries nothing.
- [ ] A test drives the index `GetObject` raising a throttle and asserts (1) no `AssumeRole` was
      issued, (2) the identity-unavailable response, (3) the credential cache is empty afterwards.

### FR-004: The route-level membership check moves with the source

#### Description:

SPEC-198 FR-001 resolves a route's bucket and root prefix from the verified username and the caller's
**membership claims**, and refuses a shared space with no matching claim as **403 with zero AWS
calls** — asserted by call count. That check lives in `apicommon/spaces.py`.

With `MEMBERSHIP_SOURCE=index` there are no claims. Left alone, `spaces.py` refuses every shared
space; re-sourced carelessly, it disagrees with the tag the identity layer stamped.

#### Acceptance Criteria:

- [ ] `apicommon/spaces.py` resolves membership through **the same FR-002 interface** as the identity
      layer, from the same resolved set, computed **once per request** and shared. Two reads is two
      answers.
- [ ] **SPEC-198's zero-AWS-calls refusal is preserved**, and its call-count assertion is re-run
      under both sources. It is the stronger contract: a refusal before any AWS call is also
      SPEC-113's no-existence-oracle guarantee, and letting the request proceed to an IAM denial
      would weaken both.
- [ ] A test asserts the tag set and the route's resolved space agree — specifically, that a space
      `spaces.py` accepts always has a stamped tag, and one it refuses never does. A disagreement is
      a 403 on a space the session could reach, or worse.
- [ ] This is an **edit to SPEC-198's module**, declared here rather than discovered: FR-011's
      "nothing else changes" does not cover it, and a spec that claimed it did would be wrong.

### FR-005: The index is in the admin bucket because the cache is writable

#### Description:

There is already an object listing a user's spaces, one `GetObject` away, keyed by username:
`{username}/user_settings/shared-connections.json` (SPEC-075's roster fan-out). It is the exact shape
this spec needs and it is the wrong object.

**It is in the user's own prefix and the user can write it.** `portal-role-permissions.json.tftpl`
grants `s3:PutObject` on `${bucket_arn}/${aws:PrincipalTag/username}/*` with no Deny under
`user_settings/`, and `user_settings/` is hidden only client-side (`HIDDEN_BROWSER_FOLDERS`). A user
who edits that file to name a space they do not belong to would be handed a session tag granting it.

#### Acceptance Criteria:

- [ ] The identity layer and `spaces.py` read **only** `memberships/{username}.json` from the admin
      bucket. A test asserts their modules name neither the connections-cache key nor `user_settings`.
- [ ] A test drives the bypass directly: a connections cache naming `finance_space`, an index that
      does not, and an assertion that **no** tag is stamped. It fails loudly against an implementation
      that read the cache.
- [ ] **The reachability caveat is stated rather than left as an overclaim**: after Arc B the browser
      holds no AWS credentials, so the write is reachable only through `PUT /v1/objects/content` and
      whatever `protected.py` permits. The rule stands as defence in depth and as the reason the index
      is not simply the cache — but "the user can write it" describes the pre-Arc-B world, and the
      spec says so.
- [ ] The connections cache keeps its job. This spec adds an index; it does not replace the roster.

### FR-006: The index IS an authorization input, unlike SPEC-146's directory

#### Description:

SPEC-146's username directory is **advisory** — a tripwire test forbids it being an authorization
input, and every existence check stays `admin_get_user`. This index is the opposite: it decides what
a session may reach. That inversion is deliberate and needs its safety stated, not assumed by analogy.

#### Acceptance Criteria:

- [ ] Three properties make it safe, each asserted: it is **user-unreachable** (admin bucket, FR-005),
      it is written **only** by the plane that owns membership (FR-001), and it is written **under
      CAS** at the registry's own consistency point.
- [ ] **The residual is a staleness window, and it is smaller than the one it replaces.** A removal
      whose index write is lost leaves a member holding a tag. The `claims` source has exactly this
      property today and worse: `clear_slot` clears the attribute, but the user's *existing token*
      carries the old claim until it refreshes — SPEC-056's propagation delay, which
      `useSharedSpaceAccessRecovery` exists to paper over. The index is read per mint, so the window
      closes on the next request rather than on the next token refresh. A test asserts the removal
      takes effect on the next mint with no refresh.
- [ ] FR-001's fail-the-run write is what bounds the window; **SPEC-204's sweep closes it** by
      reconciling the index against the registry, and until that ships the window is a stated,
      accepted residual rather than an unnoticed one.
- [ ] A test asserts no module treats this index as advisory — no fallback that proceeds when it is
      missing beyond FR-003's "member of no space", and no path that reads it for display.

### FR-007: The two sources agree — the assertion that expires

#### Description:

The reason this spec ships before the environment moves. While Cognito slots and the index both
exist, the same user's membership is knowable two ways.

#### Acceptance Criteria:

- [ ] An offline test resolves the space set for a fixture user under **both** sources and asserts
      they are equal, compared as sets.
- [ ] **The one legitimate divergence is carved out as its own positive assertion, not excluded.**
      `create_space` calls `membership.assign_or_find_slot(actor, name)` **before**
      `reg.finalize(..., "active")`, so a space still provisioning legitimately holds a Cognito slot
      and legitimately yields no tag from the index. The test asserts exactly that shape — claims
      source: present; index source: absent — rather than treating it as a failure or excusing it
      away. Without this, the mandated non-active fixture makes the mandated equality fail on a
      correct implementation.
- [ ] The fixture includes a user in **more than one** space, one space mid-provision (above), and
      one space the user was removed from. A single-space fixture agrees under almost any
      implementation.
- [ ] **The live check compares the two sources against a real user, and that is what makes it
      worth running.** Against the deployed API in a non-production environment with
      `MEMBERSHIP_SOURCE=index`: read the user's `custom:shared_space_*` attributes with
      `admin_get_user`, read the resolved space set from the `logs/` record for a real request
      (FR-010 puts it there), and compare. A run that only exercises the index source proves the
      index works and proves nothing about agreement — which is the whole claim.
- [ ] The script under `docs/testing/` states that it **cannot be re-run after the environment
      moves**, and that a later reader should treat the result as evidence rather than as a
      repeatable gate.

### FR-008: The index read is an API-plane call, and its grant is narrow

#### Description:

The tags are computed **before** the user's credentials exist, so the read uses the API Lambda's own
execution role — SPEC-196's API plane. That is a privilege held on behalf of every caller.

#### Acceptance Criteria:

- [ ] The grant is `s3:GetObject` on `arn:{admin-bucket}/memberships/*` **plus a `s3:ListBucket` on
      the bucket conditioned to `s3:prefix = memberships/*`**, and nothing else — no other prefix, no
      write. A test reads the rendered policy back and asserts the action and resource set exactly.
- [ ] **CORRECTED DURING BUILD: the `ListBucket` is required, and its CONDITION is the load-bearing
      half.** This AC originally read "no `ListBucket`", and it cannot stand beside FR-003. S3
      answers `NoSuchKey` only to a caller holding `s3:ListBucket`; to a caller without it the same
      missing object is `AccessDenied` — which FR-003 requires to fail the request. So a read-only
      grant would refuse, with an unactionable 5xx on the credential-minting path, **every user who
      belongs to no shared space**, which FR-003 names as the common and correct case. This is the
      defect the register already records against `cpcommon.registry.load`, measured live
      2026-08-17, and its settled remedy is a conditioned grant scoped to the keys read — never an
      unconditioned one, and never reading `AccessDenied` as absence. Conditioned to
      `memberships/*` the grant discloses *which usernames have ever been in a shared space*, a
      proper subset of the directory SPEC-146 already publishes to every authenticated user; it
      discloses no space name and no roster. An **unconditioned** list would, which is why every
      admin-bucket list statement on both roles is asserted to carry a condition.
- [ ] The same pair is granted to the shared-space orchestrator, for the write side: the first
      write for a user begins by reading an index that is not there, and `cas_mutate` runs its read
      **outside** the retry guard, so without the list that read raises on the first attempt and
      FR-001 fails the run. Its condition is pinned by **pattern**, not by presence — `s3:prefix:
      "*"` is a bucket-wide list wearing a condition — and its object statement is pinned to the
      prefix, because widened to the bucket it reaches every other plane's registry record and lock
      under a Sid that still says memberships.
- [ ] **The identity layer's own API-plane call sits outside `ROUTE_PLANES`.** SPEC-196 FR-005's
      registry is keyed by *route* and its default is the user plane, deliberately; declaring
      `Plane.API` per route to cover a call the identity layer makes on every request would invert
      that default for the whole API. The exemption is **by module identity** (SPEC-165's rule), it
      covers only the identity layer, and FR-005's AST sweep still sees the call.
- [ ] **CORRECTED DURING BUILD: the read reuses the API package's OWN one client construction site
      (`apicommon.identity._client`), not `cpcommon.clients`.** `test_credential_planes.py` forbids
      any `cpcommon.clients` import anywhere in the API package and asserts the package holds
      **exactly one** construction site; reaching for `cpcommon.clients` would need
      `apicommon/memberships.py` added to `EXEMPT_MODULES`, which removes that whole module from the
      sweep. It would also bypass `S3_ENDPOINT_CONFIG`, which `_client` pins and the shared cache
      does not. So the door stays one door, and the exemption list does not grow: the index read is
      a **public** function on the identity layer, called from the source module, which therefore
      stays fully swept.
- [ ] A deployed-role IAM simulation on SPEC-186's discipline: every denial paired with an `allowed`
      control, because an `implicitDeny` alone cannot distinguish an ungranted action from a wrong ARN.
      **The list grant needs `s3:prefix` supplied as a context entry** — the register records that a
      prefix-conditioned `ListBucket` simulates as `implicitDeny` when it is not, because IAM answers
      what it decides given *your* context and never what the service supplies. Run without it, this
      AC produces a false negative on the one statement it most needs to confirm.
- [ ] The deploy role is **verified as already sufficient** rather than assumed; no new resource type.

### FR-009: The slot ceiling, restated correctly

#### Description:

An earlier draft claimed this spec lifts the ten-slot ceiling. It does not, and the claim would have
silently reversed `transition_plan.md` §6.4.

#### Acceptance Criteria:

- [ ] The spec states plainly: **the ceiling still binds on how many spaces a user may join**, and it
      binds in two independent places. `membership.assign_or_find_slot` raises
      `ProvisioningError("membership limit reached")` at **add** time regardless of where tags come
      from; and `portal-role-shared-space.json.tftpl` sizes its tag-bearing statements by
      `max_shared_memberships`, so an eleventh tag matches nothing whatever wrote it.
- [ ] The index source stamps at most `MAX_SHARED_MEMBERSHIPS` tags, from the same Tofu variable that
      sizes the templates (SPEC-196 FR-002's rule).
- [ ] **An index holding more spaces than there are slots fails the request** (FR-003's rule), rather
      than truncating. It is unreachable while `assign_or_find_slot` is live and becomes reachable the
      moment the slots retire, which is why it is asserted rather than assumed impossible.
- [ ] **The slot index carries no meaning**, and the AC says why correctly — with one negative claim
      **corrected during build**: `portal-role-shared-space.json.tftpl` is *not* the only file in
      `infra/` referencing `shared_space_k` — two others **produce** the tag name from the same
      range (`auth/cognito.tf` declares the custom-attribute schema, `data/iam.tf` builds the trust
      policy's `sts:TagKeys` list) and several more mention it in prose.
      The conclusion is unaffected and rests on the template alone: its **three** tag-bearing
      statements — `SharedSpaceObjects`, `SharedSpaceList`,
      `SharedSpaceGlue` — each carry one resource entry or condition value per slot **inside a single
      statement**, so the resource lists and the `StringLike` prefix list are unions. *An earlier
      draft said "one identical statement pair per slot", which is not the shape.* The property is
      confirmed by the **deployed-role simulation** of FR-008, not by a test comparing the spec's own
      renderer against itself.
- [ ] This spec does **not** raise `max_shared_memberships`. `transition_plan.md` §8 carries it as a
      transition Phase 0 question.

### FR-010: Observability

#### Acceptance Criteria:

- [ ] One span per credential mint carrying the configured source, the resolved space **names** and
      their count. Space names and usernames are user metadata and are permitted; the token, its
      claims and the index body are not.
- [ ] The resolved space set is a **field**, because FR-007's live check reads it back.
- [ ] A space present in the index but not `active` is recorded at `debug` with its status — the
      difference between "not a member" and "the space is not ready" is otherwise invisible.
- [ ] **A stored `status` is stamped at write time and refreshed by nothing, which is a stated
      residual.** `set_status` changes a registry status with no membership change, so a delete that
      fails partway leaves a not-yet-dropped member's entry reading `active` for a space the registry
      calls `failed`. Premise 1 says the index is never the authority on a space's status, and
      FR-003's filter reads exactly that field — the two are reconciled by SPEC-204's sweep and by
      nothing before it. Accepted, and named rather than left to be found.
- [ ] An index write failure (FR-001) is recorded at `error` with a stable reason token, the member
      and the space.
- [ ] `env` and `version` on every record; messages are literals; `echo=` prohibited. The
      `error.stack` scrub is SPEC-195 FR-007's, inherited.

### FR-011: What does not change

#### Acceptance Criteria:

- [ ] **The default is `claims`** and every deployed environment omits `MEMBERSHIP_SOURCE`. No user
      in the current environment can observe this spec.
- [ ] **Not one TAG-CONSUMING IAM policy, bucket policy or Lake Formation grant is edited.**
      SPEC-196 FR-008's no-change guard stays green — the tag names and values are identical across
      sources, which is the entire reason a source swap is possible. Two **execution-role** policies
      do change (FR-008), and that is the scope this AC always meant: the guarantee is about the
      policies the session tags are evaluated against, not about the roles that compute them.
- [ ] **`useSharedSpaceAccessRecovery` stays.** Under `claims` it papers over SPEC-056's delay, which
      is unchanged. Under `index` it is inert but harmless, and removing it would have to be undone
      if the source were flipped back.
- [ ] **The Cognito slot machinery stays live** — under `claims` it is authoritative.
- [ ] **CORRECTED DURING BUILD, in both directions.** `apicommon/spaces.py` needs no *functional*
      change at all: it already resolves membership from `identity.memberships` on the `UserIdentity`
      the router builds once per request, which **is** the FR-002 interface's output. Only its module
      docstring changes, because "It reads claims and nothing else" goes false. And `router.py` does
      change, one clause: `identity.for_request` runs **before** dispatch, so an
      `IdentityUnavailableError` raised there escapes `route()` entirely and reaches the caller as
      `InternalError` — FR-003's "maps to `IdentityUnavailable`" does not hold without it. No
      `*.service.ts`, hook, component or route handler changes.

---

## Data Model

```
s3://{admin-bucket}/memberships/{username}.json          # new, this spec
  { version: 1, username, spaces: [{name, status}], updatedAt }

s3://{admin-bucket}/shared-spaces/{name}.json            # unchanged, still the source of truth
{username}/user_settings/shared-connections.json         # unchanged, still the roster; never read here
```

## Environment Variables

| Name | Values | Default | Notes |
|---|---|---|---|
| `MEMBERSHIP_SOURCE` | `claims` \| `index` | `claims` | Unrecognised value raises at import (FR-002) |

`ADMIN_BUCKET` and `MAX_SHARED_MEMBERSHIPS` are already delivered to both the API and the
shared-space plane.

## File & Folder Structure

The index writer lives in `lambdas/shared-space-common/` beside `cache.py`, whose fan-out it rides.
The two read implementations live behind one interface in `lambdas/api/`, beside SPEC-196's identity
layer, with `apicommon/spaces.py` calling the same interface.

## Implementation Phases

### Phase 1: The index and its writers

FR-001 across all six verbs, with the enumerate-the-verbs guard and the create-ordering test. The
index exists and nothing reads it — provable in isolation, and shippable alone.

### Phase 2: The interface and the claims source behind it

FR-002, extracting SPEC-196's claim reading with no behaviour change. The existing SPEC-196 tests
must pass untouched; if any needs editing, the extraction changed behaviour.

### Phase 3: The index source and the route check

FR-003, FR-004, FR-005, FR-006 and FR-009, with the bypass test and the `spaces.py` agreement test
written **before** the implementation.

### Phase 4: The grant and the observability

FR-008's grant and simulation, FR-010's span.

### Phase 5: Parity and verification

FR-007's offline test, then the formatter, linter, `ruff`, blocking `mypy`, `pytest lambdas/`, the
portal suite and `npm run build`. Then the FR-007 live check in a non-production environment with
`MEMBERSHIP_SOURCE=index`, and the deployed-role simulation.

### Phase 6: Completion ritual

Per `CLAUDE.md`. The `decisions/` entry is the index itself: why it is an authorization input where
SPEC-146's directory is not, what makes that safe, and — recorded because it will be re-proposed —
why per-request scoping was tried and could not work.
