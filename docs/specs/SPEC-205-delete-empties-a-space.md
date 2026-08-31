# Spec: A Delete Empties a Space and Destroys Nothing

**ID:** SPEC-205
**Status:** Draft
**Last Updated:** 2026-08-31
**Depends On:** SPEC-051/052/053/054/055 (the shared-space control plane, its registry, its verbs, and the criterion that the registry record is the name lock), SPEC-073 (acknowledge is display-only), SPEC-075 (the roster fan-out), SPEC-125 (`shared-space-common`), SPEC-151 (a partial teardown never frees the name — retained in full on the one route that still destroys), SPEC-157 (FIFO orders delivery, not executions — FR-008), SPEC-113 (no existence oracle), SPEC-106 (`toUserMessage`), SPEC-074 (Help content), SPEC-155 (`ConfirmDialog`, and its `irreversible` line), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

**Downstream:** **SPEC-204** is written against these semantics and cannot be built until this ships.
**SPEC-203**'s index writer is simpler because of them.

## Overview

Deleting a shared workspace destroys it. `shared-space-delete` deletes every object under the
space's prefix, drops its Glue database, revokes its Lake Formation grants, clears every member's
slot and deletes the registry record — after which the name is free and the data is gone.

This spec makes a delete **remove people instead of things**. Every member's access ends, including
the owner's, and the space disappears from every list — but the objects, the Glue database and the
registry record all survive, and the record stays `active` with an empty roster.

Two motivations, and the second is why it is worth doing on its own account:

- **Deleting a workspace is irreversible and unconfirmable.** A user who empties a shared space by
  mistake has no recourse: the objects are gone from a bucket with versioning off. Retention makes
  the mistake recoverable by an administrator.
- **It deletes a whole class of failure from the control plane.** SPEC-151 exists because a partial
  teardown could free a name while resources survived under it. On a route that releases no record,
  the hazard is unreachable rather than mitigated.

**The cost is stated up front because it is user-visible and permanent.** A name a space once used
can never be claimed again, and data a user asked to delete is retained.

### The correction this spec is built around, because the obvious design is wrong

The first draft keyed retention on `status`: a space that is `active` is emptied, one that is not is
destroyed by `shared-space-forget`'s owner path. **That is unsafe, and the code already said so.**

`forget_space`'s owner path fires on `status != "active"` — **any** non-active status, which
`transition_plan.md` §6.3 has documented for months. A delete that fails midway writes
`status: "failed"` and leaves the space's data completely intact. The Connections page renders
**Dismiss** and **Retry** on any failed row. Dismiss calls `forget`, which — seeing a non-active
space owned by the actor — would run the full teardown on a live workspace. Retry calls **`create`**,
which through `_resolve_reserve_collision`'s failed-retry overwrite re-provisions the record with
`members: [actor]`, silently reviving the space with the roster reset to the owner alone and every
previous member's files intact underneath.

So live `status` cannot be the seam. **The seam is a durable, monotonic fact on the record**
(FR-001), and two UI affordances have to stop meaning what they mean today (FR-007).

**And the justification for destroying a never-`active` space is weaker than "by construction".**
`create_space` calls `membership.assign_or_find_slot` **before** `finalize(..., "active")`, and the
Cognito slot *is* the access grant — `portal-role-shared-space.json.tftpl` scopes `s3:PutObject` by
`${aws:PrincipalTag/shared_space_k}` and registry status gates nothing in IAM. So a creator can
write into a space that never reaches `active`. FR-002 states the honest version instead.

## Scope

### In Scope

- **`everActive` — the durable fact retention keys on**, its writers, and the backfill existing
  records need (FR-001).
- **The retention rule**, and the honest justification for the destroying route (FR-002).
- **The delete verb becomes a membership removal** (FR-003).
- **Clearing the `owner` field, and the inert record it leaves** (FR-004).
- **The permanent name lock**, and closing the revive-through-create door (FR-005).
- **`active` with zero members as a legitimate state**, with the reader audit done here (FR-006).
- **The failed-delete affordances** — Dismiss and Retry must stop destroying and reviving (FR-007).
- **Concurrency**: a membership write racing the empty (FR-008).
- **Failure semantics for a partial empty** (FR-009).
- **What the user is told** — the copy that is false after this change (FR-010).
- **What accumulates**, including the quota that actually binds (FR-011).
- **Observability** (FR-012), and **what does not change** (FR-013).

### Out of Scope

- **Any surface for retained spaces.** No admin UI, no restore button, no listing. Recovery is an
  operator acting on the registry and the bucket; an admin UI is a standing Out-of-Scope item.
- **Lifecycle or expiry on retained data** (FR-011 states the accumulation and declines to manage it).
- **A true-erasure path** for a compliance request. There is none today either.
- **Moving `assign_or_find_slot` after `finalize` in `create_space`.** It would make FR-002's
  justification stronger, and it is refused: the assignment is where a membership-cap refusal
  happens, so moving it past `finalize` would let a space become `active` whose owner cannot be
  given access — a worse failure than the one it fixes.
- **Fixing the stuck `deleting` record generally.** The state machine's `RecordFailure` is a `Pass`
  that writes no registry status, so a Lambda timeout leaves `status: "deleting"` permanently. This
  spec makes that state **safe** — FR-001's backfill stamps `deleting` records, which is unambiguous
  because only `delete_space` writes that status, and FR-002's guard then refuses to tear them down —
  and **exitable**, because FR-002 stops `forget` clearing the row and FR-007 renders Retry on it. It
  does not otherwise change the state machine.
- **Entitlements, Access Grants, Identity Center.** SPEC-204, which this unblocks.

### What runs today, and what each step becomes

`shared-space-delete`'s verb body:

| Today | After |
|---|---|
| — | **New first steps**: load the record fresh, evaluate FR-002's predicate, and — **on the emptying route only** — stamp `everActive: true` |
| `reg.set_status(registry, "deleting")` | **Unchanged** |
| `teardown.delete_shared_prefix(space)` | **Not called on the emptying route.** Called on the never-active route, which is today's behaviour unchanged |
| `teardown.revoke_portal_role(space)` | **Not called on the emptying route** (FR-003) |
| `teardown.drop_database(space)` | **Not called on the emptying route** |
| per member: `clear_slot`, `cache.remove_entry` | **Unchanged** — `members` already includes the owner |
| `reg.delete(space)` | **Replaced**: rewrite with `members: []`, `owner` removed, `status: "active"` |
| notify every member | **Unchanged wording** (FR-010) |

`shared-space-forget`'s owner path keeps its full teardown **and gains a guard** (FR-002).

### Premises later specs must honour

1. **`status` describes the space's resources; `everActive` describes whether it was ever usable.**
   Retention keys on the second. Any spec reading live `status` to decide whether data may be
   destroyed is repeating this spec's first draft.
2. **The registry record is the name lock and this route never releases it** (SPEC-054's criterion,
   permanent in effect).
3. **Authorization reads the `owner` field, never membership** (`shared-space-common/auth.py`). A
   spec changing what a delete leaves there is changing an authorization boundary.

---

## Functional Requirements

### FR-001: `everActive` — the durable fact, and the backfill

#### Description:

A monotonic field, written once, never cleared. It answers "was this space ever usable by anyone",
which live `status` cannot: `status` moves `active → deleting → failed` on a failed delete, and every
one of those transitions describes a space whose data is intact.

#### Acceptance Criteria:

- [ ] **`finalize` stamps `everActive: true` ONLY when the outcome status is `active`.** `finalize`
      is called on **both** create outcomes — `finalize(..., "active")` and
      `finalize(..., "failed", reason)` — so an unconditional stamp marks every failed create as
      ever-active, which makes FR-005's guard refuse every legitimate retry and makes `forget` refuse
      to tear down any failed create. A test drives the **failed** path and asserts the field is
      absent; a round-trip test alone passes either way.
- [ ] **`finalize` also carries an existing `everActive` forward, on both status paths.** It
      **rebuilds** the record from a literal rather than copying it — it carries forward only
      `createdAt` today — so it is the one writer that provably drops fields. Asserted separately
      from the stamp, because the two are different bugs.
- [ ] **`delete_space` reads first, decides the route, and stamps only on the emptying route.** The
      order is load-fresh → evaluate → stamp → `set_status("deleting")`. *An earlier draft stamped as
      the verb's first action, which was two defects at once: it made FR-002's predicate vacuous —
      the fresh read would always see `everActive`, so no fixture could take the other branch — and
      it burned never-active spaces, because `delete` has no status guard (FR-002) and the portal
      role can enqueue it directly, so an owner deleting their own failed create would have stamped
      it ever-active and permanently blocked both `forget`'s teardown and `_resolve_reserve_collision`'s
      overwrite. The name would be unreclaimable and the Glue database orphaned.*
- [ ] Stamping is idempotent and skipped when the field is already present.
- [ ] The field is **never cleared or set false** by any verb. A sweep asserts no module writes
      `everActive` to anything but `True`.
- [ ] `save_members` and `set_status` preserve it — both already do `dict(existing)`, asserted
      because the protection depends on it and a later projection-style rewrite would drop it
      silently.
- [ ] **A one-time backfill stamps `everActive: true` on every record whose status is `active` OR
      `deleting`.** *An earlier draft skipped every non-active record on the grounds that they are
      "indistinguishable from failed creates". That is false for the highest-risk status:*
      **`deleting` is written by `delete_space` and by nothing else** — `create_space` writes only
      `provisioning`, `active` and `failed` — so a `deleting` record is unambiguously a space that
      reached `active` and whose delete did not finish. And because the state machine's
      `RecordFailure` is a `Pass` that writes no registry status, a timed-out delete leaves that
      status permanently. Skipping them leaves round one's exact data-loss path open on every such
      record that exists on the day this ships.
- [ ] **Pre-existing `failed` records are enumerated and dispositioned manually before deploy**, not
      skipped silently. A failed *delete* was ever-active and must be stamped; a failed *create* must
      not be, or its name is burned. The set is small, but **the discriminator is the space's
      resources, not its roster**: a failed *create* has no Glue database and no objects under
      `{space}/`, a failed *delete* has whichever the cascade did not reach, and `reason` names a
      `finalize` fault or a teardown one. *The roster cannot decide it. The old rule — "a failed
      create is single-member, since creating is creator-only" — is the claim FR-002 withdraws, and
      it fails in both directions: a failed create can have been added to before FR-002's gate, and a
      failed delete of a single-member space is single-member too, since `set_status` preserves
      `members`.* The spec requires the enumeration to be run and its disposition recorded, rather
      than guessing a rule that is wrong in one direction or the other.
- [ ] **The backfill runs as a one-shot Lambda under the plane's orchestrator role**, which is the
      only principal that can read and write the registry — the deploy user cannot read the data
      buckets, so a local script cannot do it. The same access is what FR-001's manual `failed`-record
      enumeration needs.
- [ ] **It rides `locals.tf`'s `shared_space_functions` map**, which feeds both the function set and
      the orchestrator's `InvokeFunction` list, so it inherits the role, the env, the log group and
      the deploy-role and layer wildcards. **No IAM change is needed** — `AdminRegistryList`'s
      existing `s3:prefix` of `shared-spaces/*` already covers the enumeration. Stated because a
      builder who does not check will assume a new grant.
- [ ] **`test_instrumentation_coverage.py` carries the shared-space verb count as a literal** and the
      backfill matches its glob without being a verb, so it fails a test in a plane this spec never
      otherwise touches. Bump it, and note the failure text names the new module so the cause is
      visible.
- [ ] **`FakeS3.list_objects_v2` accepts only `Bucket`, `Prefix` and `ContinuationToken`.** A backfill
      passing `MaxKeys` `TypeError`s against the fake and works in production.
- [ ] **The deploy order is stated, because there is no enable switch**: run the backfill, *then*
      deploy the verb change. The Lambda's new behaviour is live the moment it deploys, so the
      reverse order leaves a window in which a delete can fail on an unstamped record.
- [ ] The backfill is idempotent and re-runnable, and reports the object count and how many records
      it stamped, split by the status it found.
- [ ] `SCHEMA_VERSION` does **not** bump. The fields are additive and every reader uses `.get`;
      stated so it is not raised as an omission.

### FR-002: The retention rule, and the honest justification

#### Description:

Two routes. The rule is one predicate on the record, and the destroying route gains a guard it does
not have today.

#### Acceptance Criteria:

- [ ] The predicate is `record.get("everActive") is True` → **emptied, never destroyed**.
- [ ] **`forget_space` gets FOUR branches in this order, and the order is the requirement.** *An
      earlier draft gave two guards that were not the same guard and could not both be live: an
      owner-scoped conjunction and a standalone ever-active no-op. The conjunction alone leaves a
      **member** dismissing a failed-delete row falling through to cache-only, clearing their own
      chip and slot — and a standalone no-op covering everyone makes the conjunction dead code.*
      1. `status == "active"` and the actor is a member → `AuthorizationError`, **unchanged**.
      2. `owner == actor` and `status != "active"` and **not** `everActive` → **full teardown**, today's
         behaviour with the new guard.
      3. `owner == actor` and `everActive` → **no-op that clears nothing** (below). This is the branch
         that keeps the owner's row, and with it FR-007's Retry.
      4. Anything else → **cache-only, unchanged**. A *member* clearing their own chip on a stuck
         space is choosing to leave, which is what this branch has always meant and what `leave`
         does deliberately; only the owner's row is load-bearing. **A test drives forget as the owner against a record that was
      `active` and is now `failed`, and asserts no teardown helper is called** — that is the exact
      data-loss path the first draft left open, and a test using a never-active fixture passes over
      it.
- [ ] **A fresh read returning `None` refuses.** The record is the only evidence of what the space
      was, and destroying a prefix and a database on its absence is the worst available option. It is
      near-unreachable **on `delete`** — `validate` loads the record and `authorize` refuses a missing
      space — which is why it is stated rather than left to the builder. *On `forget` it is merely
      rare: `authorize` returns early on `forget` before that refusal, deliberately, so a phantom
      card stays dismissible — so branch 2's fresh read can genuinely find the record gone under a
      competing delete, and the refusal is a live path there rather than a stated impossibility.*
- [ ] **The no-op below is placed AFTER `forget`'s existing active-member refusal, not before it.**
      Placed first it would convert today's `AuthorizationError` on a healthy active space the actor
      still belongs to into a silent success, which FR-013 says is untouched.
- [ ] **On an ever-`active` space, `forget` is a no-op that clears NOTHING.** Not the slot, not the
      chip. Its cache-only branch calls `membership.clear_slot(actor, space)` and
      `cache.remove_entry`, and the Connections page derives every row from the cache — so clearing
      the chip deletes the row, which deletes FR-007's Retry, which is the only exit from a failed
      delete. `create` is refused by FR-005, `forget` by this criterion, and `delete` needs an
      affordance that no longer renders: the space would be permanently stranded by one Dismiss
      click. It does not raise; it returns a no-op result and the row survives.
- [ ] **`delete_space` has two routes, and the never-active one is specified rather than implied.**
      The predicate is `everActive is True or status == "active"` — the second disjunct covers a
      record that predates the backfill. True → empty (FR-003). **False → destroy**, exactly as the
      verb does today, because a never-active space reached by `delete` is the same object
      `forget`'s owner path would destroy and the same argument applies (FR-002's justification
      below). An earlier draft left this branch unnamed while FR-003's table said the helpers are
      "not called on this route", which describes a second route the spec never wrote.
- [ ] `delete_space` reads the **freshly loaded** record. *The reason is the validate→verb window,
      not staleness in general:* `validate` already does `reg.load(space)` at the start of every
      execution, so the event record is not stale by construction — but FIFO orders delivery and not
      executions (SPEC-157), so an `add-members`, `leave` or competing `delete` can land between
      validate and this verb. *An earlier draft justified this by claiming the event record would
      "see `active` where a fresh read sees otherwise", which is not true of the code.*
- [ ] **`forget_space`'s branch 2 reads freshly too, and both name-freeing routes clear the UNION.**
      `reg.delete` has exactly two callers — this branch and `delete_space`'s never-active route
      above — and freeing a name makes the roster those routes clear a security boundary rather than
      housekeeping: a slot outliving the record is a principal tag on whatever is created under that
      name next, because the portal role's shared-space policy is scoped on the tag value and not on
      any space identity. Both take `members` from the validator's event and inherit the same
      window, so both re-read before the loop and clear slots, index entries and cache cards for the
      union of the event roster and the fresh one, then `reg.delete`. *Stated because FR-008's union
      pass is written entirely against the emptying route's rewrite, and a builder closing that race
      exactly as specified leaves it open on both routes that actually free a name.*
- [ ] **The justification for destroying a never-`active` space is stated honestly**, and the "no
      user data by construction" claim is **withdrawn**: `create_space` assigns the Cognito slot —
      which *is* the S3 grant — before `finalize`, so a creator can write into a space that never
      becomes active. The real argument is narrower and sufficient: such a space was reachable **only
      by its creator**, and the destroying route is that same creator explicitly discarding their own
      failed create. Nobody else's data can be lost.
- [ ] **"Reachable only by its creator" is itself FALSE, and the remedy is a status gate on
      `add_members`, not a roster check on the destroying route.** `authorize` has no status gate —
      `OWNER_ONLY_ACTIONS` checks the owner and nothing else — so an owner may `add_members` to a
      `provisioning` or failed-create record, and `assign_or_find_slot` stamps each new member's
      slot, which *is* the S3 and Glue grant, before `save_members` commits. A never-`active` space
      can therefore hold data written by somebody other than its creator, and the sentence above is
      what licenses destroying it. **The refusal goes in `save_members`' CAS transform, beside
      FR-008's no-owner guard, and raises the same `MembershipRefused`**: that is the only site
      holding a *fresh* record, so a gate in `authorize` or at the top of the verb would read the
      same validate-loaded copy and inherit the staleness it exists to prevent — and `authorize` is
      additionally the wrong home, since FR-013 keeps authorization untouched and this FR states
      `delete`'s missing status guard there as a live fact. **FR-008's slot-rollback criterion covers
      this refusal too**, unchanged in shape: without it the gate leaves the added user holding a
      live `custom:shared_space_k` and appearing in no roster, which that criterion already calls
      strictly worse than the state it prevents. The gate changes the retention predicate not at all
      — both destroying routes keep evaluating `everActive` alone. *A roster check on the destroying
      route was the obvious alternative and is rejected,
      because it is blind to exactly the case that motivates it: `finalize` rebuilds the record from
      a literal carrying `members: [actor]`, so an add that loses its race to `finalize` leaves a
      live slot and no roster entry to read. It would also retain every failed create that ever had a
      member, burning those names permanently — and it would pass any test written from the roster.*
- [ ] `delete` has **no status guard** in `authorize` (`OWNER_ONLY_ACTIONS` checks the owner only);
      "delete operates on live spaces" is a UI convention, not an invariant. Stated, and the fresh
      read above is what makes the verb correct without one.

### FR-003: The delete verb empties the space

#### Acceptance Criteria:

- [ ] On the emptying route, `delete_space` calls neither `teardown.delete_shared_prefix` nor
      `teardown.drop_database`. Asserted against the real verb's call sequence, not by reading source.
- [ ] `teardown.revoke_portal_role` is **also not called**, and the rationale is stated precisely
      rather than as "the database becomes unreachable": with every member's slot cleared, the
      portal-role grant reaches no *user*, because every resource in
      `portal-role-shared-space.json.tftpl` is scoped by `${aws:PrincipalTag/shared_space_k}` — the
      object statement by resource substitution, `ListBucket` by prefix condition, with the Glue
      `:catalog` ARN carrying no space grant of its own. The database **does** remain reachable by the control-plane execution roles, which hold tag-policy
      grants on its still-present `portal-managed` LF-Tag; application-level `is_active_member` is
      what gates them, and that returns false for everyone (FR-006). Revoking the grant would leave a
      restored space's catalog unusable for no benefit.
- [ ] **This contradicts SPEC-204 FR-011's last criterion, which says a delete must still revoke
      while role-level grants exist.** SPEC-205 wins and SPEC-204 is edited; the rejection is written
      down in both files, per the reviewer contract.
- [ ] The per-member loop is unchanged. `members` already includes the owner, so "removes everyone
      including the owner" needs no new code — asserted, because it looks like it would.
- [ ] `reg.delete(space)` is replaced by **`reg.empty_space(name, previous_owner, request_id)`**,
      committing `members: []`, `acknowledged: []`, `owner` **removed from the record** (not set to
      `null` — one representation, FR-004), `status: "active"`, `previousOwner`, and `emptiedAt` in
      `registry.now_iso()`'s format. Any `reason` left by an earlier failure is **removed**; every
      other field is carried forward.
- [ ] **It builds from `dict(existing)`, never from a literal.** A literal drops `everActive` and
      `createdAt` — the same defect FR-001 catches in `finalize`.
- [ ] **Re-emptying an already-emptied record is a no-op.** `delete` is idempotent today
      (`test_delete_idempotent_…` exists) and a replay on this route would otherwise overwrite
      `emptiedAt` with a later time and fall back to the stale event record for `previousOwner` — an
      operator reading either gets a wrong answer and no test looks. If the record already has no
      `owner` and an empty roster, both fields are preserved and the write is skipped.
- [ ] **It returns `(committed, replaced)`.** `cpcommon.cas.cas_mutate` returns only the committed
      value, so the replaced record is captured out of the mutator rather than read beforehand — a
      pre-read is a different record under a race and would pass every test that does not race.
      FR-008's latecomer pass consumes `replaced`.
- [ ] **The capture is attempt-scoped.** `cas_mutate`'s transform runs **once per attempt**, so the
      captured value is reset at the top of the transform — a capture that persists across a losing
      attempt leaves a stale record behind, and every non-racing test passes either way. The test
      drives a genuine CAS retry.
- [ ] After a delete: `load(space)` returns a record; `members` is empty; `owner` is absent;
      `status` is `active`; the objects under `{space}/` and the Glue database are **present**. A
      test that checks only the registry passes over the point of the spec.

### FR-004: The `owner` field is cleared, and the record is inert

#### Description:

`authorize` gates every owner-only action on `actor != registry.get("owner")` — the field, never the
roster. An `owner` retained through a delete leaves the original owner able to `add-members` on the
emptied space and revive it, with the previous cohort's files intact.

#### Acceptance Criteria:

- [ ] The rewrite removes the `owner` key. With it absent and `members` empty, `authorize` refuses
      every owner-only action (`actor != None`) and every member-only action (empty roster).
- [ ] **The inert-state test is driven as the ORIGINAL OWNER** — `add-members`, `remove-members`,
      `leave`, `acknowledge-membership` and `delete` each raise `AuthorizationError`. As a stranger it
      passes over the defect, because the field `authorize` reads is `owner`.
- [ ] `previousOwner` is written and **no authorization path reads it**. A test asserts `authorize`
      refuses an actor equal to `previousOwner`.
- [ ] **Five verbs subscript `registry["owner"]` directly** (`add_members`, `delete_space`,
      `acknowledge_membership`, `remove_members`, `leave`). All are unreachable on an emptied record
      because `authorize` refuses first — asserted as its own criterion, because it is exactly what a
      later change to `authorize` would break silently, turning a refusal into a `KeyError`.
- [ ] **The `owner` readers outside the verbs are audited here, not deferred**: `tscommon/notify.py`
      and `fscommon/notify.py` resolve a space's owner to build a notification link, and both already
      degrade safely on a missing owner. Recorded so a later reader does not rediscover it.

### FR-005: The name is permanently taken, and create cannot revive a space

#### Acceptance Criteria:

- [ ] Creating a space whose name matches an emptied record is refused through `reserve`'s existing
      taken-name path: `_resolve_reserve_collision` requires `existing.get("owner") == actor`, which
      is `None != actor` on an emptied record. No new code path, no new wording.
- [ ] **`_resolve_reserve_collision`'s failed-retry overwrite additionally requires
      `not existing.get("everActive")`.** Without it, a failed *delete* leaves an owner-retained
      `failed` record that the overwrite re-provisions — reviving the space with the roster reset to
      the owner alone and every previous member's files intact. This is the same hazard FR-004 exists
      to prevent, through a different door.
- [ ] A test drives create against (a) a failed *create* record — overwrite permitted, name
      reclaimed; and (b) an ever-`active` `failed` record — refused. Both by the original owner.
- [ ] **The refusal reveals nothing new**: the namespace is already global and already probeable, so
      an emptied space is one more record the caller could already not distinguish. SPEC-113 is not
      weakened. *If a future spec makes space names non-probeable, this is what it must revisit.*

### FR-006: `active` with zero members is legitimate, and the readers are audited here

#### Acceptance Criteria:

- [ ] `cpcommon.registry.is_active_member` is **unchanged** — it requires `status == "active"` **and**
      the user in `members`, so it returns false for everyone on an emptied space. Asserted, because
      the whole audit turns on it.
- [ ] **Five planes call it, not four**, and they are enumerated in this spec:
      `table-share-validate-authorize`, `table-builder-validate-authorize`, `file-send-common`,
      `archive-common`, and **`data-quality-validate-authorize`**. A test asserts an emptied space is
      refused by all five.
- [ ] **`cpcommon.registry.is_active` is a SECOND predicate and auditing only the first misses the
      worst case.** It is `record.get("status") == "active"` and nothing else, and its two callers are
      **destination** validators: `table_share_validate_authorize.py` and
      `file_send_validate_authorize.py` both use it to decide whether a named space may receive a
      share. On an emptied record — `active`, `members: []` — it returns **true**, so **any former
      member who remembers the name can still push a table or send files into the deleted
      workspace**. SPEC-158 keeps an unlisted space typeable and a former member knows the name; the
      objects land under a prefix nobody holds a slot for, a table is created in the retained
      database, and the sender is told it succeeded. The owner notification is skipped because there
      is no owner (FR-004), so **nobody is told at all**.
- [ ] **The two destination validators move to `cpcommon.registry.may_receive_share(record)`** —
      `is_active(record) and record.get("owner")`, expressed once in `cpcommon` (both callers are
      different planes, so it belongs there and not in `shared-space-common`), never reimplemented at
      a call site. The name is fixed here because FR-006's sweep hard-codes it.
      `is_active` itself keeps its meaning; what changes is that no caller may use it alone to decide
      reachability.
- [ ] **The guard sweeps THREE names, not two** — `is_active_member`, `is_active` and the new
      destination predicate. *Two would go blind the moment this FR lands: the validators move to the
      new name, so sweeping the old two drops them out of the swept set entirely and a later caller
      of the new predicate would not fail CI — the guard's whole purpose.*
- [ ] **The covered set is six modules, not five.** `file-send-validate-authorize` is a sixth
      module inside an already-counted plane, so counting planes and counting modules give different
      answers. The sweep compares **modules**. The shape to reuse is this repo's existing AST sweeps
      (`test_layer_import_safety.py`, SPEC-165's), not a new mechanism.
- [ ] A test asserts a share and a file-send **targeting an emptied space are refused**, driven as a
      former member of that space.
- [ ] **Both validator suites' destination fixtures gain an `owner`, in the same commit.** They build
      `{"status": "active", "members": [...]}` with no owner, so under the new predicate **every
      existing destination fixture is an emptied space** and three tests fail — one of them
      (`test_membership_is_not_required_to_send_to_a_space`) with a message about membership, which
      is the opposite of the reason. The corollary matters more than the fix: the suite had **no**
      coverage distinguishing owner-present from owner-absent, so nothing existing was protecting the
      behaviour this FR changes.
- [ ] No new status value. A terminal status was considered and declined: it would make every reader
      above learn a new value, where the empty roster already makes each answer correctly.

### FR-007: The failed-delete affordances

#### Description:

The Connections page renders **Dismiss** and **Retry** on any `failed` row, and both were written
when the only thing that could fail was a create. After this spec a failed *delete* leaves live data,
and Dismiss destroys it while Retry revives it. FR-002 and FR-005 close the server-side doors; this
FR makes the buttons mean the right thing.

#### Acceptance Criteria:

- [ ] The cache entry a failed verb writes carries the **action** that failed. `cache.upsert_entry`'s
      failure entries gain a field distinguishing a failed create from a failed delete; the shape is
      additive and older entries without it are treated as create, which is what they were.
- [ ] On a failed **create** row, Dismiss and Retry behave exactly as today — `forget` and `create`.
- [ ] On a failed **delete** row, **Retry re-enqueues the delete**, not a create. A test asserts the
      enqueued verb.
- [ ] On a failed **delete** row, **Dismiss clears the chip and does not destroy the space** — which
      FR-002's guard already guarantees server-side, so this is the affordance agreeing with the
      server rather than a second enforcement.
- [ ] A row in `deleting` renders the same Retry, so the stuck-`deleting` state (Out of Scope to fix
      generally) has an exit that is not an operator.
- [ ] The discriminator is **`failedAction: 'create' | 'delete'`**, reusing the existing action
      vocabulary, written explicitly by both `create_space` failure upserts and by `delete_space`'s.
- [ ] **It travels through SIX sites across TWO features**, enumerated because
      `features/connections/` is a separate area the spec would otherwise never name:
      `features/shared-spaces/sharedSpaces.types.ts` (`SharedConnectionEntry`),
      `sharedSpaces.service.ts`'s `normalizeEntry` (**or an unvalidated union member reaches the
      row**), `features/connections/connection.types.ts` (`Connection`, separately enumerated),
      `features/connections/useConnections.ts` (**a field-by-field spread-conditional mapper — an
      unmapped field is silently dropped**), and `ConnectionsPage.tsx`'s `ConnectionRow` type and its
      mapper.
- [ ] **`retrying` becomes `Map<string, 'create' | 'delete'>` and `onRetry` receives the row, not the
      name.** The optimistic override must show `deleting` for a retried delete, and forcing that
      status makes `row.status === 'failed'` false on the next render — so `failedAction`-based logic
      flips the row back to `provisioning` unless the retry kind is carried. One more call site than
      the enumerated six.
- [ ] **Retry must not render on an optimistically-`deleting` row.** `ConnectionsPage`'s
      `transitioning` map forces `status: 'deleting'` the instant the user confirms a delete, and
      that is **indistinguishable in `rows`** from the durable `deleting` the validator writes. Left
      alone, this FR's "a row in `deleting` renders Retry" puts a Retry button beside a delete
      submitted two seconds ago. The two must be told apart — the optimistic set is local state and
      already known.
- [ ] **`ConnectionsPage`'s optimistic retry override hard-codes `status: 'provisioning'`**, which is
      wrong for a retried delete — it must show `deleting`. Named because it is invisible in review
      and produces a row that lies for the length of the run.
- [ ] **Dismiss is suppressed on a failed-delete and a `deleting` row.** FR-002 makes `forget` a
      no-op there, so offering the button would present an action that does nothing; and the earlier
      draft's criterion — "Dismiss clears the chip and does not destroy the space" — described
      clearing the row, which is itself the trap that strands the space.
- [ ] **FR-013's "no browser change" does not cover this**, and the spec says so rather than letting
      the contradiction stand.

### FR-008: A membership write racing the empty

#### Description:

`validate` loads the record and authorizes; the verb runs later. FIFO orders delivery, not executions
(SPEC-157). So `add-members` authorized against a live record can commit *after* a delete emptied it:
`save_members` CAS-reads the fresh emptied record and appends, producing a member with a live Cognito
slot and full access to a supposedly deleted space, in a record with **no owner** — so nobody can
remove them and nobody can delete it. Under today's semantics the analogous race is a zombie record
over destroyed data; here it is live access to retained data.

#### Acceptance Criteria:

- [ ] **`save_members` refuses to `add` to a record with no `owner`**, inside the CAS loop where the
      record is fresh. `remove` and `acknowledge` are unaffected — both only shrink or annotate, and
      refusing them would strand a member who slipped through. (`create_space` never reaches
      `save_members`, so creation is untouched.)
- [ ] **`add_members` rolls back the slots it assigned in this run when the refusal fires.** It calls
      `membership.assign_or_find_slot` for every new member **before** `save_members` and, unlike
      `create_space`, has **no rollback** — so the guard alone leaves the added user holding a live
      `custom:shared_space_k` slot, which *is* the S3 and Glue grant, while appearing in no roster
      anywhere. That is strictly worse than the state the guard was written to prevent: at least a
      roster entry is visible. The rollback mirrors `create_space`'s.
- [ ] **The narrow window is not the only window, and the wide one needs the delete side to close
      it.** The guard fires only once the rewrite has committed; FR-009 requires the rewrite to be
      **last**, so an `add-members` committing while `delete_space` is mid-loop sees an owner and
      succeeds. `delete_space` captured `members` before the loop, so the new member's slot is never
      cleared and the rewrite blanks the roster over them — the same orphan, through the ordinary
      interleaving rather than a knife-edge one. **The rewrite's CAS returns the record it replaced,
      and `delete_space` clears slots for the UNION of its captured list and that record's members**,
      then re-checks. Without this, FR-008 and FR-009 together guarantee the orphan rather than
      prevent it.
- [ ] **The refusal raises `MembershipRefused`, a new exception defined in
      `lambdas/shared-space-common/registry.py`** — the module `save_members` actually lives in.
      *An earlier draft said `cpcommon/registry.py`, which is the wrong one of two files with that
      name: it is documented read-only, holds no writer, and imports only `clients` and `config`, so
      the "adds no import edge" argument is false there and putting a shared-space domain exception
      in it would break its own contract.* *An earlier draft offered three options and said "the spec
      states which" without stating it — an Open Question in a sentence promising not to be one.*
      The two rejected alternatives, with why: reusing `ProvisioningError` is **silently** wrong —
      `add_members` already catches it around `assign_or_find_slot`, so a later widening of that
      `try` would turn a hard refusal into a "skipped at limit" summary row and the add would
      half-succeed; and a sentinel return changes `save_members`' contract, which four verbs consume
      as "the committed record". Defining it in `registry.py` adds no import edge and collides with
      no existing handler. The plane's ASL catches on `States.ALL`, so no state-machine change is
      needed.
- [ ] **The latecomer pass runs AFTER the rewrite, and FR-009's "last" is scoped accordingly.** The
      union is only knowable once the rewrite returns the record it replaced, so the two cannot both
      be last. *This contradicted FR-009 as originally written and a builder honouring FR-009
      literally cannot close FR-008's second window at all — while producing code that looks like it
      does.* The order is: per-member loop over the **captured** roster → rewrite → **latecomer
      pass** clearing slots and cache entries for anyone in the replaced record's roster who was not
      in the captured one.
- [ ] **Latecomers are notified and counted.** A user added between the captured loop and the
      rewrite has their access revoked by the latecomer pass, so they receive the same
      `The shared workspace "X" was deleted.` message as everyone else and appear in the run's
      revoked-member count. Stated because either choice compiles, passes every test this spec asks
      for, and the wrong one silently revokes a user's access with no message.
- [ ] **Every new exception registers its reason token** with the domain resolver `ss_notify_failure`
      reaches through `cpcommon.errors.failure_reason`. An unregistered reason degrades to generic
      text, and a `TerminalError` carrying one raises `ValueError` **at the raise site** — a runtime
      break rather than a review finding. This covers `MembershipRefused` — including FR-002's
      `add_members` gate, which raises it — the `None`-record refusal, the re-check failure below and
      the destroying routes' post-`reg.delete` resurrection raise.
- [ ] **The re-check is one re-read, and it raises.** After the latecomer pass, re-read the record;
      a non-empty roster raises rather than looping — the `save_members` guard forbids further adds
      once the owner is gone, so a loop would be unreachable code and a version without the assertion
      would be indistinguishable in every test.
- [ ] **The destroying routes have the same race and cannot use the same mechanism.** The no-owner
      guard does not cover them: they delete the record rather than blanking its owner, so there is
      no emptied record to refuse against, and there is no CAS return to take a union from — hence
      FR-002's fresh read. Two outcomes, and the second is the one no union pass fixes. An
      `add-members` committing *before* `reg.delete` leaves a member holding a slot for a name about
      to be freed, which the fresh-read union catches. One committing *after* it **resurrects the
      record**: `save_members` falls back to `dict(registry)` from the stale event copy and `_put`
      sends `IfNoneMatch="*"` against a now-absent object, so the write succeeds and leaves a record
      locking a name over torn-down resources. **The destroying routes re-read once after
      `reg.delete` and raise if the record is back**, the same shape as the re-check above, because
      the alternative is a name permanently held by a space that no longer exists. *The resurrector
      is NOT `add-members`: FR-002's gate refuses it on exactly the never-`active` records these
      routes handle. It is `remove_members`, `leave` or `acknowledge_membership` — which share the
      same fallback and which the no-owner guard deliberately exempts — running against the legacy
      multi-member never-`active` records FR-001 enumerates. Named because a builder reasoning from
      the add case concludes the window is closed and skips the re-read.*
- [ ] Two tests, one per window: (a) authorize `add-members` against a live record, empty the space,
      run the verb — the member is not added and holds no slot; (b) `add-members` commits mid-loop —
      the member's slot is cleared by the union pass. **The notification is asserted on the state
      machine's `NotifyFailure` path**, not on the verb, which emits none of its own.

### FR-009: A partial empty

#### Acceptance Criteria:

- [ ] A failure during the per-member loop records `status: "failed"` and notifies the owner, as
      today. **The `owner` field is kept on this path** so the space stays operable for a retry.
- [ ] **The rewrite is the last step of the captured loop** — after every slot and cache entry for
      the roster the verb captured is cleared. Failing the other way leaves a record with no owner
      and members still holding slots: unrecoverable *as an owned space*, since no owner-only action
      is reachable. *(Members could still `leave`, so it is not inert — the earlier "inert and
      unretryable" phrasing was wrong; the ordering requirement is unchanged and this is why it
      holds.)* **FR-008's latecomer pass then follows the rewrite**, because the union it clears is
      only knowable from the record the rewrite replaced. "Last" means last of the captured loop, not
      last in the verb.
- [ ] A test drives a `clear_slot` failure mid-loop and asserts the record still names its owner, its
      status is `failed`, `everActive` is set, and a retried delete succeeds.
- [ ] **The credential window is named, bounded and accepted.** `membership.clear_slot` empties the
      Cognito attribute, but the principal tag is stamped at credential-vend time — which is why
      `useConnections` forces a token refresh after a membership change and why `add_members` logs
      `principal_tag_needs_token_remint`. So **every removed member keeps live S3 and Glue access to
      the retained data until their session credentials expire**, the deleter's own browser most of
      all. Under today's semantics that window is harmless because the data is gone; here it is not.
      The bound is the Identity Pool credential TTL, it is accepted rather than mitigated, and the
      spec says so — "every member's access ends" is true only after the last credential expires.
- [ ] `TeardownIncompleteError` is not raised on the emptying route and is retained in full on
      FR-002's destroying route.

### FR-010: What the user is told

#### Description:

The user-facing verb stays "delete" — from every user's point of view the space is gone. What must
not survive is the product claiming the data was destroyed, and today it claims it in four places.

#### Acceptance Criteria:

- [ ] **The four false statements are named and fixed**, verified as present today:
      `DeleteSharedSpaceDialog.tsx`'s body ("This permanently deletes … all of its files, all of its
      tables, the database, and every member's access"), its JSDoc, the `irreversible` prop it passes
      to `ConfirmDialog` (which renders "This can't be undone."), and `helpContent.ts`'s
      `delete-space` subtitle and its "There's no undo." callout.
- [ ] **The `irreversible` prop is dropped from `DeleteSharedSpaceDialog`**, not reworded in
      `ConfirmDialog` — that component is shared by dialogs whose actions genuinely are irreversible.
- [ ] **The assertion is render-based, not a word sweep.** A test renders `DeleteSharedSpaceDialog`
      and asserts its text makes no destruction claim, and a test asserts the `delete-space` guide
      object's content. *A word list was specified in an earlier draft and would have been vacuous:
      the strings in the code are "This can't be undone." with a curly apostrophe and "There's no
      undo.", neither of which matches the terms it listed.*
- [ ] Notification wording is **unchanged** — the space is gone from every member's view, and a
      message about retention describes something only an administrator can act on.
- [ ] Help gains two facts in the **`delete-space` guide of the `shared-connections` section** —
      there is no "shared workspaces" section; *the earlier draft named one that does not exist*: a
      deleted workspace is removed from everyone and its contents are retained by administrators, and
      its **name cannot be reused**.
- [ ] **`ConnectionsPage`'s `metaLine` "Deleting — applies on next refresh" is false on a stuck
      `deleting` row** that FR-007 now gives a Retry to, and is fixed with the other copy.
- [ ] `CreateSharedConnectionDialog`'s "the name is permanent (it can't be renamed)" gains the second
      half — a name is never reusable after deletion. It is where the user chooses the name, and where
      FR-005's refusal will later confuse them.

### FR-011: What accumulates, and the quota that binds

#### Acceptance Criteria:

- [ ] Three things now grow without bound: S3 objects under emptied prefixes, Glue databases with no
      members, and registry records. None is managed by this spec.
- [ ] **The binding constraint is the Glue databases-per-account quota**, not storage cost. Every
      user already consumes one for their personal database, and emptied spaces never release theirs.
      **This spec does not compute the headroom and does not pretend to**: the quota is
      account-specific and the create rate is not yet observable at a useful scale, so promising a
      computed bound here would defer a decision while looking like one. The disposition instead is
      unconditional — **request a Service Quotas increase as a Phase 4 task**, and record the quota,
      the current database count and the resulting headroom in the delivery doc as a measurement.
      *An earlier draft asked for a computed bound and supplied none of its three inputs, which is
      the Open-Question shape this project forbids.*
- [ ] The registry listing grows with historical spaces, not live ones, and **SPEC-204's sweep
      iterates every record** — so its cost and its `identitystore`/Lake Formation call budget are
      sized against all spaces ever created. Named as an input to its FR-009.
- [ ] Retained objects keep costing money, accepted rather than unnoticed. If it ever needs managing
      it is an S3 lifecycle rule, not application logic.

### FR-012: Observability

#### Acceptance Criteria:

- [ ] The `space deleted` record gains a field distinguishing **emptied** from **destroyed**, so
      FR-002's two routes are visible in `logs/` rather than inferred from which verb ran. *The member
      count is already there (`members_applied`); only the discriminator is new.*
- [ ] The backfill (FR-001) reports **registry objects scanned** and how many it stamped, split by
      the status it found. *"Object count" alone is ambiguous between registry records and the S3
      objects under an emptied prefix; it means the former.*
- [ ] The `stores=` list differs per route — the emptying route writes no `glue` — so it is set from
      the route rather than left as today's literal.
- [ ] Space names and usernames are permitted user metadata; nothing else is added. `env` and
      `version` on every record; messages are literals; `echo=` prohibited.

### FR-013: What does not change

#### Acceptance Criteria:

- [ ] Authorization is untouched — `delete` stays owner-only, `leave` still refuses the owner.
- [ ] The verb's queue, its FIFO keys, its state machine position and its notification dedup ids are
      unchanged.
- [ ] No IAM policy, bucket policy or Lake Formation grant is edited. The plane keeps its
      `s3:DeleteObject` and `glue:DeleteDatabase` grants because FR-002's route still uses them.
- [ ] **The browser changes in exactly the places FR-007 and FR-010 enumerate**, which span
      `features/shared-spaces/` **and** `features/connections/` — five files for the discriminator,
      plus the retry status override and the copy. *An earlier draft said "two places and only two",
      which was wrong in both the count and the feature.* Nothing outside that list changes.
- [ ] **A backfill is required** (FR-001) and it is the only migration. Spaces deleted before this
      ships were destroyed; there is nothing to retain retroactively.
- [ ] **Nine existing tests change and are expected to**, named so their failure is not read as a
      regression. *An earlier draft named four and missed the rest, including the only one outside
      `lambdas/`.* In `test_delete_space.py`: `test_delete_cascades_files_tables_db_members_and_registry_frees_name`
      and `test_delete_idempotent_tolerant_of_partial_prior_progress` (both seed `active` and assert
      the prefix, database and record are gone); the two `TeardownIncompleteError` tests (their
      fixture no longer reaches that route);
      `test_delete_records_failure_and_reraises_without_deleting_registry` and
      `test_delete_failure_notifies_owner_with_reason` — **both inject a fault into
      `teardown.drop_database`, which the emptying route never calls, so they fail as "expected
      RuntimeError, none raised", which reads as a broken test rather than an inverted one**; and
      `test_delete_swallows_emit_failure_and_still_succeeds` and `test_handler_uses_validated_context`,
      which assert the registry key is gone.
- [ ] **The ninth is in the portal suite**, which is the silent one: `sharedSpacesUi.test.tsx`'s
      `it('marks the action irreversible')` asserts `/can.t be undone/i` on `DeleteSharedSpaceDialog`,
      and FR-010 removes that line. A builder working from a lambdas-shaped list will meet it as a
      surprise in a different suite.
- [ ] `test_forget_space.py`'s teardown tests use never-`active` fixtures and **survive**, which is
      FR-002's split working. Two caveats for whoever runs them. The multi-member test's comment
      describes a was-`active`-now-`failed` record as the branch's population, and branch 3 stops
      that record reaching teardown — **reword the comment, keep the assertions**: they guard the
      union pass above on the never-`active` multi-member records FR-001 enumerates, which predate
      FR-002's `add_members` gate and still reach branch 2. And **two** comments in that file carry
      the withdrawn claim, not one — the multi-member test's and the index fan-out test's — as does
      `forget_space.py`'s own verb docstring ("a failed create is single-member, creating being
      creator-only"). Named by file because the tests have no docstrings, so a builder greps the
      test file for the sentence, finds only comments, and leaves the verb's copy standing.
- [ ] **The "nine existing tests" inventory above is STALE and is re-derived before it is worked
      from, not trusted.** It predates the suite cut that reduced `test_delete_space.py` to a
      caller-shaped set and the membership-index test added after it, so it names tests that no
      longer exist while missing two that do and that this spec breaks:
      `test_delete_clears_every_index_entry_BEFORE_the_name_is_freed` patches `registry.delete` with
      a watcher the emptying route never calls, and
      `test_a_key_that_could_not_be_deleted_leaves_the_registry_record_intact` injects an undeletable
      key into a `delete_shared_prefix` that route never reaches — both fail as "expected raise, none
      raised", which reads as a broken test rather than an inverted one. *Recorded rather than
      rewritten here: re-deriving the list is the builder's first step, and a second stale list would
      be worse than none.*
- [ ] **The reasoning in this spec cannot be carried into `lambdas/` as comments.** That tree allows
      **zero** inline comments, and `scripts/validate_docs.py`'s citation rule bans `FR-\d+` and
      `AC-\d+` alongside `SPEC-\d{3}` — so the read-first ordering, the union pass and the `None`
      route are expressed in Google-style docstrings without requirement numbers, or moved to
      `lambdas/info/planes/shared-spaces.md`. Budgeted here because it is the largest unbudgeted chunk of the
      work and it fails CI rather than review.

---

### Which criteria can drive the build, and which only guard it

Stated because a builder who expects every criterion to go red first will assume they have
mis-implemented something. **Regression guards, not drivers:** FR-001's `finalize(..., "failed")`
no-stamp assertion and its never-cleared sweep (both pass before the change, because nothing stamps
anything yet), and FR-005's first criterion (`_resolve_reserve_collision` already requires the owner
match — the spec says "no new code path", and it is the *second* criterion, the ever-active guard,
that drives). **FR-001's sweep ships with a guard-the-guard** on SPEC-153's pattern, because a sweep
that is vacuous today and silently goes trivial later is this repo's recorded failure mode.

**Not assertable from here:** FR-004's "five verbs subscript `registry["owner"]` … unreachable
because `authorize` refuses first" — you cannot assert a `KeyError` did not fire on a line that never
executes. The reachable half (the refusal) is asserted; the rest is documentation. And FR-008's
notification criterion needs an ASL-graph walk this plane does not have (SPEC-169's shape), so the
refusal and the rollback are asserted at the verb and the notification is **owed**, recorded as such
rather than asserted against a stub.

## Data Model

```
s3://{admin-bucket}/shared-spaces/{name}.json

  in use:   { version, name, owner, members: [...], acknowledged: [...], status: "active",
              everActive: true, createdAt, lastRequestId }
  emptied:  { version, name,        members: [],    acknowledged: [],     status: "active",
              everActive: true, createdAt, lastRequestId, previousOwner, emptiedAt }
```

`owner` is **removed**, never `null`. `previousOwner` is read by no authorization path.
`emptiedAt` uses `registry.now_iso()`'s format and is for the operator.

**What the emptying rewrite does to every other field is stated, because `dict(existing)` carries
them all forward silently:** `acknowledged` is cleared to `[]` (it is a projection of a roster that
no longer exists), any `reason` left by an earlier failure is **removed**, and everything else —
`createdAt`, `everActive`, `version`, `lastRequestId` — is carried forward. An emptied record that
still names acknowledgements of departed members is not wrong in any test the spec asks for, which
is why it is written down.

## Implementation Phases

**Every boundary below is safe to leave on `main`, and one earlier arrangement was not.** An earlier
draft split the emptying rewrite (Phase 2) from the destination-predicate change and the add-refusal
(Phase 3). For that whole interval every emptied record is `status: "active"` with no owner, so
`is_active` returns true, **any former member who remembers the name can push a table or send files
into a deleted workspace**, and with no owner there is nobody to notify — the exact hazard FR-006
exists for, opened deliberately by the phase order. The concurrency window was open for the same
interval. They are one phase now.

### Phase 1: The durable fact

FR-001 — the field, `finalize`'s conditional stamp and its carry-forward, preservation in
`save_members`/`set_status`, the one-shot backfill Lambda and the deploy order.

*Safe alone:* the field is written and read by nobody, and the backfill is idempotent.

*Two orderings inside this phase, not one.* FR-001 states backfill-then-verb. The other is this
repo's standard code/infra split: the backfill Lambda's `locals.tf` entry must apply through **Deploy
Infrastructure before `deploy-lambdas.yml` can push its code**, or the matrix row targets a function
that does not exist.

### Phase 2: The retention rule, both routes, and everything that must land with them

FR-002, FR-003, FR-005, FR-004, FR-006 and FR-008 together. The was-`active`-now-`failed` forget test
and the `finalize(..., "failed")` no-stamp test are written **before** the implementation.

*Safe alone, and only as a whole:* the first emptied record cannot exist before the predicate that
refuses it as a share destination and the guard that refuses an add into it.

*Two things land here that read like Phase 3 work.* The destination validators' **fixtures**
(FR-006) must change in this commit or the phase lands red. And `failedAction`'s **writers** are
`create_space` and `delete_space` — Phase 2 files this phase rewrites wholesale — so they are written
here and only the readers are Phase 3; splitting them means touching `delete_space.py` twice for one
field.

### Phase 3: The browser

FR-007's affordances and discriminator, and FR-010's copy.

*Safe alone; worse than "does nothing" if it never lands.* Between Phase 2 and here a failed delete
has **no exit at all**: Dismiss is a server no-op (FR-002), Retry re-runs a *create* which FR-005 now
refuses, and the row has no other affordance. Still safe to leave on `main` — the space is intact and
an operator can act — but say it accurately.

### Phase 4: Verification

FR-011's quota request, FR-012's fields, then the formatter, `ruff`, the blocking `mypy`,
`pytest lambdas/`, the portal suite and `npm run build`.

### Phase 5: Live checks

Against a deployed environment: a space with two members and files, deleted — gone from both lists,
objects and database present, name refused on re-create, original owner cannot add a member. **Both
browsers must re-mint credentials (sign out and back in, or wait out the Identity Pool TTL) before
the access checks are believed** — FR-009's credential window means a session that still holds the
old principal tag can read a space it was told is deleted, and the deleter's own browser is the one
most likely to be used for the check. Then a **share and a file-send targeting the emptied space**,
confirming both are refused (FR-006). Then a **failed delete**, confirming Dismiss is not offered and
Retry re-runs the delete. Then a failed create forgotten by its owner, confirming its name **is**
reclaimable — and separately, a failed create **deleted** by its owner, confirming the never-active
route destroys it and its name is still reclaimable. Into `docs/testing/e2e.md`'s shared-workspaces
section.

### Phase 6: Completion ritual

Per `CLAUDE.md`. Three `decisions/` entries: retention keyed on a durable fact rather than live
status and why; the cleared `owner` field with the `authorize` reasoning; and the `revoke_portal_role`
disagreement with SPEC-204, resolved in this spec's favour. `transition_plan.md` §6.3's rows are
corrected per FR-002's two routes.
