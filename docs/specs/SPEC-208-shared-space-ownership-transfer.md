# Spec: Shared-Space Ownership Transfer

**ID:** SPEC-208
**Status:** Completed
**Last Updated:** 2026-09-01
**Depends On:** SPEC-051/053 (the shared-space control plane, `create` and member management), SPEC-062 (single-task verb Lambdas), SPEC-073 (join status is display-only; access is granted at add time), SPEC-075 (the roster fan-out), SPEC-082 (registry CAS), SPEC-125 (`shared-space-common`), SPEC-152 (a pre-verb failure notifies), SPEC-206 (the `SenderId` role-id boundary — the mechanism the operator path reuses), SPEC-106 (`toUserMessage`), SPEC-155 (`ConfirmDialog`), SPEC-074 (Help content)

**Interacts with:** SPEC-205 empties a space rather than destroying it. Transfer is the other exit —
the one that keeps the space alive with someone else holding it — so a space no longer has to be
emptied just because its owner is leaving.

## Overview

A shared space's owner is whoever created it, forever. There is no way to hand one on: not when a
project changes hands, not when the owner leaves the organisation, not when the wrong person clicked
Create. The only exits are to abandon the space or to delete it, and both are worse than the problem.

This spec adds a transfer. The current owner picks an existing member and hands them the space; the
former owner stays on as an ordinary member. Everything else about the space is untouched — the same
prefix, the same Glue database, the same roster, the same data.

It also adds the path for the case the UI cannot serve: an owner who has already left. A scheduled
reader picks up a CSV of transfers from the admin bucket and puts each row on **the same queue** the
UI writes to, so an operator-driven transfer and a user-driven one are the same verb doing the same
work. That reuse is the point, and it forces the one genuinely new fence in this spec: the verb
derives its trusted actor from a verified ID token, and an operator has no token to offer.

## Scope

### In Scope

- A `transfer_ownership` action on the existing shared-space queue and state machine.
- Registry semantics: the `owner` field is rewritten under ETag compare-and-swap, and the
  `acknowledged` list is corrected to match the new roles; membership, status, `createdAt` and every
  other field are preserved.
- The roster fan-out, so every member's cached `role` and `owner` are correct afterwards.
- Notifications to the outgoing and incoming owner.
- The browser surface: a "Transfer ownership" action in the owner's Manage members drawer, and its
  confirm dialog.
- `shared-space-transfer-reader`: a scheduled Lambda that reads a CSV from the admin bucket and
  enqueues one request per row.
- The operator-origin boundary: a message with no ID token is accepted only when its SQS `SenderId`
  matches the reader's role.
- Help content for the new capability.

**On Arc B:** FR-006 adds a new *action* to `sharedSpaces.service.ts`'s existing enqueue path, not a
new browser→AWS call site. SPEC-200 ports that path once and this action goes with it; nothing here
adds a sixteenth direct call for it to find.

### Out of Scope

- **Co-ownership.** `owner` stays a single string. Several people holding a space at once changes
  the field's *type* and every read of it — `reserve`'s failed-reservation replay, the roster's
  owner exclusion, `forget_space`'s owner branch, the browser's `role` derivation. That is its own
  spec, and this one deliberately does not prepare for it.
- **An in-app admin surface.** No admin group, no admin role, no admin route. The operator path is
  a file in a bucket and a scheduled reader, and CLAUDE.md's *no admin UI* fence is unmoved.
- **Transferring to someone who is not already a member.** The owner adds them first. Making
  transfer double as an invitation would let one action grant access to a stranger.
- **Renaming a space, or moving its data.** The name is the prefix and the database, and it does
  not change.
- **Reversing a transfer.** The new owner can transfer it back. There is no undo, and the dialog
  says so.
- **A notification to the rest of the roster.** Only the two people whose role changes are told.

---

## Functional Requirements

### FR-001: The `transfer_ownership` verb

#### Description:

A new single-task Lambda, `shared-space-transfer-ownership`, reached by a new `Choice` branch on the
existing orchestrator. It rewrites the registry record's `owner` to the named member under ETag
compare-and-swap on a freshly read record, in the manner `set_status` already uses.

#### Acceptance Criteria:

- [ ] After a successful transfer the registry record's `owner` is the new owner's username.
- [ ] `members`, `status`, `createdAt`, `version` and `name` are byte-identical to their pre-transfer
      values; a test compares the whole record minus `owner`, `acknowledged`, `lastRequestId` and
      `updatedAt`. The last two are excluded because `set_status` and `save_members` both stamp
      `updatedAt`, and a `set_owner` written in their manner does too — a criterion forbidding it
      would be unsatisfiable by the implementation it prescribes. `acknowledged` is excluded because
      FR-003 requires it to change.
- [ ] `lastRequestId` is the transferring request's id.
- [ ] `set_owner` takes the **expected current owner** and re-checks it inside the CAS body, refusing
      if it no longer holds. `set_status` may retry unconditionally because a status is not
      authorization-carrying; a transfer is. Without it: alice's request is authorized while she owns
      the space, a concurrent transfer moves it to carol, alice's write retries against the fresh
      record and **takes it away from carol** — a lost authorization wearing the shape of a correct
      CAS retry.
- [ ] A concurrent write that does not change the owner causes a retry against the fresh record, not
      a lost update; a test drives a precondition failure and asserts the second attempt carries the
      newly read ETag.
- [ ] A concurrent write that **does** change the owner causes the retry to refuse, and a test drives
      exactly the alice/carol interleaving above.
- [ ] The verb makes no S3 object copy, no Glue call and no Lake Formation call — a test asserts the
      client fakes recorded none.

### FR-002: Who may transfer, and to whom

#### Description:

The authorization runs in `shared-space-validate`, from the verified actor, never the body.

#### Acceptance Criteria:

- [ ] A request whose verified actor is not the record's current `owner` is refused with an
      authorization error naming the reason code, and the record is unchanged.
- [ ] A request naming a target who is not in `members` is refused, and the refusal names the target.
- [ ] A request naming the current owner as the target is refused as a no-op rather than silently
      succeeding, so the notification pair is never sent for a transfer that did not happen.
- [ ] A target who is a member with join status `pending` **is accepted**. Pending records the fact
      that they have not signed in since being added, not their entitlement — access was granted at
      add time — and refusing would make a space untransferable for a reason the owner cannot fix.
- [ ] A request against a space whose `status` is not `active` is refused; a space mid-provision or
      mid-delete does not change hands.
- [ ] An **emptied** space — SPEC-205 leaves one `active` with an empty roster — is refused with a
      refusal saying the space has been deleted, not "that person is not a member". Both are correct
      outcomes; only one is a true sentence, and the empty-roster case is distinguishable before the
      membership check runs.
- [ ] Every refusal above is a **return value**, not a raised `TerminalError`, so the notification
      can name the space and the target.

### FR-003: The outgoing owner becomes a member

#### Description:

Transfer changes who the owner is, and the bookkeeping that is derived from it. The former owner
keeps their membership; what has to move with the role is spelled out below rather than assumed,
because the obvious "change one field" implementation ships a visible defect.

#### Acceptance Criteria:

- [ ] After a transfer the former owner is still in `members`.
- [ ] The former owner's cached entry has `role: 'member'` and `owner: <new owner>`.
- [ ] The new owner's cached entry has `role: 'owner'`.
- [ ] The former owner's own AWS access is unchanged by the transfer; a test asserts no membership
      slot or tag was written or cleared.
- [ ] **The former owner is added to the registry's `acknowledged` list**, and the incoming owner is
      removed from it. This is the one place "transfer changes exactly one thing" is false, and it is
      not optional: `effective_acknowledged` excludes the owner on the stated grounds that "the owner
      is always active and is never listed here", and the cache's roster projection is
      `"active" if (m == owner or m in ack) else "pending"`. So on any space where an explicit
      `acknowledged` list exists — every space `add_members` has ever run on — a transfer touching
      only `owner` would leave the outgoing owner in `members`, absent from `acknowledged`, and
      rendering as **pending** in every member's roster: someone who has used the space for months
      shown as not having picked it up yet.
- [ ] A test drives a space that has had `add_members` run, transfers it, and asserts both parties
      render `active` in the roster afterwards.
- [ ] A test drives a space with **no** `acknowledged` field — created before the field existed and
      never added to — and asserts the transfer still leaves both parties `active`, preserving the
      legacy path where absence means everyone is acknowledged.
- [ ] Transferring to a `pending` member and back leaves them reading `active` although they have
      never signed in, because the round trip put them in `acknowledged` and nothing takes them out.
      Accepted, and named rather than discovered: the alternative is remembering a pre-transfer join
      status, which is state kept solely to re-create a chip. A test pins today's outcome so it is a
      decision and not a drift.
- [ ] Leaving is still a separate action — a test asserts the transfer verb never enqueues or
      performs a `leave`.

### FR-004: The roster fan-out runs

#### Description:

Every member's `{username}/user_settings/shared-connections.json` carries `owner` and a derived
`role`, so every member's cache is stale the moment the registry changes.

#### Acceptance Criteria:

- [ ] After a transfer, every member's cache entry for the space names the new owner.
- [ ] A member whose cache document is absent is created rather than skipped, matching the existing
      fan-out's behaviour.
- [ ] A fan-out failure for one member does not abort the others, and the failure is logged with the
      member named.
- [ ] The registry write happens **before** the fan-out; a test asserts the ordering, because a
      fan-out that lands first would publish an owner the registry does not agree with.

### FR-005: Both parties are notified

#### Description:

One producer, at the end of the machine, says the outcome — never each verb.

#### Acceptance Criteria:

- [ ] On success the outgoing owner receives a notification naming the space and the new owner.
- [ ] On success the incoming owner receives a notification naming the space and the outgoing owner.
- [ ] No other member receives a notification.
- [ ] A pre-verb failure (a refusal in FR-002, or a validate fault) notifies the requester through
      the plane's existing `NotifyFailure`-before-`Fail` path, and a test walks the ASL to assert
      every arm of the new branch reaches it.
- [ ] Every notification's wording is a literal in the domain layer's `messages` module, not built
      at the raise site.

### FR-006: The browser surface

#### Description:

The owner's Manage members drawer gains a transfer action per member row, behind a confirm dialog.

#### Acceptance Criteria:

- [ ] A member row in `ManageMembersDrawer` renders a control named `Make owner: <username>`
      for the owner, and for nobody else — a member viewing the read-only roster sees none.
- [ ] The control opens a `ConfirmDialog` naming the space and the new owner, and stating that the
      user will become an ordinary member and cannot undo this themselves.
- [ ] Confirming enqueues one request with `action: 'transfer_ownership'` and the target in the
      payload; a test asserts exactly one message and its shape.
- [ ] Cancelling enqueues nothing and returns focus to the control that opened the dialog.
- [ ] While the request is in flight the control is disabled and the space's row shows the existing
      in-progress treatment; the drawer does not optimistically flip the roles.
- [ ] A failure renders wording from `lib/errorMessages.ts`; no AWS or service text reaches the
      screen.
- [ ] `expectNoA11yViolations` runs against the driven container with the dialog open.

### FR-007: The scheduled CSV reader

#### Description:

`shared-space-transfer-reader` runs on an EventBridge `rate()` schedule. It lists
`<admin-bucket>/ownership-transfers/inbox/`, and for each CSV object enqueues one shared-space
request per data row, then moves the object aside.

#### Acceptance Criteria:

- [ ] The CSV's header row is exactly `space,new_owner` — any other header set rejects the whole
      file without enqueuing any of its rows.
- [ ] Each valid row enqueues exactly one message onto the existing shared-space FIFO queue.
- [ ] On success the object is copied to `ownership-transfers/processed/<invocation-timestamp>/<key>`
      and deleted from the inbox, so a later tick cannot re-enqueue it.
- [ ] A file that fails to parse is copied to `ownership-transfers/rejected/<invocation-timestamp>/`
      with a sibling `<key>.reason.txt` naming the failure, and deleted from the inbox.
- [ ] An **empty or absent** inbox is a successful no-op that enqueues nothing — the first firing of
      a newly created `rate()` rule must not fail.
- [ ] The copy is confirmed before the delete; a delete that runs first and a failed copy would lose
      the operator's file. A test asserts the ordering.
- [ ] Objects are processed in listing order and the function stops cleanly at a computed cap on
      rows per invocation, derived in the test from the queue's send rate and the function timeout,
      naming the budget it was derived from. If the cap is reached the function **logs how many rows
      it did not process** and leaves the file in the inbox for the next tick.

      > **Corrected at build time.** "Leaves it for the next tick" is right for a file bigger than
      > what is LEFT of an invocation's budget, and wrong for one bigger than the WHOLE cap: no
      > tick could ever take that file, so deferring it leaves it in a prefix with no expiry rule
      > forever, behind a log line nobody is alerted on. It is **rejected** instead, with a reason
      > naming the cap, because splitting the file is the fix and only the operator can do it. The
      > sweep also **stops** at a deferral rather than skipping it — carrying on lets a smaller
      > later file overtake an earlier one, which breaks the listing order this same criterion
      > requires. Found by review, reproduced before it was changed.
- [ ] The reader never reads or writes the registry directly; a test asserts its only S3 calls are
      against the `ownership-transfers/` prefix.
- [ ] `ownership-transfers/` gains its **own** admin-bucket lifecycle rule expiring
      `ownership-transfers/processed/` and `ownership-transfers/rejected/` — a rule per prefix, since
      S3 lifecycle takes one prefix per rule and the prefix covering both, `ownership-transfers/`,
      would also match `inbox/`. The `inbox/` prefix gets **no** expiring rule: a file the reader has not managed to
      process must not be deleted out from under it.

### FR-008: The operator-origin boundary

#### Description:

A UI request carries a verified identity and the plane derives the actor from it. An operator has
none. So an operator message declares `origin: 'operator'` and carries **no identity**, and
`shared-space-validate` accepts it only when the SQS record's `attributes.SenderId` role-id half
matches the reader's role — the same runtime comparison SPEC-206 established, and for the same
reason: no SQS condition key reaches a message body, so nothing but the sender's identity can be
trusted.

> **Corrected at build time.** This FR was authored against a wire that carried an `idToken` in the
> message body. SPEC-201 retired it: the API verifies the bearer at the edge and stamps a nested
> `identity` block, which `cpcommon.actor` reads. Every criterion below therefore reads "identity
> block" where it said "ID token" — the SenderId half is unchanged, and it was always the half that
> mattered. Two further corrections the build made, both recorded in
> `docs/decisions/control-planes.md`: `origin` is **not** declared on the API's request type (the
> contract refuses an undeclared key, which is what stops a signed-in caller claiming operator
> origin at all), and the acting identity is recorded as `origin` on the context while `actor`
> carries the space's current owner — `operator` is a catalog-valid username and would address a
> real user's notification prefix.

#### Acceptance Criteria:

- [ ] A message with `origin: 'operator'` and a `SenderId` whose role-id half matches the configured
      reader role id is accepted, and the acting identity recorded on the execution is `operator`
      (as the context's `origin` — see the correction above).
- [ ] A message with `origin: 'operator'` sent by any other principal is **refused**, and the
      refusal is a return value that reaches `NotifyFailure` — not a silent drop, because unlike the
      notifications boundary this queue is drained and a forged request here has a named victim.
- [ ] An operator-origin message is accepted for `transfer_ownership` **only**; the same envelope
      naming any other action is refused. A test enumerates every action in `SharedSpaceAction` and
      asserts each non-transfer one is refused.
- [ ] An operator-origin transfer skips the FR-002 owner check (that is its purpose) and enforces
      every other check in FR-002 unchanged — target is a member, target is not the current owner,
      space is `active`. A test asserts each of those still refuses.
- [ ] A message carrying **both** `origin: 'operator'` and an identity block is refused rather
      than resolved to one of them.
- [ ] The reader's role id is read from configuration; a test asserts the comparison is against the
      role-**id** half of `SenderId` and not against a role name or ARN, neither of which `SenderId`
      carries.
- [ ] The notification for an operator-driven transfer still goes to both parties, and names no
      operator.

### FR-009: Help content

#### Description:

Transfer is user-visible and wired end to end, so it is documented.

#### Acceptance Criteria:

- [ ] The Shared connections section gains a guide covering transferring ownership, its
      owner-only-ness, and the fact the former owner stays a member.
- [ ] No guide documents the operator CSV path — it is not a user capability.

---

## Data Model

```ts
// apps/portal/src/features/shared-spaces/sharedSpaces.types.ts — additions

// 'transfer_ownership' joins the existing union.
export type SharedSpaceAction =
  | 'create' | 'add_members' | 'remove_members' | 'leave' | 'delete' | 'forget'
  | 'acknowledge_membership'
  | 'transfer_ownership';

/** The payload for a transfer. `newOwner` must already be in the space's roster. */
export type TransferOwnershipPayload = {
  newOwner: string;
};
```

```python
# lambdas/shared-space-common/registry.py — the new writer, beside set_status

def set_owner(registry: dict, expected_owner: str, new_owner: str, request_id: str) -> dict:
    """Rewrites a space's owner under CAS, refusing if `expected_owner` no longer holds.

    The expected owner is what separates a safe retry from a lost authorization: a retry that
    re-reads a record someone else has already transferred must refuse, not re-apply.
    """
```

```
# The operator CSV — <admin-bucket>/ownership-transfers/inbox/<anything>.csv
space,new_owner
finance_reports,bcarter
project_atlas,dmehta
```

```jsonc
// The operator message body. FLAT, like every other request envelope, and carrying
// no token at all — which is what the SenderId check is standing in for.
{
  "schemaVersion": 1,
  "requestId": "…",
  "action": "transfer_ownership",
  "origin": "operator",
  "space": "finance_reports",
  "payload": {"newOwner": "bcarter"}
}
```

## File & Folder Structure

```
lambdas/
├── shared-space-transfer-ownership/
│   ├── transfer_ownership.py
│   └── test_transfer_ownership.py
├── shared-space-transfer-reader/
│   ├── transfer_reader.py
│   └── test_transfer_reader.py
└── shared-space-common/           # set_owner + the operator-origin check + wording

infra/modules/shared-spaces/       # the verb, the reader, the schedule, the Choice branch, IAM

apps/portal/src/features/shared-spaces/
├── TransferOwnershipDialog.tsx
├── useTransferOwnership.ts
└── (ManageMembersDrawer, sharedSpaces.service.ts, sharedSpaces.types.ts amended)
```

## Implementation Phases

### Phase 1: The verb, the registry and the notifications

- `registry.set_owner` under CAS, and its tests.
- `shared-space-transfer-ownership` and the validate-side authorization (FR-002).
- The `Choice` branch, the failure seed, and the ASL walk asserting every arm notifies.
- The roster fan-out and the two notifications.
- Terraform: the function, the branch, the execution-role grants, and the deploy-role expansion in
  its own PR ahead of this one.

### Phase 2: The browser surface

- `TransferOwnershipDialog`, the per-member control, the enqueue hook.
- In-flight treatment, error wording, focus behaviour, axe.
- The Help guide.

### Phase 3: The operator path

- `shared-space-transfer-reader`, the inbox/processed/rejected lifecycle, the computed row cap.
- The operator-origin boundary in `shared-space-validate`, including the enumerated
  every-other-action refusal.
- The schedule, the reader's IAM, and the admin-bucket prefix.
