# Spec: A Delete Empties a Space and Destroys Nothing

**ID:** SPEC-205
**Status:** Draft
**Last Updated:** 2026-08-18
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
      not be, or its name is burned. They are distinguishable by hand at this scale — a failed create
      is single-member by construction, since creating is creator-only — and the set is small. The
      spec requires the enumeration to be run and its disposition recorded, rather than guessing a
      rule that is wrong in one direction or the other.
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
- [ ] `forget_space`'s owner path becomes `owner == actor and status != "active" and not
      record.get("everActive")`. **A test drives forget as the owner against a record that was
      `active` and is now `failed`, and asserts no teardown helper is called** — that is the exact
      data-loss path the first draft left open, and a test using a never-active fixture passes over
      it.
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
- [ ] **The justification for destroying a never-`active` space is stated honestly**, and the "no
      user data by construction" claim is **withdrawn**: `create_space` assigns the Cognito slot —
      which *is* the S3 grant — before `finalize`, so a creator can write into a space that never
      becomes active. The real argument is narrower and sufficient: such a space was reachable **only
      by its creator**, and the destroying route is that same creator explicitly discarding their own
      failed create. Nobody else's data can be lost.
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
- [ ] `reg.delete(space)` is replaced by a rewrite committing `members: []`, `owner` **removed from
      the record** (not set to `null` — one representation, FR-004), `status: "active"`,
      `previousOwner`, and `emptiedAt` in `registry.now_iso()`'s format.
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
- [ ] **The two destination validators move to a predicate that also requires an owner** —
      `is_active(record) and record.get("owner")`, expressed once in `cpcommon` under a name that
      says what it decides (a space that may receive a share), not reimplemented at each call site.
      `is_active` itself keeps its meaning; what changes is that no caller may use it alone to decide
      reachability.
- [ ] **The guard test derives the list for BOTH names** — the set of modules calling
      `is_active_member` or `is_active` equals the set the refusal test covers — so a sixth caller of
      either fails CI. A hand-written list of five rots exactly as the list of four did. The shape to
      reuse is this repo's existing AST sweeps (`test_layer_import_safety.py`, SPEC-165's), not a new
      mechanism.
- [ ] A test asserts a share and a file-send **targeting an emptied space are refused**, driven as a
      former member of that space.
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
- [ ] **The discriminator travels through five files across TWO features**, enumerated because
      `features/connections/` is a separate area the spec would otherwise never name:
      `features/shared-spaces/sharedSpaces.types.ts` (`SharedConnectionEntry`),
      `features/connections/connection.types.ts` (`Connection`, separately enumerated),
      `features/connections/useConnections.ts` (**a field-by-field spread-conditional mapper — an
      unmapped field is silently dropped**), and `ConnectionsPage.tsx`'s `ConnectionRow` type and its
      mapper. `parseCache`/`normalizeEntry` spread, so the read side needs no change.
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
- [ ] The refusal raises an error type reachable from `registry.py` **without adding a
      `registry → auth → config` import edge** to a module every verb loads — either the exception
      moves to a shared location or `save_members` returns a refusal the caller raises. The spec
      states which.
- [ ] Two tests, one per window: (a) authorize `add-members` against a live record, empty the space,
      run the verb — the member is not added and holds no slot; (b) `add-members` commits mid-loop —
      the member's slot is cleared by the union pass. **The notification is asserted on the state
      machine's `NotifyFailure` path**, not on the verb, which emits none of its own.

### FR-009: A partial empty

#### Acceptance Criteria:

- [ ] A failure during the per-member loop records `status: "failed"` and notifies the owner, as
      today. **The `owner` field is kept on this path** so the space stays operable for a retry.
- [ ] **The rewrite is the last step**, after every slot and cache entry is cleared. Failing the other
      way leaves a record with no owner and members still holding slots: unrecoverable *as an owned
      space*, since no owner-only action is reachable. *(Members could still `leave`, so it is not
      inert — the earlier "inert and unretryable" phrasing was wrong; the ordering requirement is
      unchanged and this is why it holds.)*
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
- [ ] Help gains two facts in the shared-workspaces guide: a deleted workspace is removed from
      everyone and its contents are retained by administrators, and its **name cannot be reused**.
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
      unconditional — **request a Service Quotas increase as a Phase 5 task**, and record the quota,
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
- [ ] The backfill (FR-001) reports its object count and how many records it stamped.
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

---

## Data Model

```
s3://{admin-bucket}/shared-spaces/{name}.json

  in use:   { version, name, owner, members: [...], status: "active", everActive: true,
              createdAt, lastRequestId }
  emptied:  { version, name,        members: [],    status: "active", everActive: true,
              createdAt, lastRequestId, previousOwner, emptiedAt }
```

`owner` is **removed**, never `null`. `previousOwner` is read by no authorization path.
`emptiedAt` uses `registry.now_iso()`'s format and is for the operator.

## Implementation Phases

### Phase 1: The durable fact

FR-001 — the field, its two writers, the preservation assertions and the backfill script. Nothing
else changes; the field is inert until Phase 2 reads it.

### Phase 2: The retention rule and the two routes

FR-002 and FR-003, with the was-`active`-now-`failed` forget test written **before** the
implementation. FR-005's `_resolve_reserve_collision` guard lands here — it is the same fact.

### Phase 3: The inert record and the audits

FR-004, FR-006 and FR-008, with the inert-state test driven as the original owner, the five-plane
refusal test and its derived guard.

### Phase 4: The browser

FR-007's affordances and FR-010's copy.

### Phase 5: Verification

FR-011's computed headroom, FR-012's fields, then the formatter, `ruff`, the blocking `mypy`,
`pytest lambdas/`, the portal suite and `npm run build`.

### Phase 6: Live checks

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

### Phase 7: Completion ritual

Per `CLAUDE.md`. Three `decisions.md` entries: retention keyed on a durable fact rather than live
status and why; the cleared `owner` field with the `authorize` reasoning; and the `revoke_portal_role`
disagreement with SPEC-204, resolved in this spec's favour. `transition_plan.md` §6.3's rows are
corrected per FR-002's two routes.
