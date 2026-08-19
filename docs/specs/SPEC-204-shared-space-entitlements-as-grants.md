# Spec: Shared-Space Entitlements as Grants — the Projection that Replaces the Tag

**ID:** SPEC-204
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-203 (the registry as the membership source, and the interim tag plane this spec eventually retires), SPEC-196 (the tag set being replaced), SPEC-051/052/053/054/055 (the shared-space control plane, its registry, its verbs and its FIFO queue), SPEC-073 (acknowledge is display-only — access is granted at add time), SPEC-075 (the roster fan-out, and why its best-effort posture does **not** transfer here), SPEC-125 (`shared-space-common`, the domain layer), SPEC-151 (a partial teardown never frees the name — the ordering rule this spec extends), SPEC-152 (every plane notifies on a pre-verb failure), SPEC-157 (FIFO orders delivery, not executions), SPEC-107/156 (`cpcommon`, and the one-implementation rule), SPEC-106 (`toUserMessage`), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

**Transition context:** `transition_plan.md` §3.4, §3.9 and Phase 5. This spec is the work those
sections name and no spec owned.

## Overview

A member's access to a shared space is a principal tag. `shared-space-add-members` writes
`custom:shared_space_k` on the member, the Identity Pool stamps it, and the portal role's policy
expands `${aws:PrincipalTag/shared_space_k}` into the S3 prefix, the `ListBucket` condition and the
Glue ARNs. One attribute write grants everything.

The transition removes that mechanism. On an identity-enhanced session there are no principal tags,
and `AWSIAMIdentityCenterAllowListForIdentityContext` denies plain S3 outright — so storage moves to
**S3 Access Grants** and the catalog to **Lake Formation grants against the Identity Center
principal**. A member's access stops being one attribute and becomes **two grants**, per (member,
space), and something has to issue and revoke them at the same five moments the membership changes.

This spec is that something. The registry stays the source of truth and the verbs stay unchanged in
what they *decide*; what changes is that a membership decision now has to be **projected** into two
external systems that can drift from it.

**One thing here is a security cliff rather than a migration step, and it is the reason this spec is
worth reading before Phase 5 is planned.** Today `shared-space-create` grants Lake Formation
`Database` and `Table` permissions to the **shared portal role** — one grant covering every space,
with per-user isolation supplied entirely by the IAM principal tag. Remove the tags and leave those
grants, and every portal user holds catalog access to every shared space. FR-008 is the ordering that
prevents it, and getting the order backwards locks every member out instead.

## Scope

### In Scope

- **The entitlement pair** — an S3 Access Grant on the space prefix and a Lake Formation grant on
  the space database, per (member, space), keyed to the member's Identity Center principal (FR-001).
- **Why shared spaces force the literal per-member grant form** (FR-002), which partly settles a
  transition Phase 0 question.
- **Principal resolution** — portal username to Identity Center principal, and what an unresolvable
  member means (FR-003).
- **The five trigger points, and the one that deliberately is not** (FR-004).
- **Convergence: event-driven projection plus a periodic sweep**, and why neither alone is enough
  (FR-005).
- **Idempotency in both directions**, revocation being the harder one (FR-006).
- **Failure semantics and notification** — a member who is a member with no access (FR-007).
- **The cutover ordering**, including the role-grant revocation (FR-008).
- **The grant budget**, against a shared account-wide instance with a hard ceiling (FR-009).
- **Observability** (FR-010).
- **Teardown** — a deleted space leaves no grants behind (FR-011).

### Out of Scope

- **Personal-prefix Access Grants.** A user's own space is provisioning work under the transition's
  provisioning contract (`transition_plan.md` §2 item 7, §3.9), on a different trigger and a
  different owner. This spec is shared spaces only.
- **Core-dataset grants and data cell filters.** `transition_plan.md` §3.8's reconciler, config-driven
  and out of band. This spec follows its *pattern* and shares none of its code paths — a shared space
  is this app's own construct with no Entra group behind it, so its grants are per-user and
  registry-driven (`ARCS.md` → *Shared-space membership*).
- **Creating the S3 Access Grants instance, associating it with Identity Center, registering
  locations, or the `sts:SetContext` trust statement on the location role.** Account-wide singletons,
  built once in transition Phase 5 and named in the coordination contract (§4.4). This spec consumes
  them.
- **Retiring the principal tags, the interim plane, or SPEC-203's `registry` source.** That is the
  last step of transition Phase 5 and it happens *after* this spec's grants are live and verified —
  FR-008.
- **Modelling shared spaces as directory groups.** Rejected: SCIM-synced Entra groups are good grant
  targets for team-level data, but a shared space has no Entra group behind it and this application
  cannot author one (`ARCS.md`).
- **Any browser change.** Membership is created and displayed exactly as today.

### Preconditions this spec takes as inputs, not open questions

`CLAUDE.md` forbids a spec carrying Open Questions. The transition has gates outstanding; this spec
is written so that **none of them changes its design**, and the ones that would are consumed as
inputs:

| Input | Source | Why this spec is invariant to it |
|---|---|---|
| The Access Grants instance exists and accepts TIP identities | Transition Phase 5 | This spec creates grants on it; it does not create it |
| The personal-prefix grant form (literal vs location-role policy) | Transition Phase 0 (§3.9) | FR-002: shared spaces force the literal form **regardless** of what personal prefixes do. The two buckets may differ |
| Gate G7 — whether `StartQueryExecution` works on our own identity-enhanced session | Transition Phase 0 | The **Lake Formation grant is correct either way**; G7 decides the query *surface*, not who is entitled. If G7 fails, the grant this spec issues is what a studio product would honour |
| Gate G9 — presigning from `GetDataAccess` credentials | Transition Phase 0 | This spec issues grants; how bytes are fetched under them is SPEC-198's |
| Which claim identifies an Identity Center user | Transition Phase 0 (§6.1) | FR-003 takes it as configuration |

**What this spec cannot be built without** is the instance and the Identity Center integration. It is
therefore Draft until transition Phase 5 begins, and it is written now because `transition_plan.md`
Phase 3's inventory sizes it and Phase 5 cannot start without it.

---

## Functional Requirements

### FR-001: The entitlement is a PAIR, and it is one operation

#### Description:

A member needs both halves. The S3 Access Grant lets them read and write the space's objects; the
Lake Formation grant lets them see its database and tables. A member holding one and not the other is
a support ticket that looks like a product bug: files but no tables, or tables that return
`AccessDenied` on their own data.

#### Acceptance Criteria:

- [ ] One operation projects both halves for one (member, space) pair: an S3 Access Grant scoped to
      the space's prefix in the shared-space bucket at `READWRITE`, and Lake Formation permissions on
      the space's database and its tables — the same permission sets `shared-space-create` uses
      today (`config.DATABASE_PERMISSIONS`, `config.TABLE_PERMISSIONS`), reused rather than restated.
- [ ] **A partial projection is a failure of the whole operation**, reported as one outcome. It is
      not two independent best-effort steps, and it does not report success having done half.
- [ ] Ordering within the pair is **most durable first**: the Lake Formation grant, then the Access
      Grant. A member with catalog access and no storage access sees an empty space; a member with
      storage and no catalog sees files and no tables. Neither is good, and the first is the one the
      sweep repairs without the user acting.
- [ ] The pair is expressed once, in `shared-space-common`, and every trigger calls it. A test
      asserts no verb issues a `grant_permissions` or a `CreateAccessGrant` of its own — SPEC-156's
      one-implementation rule, and the reason it matters here is that revocation must mirror grant
      exactly.
- [ ] The space prefix is derived from the space name by the **existing** path builder, not
      reconstructed. A grant scoped one segment wrong is a grant on somebody else's data.

### FR-002: Shared spaces force the literal per-member grant, whatever personal prefixes do

#### Description:

`transition_plan.md` §3.9 leaves open whether a user's storage entitlement is *one literal grant per
user* or *one broad grant narrowed by `${identitystore:UserId}` in the location role's permission
policy*. For personal prefixes both work, because the prefix is a function of the identity.

**For shared spaces only the literal form works, and the reason is structural.** A location-role
policy variable can narrow by properties of the *caller*; membership of a shared space is not a
property of the caller — it is a relation held in our registry, which no IAM policy variable can
consult. There is no `${...}` that expands to "the spaces alice belongs to".

This is worth stating as a finding rather than a constraint: it means the two buckets may use
**different forms**, and the personal-prefix decision does not have to wait for this one.

#### Acceptance Criteria:

- [ ] Entitlements on the shared-space bucket are **literal per-(member, space) grants**. The spec
      states the reasoning above so a later reader does not "unify" the two buckets onto a policy
      variable and silently grant every member every space.
- [ ] A test asserts each grant's scope names exactly one space prefix — no wildcard covering the
      bucket, no shared grant covering multiple spaces.
- [ ] The rejection of the policy-variable form **for this bucket** is recorded in `decisions.md`,
      with the note that it says nothing about the personal bucket.

### FR-003: The Identity Center principal, and what an unresolvable member means

#### Description:

The registry holds portal usernames. Grants take Identity Center principals. Something has to join
them, and the join is the one place this design touches a directory it does not own.

#### Acceptance Criteria:

- [ ] The portal username resolves to an Identity Center principal through `identitystore:GetUserId`
      on the configured attribute — the same claim the token exchange maps (transition §6.1), read
      from configuration, not hard-coded.
- [ ] The resolution is **cached** per container with a bounded TTL. It is stable for the life of a
      user and is on the path of every membership change.
- [ ] **An unresolvable member is a refusal, not a skip.** The operation fails and the member is
      told. Skipping produces a member the registry lists with no entitlement and no error anywhere —
      exactly the state FR-007 exists to make impossible.
- [ ] A member who exists in the registry but not in Identity Center is distinguishable in `logs/`
      from a resolution *fault*, with its own reason token. The first means provisioning has not run
      for them (transition §2 item 7's latency window); the second means the directory is unhealthy.
      They need different responses and they look identical in a generic error.
- [ ] The resolved principal id is user metadata and may be logged. The claim value it was resolved
      from is **not** — email addresses are always out under the field rule.

### FR-004: Five triggers, and the one that is deliberately not a trigger

#### Description:

The moments a membership changes are already known and already implemented. This spec adds a
projection at each; it does not add a decision at any.

#### Acceptance Criteria:

- [ ] Projection runs on: **create** (the owner, who is in `members` from `reserve`), **add-members**,
      **remove-members**, **leave**, and **delete** (revoking everything — FR-011).
- [ ] **`acknowledge-membership` is NOT a trigger.** SPEC-073 settled that acknowledgement is
      display-only and access is granted at add time; making it a trigger would deny an added member
      until they signed in, reversing that decision. A test asserts the acknowledge verb issues no
      grant call.
- [ ] Projection runs **after** the registry write commits, never before. The registry is the source
      of truth and a grant issued against an uncommitted membership is a grant with no record.
- [ ] It runs as a verb on the existing shared-space state machine, under the existing execution
      role, reusing the plane's FIFO queue, its DLQ and SPEC-126's drain. No new plane.
- [ ] The verb is **not** in the roster fan-out's position and does not inherit its posture. SPEC-075
      and SPEC-186 FR-008 make roster writes best-effort because a stale roster is cosmetic; a
      missing entitlement is total loss of access. FR-007 states what happens instead.

### FR-005: Convergence — the event projects, the sweep repairs

#### Description:

Event-driven projection alone drifts: a failed run, a dead-lettered message or a manual registry edit
leaves the grant systems disagreeing with the registry, permanently, with nothing looking wrong. A
sweep alone is too slow: a member added at 09:00 should not wait for a nightly reconcile.

`transition_plan.md` §3.8's reconciler is the pattern — desired state from config, read current,
converge — and the registry is this one's config.

#### Acceptance Criteria:

- [ ] A **sweep** reconciles every space on a schedule: for each registry record, compute the desired
      set of (member, space) entitlements, read the current set, grant the difference and revoke the
      surplus. Idempotent and safe to re-run, on the username-directory builder's precedent.
- [ ] **The sweep revokes.** A revocation lost by a failed event is a member who still has access to a
      space they left — the security-relevant direction, and the one a grant-only sweep never fixes.
- [ ] The sweep reports **drift it corrected** at `warn` with counts, per space. Silent correction
      hides a broken event path indefinitely; this is the only signal that it is broken.
- [ ] A space whose `status` is not `active` has **no** desired entitlements. The sweep converges it
      to empty, which is what makes FR-011's teardown recoverable if it failed midway.
- [ ] Desired state is computed with `registry.is_active_member` (SPEC-203 FR-004's rule), not by
      reading `members` directly — the two differ on a non-active space, and the direct read grants
      access to a space that is provisioning or failed.
- [ ] The sweep's cadence is a stated decision with its reasoning, and it is bounded by the entitlement
      change latency the product promises rather than chosen round.

### FR-006: Idempotency in both directions

#### Description:

Every run must tolerate the state it is trying to produce already existing. The grant direction is
easy and already true of Lake Formation; the revoke direction is where the traps are.

#### Acceptance Criteria:

- [ ] Granting an entitlement that already exists **succeeds**. Lake Formation re-granting is already
      idempotent (`create_space.py` documents it); the Access Grants half must be asserted, and a
      duplicate grant must not be created — a grant per run would exhaust FR-009's budget.
- [ ] Revoking an entitlement that does not exist **succeeds**. A `not found` on either half is a
      no-op, not a fault. This is the single most common state during a sweep and after a partial
      failure.
- [ ] Revocation is matched by **(principal, scope)**, not by an id this system stored. A stored id is
      a second source of truth that drifts from the grant systems and strands grants nothing can find.
- [ ] A test drives every operation **twice in sequence** and asserts the second is a no-op that
      succeeds — for grant, for revoke, and for the sweep as a whole.
- [ ] Concurrency: two runs projecting the same pair must not produce two grants or a spurious
      failure. SPEC-157's rule applies — FIFO orders delivery, not executions — so this is asserted
      against genuinely concurrent runs, not inferred from the queue.

### FR-007: A member with no access must never be silent

#### Description:

The registry commits first (FR-004), so a projection failure leaves a durable state: the app says
alice is a member of `finance`, the roster shows her, and she cannot open it. Every surface agrees
she has access except the two systems that grant it.

#### Acceptance Criteria:

- [ ] A projection failure **fails the run** and notifies through the plane's existing failure path
      (SPEC-152's `NotifyFailure`, decoded by `cpcommon.errors.failure_reason` — the only decoder).
- [ ] The **actor** is told the membership change did not fully apply, in SPEC-106 wording, naming the
      member and the space. Raw AWS or Lake Formation text is never rendered.
- [ ] **The affected member is told nothing**, on the send-files precedent (SPEC-167): a member who
      never gained access has nothing to act on, and a message about a space they cannot open is
      worse than silence.
- [ ] The registry is **not** rolled back. It is the source of truth and it is correct — the grant
      systems are behind, which is what FR-005's sweep exists to fix. A rollback would make the
      registry wrong to make two projections right.
- [ ] `logs/service=shared-spaces/` carries one record per failed pair with the member, the space, the
      half that failed and a stable reason token.

### FR-008: The cutover order, and the role grant that must not be left behind

#### Description:

The most consequential requirement here, and the one with a wrong answer in both directions.

Today `shared-space-create` grants Lake Formation `Database` and `Table` permissions to
`config.PORTAL_ROLE_ARN` — the **shared** portal role — for every space. Per-user isolation is
supplied entirely by `${aws:PrincipalTag/shared_space_k}` in the IAM policy. Those role-level grants
are invisible in the transition's plan and are the thing most likely to be left in place.

On the identity-enhanced plane Lake Formation authorizes the **propagated identity**, so a role-level
grant is not what governs a TIP query. That is not a reason to leave it: it stays live for any
non-TIP assumption of that role, and once the tags are gone there is nothing narrowing it. Left
behind, it is a standing union grant on every shared space.

#### Acceptance Criteria:

- [ ] The order is stated as a decision: **(1)** issue per-member entitlements for every space and
      verify them; **(2)** retire the principal tags and the interim plane; **(3)** revoke the
      role-level Lake Formation grants. Each step is separately verifiable and step 1 is additive.
- [ ] **Reversing (1) and (3) locks every member out** of every shared space at once; **skipping (3)**
      leaves every user entitled to every space. The spec says both consequences explicitly, because
      the ordering looks like housekeeping and is not.
- [ ] Step 3 removes the role-level grants **and** stops `shared-space-create` issuing them for new
      spaces. A test asserts the create path no longer names `PORTAL_ROLE_ARN` in a
      `grant_permissions` call — otherwise every space created after the cutover reintroduces the
      union grant one space at a time.
- [ ] A verification step between (1) and (2) confirms a **non-owner member** reaches a space through
      the entitlement alone, with the tags already inert for them. Proving it while the tags still
      work proves nothing.
- [ ] Step (2) is out of this spec's scope and is named as the transition's, so the sequence is not
      read as three merges here.

### FR-009: The grant budget

#### Description:

FR-002's literal grants consume a pool on an account-wide singleton shared with every other tenant:
**100,000 grants** and **1,000 locations** per Access Grants instance, one instance per account and
Region (`transition_plan.md` §3.9, §4.4). Consumption is members × spaces, which grows faster than
either.

#### Acceptance Criteria:

- [ ] The sweep reports **total grants held by this application** on every run, as a counted figure,
      so consumption is a trend and not a surprise at the ceiling.
- [ ] A stated threshold raises a `warn` well below the ceiling, computed against the instance limit
      rather than written round — the repo's compute-the-bound rule.
- [ ] The spec records the arithmetic: at the Phase 3 inventory's (member, space) pair count, what
      fraction of the instance this application consumes, and what a co-tenant granting per object
      prefix would do to the remainder.
- [ ] Hitting the ceiling is a **refusal with a named reason**, not an opaque AWS error surfaced
      through `toUserMessage`'s generic path.

### FR-010: Observability

#### Acceptance Criteria:

- [ ] One span per projection operation and one per sweep, through `cpcommon.observability` — the
      only door — carrying the space, the member, the operation and the outcome.
- [ ] Space names, usernames and Identity Center principal ids are user metadata and are permitted.
      The claim value a principal was resolved from, and any token, are **not**.
- [ ] `env` and `version` on every record (SPEC-186 FR-005). Messages are literals; `echo=` is
      prohibited.
- [ ] The sweep's corrected-drift counts (FR-005) and the budget figure (FR-009) are fields, not
      interpolations into a message.

### FR-011: Teardown leaves nothing behind

#### Description:

SPEC-151's rule — a partial teardown never frees the space name — now has a third thing to clean up
alongside the objects and the catalog.

#### Acceptance Criteria:

- [ ] Deleting a space revokes **every** member's entitlement pair before the registry record is
      released, on SPEC-151's ordering: the record is the name lock and it survives an incomplete
      teardown.
- [ ] An incomplete revocation raises `TeardownIncompleteError` and **leaves the registry record
      intact**, exactly as the object and catalog teardowns do. A freed name with live grants on its
      prefix means the next space of that name inherits the previous one's members.
- [ ] Counts, never keys, in the raise — SPEC-151's rule.
- [ ] The teardown is covered by FR-005's sweep as a backstop: a non-active space converges to no
      entitlements, so a teardown that failed midway is repaired rather than permanent.
- [ ] `teardown.py`'s existing `revoke_portal_role` is **retired with FR-008 step 3**, not before —
      while role-level grants exist, a delete must still revoke them.

---

## Data Model

No new persisted state, and that is deliberate: the registry is the desired state and the two grant
systems hold the current state. A third store would be a source of truth that can drift from both.

Desired entitlement, derived and never stored:

```
(member, space) where registry.is_active_member(load(space), member)
  → Lake Formation : principal = <IdC principal for member>
                     resources = Database{space} + Table{space, wildcard}
                     permissions = DATABASE_PERMISSIONS / TABLE_PERMISSIONS  (reused)
  → S3 Access Grant: grantee   = <IdC principal for member>
                     scope     = <shared-space bucket>/<space prefix>/*
                     permission = READWRITE
```

## Environment Variables

| Name | Purpose |
|---|---|
| `ACCESS_GRANTS_INSTANCE_ARN` | The account's Access Grants instance (§4.4's singleton) |
| `IDENTITY_STORE_ID` | For `identitystore:GetUserId` |
| `IDC_USER_ATTRIBUTE` | Which attribute the portal username resolves against (FR-003) |

## File & Folder Structure

The projection lives in `lambdas/shared-space-common/` beside `registry.py`, `membership.py` and
`teardown.py` — it is domain logic for this plane and has no second consumer, so it does not belong
in `cpcommon` (SPEC-156's rule: `cpcommon` owns the algorithm, a domain layer owns its wording). The
verb and the sweep are new Lambdas on the existing plane.

## Implementation Phases

### Phase 1: The pair, and principal resolution

FR-001, FR-002, FR-003 and FR-006 in the domain layer, with the double-run idempotency tests written
first. No trigger wired — the operation is provable in isolation.

### Phase 2: The triggers

FR-004 and FR-007: the verb on the state machine, the five call sites, the acknowledge negative
assertion, and the failure path through SPEC-152's `NotifyFailure`.

### Phase 3: The sweep

FR-005, FR-009, FR-011's backstop, and the drift and budget reporting of FR-010.

### Phase 4: IAM and infrastructure

The execution role's grants — Access Grants create/delete/list, `lakeformation:GrantPermissions` /
`RevokePermissions` / `ListPermissions`, `identitystore:GetUserId` — plus the deploy-role expansion,
as in-scope work per `CLAUDE.md`'s infra rule. New resource types are involved, so
`architecture.md` → *Deploy-role IAM — adding a new resource type* is read first. Deployed-role
simulation on SPEC-186's discipline: every denial paired with an `allowed` control.

### Phase 5: Verification, and the cutover rehearsal

The suites and the gates. Then, in a non-production environment: a member added and reaching the
space through the entitlement alone with the tags inert (FR-008's between-step check), a member
removed and refused, a sweep correcting deliberate drift in both directions, and a space deleted
leaving no grants. The FR-008 ordering is **rehearsed here and executed in transition Phase 5** — it
is not a merge in this spec.

### Phase 6: Completion ritual

Per `CLAUDE.md`. Two `decisions.md` entries: FR-002's literal-grant finding (and what it does not say
about the personal bucket), and FR-008's ordering with both failure directions named.
