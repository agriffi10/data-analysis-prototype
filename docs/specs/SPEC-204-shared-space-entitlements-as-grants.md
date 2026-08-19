# Spec: Shared-Space Entitlements as Grants — the Projection that Replaces the Tag

**ID:** SPEC-204
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-203 (the per-user membership index, the interim tag plane this spec eventually retires, and the index staleness residual FR-005's sweep closes), SPEC-196 (the tag set being replaced), SPEC-051/052/053/054/055 (the shared-space control plane, its registry, its verbs and its FIFO queue), SPEC-073 (acknowledge is display-only — access is granted at add time), SPEC-075 (the roster fan-out, and why its best-effort posture does **not** transfer here), SPEC-125 (`shared-space-common`, the domain layer), SPEC-151 (a partial teardown never frees the name — the ordering rule this spec extends), SPEC-152 (every plane notifies on a pre-verb failure), SPEC-157 (FIFO orders delivery, not executions), SPEC-107/156 (`cpcommon`, and the one-implementation rule), SPEC-106 (`toUserMessage`), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

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
space), and something has to issue and revoke them at the same six moments the membership changes.

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
- **The six trigger points, and the one that deliberately is not** (FR-004).
- **Convergence: event-driven projection plus a periodic sweep**, and why neither alone is enough
  (FR-005).
- **Idempotency in both directions**, revocation being the harder one (FR-006).
- **Failure semantics and notification** — a member who is a member with no access (FR-007).
- **The cutover ordering**, including the role-grant revocation (FR-008).
- **The grant budget**, against a shared account-wide instance with a hard ceiling (FR-009).
- **Observability** (FR-010).
- **Delete as a membership removal**, and the inert state it leaves behind (FR-011).

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
- **Modelling shared spaces as directory groups.** Rejected. SCIM-synced Entra groups are good grant
  targets for team-level data, but a shared space has no Entra group behind it (`ARCS.md`). Note the
  reason is **governance, not capability**: `identitystore:CreateGroup` exists, and the Identity
  Store's mutating APIs stay reachable to the management and delegated-administrator accounts — but
  AWS warns in the same breath that using them on a SCIM-provisioned directory makes it **drift from
  the IdP**, and this application will never hold that privilege. Recorded precisely so the rejection
  is not later overturned by someone who finds the API and concludes the spec was mistaken.
- **Any browser change.** Membership is created and displayed exactly as today.

### The delete semantics this spec is written against

**Decided 2026-08-18. It is an input to this spec, and it is owned by SPEC-205**, which changes the
verb and ships independently of the transition. A shared-space **delete removes every member —
including the owner — and destroys nothing**. The objects under `{name}/`, the Glue database and the
registry record all survive; the record keeps `status: "active"` with an empty member list, and takes
no terminal state.

**One qualification, because an earlier draft of this block overstated it.** SPEC-205 FR-002 keys
retention on whether the space ever reached `active`: a space that did is emptied, and a space that
never did — a failed create, which by construction holds no user data — is still **destroyed** by
`shared-space-forget`'s owner path, teardown protocol and all. So `delete_shared_prefix` and
`drop_database` do not disappear; they stop being reachable on the **`delete`** route. This spec's
FR-011 covers the emptying route, and its forget-path criterion covers a verb that may still tear
down.

Four consequences run through the requirements below, and they are why FR-011 is three criteria
rather than a teardown protocol:

- **On the `delete` route nothing is destroyed.** Both halves of the entitlement pair
  therefore have the same lifetime — the Access Grant's prefix and the Lake Formation grant's
  database both outlive the space's membership — so FR-001's "one operation, both halves" holds
  through deletion as well as through creation. Had the database still been dropped, the pair would
  tear down asymmetrically and a revived space would have files and no tables.
- **SPEC-151's name-lock ordering stops applying to `delete`, and still applies to `forget`.** On
  the emptying route the registry record is never released, so the interleaving FR-011 was
  originally written against — an incomplete revocation freeing a name whose prefix still carries
  live grants, letting the next space of that name inherit the previous one's members — **is
  unreachable**. On the destroying route it remains reachable and SPEC-151 still governs it; the
  difference is that a never-`active` space has no members to have inherited anything.
- **`active` with zero members becomes a legitimate, permanent state.** Nothing below may infer
  membership from status. FR-005's desired set is already computed from `is_active_member`, which
  is false for everyone on an empty space, so it converges correctly — but the inference is now
  wrong rather than merely unnecessary, and a test asserts it.
- **The name is permanently taken.** A user can never re-create a space with a name some earlier
  space used, because the record that locks it is never deleted. Product-visible, and stated here
  so it is not discovered.

**The `owner` field is cleared with the members, and that is load-bearing.**
`shared-space-common/auth.py`'s `authorize` gates every owner-only action on
`actor != registry.get("owner")` — it reads the **owner field**, never membership. So an `owner`
retained through a delete leaves the original owner able to call `add-members` on the emptied
space and revive it, with the previous cohort's files intact, in one call and with no confirm. That
contradicts the requirement that nothing in the product can reach a deleted space. Clearing the
field makes `authorize` refuse every owner-only action (`actor != None`) and every member-only
action (empty roster), so the record is inert. Reviving a space becomes an operator act that
rewrites `owner` — which is the intended door.

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
| Which claim identifies an Identity Center user | Transition Phase 0 (§6.1) | **NOT invariant — this row states a requirement, not an assumption.** See below |

**The one gate that is genuinely load-bearing, stated as a requirement on Phase 0.** FR-003 resolves a
portal username to an Identity Center principal through `identitystore:GetUserId`, which matches
`UserName`, `Email` or `ExternalId`. The registry holds the **portal** username — catalog-safe
`^[a-z][a-z0-9_]{2,62}$`, which can never be an email address. So this spec requires that **the portal
username equals exactly one Identity Store attribute value**, most plausibly `UserName` or
`ExternalId`.

`transition_plan.md` §6.1 leaves open whether the portal username is *derived* rather than stored —
"if no existing claim carries it, the username must be derived or mapped rather than stored". **If
Phase 0 decides derived, this spec changes**: it needs a stored username → principal map, which its
Data Model currently refuses on purpose. That is a real dependency and pretending otherwise would put
an Open Question in a table denying it has any. Carry it to Phase 0 as a constraint this spec places
on the decision, not as a question this spec asks.

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
      the space's database and its tables.
- [ ] **The member's Lake Formation permissions are DERIVED from today's EFFECTIVE rights, and
      reusing `config.DATABASE_PERMISSIONS` / `TABLE_PERMISSIONS` directly is a privilege
      escalation.** Those constants — `["DESCRIBE", "CREATE_TABLE", "ALTER", "DROP"]` on the database
      and `["SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP"]` on tables — were sized for the **shared
      portal role**, whose rights are then narrowed by `SharedSpaceGlue`, which grants
      `GetDatabase`, `GetTable(s)`, `GetPartition(s)`, `CreateTable`, `UpdateTable`, `DeleteTable`
      and the two partition batches — and **no `glue:DeleteDatabase`, no `glue:UpdateDatabase`**. So
      today a member *cannot* drop or alter a shared space's Glue database. Grant the role's LF set
      straight to a member's principal with the narrowing IAM statement gone, and `DROP` and `ALTER`
      on the **Database** become live: any member can delete the space's catalog. That is FR-008's
      own finding, one layer down, manufactured by the reuse instruction.
- [ ] The member set is therefore the **intersection** of the LF grant and `SharedSpaceGlue`, computed
      and stated in the spec rather than inherited: **Database — `DESCRIBE`, `CREATE_TABLE`**;
      **Tables — `SELECT`, `INSERT`, `DESCRIBE`, `ALTER`, `DROP`**. A test asserts the database set
      excludes `ALTER` and `DROP`, and names the two absent Glue actions as the reason, so a later
      reader cannot "restore parity with the role" without reading why.
- [ ] **A partial projection is a failure of the whole operation**, reported as one outcome. It is
      not two independent best-effort steps, and it does not report success having done half.
- [ ] Ordering within the pair is **least privileged first: the S3 Access Grant, then the Lake
      Formation grant.** *An earlier draft had this reversed on a "most durable first" reading, and
      the reasoning was wrong:* with the space's data location registered with Lake Formation in
      hybrid mode (`transition_plan.md` §6.2), an LF grant is sufficient for Athena to read the whole
      space through LF credential vending, while the Access Grant is what the **file browser** needs.
      LF-first therefore hands a member the ability to query everything in the space while the UI
      still looks empty — the *more* privileged half, not the less. Since FR-005's sweep repairs
      both directions without the user acting, durability does not distinguish the two orders and
      privilege does.
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

- [ ] Projection runs on **six** verbs, not five: **create** (the owner), **add-members**,
      **remove-members**, **leave**, **delete**, and **`shared-space-forget`**. Forget is easy to
      miss and is two things at once — it calls `membership.clear_slot(actor, space)` on **both** its
      paths (that is today's revocation), and its owner path runs a **full teardown**
      (`delete_shared_prefix`, `revoke_portal_role`, `drop_database`, `cache.remove_entry`,
      `reg.delete`). So it is also a **second space-deletion route**, and FR-011 written against
      `delete` alone would leave a forgotten space's grants live on a freed name.
- [ ] **Revocation lives in `teardown.py`, not at the `delete` verb's call site**, so both deletion
      routes inherit it by construction rather than by two call sites staying in step. A test
      enumerates the verb directory and fails on a membership-affecting verb with no projection, so a
      seventh cannot be added silently.
- [ ] **Create's projection runs after `reg.finalize(..., "active")`, not inside the provisioning
      steps.** `reserve` writes `status: "provisioning"` and FR-005 AC5 computes desired state with
      `is_active_member`, which is false then — so a projection placed where every other create step
      lives entitles nobody. Placed after `finalize` it falls outside the verb's three-part failure
      recording (`clear_slot` rollback, `finalize(..., "failed")`, the cache failure entry), which is
      correct and is stated so it is not "fixed" back inside the guard.
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
- [ ] **The sweep re-reads each registry record immediately before acting on it and abandons that
      space if the ETag moved.** Without it the sweep's authority in both directions is a defect:
      it reads `finance_space`, computes a desired set including `alice`, `remove-members` then
      commits and revokes her, and the sweep — still holding the stale desired set — "grants the
      difference" and **puts her back**. FR-006 AC5's concurrency criterion is about two runs
      projecting the *same pair* and does not cover this. SPEC-157's own answer to this shape is a
      per-key claim under ETag CAS; a re-read plus an ETag comparison is the cheaper form and is
      sufficient because the sweep is idempotent and can simply skip.
- [ ] A test drives exactly that interleaving — sweep reads, verb commits a removal, sweep acts — and
      asserts the member is **not** re-granted and the space is reported as skipped.
- [ ] **The sweep also reconciles SPEC-203's membership index** against the registry, on the same
      pass and under the same re-read rule. That index is an authorization input with a stated
      staleness residual (SPEC-203 FR-006) and this is what closes it.
- [ ] **The cadence is hourly**, and the reasoning is stated rather than the number chosen round:
      Identity Center entitlement changes take **up to an hour** to take effect (`transition_plan.md`
      §3.5), which floors the end-to-end latency no sweep can beat, so a faster sweep spends API
      quota (FR-006) to beat a floor it cannot beat. The event path is what delivers the fast case;
      the sweep is the repair, and an hour bounds how long a lost event can hide.

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
- [ ] **Every criterion above is a claim about the behaviour of the S3 Access Grants and Lake
      Formation APIs, and offline it can only be asserted against a stub this repo wrote.** A
      double-run test against a fake programmed to be idempotent **cannot fail**. So: the offline
      tests are declared **shape assertions** that state what they do not prove, and each of these
      properties is a **live check in Phase 5** — grant twice, revoke twice, revoke what is absent,
      and two concurrent projections of one pair — run against the real APIs in the non-production
      account. `process.md`'s rule is explicit that a spec touching lifecycle, IAM or concurrency
      gets an execution harness rather than a review.
- [ ] **Revocation is a list-then-delete, and the spec says so rather than leaving it to be
      discovered.** `DeleteAccessGrant` takes an `AccessGrantId`, so matching by (principal, scope)
      means a paginated `ListAccessGrants` and then a delete; `lakeformation:ListPermissions` is the
      same shape. A sweep is therefore O(spaces × members) list calls, not O(1).
- [ ] **The API rate limits are budgeted, and the sweep is paced against them.**
      `identitystore:GetUserId`, `lakeformation:GrantPermissions` / `RevokePermissions` /
      `ListPermissions` and `s3control:ListAccessGrants` are all low-TPS. The spec records the
      measured or documented limit for each, and the sweep's pacing is **computed** from the Phase 3
      pair count against the tightest of them — the repo's compute-the-bound rule, and the reason
      the hourly cadence above is a floor rather than an aspiration. A per-container `GetUserId`
      cache buys a scheduled Lambda almost nothing and is not counted as mitigation.

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
- [ ] **The affected member is told nothing**, and this is a disposition rather than a citation.
      SPEC-167's precedent is a failed *recipient of a transfer*, who never knew a transfer was
      coming; here the member appears in a roster the app shows them, in a space they can see and
      cannot open, so the analogy is weaker than it looks. It is still the right call: the member can
      do nothing about a failed grant, the actor can, and the sweep repairs it within the cadence
      (FR-005) — usually before the member notices. **If the sweep's repair window ever exceeds the
      cadence, revisit this**, because at that point silence stops being brief.
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
- [ ] **The hazard's actual trigger is the POLICY REWRITE, not the tags going quiet, and step 3 must
      carry both.** The role-level LF grants become a union only if the portal role also keeps **IAM**
      Glue permissions on those databases — and the only such grant today is `SharedSpaceGlue`, every
      resource of which is `${aws:PrincipalTag/shared_space_k}`. If tags simply stop being stamped
      and that policy is untouched, the ARNs resolve to nothing and the outcome is a **lockout**, not
      a union. The union materialises when the transition rewrites that statement tag-free, which it
      must. So step 3 revokes the role-level LF grants **and** removes or rewrites
      `portal-role-shared-space.json.tftpl`'s tag-scoped Glue statement **in the same change**, and
      the AC names the rewrite as the trigger.
- [ ] A verification step between (1) and (2) confirms a **non-owner member** reaches a space through
      the entitlement alone. Proving it while the tags still work proves nothing — and **the tags
      cannot be made inert for one member**, which an earlier draft asked for: under the interim
      plane the tag and the entitlement both derive from the same registry record (SPEC-203), so
      removing the member removes both. The only shape that works is exercising an
      **identity-enhanced session**, where principal tags do not exist by construction — a different
      session from the one the app runs on at that point, driven with raw credentials rather than
      through the UI. The AC says so, because otherwise an implementer either fakes it or skips it.
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
- [ ] **The threshold is 50% of the instance's 100,000-grant ceiling, and the schedulable unit that
      sizes it is the (member, space) pair.** The reasoning, which is what the compute-the-bound rule
      actually asks the spec to supply: the instance is shared account-wide (§4.4), this application
      cannot see a co-tenant's consumption, and it cannot shed load — so the threshold has to leave
      room for a co-tenant's whole footprint rather than for this application's growth alone. Half is
      the only defensible split absent a contractual budget; **if §4.4's coordination contract ever
      states one, this number is replaced by it and the test reads it back.**
- [ ] The arithmetic is recorded **once the Phase 3 inventory exists**, and until then the spec
      states the formula rather than the figure: `pairs = Σ(members per space)`, consumption =
      `pairs` grants, headroom = `50,000 − pairs`. This is the one deferral in the spec and it is
      deferred to a *measurement*, not to a decision.
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

### FR-011: A delete is a membership removal, and nothing is torn down

#### Description:

Under the delete semantics above, this FR is three criteria rather than the teardown protocol an
earlier draft carried. A delete revokes entitlements the same way a `remove-members` covering the
whole roster would; there is no prefix deletion, no database drop, and no registry record to
release, so there is no ordering to get wrong and no name to free early.

**What is left is the state the delete produces**, which is new: a permanently `active` space with
no members, no owner, live data and a live catalog. That state has to be inert and has to stay
inert.

#### Acceptance Criteria:

- [ ] Deleting a space revokes **every** member's entitlement pair, through the same operation
      `remove-members` uses (FR-001). Both routes are covered — the `delete` verb and
      `shared-space-forget`'s owner path — because FR-004 puts the projection where both reach it. A
      test drives the forget path specifically; it is the one a spec written against `delete` alone
      misses.
- [ ] A failed revocation is FR-007's failure — the run fails and the actor is notified — and
      **`TeardownIncompleteError` does not apply**. It exists to stop a partial teardown freeing a
      name (SPEC-151); nothing here frees a name. A spec that kept the raise would be guarding an
      unreachable state and would fail closed on the wrong condition.
- [ ] **The emptied space is inert, asserted directly.** With `members` empty and `owner` cleared,
      `shared-space-common/auth.py`'s `authorize` refuses every owner-only action and every
      member-only action. A test drives `add-members`, `remove-members`, `leave`, `acknowledge` and
      `delete` against an emptied record **as the original owner** and asserts each raises
      `AuthorizationError`. Driving it as a stranger passes over the defect — the field
      `authorize` reads is `owner`, so the original owner is the only actor who could have survived
      it.
- [ ] **No requirement infers membership from status.** `active` with zero members is legitimate and
      permanent, so FR-005's desired set stays computed from `is_active_member` and a test asserts an
      emptied but `active` space converges to **zero** entitlements rather than being skipped as
      "not deleted".
- [ ] The sweep is the backstop (FR-005): a delete whose revocation failed is repaired on the next
      pass rather than being permanent, and its correction is reported as drift.
- [ ] `teardown.py`'s existing `revoke_portal_role` is **retired with FR-008 step 3**, not before —
      while role-level grants exist, a delete must still revoke them. It is the one teardown helper
      that survives the change, because it revokes a grant rather than destroying data.

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
