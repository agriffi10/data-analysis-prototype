# Spec: Operator-Driven Shared-Space Membership

**ID:** SPEC-217
**Status:** Draft
**Last Updated:** 2026-09-02
**Depends On:** SPEC-208 (the operator CSV door, the `SenderId` boundary, refusals as return values), SPEC-206 (the `SenderId` role-id comparison), SPEC-205 (a delete empties a space; `emptiedAt`, the cleared `owner`, and the inertness test this spec re-points), SPEC-051/053 (the shared-space plane, `add_members` and `remove_members`), SPEC-082 (registry CAS), SPEC-125 (`shared-space-common`), SPEC-152 (a pre-verb failure notifies), SPEC-201 (the API stamps the identity block the plane reads)

**Interacts with:** SPEC-203's membership index and the roster fan-out are written by the existing
verbs and are untouched — this spec changes who may ask for a membership change and how a request
arrives, never what a verb does once it has one.

## Overview

An operator can hand a shared space to a new owner by dropping a CSV in the admin bucket, and can do
nothing else. Every other membership question — the departed owner still sitting in the roster, the
contractor whose access should have ended on Friday, the ten people a re-organisation moved into a
space whose owner is on leave — has no answer but "ask the owner", and the cases that reach an
operator are precisely the ones where the owner cannot be asked.

This spec widens that door to member management: an operator's CSV may add members to a space and
remove them, as well as transfer it. The rows become ordinary requests on the plane's existing
queue, so an operator-driven add and an owner-driven add are the same verb, notifying the same
people and writing the same records. The CSV grows a column and gets a defined structure, because it
now has to say which of three things a row asks for.

Widening the door forces the fence beside it to be rebuilt. The plane's member actions are
owner-only, and they refuse by raising — a raise in the validator loses the actor and the space, so
the refusal reaches nobody. An operator request also arrives with its acting identity recorded as
the space's own owner, which means the owner-only check passes for it without being skipped. So the
two things this spec must not get wrong are that a member refusal now has to be a value a notifier
can read, and that the check standing between any signed-in user and any space's roster has to be a
predicate that is actually consulted.

## Scope

### In Scope

- One operator prefix, `operator-requests/`, replacing `ownership-transfers/`, and one CSV shape:
  `space,action,username`.
- `add_members` and `remove_members` joining `transfer_ownership` in `OPERATOR_ACTIONS`, and every
  other action staying refused on that origin.
- `auth.member_refusal`: one pure predicate deciding a member change for **both** origins, returning
  a `(code, message)` pair, routed to the plane's existing `RefusedSeed` branch.
- `add_members` and `remove_members` leaving `OWNER_ONLY_ACTIONS`, with the owner check moving into
  that predicate rather than being lost — and SPEC-205's emptied-record inertness test re-pointed at
  the predicate for those two actions, still driven as the original owner.
- An explicit refusal for removing a space's current owner, which today is silently dropped.
- The reader coalescing a file's rows into one request per `(space, action)`, the two caps that
  bounds, and the per-row syntactic checks.
- The admin bucket's lifecycle rules and the reader's IAM, re-pointed at the new prefix.

**The threat model widens, and that is the decision being taken.** Under SPEC-208 the operator door
could only move ownership *between people who were already members*: it granted access to nobody. A
row now grants a stranger live S3, Glue and Lake Formation access to a space's data, and the fences
are the admin-bucket prefix's write IAM and the `SenderId` comparison — the same two, now guarding
more. `shared-space-common/config.py`'s own docstring asks that widening `OPERATOR_ACTIONS` "be a
decision rather than an oversight"; this spec is that decision, and it is recorded in the register
rather than only here.

### Out of Scope

- **`create`, `delete`, `leave`, `forget` and `acknowledge_membership` from a CSV.** The first two
  are the destructive pair, and an operator holding them turns this door into the admin surface
  CLAUDE.md forbids; the last three are self-scoped acts, and an operator performing one impersonates
  a user rather than administering a space. All five stay refused, and a test enumerates them.
- **An in-app admin surface.** Unmoved from SPEC-208: no admin group, no admin role, no admin route.
- **Sequencing between requests.** The Pipe is `FIRE_AND_FORGET` with `batch_size = 1`, so requests
  are *delivered* in order and their executions overlap. A change that depends on an earlier one
  having landed — transfer a space, then remove its former owner — is two files, the second uploaded
  after the first has been processed. FR-001 refuses the shape that hides this rather than
  pretending a file can express it, and every refusal it causes is a named one.
- **An operator outcome ledger.** The reader can say what it enqueued and cannot say what happened —
  the outcome is decided later, by the one producer at the end of the machine. A receipt written at
  enqueue time would be read as an outcome and would be wrong exactly when it mattered. The
  operator's channel stays the reader's structured log, and the residual stays recorded.
- **Renaming `shared-space-transfer-reader`, its role, or `TRANSFER_READER_ROLE_ID`.** The name will
  under-describe what the function reads, and that is the cheaper defect: the role's unique id is
  half of the `SenderId` comparison, so renaming it rotates the value the boundary compares against,
  and any operator file consumed in that window is moved to `processed/` with every one of its rows
  refused. A misleading name is paid for in a docstring; a rotated role id is paid for in lost work.
- **Any change to the browser's member management**, or to what the verbs do once a request reaches
  them. Slots, grants, the roster fan-out, the membership index and the notifications are unchanged.
- **A backfill of files left under `ownership-transfers/`.** The cutover confirms that prefix empty
  rather than teaching the reader to drain a prefix it is retiring.

---

## Functional Requirements

### FR-001: The operator CSV

#### Description:

One prefix, `<admin-bucket>/operator-requests/inbox/`, holding CSVs whose header is exactly
`space,action,username`. One data row names one member. `<admin-bucket>/ownership-transfers/` is
retired.

#### Acceptance Criteria:

- [ ] The header row is exactly `["space", "action", "username"]`, compared as an **ordered list**
      and not as a set, preserving SPEC-208's reason: a file whose columns are the right names in the
      wrong order parses perfectly and acts on every row against the wrong argument.
- [ ] A file whose header is the retired `space,new_owner` is rejected with a reason that names the
      accepted header, rather than the generic wrong-header sentence. An operator who wrote
      yesterday's file gets told what changed.
- [ ] `action` must be one of `transfer_ownership`, `add_members`, `remove_members`, held as a
      **local constant** in the reader — it has no domain layer and importing one for a frozenset
      would buy a cold-start crash — and a test asserts that constant **equals**
      `shared-space-common`'s `config.OPERATOR_ACTIONS`, in the manner `SCHEMA_VERSION` and
      `MESSAGE_GROUP_ID` are already cross-checked. Equality, not containment: a subset assertion
      passes while the reader silently refuses an action the plane admits.
- [ ] A row naming any other action rejects the **whole file**, with a reason naming the line number
      and the accepted actions. Partial enqueueing is not an option this reader has: SPEC-208's rows
      are enqueued neither wholly nor partly, and mixing actions does not change that.
- [ ] **A file naming one space under more than one action is rejected**, naming the space and both
      lines. Two actions on one space in one file read as a sequence and are not one: their
      executions overlap, so `transfer_ownership` then `remove_members` on the same space can be
      validated in either order, and the losing order refuses with FR-004's brand-new "transfer the
      space first" — advice the previous line already took. The refusal is at the reader because it
      is the only place that can see the pair.
- [ ] Two rows carrying the same `(space, action, username)` triple reject the whole file, naming
      both lines. Duplicates within one coalesced request are a no-op at best and a mistake at worst,
      and the file has no way to mean anything by them.
- [ ] `space` and `username` are each held to `cpcommon.config.CATALOG_IDENTIFIER_RE`, and a row
      failing either rejects the whole file naming the line and the field. This is a syntactic check,
      not a domain one — the reader still asks no question about whether the space or the member
      exists. It earns its place because the two verbs disagree about case: `normalize_members`
      lowercases, so `Alice` in an add row silently becomes `alice`, while `transfer_refusal` compares
      the target verbatim, so `Alice` in a transfer row refuses as "not a member". One spelling, two
      behaviours, neither visible to the operator; refusing at the reader makes it one. **It makes
      the door stricter than the plane** — a space name is format-checked nowhere server-side, so a
      space whose name does not satisfy the rule is unreachable by CSV. Accepted deliberately: such a
      space cannot be created through the product, and a reader that tolerated the name would be the
      only component in the fleet that did.
- [ ] A row with a field count other than three, or any blank field, rejects the whole file naming
      the line. Wholly blank lines are skipped.
- [ ] An empty or absent inbox is a successful no-op, as it is today — a newly created schedule fires
      against an inbox nobody has written to.
- [ ] The existing BOM strip is kept and pinned by a test rather than re-derived: Excel writes one by
      default and it is invisible in the operator's own editor. This criterion is a regression pin on
      shipped behaviour, not new work.
- [ ] A test drives one valid file covering all three actions across **different** spaces and asserts
      what comes off the queue.

### FR-002: What the reader enqueues

#### Description:

A file's rows are coalesced into **one message per `(space, action)`**, carrying the declared
operator origin and no identity block, in the envelope SPEC-208 established.

#### Acceptance Criteria:

- [ ] Rows sharing a `(space, action)` become one message whose payload carries every one of their
      usernames, in file order. One row per member and one message per member is the mapping this
      criterion exists to forbid: the Pipe is `batch_size = 1` and `FIRE_AND_FORGET`, so N messages
      for one space are N overlapping executions, each a compare-and-swap against a single registry
      object whose `cpcommon.cas.MAX_ATTEMPTS` is 6 and whose docstring rests on contention being
      rare — and each dragging a full `write_roster_to_all`, so N single-member adds to one space
      cost O(N²) cache writes. The verbs already take a list, and one message is one CAS and one
      fan-out.
- [ ] `transfer_ownership` enqueues `payload: {"newOwner": <username>}`; `add_members` and
      `remove_members` each enqueue `payload: {"members": [...]}`. A test asserts each shape against
      the key the corresponding verb actually reads, rather than against a literal repeated in the
      test.
- [ ] A file naming one space under `transfer_ownership` more than once is already refused by
      FR-001's duplicate rule only when the target repeats. A second transfer row for the same space
      naming a *different* target is refused too, by the same one-action-one-space reasoning: two
      transfers of one space in one file are a race whichever way they are read.
- [ ] Every message carries `origin: "operator"`, no `identity` key, the queue's single message group
      and the schema version the validator accepts.
- [ ] The request id is derived from the object key and the `(space, action)` pair, so a crashed tick
      that had already sent some messages re-sends the same ids. **Replay safety rests on the verbs'
      idempotency, not on deduplication**, and the spec says so rather than repeating SPEC-208's
      claim: the schedule is `rate(1 hour)` and the FIFO deduplication window is five minutes, so no
      two sweeps ever fall inside one window. A re-add of a current member is skipped, a re-removal
      of an absent member is skipped, and a re-transfer to the current owner is refused as a no-op.
- [ ] The residual that idempotency does **not** cover is named: a replayed `remove_members` an hour
      later removes a member who was legitimately re-added in between. It is recorded, not solved —
      the fix is a request ledger the plane does not have.
- [ ] Files are processed in listing order, and the sweep still **stops** at a file it has no budget
      for rather than skipping past it.
- [ ] **Two caps, each computed by a test against the budget that sized it, and each naming that
      budget.** The first is rows per invocation, the reader's existing derivation from its own
      timeout, send fraction and one `SendMessage` round trip — unchanged in shape, re-derived
      because coalescing changes what a row costs to send. The second is **members per message**,
      derived from the `add_members` verb's own timeout (60 s, from the Terraform map, read the way
      the existing cap reads the reader's) and a per-member cost covering its Cognito lookup, slot
      assignment, cache write and index write. Without the second, coalescing hands one message a
      list longer than the verb it feeds can process, and the failure is a timeout — a top-level
      execution failure that catchers do not cover. A file needing more than that many members for
      one `(space, action)` is **rejected** with a reason naming the cap, on SPEC-208's reasoning
      that only the operator can split it.
- [ ] The structured log names the action and the space on every enqueued message and says which
      lines went into it, so the operator's only feedback channel distinguishes an add from a
      removal. The reader's existing event messages, which say "ownership-transfer", are re-worded.

### FR-003: One member-refusal predicate, for both origins

#### Description:

`auth.member_refusal(requester, space, action, targets, registry)` decides an `add_members` or
`remove_members` request and returns a `(code, message)` pair or `None`, in the manner of
`transfer_refusal`. `add_members` and `remove_members` leave `OWNER_ONLY_ACTIONS`, and `authorize`
gains an explicit `return` branch for each, as `transfer_ownership` already has.

**This is the dangerous requirement in this spec.** The owner-only branch in `authorize` is today the
only thing stopping any signed-in user adding themselves to any space. Moving that check into a
predicate that is not wired, or is wired after the fall-through, is a complete authorization bypass
that no existing test would catch — the browser only ever sends an owner's request.

#### Acceptance Criteria:

- [ ] A **UI** `add_members` request whose verified actor is not the space's owner is refused, and the
      test asserts the **reason code by name**, not merely that the request did not succeed.
- [ ] The same for `remove_members`.
- [ ] Both refusals reach the requester as a notification through the plane's existing `RefusedSeed`
      arm, which they do not today: `authorize` raises, the validator's `Catch` carries no
      `ResultPath`, `ValidateFailureSeed` seeds a null actor, and `shared-space-notify-failure`
      returns without notifying on a falsy actor. This is a behaviour change on the UI path and is
      deliberate — a member change that refuses is currently a request the user watches disappear.
- [ ] **`test_the_emptied_record_is_inert_to_its_ORIGINAL_OWNER` is re-pointed, not trimmed.** That
      SPEC-205 test loops five actions asserting `authorize` raises on an emptied record; two of them
      are the actions this FR moves, so it reddens on a correct change and the cheapest repair is to
      delete those two names — losing the detection while production behaviour rests on FR-004 being
      wired. The two actions must instead be asserted through `member_refusal`, **still driven as the
      original owner**, which is SPEC-205's own trap: `authorize` read the `owner` field, so the
      original owner is the only actor who could have survived the clearing. This supersedes the
      mechanism half of the register's *emptied record is inert* entry, and the entry is amended in
      place rather than left to disagree.
- [ ] `delete` **stays** in `OWNER_ONLY_ACTIONS`, and a test asserts the set's exact contents, so
      removing the last member of it cannot pass as tidying.
- [ ] **The predicate takes `requester`, never the context's `actor`, and `requester is None` is what
      skips the owner check for an operator.** Written against `actor` the operator case would pass
      anyway — the validator records an operator request's `actor` as the space's own current owner,
      so it compares equal — and the skip could then be deleted with every test still green. This is
      the trap `transfer_refusal` already documents, one action over.
- [ ] `targets` is a **list**, because that is what the wire carries: the contract declares
      `members: list[str]` and the browser sends an array. Request-level conditions refuse the whole
      request; the one per-name condition, FR-004's removal naming the owner, also refuses the whole
      request rather than dropping that name, so the operator is told rather than partly served.
- [ ] Removing the owner check from `member_refusal` reddens the named tests and nothing unrelated;
      the mutation is planted, run and reverted, and the delivery doc says which tests caught it. The
      guard's failure would otherwise be silent, which is the class this project mutation-tests.
- [ ] `member_refusal` is pure: no AWS calls, and a test asserts the client fakes recorded none.
- [ ] The predicate is the **only** authority on these two actions. A test asserts `authorize` no
      longer decides them — an owner check written in both places is the complement that drifts.
- [ ] **Every code the predicate can return has an entry in the message table**, asserted as set
      equality between the codes in `auth` and the keys of the table in `messages`. Today an
      unregistered code degrades to `'We couldn't transfer the shared workspace "{space}".'` — so a
      member refusal shipped without wording tells the user their *transfer* failed, silently. The
      table is either renamed away from `_TRANSFER_REFUSALS` or joined by a second one; the spec does
      not care which, only that the set equality holds.

### FR-004: What an operator may ask of a member change, and what refuses

#### Description:

An operator-origin member request skips the owner check and nothing else. Every other condition the
owner's own request would face still holds, and each refusal names what happened.

#### Acceptance Criteria:

- [ ] A space with no registry record is refused, naming the space.
- [ ] An **emptied** space — SPEC-205 leaves one `active` with a cleared `owner` and an `emptiedAt` —
      is refused as deleted, before any membership check runs, so the sentence is the true one.
      Reached the other way round the user is told "that person is not a member" of a space that no
      longer has members, which is also true and tells them nothing.
- [ ] A space whose `status` is not `active` is refused.
- [ ] **`remove_members` naming the space's current owner is refused, naming them.** Today
      `normalize_members` drops the owner silently, so the request succeeds having removed nobody and
      notified no one — and "remove the owner who left" is the single most likely thing an operator
      will write in this file. The refusal says to transfer the space first.
- [ ] `add_members` naming someone already a member stays an idempotent success rather than becoming
      a refusal. Replay-safety is worth more than the diagnostic here, and FR-002's derived request
      ids depend on it.
- [ ] An operator `add_members` naming a username no user pool account matches keeps today's
      behaviour — the verb collects it and notifies the space's owner by name. The same for a member
      who has reached `MAX_SHARED_MEMBERSHIPS`. Tests pin both, because both send the diagnostic to
      the owner, who in the motivating case is exactly the person whose absence prompted the file.
- [ ] A test drives an operator request against a space whose owner is a real user and asserts it
      proceeds; a UI request for the same change from a non-owner is refused. Both halves are needed:
      the first alone passes with the owner check deleted, the second alone passes with the operator
      skip deleted.
- [ ] Every refusal above is a return value reaching `NotifyFailure`. **The recipient differs by
      origin, and the criterion splits accordingly:** a UI refusal reaches the requester, because the
      validator sets `actor` from the verified identity; an operator refusal reaches the space's
      owner, who is the named party for a forged or mistaken request. An emptied space has no owner
      and honestly nobody to tell.

### FR-005: The boundary, the prefix and the infrastructure

#### Description:

`OPERATOR_ACTIONS` widens to the three actions; the `SenderId` comparison is unchanged. The admin
bucket's prefix, its lifecycle rules and the reader's IAM move from `ownership-transfers/` to
`operator-requests/`.

#### Acceptance Criteria:

- [ ] `OPERATOR_ACTIONS` is `{transfer_ownership, add_members, remove_members}`, asserted as **exact
      contents** — the mirror of FR-003's assertion on `OWNER_ONLY_ACTIONS`, and the half that
      matters here: a test deriving the refused set from `VALID_ACTIONS - OPERATOR_ACTIONS` stays
      green when `delete` is added to the admitted set, because the asserted set shrinks with it.
- [ ] A test enumerates that difference and asserts every action in it — `create`, `delete`, `leave`,
      `forget`, `acknowledge_membership` — is refused on the operator origin, naming each, and
      asserts the difference is non-empty so the loop cannot pass by iterating over nothing.
- [ ] The rest of `operator_refusal` is unchanged and its tests still pass: an unknown origin, a
      message carrying both an origin and an identity block, an unset role-id configuration and a
      `SenderId` from any other principal are each still refused, in that order.
- [ ] The reader's S3 grant — object actions on the prefix and an `s3:prefix`-conditioned
      `ListBucket` — is re-pointed at `operator-requests/*`, and a test asserts the reader's only S3
      calls are against that prefix.
- [ ] Two lifecycle rules expire `operator-requests/processed/` and `operator-requests/rejected/`,
      one rule per prefix; `operator-requests/inbox/` gets **no** expiring rule, for SPEC-208's
      reason.
- [ ] **The old prefix is confirmed empty by a listing of `ownership-transfers/` — all three
      sub-prefixes, not just the inbox — before its two lifecycle rules are removed.** Deleting an
      expiring rule while objects sit under it leaves them with no expiry at all, forever, which is
      the structural guarantee `infra/modules/analytics/s3.tf` records for `logs/`. If the listing is
      not empty, the two rules stay until the last object has aged out and the retirement waits; if
      the listing cannot be run from the building session it goes to `docs/testing/owed.md` with the
      exact command, and the retirement waits on that.
- [ ] `docs/testing/owed.md`'s two SPEC-208 operator rows are **rewritten**, not appended to: they
      are the instruction sheet for a check nobody has run, and they currently name
      `ownership-transfers/inbox/` and a `space,new_owner` file. Left as they are, the next operator
      writes a file this reader rejects.
- [ ] Every other site still stating the old shape is corrected in the same change: the plane page
      `lambdas/info/planes/shared-spaces.md`, the SPEC-208 entry in `docs/decisions/control-planes.md`
      (which describes the queue's second producer as reading "an operator's CSV of ownership
      transfers"), `shared-space-common/config.py`'s `OPERATOR_ACTIONS` docstring, and SPEC-208's own
      spec and delivery doc, marked in place rather than left to disagree.
- [ ] No new resource family is provisioned, so no deploy-role expansion is expected. That is
      **confirmed by a plan showing no diff under `infra/modules/base/policies/`**, not assumed; if
      the re-pointed grant needs one, it lands in its own PR ahead of this work.

---

## Data Model

```
# The operator CSV — <admin-bucket>/operator-requests/inbox/<anything>.csv
space,action,username
finance_reports,add_members,bcarter
finance_reports,add_members,rsingh
project_atlas,transfer_ownership,dmehta
sales_archive,remove_members,agriffith
```

`space` is the shared space's name. `action` is one of three, spelled exactly as the plane's own
action values so the operator's file and the plane's log line say the same word. `username` is the
member the row is about: the person taking the space for a transfer, and the person being added or
removed otherwise. **One space appears under at most one action per file** (FR-001), and the rows
sharing a `(space, action)` become one request (FR-002) — the two `finance_reports` rows above are
one `add_members` naming both people.

```python
# lambdas/shared-space-common/auth.py — the new predicate, beside transfer_refusal

def member_refusal(requester, space, action, targets, registry) -> tuple[str, str] | None:
    """Decides one add_members or remove_members request. Pure — no AWS calls.

    `requester` is the verified username, or None for an operator-origin request, and None is what
    skips the owner check. It must not be the context's `actor`: for an operator request that field
    carries the space's own owner, so an owner check written against it passes without the skip and
    the skip could be deleted with every test green.

    `targets` is the list the wire carries. A request-level condition refuses the whole request; so
    does the one per-name condition, a removal naming the owner, because partly serving an operator
    is worse than telling them.
    """
```

```python
# lambdas/shared-space-common/config.py

OWNER_ONLY_ACTIONS = frozenset({"delete"})
OPERATOR_ACTIONS = frozenset({"transfer_ownership", "add_members", "remove_members"})
```

```jsonc
// One enqueued request. Flat, no identity block, exactly as SPEC-208 established.
{
  "schemaVersion": 1,
  "requestId": "…",
  "action": "add_members",
  "origin": "operator",
  "space": "finance_reports",
  "payload": {"members": ["bcarter", "rsingh"]}
}
```

## File & Folder Structure

```
lambdas/
├── shared-space-transfer-reader/     # the header, the action column, coalescing, the two caps
│   ├── transfer_reader.py
│   └── test_transfer_reader.py
├── shared-space-common/
│   ├── auth.py                       # member_refusal, and the owner check leaving authorize
│   ├── config.py                     # OWNER_ONLY_ACTIONS, OPERATOR_ACTIONS
│   └── messages.py                   # the new refusal wording, and the set-equality test
├── shared-space-validate/            # routing a member refusal to RefusedSeed
└── shared-space-delete/              # the SPEC-205 inertness test, re-pointed

infra/modules/shared-spaces/policies/transfer-reader-permissions.json.tftpl
infra/modules/analytics/s3.tf         # the two lifecycle rules, re-pointed
```

## Implementation Phases

### Phase 1: The authorization change

- `auth.member_refusal`, its wording in `messages`, the set-equality test over the codes, and the
  owner check leaving `OWNER_ONLY_ACTIONS` and `authorize`.
- The validator routing a member refusal to `RefusedSeed`, and the ASL walk asserting the arm
  notifies.
- SPEC-205's inertness test re-pointed, and the register entry amended in place.
- The planted mutation of the owner check, run and reverted.

### Phase 2: The operator boundary

- `OPERATOR_ACTIONS` widened, its exact-contents assertion, and the enumerated refusal of the
  other five.
- The operator skip, and the paired tests that neither half passes alone.

### Phase 3: The CSV and the prefix

- The header, the action column, the per-row syntactic checks, the one-action-per-space rule, the
  duplicate-row rule and the coalescing.
- The two caps, each computed by a test and naming its budget.
- The prefix move: the reader, its IAM, the two lifecycle rules, the empty-prefix confirmation, and
  the doc sites that still name the old shape.
