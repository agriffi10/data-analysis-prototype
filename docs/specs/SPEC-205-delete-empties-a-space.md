# Spec: A Delete Empties a Space and Destroys Nothing

**ID:** SPEC-205
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-051/052/053/054/055 (the shared-space control plane, its registry, its verbs, and the criterion that the registry record is the name lock), SPEC-073 (acknowledge is display-only), SPEC-075 (the roster fan-out), SPEC-125 (`shared-space-common`), SPEC-151 (a partial teardown never frees the name — the rule this spec makes unreachable for one of its two routes), SPEC-113 (no existence oracle), SPEC-106 (`toUserMessage`), SPEC-074 (Help content), SPEC-127→137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

**Downstream:** **SPEC-204** is written against these semantics and cannot be built until this ships.
**SPEC-203**'s index writer is simpler because of them.

## Overview

Deleting a shared workspace destroys it. `shared-space-delete` deletes every object under the
space's prefix, drops its Glue database, revokes its Lake Formation grants, clears every member's
slot and deletes the registry record — after which the name is free and the data is gone.

This spec makes a delete **remove people instead of things**. Every member's access ends, including
the owner's, and the space disappears from every list — but the objects, the Glue database and the
registry record all survive, and the record stays `active` with an empty roster.

Two motivations, and the second is why it is worth doing on its own account rather than as
transition work:

- **Deleting a workspace is irreversible and unconfirmable.** A user who empties a shared space by
  mistake, or who is removed from one by an owner clearing house, has no recourse: the objects are
  gone from a bucket with versioning off. Retention makes the mistake recoverable by an
  administrator.
- **It deletes a whole class of failure from the control plane.** SPEC-151 exists because a partial
  teardown could free a name while resources survived under it; the teardown ordering, the
  `TeardownIncompleteError` protocol and the seeding-window guards in `transition_plan.md` §6.3 all
  descend from that. On the route that no longer destroys anything, none of it is needed — the
  hazard is unreachable rather than mitigated.

**The cost is stated up front because it is user-visible and permanent.** A name a space once used
can never be claimed again, and data a user asked to delete is retained. FR-004 and FR-006 are where
those land.

## Scope

### In Scope

- **The delete verb becomes a membership removal** (FR-001).
- **The retention rule, which keys on whether the space was ever `active`** (FR-002) — a failed
  create still tears down, and that is what keeps the change from hoarding rubbish.
- **Clearing the `owner` field, and the inert record it leaves** (FR-003).
- **The permanent name lock**, and why it is not a new disclosure (FR-004).
- **`active` with zero members as a legitimate state**, and the audit of everything that reads
  status (FR-005).
- **What the user is told** — notifications and Help (FR-006).
- **Failure semantics for a partial empty** (FR-007).
- **What accumulates, and what deliberately does nothing about it** (FR-008).
- **Observability** (FR-009), and **what does not change** (FR-010).

### Out of Scope

- **Any surface for retained spaces.** No admin UI, no restore button, no listing. Recovery is an
  operator acting directly on the registry and the bucket, and this spec adds no path to it — an
  admin UI is a standing Out-of-Scope item in `CLAUDE.md`.
- **Lifecycle or expiry on retained data.** FR-008 states the accumulation and declines to manage it;
  if it ever needs managing, that is an S3 lifecycle policy on the prefix, not application logic.
- **A true-erasure path** for a compliance request. There is none today either — the operator route
  is the same one that exists now.
- **Anything about entitlements, Access Grants or Identity Center.** SPEC-204, which this spec
  unblocks and does not depend on.
- **Changing `create`, `add-members`, `remove-members`, `leave` or `acknowledge-membership`.** Their
  behaviour is untouched; FR-003 and FR-005 only assert how they behave when handed an emptied
  record.

### What runs today, and what each step becomes

`shared-space-delete`'s verb body, in order:

| Today | After |
|---|---|
| `reg.set_status(registry, "deleting")` | **Unchanged** — the in-flight status still exists |
| `teardown.delete_shared_prefix(space)` | **Not called.** The objects survive |
| `teardown.revoke_portal_role(space)` | **Not called** (FR-001) |
| `teardown.drop_database(space)` | **Not called.** The Glue database survives |
| per member: `membership.clear_slot`, `cache.remove_entry` | **Unchanged.** `members` already includes the owner, so this already removes everyone |
| `reg.delete(space)` | **Replaced**: rewrite the record with `members: []`, `owner` cleared, `status: "active"` |
| notify every member | **Unchanged wording** (FR-006) |

`shared-space-forget`'s owner path — which fires only when `status != "active"` — **keeps its full
teardown**, and FR-002 is why.

### Premises later specs must honour

1. **`status` describes the space's resources, not who can reach it.** `active` means the prefix and
   the database are intact and usable. Reachability is membership, and the two are now independent.
2. **The registry record is the name lock and it is never released on this route** (SPEC-054's
   criterion, unchanged in mechanism and permanent in effect).
3. **Authorization reads the `owner` field, never membership** (`shared-space-common/auth.py`). Any
   spec that changes what a delete leaves in that field is changing an authorization boundary.
4. **A never-`active` space holds no user data by construction**, which is the entire justification
   for FR-002's split. A spec that lets a space serve users before it reaches `active` invalidates it.

---

## Functional Requirements

### FR-001: The delete verb empties the space

#### Description:

Same verb, same authorization, same notifications, same in-flight status. Three teardown calls stop
being made and the final registry write changes from a delete to a rewrite.

#### Acceptance Criteria:

- [ ] `delete_space` no longer calls `teardown.delete_shared_prefix` or `teardown.drop_database`. A
      test asserts both are absent from the call sequence for an `active` space, driven against the
      real verb rather than by reading the source.
- [ ] `teardown.revoke_portal_role` is **also not called**, and the reason is stated: the grant is to
      the shared portal role, isolation is the principal tag, and with no member holding
      `shared_space_k = {space}` the grant reaches nobody. Revoking it would leave the surviving
      database unreachable even to an operator-revived space, for no benefit. *This is the one
      teardown helper that survives the change unused rather than uncalled — SPEC-204 FR-008 step 3
      revokes these grants wholesale later.*
- [ ] The per-member loop is **unchanged**: `membership.clear_slot` and `cache.remove_entry` for
      every member. `members` already includes the owner (`reserve` writes `members: [actor]`), so
      "removes everyone including the owner" needs no new code — asserted, because it looks like it
      would.
- [ ] `reg.delete(space)` is replaced by a rewrite committing `members: []`, `owner` cleared (FR-003)
      and `status: "active"`, under the registry's existing CAS discipline.
- [ ] The end state is asserted directly: after a delete, `load(space)` returns a record, its
      `members` is empty, its `owner` is absent, and its `status` is `active`.
- [ ] The objects under `{space}/` and the Glue database are asserted **present** after the delete.
      A test that only checks the registry passes over the whole point of the spec.

### FR-002: The retention rule keys on whether the space was ever `active`

#### Description:

Retaining everything would hoard rubbish. A create that failed halfway leaves a partial prefix and
possibly a Glue database, has never had a member other than its would-be owner, and by construction
holds **no user data** — nobody could reach it to put any there. Keeping that forever, and locking
its name forever, would be a cost with no recoverable value behind it.

The seam already exists in the code: `shared-space-forget`'s owner path fires only when
`status != "active"`, and `delete` operates on live spaces.

#### Acceptance Criteria:

- [ ] **A space that reached `active` is emptied, never destroyed** (FR-001).
- [ ] **A space that never reached `active` is destroyed as today.** `shared-space-forget`'s owner
      path keeps `delete_shared_prefix`, `revoke_portal_role`, `drop_database` and `reg.delete`
      unchanged, and keeps SPEC-151's `TeardownIncompleteError` protocol — on that route a partial
      teardown can still free a name with resources under it, so the rule that guards it is still
      load-bearing.
- [ ] The rule is expressed **once**, as a predicate on the record, and both verbs call it. A test
      asserts the two routes agree — a `failed` space is destroyed by whichever verb reaches it, an
      `active` space is emptied by whichever verb reaches it.
- [ ] `reserve`'s failed-retry overwrite (`_resolve_reserve_collision`) is **unaffected and still
      needed**: a failed create's record is deleted by forget, and where it is not, the same owner
      may still re-reserve. A test asserts a failed create's name is reclaimable and an emptied
      space's is not.
- [ ] The justification is recorded in `decisions.md`: a never-`active` space cannot contain user
      data, so destroying it preserves nothing and freeing its name costs nothing.

### FR-003: The `owner` field is cleared, and the record is inert

#### Description:

The load-bearing detail, and the one most likely to be implemented wrong because it looks cosmetic.

`shared-space-common/auth.py`'s `authorize` gates every owner-only action on
`actor != registry.get("owner")` — it reads the **field**, never the roster. An `owner` retained
through a delete therefore leaves the original owner able to call `add-members` on the emptied space
and revive it, in one call, with the previous cohort's files intact and no confirmation anywhere.
That is not the behaviour a user asking to delete a workspace expects to be possible.

#### Acceptance Criteria:

- [ ] The rewrite in FR-001 clears `owner`. With it cleared and `members` empty, `authorize` refuses
      every owner-only action (`actor != None`) and every member-only action (empty roster).
- [ ] **The inert-state test is driven as the ORIGINAL OWNER**, and the AC says why: `add-members`,
      `remove-members`, `leave`, `acknowledge-membership` and `delete` each raise
      `AuthorizationError`. Driving it as a stranger passes over the defect, because the field
      `authorize` reads is `owner` and the original owner is the only actor who could have survived
      the change.
- [ ] The previous owner is preserved as **`previousOwner`**, a field no authorization path reads. An
      operator restoring a space needs to know whose it was; `authorize` must not be able to see it.
      A test asserts `authorize` refuses an actor equal to `previousOwner`.
- [ ] `save_members` and `set_status` **preserve unknown fields** on rewrite, so `previousOwner`
      survives later registry writes. Asserted, because both build their output from the record and a
      naive projection would drop it.

### FR-004: The name is permanently taken, and that is not a new disclosure

#### Description:

The registry record is the name lock (SPEC-054's criterion) and this route never releases it. So a
name any space once used can never be claimed again — by its former owner or anyone else.

#### Acceptance Criteria:

- [ ] Creating a space whose name matches an emptied record is **refused**, through `reserve`'s
      existing taken-name path, with the existing wording. No new message and no new code path.
- [ ] **The refusal reveals nothing new**, and the AC states the argument rather than assuming it:
      the namespace is already global and already probeable — a user can already learn that a name is
      taken by a space they are not a member of and cannot see. An emptied space is one more record
      in a set the caller could already not distinguish, so SPEC-113's no-existence-oracle rule is
      not weakened. *If a future spec makes space names non-probeable, this AC is what it must
      revisit.*
- [ ] The permanence is documented in Help (FR-006), because "that name is taken" for a workspace
      nobody can see is otherwise inexplicable to the user who hits it.

### FR-005: `active` with zero members is legitimate, and status readers are audited

#### Description:

The end state is a record whose `status` says `active` and whose roster is empty. Anything that
treats `active` as "this space is in use" is now wrong. The transition is `active → deleting →
active`, which reads oddly and is correct under Premise 1: status describes the resources, and
reachability is membership.

#### Acceptance Criteria:

- [ ] Every reader of `status` in `lambdas/` is enumerated and dispositioned in the spec's delivery
      doc — the four planes' `is_active_member` callers, `reserve`'s collision resolution,
      `forget`'s branch predicate, and the verbs' own guards.
- [ ] `cpcommon.registry.is_active_member` is **unchanged**: it already requires `status == "active"`
      **and** the user in `members`, so it returns false for everyone on an emptied space. Asserted
      rather than assumed, because the whole audit turns on it.
- [ ] A test asserts an emptied-but-`active` space is refused to every actor by all four planes that
      authorize on membership (table-share, table-builder, file-send, archive).
- [ ] No new status value is introduced. The alternative — a terminal status — was considered and
      declined: it would need every reader above to learn a new value, where the empty roster already
      makes every membership check answer correctly.

### FR-006: What the user is told

#### Description:

The user-facing verb stays "delete", because from every user's point of view the space is gone. What
must not happen is the product claiming the data was destroyed.

#### Acceptance Criteria:

- [ ] Notification wording is **unchanged** — `You deleted the shared workspace "X".` to the actor,
      `The shared workspace "X" was deleted.` to every other member. The space is gone from their
      view; a message about retention would describe something only an administrator can act on.
- [ ] **No copy anywhere claims the data is destroyed.** A sweep over `helpContent.ts` and the
      dialog copy fails on "permanently", "cannot be undone", "destroyed" or "erased" in the
      shared-space delete flow. This is the one place the change could make an existing sentence
      false.
- [ ] Help (SPEC-074) gains two sentences in the shared-workspaces guide: a deleted workspace is
      removed from everyone and its contents are retained by administrators, and its **name cannot be
      reused**. Documented because both are user-visible and neither is guessable.
- [ ] The delete confirmation dialog is reviewed against the same rule and updated if it claims
      destruction. If it does not, the spec says so rather than leaving the reader to check.

### FR-007: A partial empty

#### Description:

The verb's failure path already exists and mostly still applies. What changes is that a failure now
leaves a space that is partly emptied rather than partly destroyed — which is a much better place to
fail, and still needs saying.

#### Acceptance Criteria:

- [ ] A failure during the per-member loop records `status: "failed"` on the record and notifies the
      owner, exactly as today. The owner keeps their `owner` field on this path — a failed delete must
      leave the space operable so it can be retried.
- [ ] **The rewrite is the last step**, after every slot and cache entry is cleared, so a failure
      cannot leave a record with no owner and members still holding slots — which would be inert and
      unretryable, the one genuinely unrecoverable state this verb can produce.
- [ ] A test drives a `clear_slot` failure mid-loop and asserts the record still names its owner,
      its status is `failed`, and a retry of the delete succeeds.
- [ ] `TeardownIncompleteError` is **not** raised on this route (nothing is torn down) and **is**
      retained on FR-002's route.

### FR-008: What accumulates, and what does nothing about it

#### Acceptance Criteria:

- [ ] The spec states the three things that now grow without bound: S3 objects under emptied
      prefixes, Glue databases with no members, and registry records. None is managed by this spec.
- [ ] **The registry listing grows with historical spaces, not live ones**, and the consequence is
      named for its one consumer: SPEC-204's sweep iterates every registry record, so its cost and
      its `identitystore`/Lake Formation call budget are sized against *all* spaces ever created. Its
      FR-009 budget arithmetic takes this as an input.
- [ ] Retained objects keep costing money, and that is accepted rather than unnoticed. If it ever
      needs managing it is an S3 lifecycle rule on the shared-space bucket — named here so it is not
      built as application logic.

### FR-009: Observability

#### Acceptance Criteria:

- [ ] The existing `space deleted` record gains the member count removed and a field distinguishing
      **emptied** from **destroyed** (FR-002's two routes), so the split is visible in `logs/` rather
      than inferred from which verb ran.
- [ ] Space names and usernames are permitted user metadata; nothing else is added.
- [ ] `env` and `version` on every record; messages are literals; `echo=` prohibited.

### FR-010: What does not change

#### Acceptance Criteria:

- [ ] Authorization is untouched — `delete` stays owner-only, `leave` still refuses the owner.
- [ ] The verb's queue, its FIFO keys, its state machine position and its notification dedup ids are
      unchanged.
- [ ] No IAM policy, bucket policy or Lake Formation grant is edited. The plane keeps its
      `s3:DeleteObject` and `glue:DeleteDatabase` grants because FR-002's route still uses them.
- [ ] No browser change beyond FR-006's copy. The space disappears from every list exactly as today,
      through the same cache removal.
- [ ] **No migration or backfill.** Spaces deleted before this ships were destroyed; there is nothing
      to retain retroactively and nothing to reconcile.

---

## Data Model

The registry record gains one field and loses one on delete:

```
s3://{admin-bucket}/shared-spaces/{name}.json
  active, in use:  { version, name, owner, members: [...], status: "active", createdAt, lastRequestId }
  emptied:         { version, name,        members: [],    status: "active", createdAt, lastRequestId,
                     previousOwner, emptiedAt }
```

`previousOwner` is read by no authorization path (FR-003). `emptiedAt` is for the operator.

## Implementation Phases

### Phase 1: The retention predicate and the verb

FR-001, FR-002 and FR-007 — the predicate expressed once, the two routes calling it, the rewrite
replacing the delete, and the failure-path ordering.

### Phase 2: The inert record

FR-003 and FR-005, with the inert-state test driven as the original owner and the four-plane refusal
test, plus the status-reader audit.

### Phase 3: The name lock and the copy

FR-004, FR-006's copy sweep and the Help content.

### Phase 4: Observability and verification

FR-008's statement, FR-009's fields, then the formatter, `ruff`, the blocking `mypy`,
`pytest lambdas/`, the portal suite and `npm run build`.

### Phase 5: Live checks

Against a deployed environment: create a space with two members and files, delete it, and confirm —
the space is gone from both members' lists, the objects and the Glue database are still present, the
name is refused on re-create, and the original owner cannot add a member to it. Then a failed create
forgotten by its owner, confirming its name **is** reclaimable. These go into
`docs/testing/e2e.md`'s shared-workspaces section.

### Phase 6: Completion ritual

Per `CLAUDE.md`. Two `decisions.md` entries: the retention rule and its never-`active` seam, and the
cleared `owner` field with the `authorize` reasoning behind it. `transition_plan.md` §6.3's three
destructive-path rows are struck for the `delete` route and kept for `forget`'s.
