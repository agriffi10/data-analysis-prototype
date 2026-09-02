# Spec: Operator-Driven Shared-Space Membership

**ID:** SPEC-217
**Status:** Draft
**Last Updated:** 2026-09-02
**Depends On:** SPEC-208 (the operator CSV door, the `SenderId` boundary, refusals as return values), SPEC-206 (the `SenderId` role-id comparison), SPEC-205 (a delete empties a space; `emptiedAt` and the cleared `owner`), SPEC-051/053 (the shared-space plane, `add_members` and `remove_members`), SPEC-082 (registry CAS), SPEC-125 (`shared-space-common`), SPEC-152 (a pre-verb failure notifies), SPEC-201 (the API stamps the identity block the plane reads)

**Interacts with:** SPEC-203's membership index and the roster fan-out are written by the existing
verbs and are untouched here — this spec changes who may ask for a membership change, never what
one does.

## Overview

An operator can hand a shared space to a new owner by dropping a CSV in the admin bucket, and can
do nothing else. Every other membership question — the departed owner still sitting in the roster,
the contractor whose access should have ended on Friday, the ten people a re-organisation moved into
a space whose owner is on leave — has no answer but "ask the owner", and the cases that reach an
operator are precisely the ones where the owner cannot be asked.

This spec widens that door to member management: an operator's CSV may add a member to a space and
remove one, as well as transfer it. The rows become ordinary requests on the plane's existing queue,
so an operator-driven add and an owner-driven add are the same verb, notifying the same people and
writing the same records. The CSV grows a column and gets a defined structure, because it now has to
say which of three things a row asks for.

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
  that predicate rather than being lost.
- An explicit refusal for removing a space's current owner, which today is silently dropped.
- The reader's per-row syntactic checks, its request-id derivation, and its row cap re-derived.
- The admin bucket's lifecycle rules and the reader's IAM, re-pointed at the new prefix.

### Out of Scope

- **`create`, `delete`, `leave`, `forget` and `acknowledge_membership` from a CSV.** The first two
  are the destructive pair and an operator holding them turns this door into the admin surface
  CLAUDE.md forbids; the last three are self-scoped acts, and an operator performing one impersonates
  a user rather than administering a space. All five stay refused, and a test enumerates them.
- **An in-app admin surface.** Unmoved from SPEC-208: no admin group, no admin role, no admin route.
- **An operator outcome ledger.** The reader can say what it enqueued and cannot say what happened —
  the outcome is decided later, by the one producer at the end of the machine. A receipt object
  written at enqueue time would be read as an outcome and would be wrong exactly when it mattered.
  The operator's channel stays the reader's structured log, and the residual stays recorded.
- **Renaming `shared-space-transfer-reader`, its role, or `TRANSFER_READER_ROLE_ID`.** The name will
  under-describe what the function reads, and that is the cheaper defect: the role's unique id is
  half of the `SenderId` comparison, so renaming it rotates the value the boundary compares against,
  and any operator file consumed in the window is moved to `processed/` with every one of its rows
  refused. A misleading name is paid for in a docstring; a rotated role id is paid for in lost work.
- **More than one member per row.** A row is one `(space, action, username)` triple. A packed list
  needs a second separator inside a CSV field, and the file's whole safety argument is that its
  columns cannot be misread.
- **Any change to the browser's member management**, or to what the verbs do once a request reaches
  them. Slots, grants, the roster fan-out, the membership index and the notifications are unchanged.
- **A backfill of files left in `ownership-transfers/inbox/`.** The cutover requires that prefix to be
  empty, rather than teaching the reader to drain a prefix it is retiring.

---

## Functional Requirements

### FR-001: The operator CSV

#### Description:

One prefix, `<admin-bucket>/operator-requests/inbox/`, holding CSVs whose header is exactly
`space,action,username`. One data row is one request. `<admin-bucket>/ownership-transfers/` is
retired.

#### Acceptance Criteria:

- [ ] The header row is exactly `["space", "action", "username"]`, compared as an **ordered list**
      and not as a set, preserving SPEC-208's reason: a file whose columns are the right names in the
      wrong order parses perfectly and acts on every row against the wrong argument.
- [ ] A leading UTF-8 BOM is stripped before the header is compared — Excel writes one by default and
      it is invisible in the operator's own editor.
- [ ] A file whose header is the retired `space,new_owner` is rejected with a reason that names the
      accepted header, rather than the generic wrong-header sentence. An operator who wrote yesterday's
      file gets told what changed.
- [ ] `action` must be one of `transfer_ownership`, `add_members`, `remove_members`. A test asserts
      the reader's accepted set **equals** `config.OPERATOR_ACTIONS` — not that it is a subset, which
      would pass while the reader silently refused an action the plane admits.
- [ ] A row naming any other action rejects the **whole file**, with a reason naming the line number
      and the accepted actions. Partial enqueueing is not an option this reader has: SPEC-208's rows
      are enqueued neither wholly nor partly, and mixing actions does not change that.
- [ ] `space` and `username` are each held to `cpcommon.config.CATALOG_IDENTIFIER_RE`, and a row
      failing either rejects the whole file naming the line and the field. This is a syntactic check,
      not a domain one — the reader still asks no question about whether the space or the member
      exists. It earns its place because the two verbs disagree about case: `normalize_members`
      lowercases, so `Alice` in an add row silently becomes `alice`, while `transfer_refusal` compares
      the target verbatim, so `Alice` in a transfer row refuses as "not a member". One spelling, two
      behaviours, neither visible to the operator; refusing at the reader makes it one.
- [ ] A row with a field count other than three, or any blank field, rejects the whole file naming
      the line. Wholly blank lines are skipped.
- [ ] Two rows in one file carrying the same `(space, action, username)` triple reject the whole file,
      naming both line numbers. A duplicate is either a mistake or a no-op; the one thing it cannot be
      is meaningful.
- [ ] An empty or absent inbox is a successful no-op, as it is today — a newly created schedule fires
      against an inbox nobody has written to.
- [ ] A test drives one file mixing all three actions and asserts the messages come off in file order.

### FR-002: What the reader enqueues

#### Description:

Each valid row becomes exactly one message on the existing shared-space FIFO queue, carrying the
declared operator origin and no identity block, in the envelope SPEC-208 established.

#### Acceptance Criteria:

- [ ] `transfer_ownership` enqueues `payload: {"newOwner": <username>}`; `add_members` and
      `remove_members` each enqueue `payload: {"members": [<username>]}`. A test asserts each shape
      against the key the corresponding verb actually reads, rather than against a literal repeated in
      the test.
- [ ] Every message carries `origin: "operator"`, no `identity` key, the queue's single message group
      and the schema version the validator accepts.
- [ ] The per-row request id is derived from the object key, the row index **and the row's content**,
      so a corrected file re-uploaded under the same key does not collapse onto the previous file's
      ids inside the deduplication window. An identical row re-uploaded under the same key still
      derives the same id, which is the replay collapse SPEC-208 wanted.
- [ ] A tick that crashes between sending some rows and moving the file re-sends the same ids on the
      next tick; a test drives it and asserts no row is applied twice. Past the deduplication window
      the replay is idempotent at the verb: a re-add of a current member is skipped, a re-removal of
      an absent member is skipped, and a re-transfer to the current owner is refused as a no-op.
- [ ] Files are processed in listing order and rows within a file in file order, so a sequence of
      operator files is replayable. The sweep still **stops** at a file it has no budget for rather
      than skipping past it.
- [ ] The row cap is **re-derived by a test** and the test names the budget that bound it. The
      existing derivation sizes only the reader's own invocation — timeout, send fraction, one
      `SendMessage` round trip — and that is no longer obviously the binding constraint, because a
      file of N rows is now N state-machine executions rather than N of one cheap verb. The test
      compares the reader's own budget against the plane's downstream drain budget and takes the
      smaller, naming both. A number carried over unexamined would be a cap sized for the wrong thing.
- [ ] A file larger than the whole cap is rejected with a reason naming the cap, unchanged from
      SPEC-208 — it can never be processed by any tick, and only the operator can split it.

### FR-003: One member-refusal predicate, for both origins

#### Description:

`auth.member_refusal(requester, space, action, target, registry)` decides an `add_members` or
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
      `ResultPath`, `ValidateFailureSeed` seeds a null actor, and the notifier stays silent. This is a
      behaviour change on the UI path and is deliberate — a member change that refuses is currently a
      request the user watches disappear.
- [ ] `delete` **stays** in `OWNER_ONLY_ACTIONS`; a test asserts the set's exact contents, so removing
      the last member of it cannot pass as tidying.
- [ ] **The predicate takes `requester`, never the context's `actor`, and `requester is None` is what
      skips the owner check for an operator.** Written against `actor` the operator case would pass
      anyway — the validator records an operator request's `actor` as the space's own current owner,
      so it compares equal — and the skip could then be deleted with every test still green. This is
      the trap `transfer_refusal` already documents, and it is the same trap one action over.
- [ ] Removing the owner check from `member_refusal` reddens a named test and nothing else; the
      mutation is planted, run and reverted, and the spec's delivery doc says which test caught it.
      The guard's failure would otherwise be silent, which is the class this project mutation-tests.
- [ ] `member_refusal` is pure: no AWS calls, and a test asserts the client fakes recorded none.
- [ ] The predicate is the **only** authority on these two actions. A test asserts `authorize` no
      longer decides them — an owner check written in both places is the complement that drifts.

### FR-004: What an operator may ask of a member change, and what refuses

#### Description:

An operator-origin member request skips the owner check and nothing else. Every other condition the
owner's own request would face still holds, and each refusal names what happened.

#### Acceptance Criteria:

- [ ] A space with no registry record is refused, naming the space.
- [ ] An **emptied** space — SPEC-205 leaves one `active` with a cleared `owner` and an `emptiedAt` —
      is refused as deleted, before any membership check runs, so the sentence is the true one. Reached
      the other way round the user is told "that person is not a member" of a space that no longer has
      members, which is also true and tells them nothing.
- [ ] A space whose `status` is not `active` is refused.
- [ ] **`remove_members` naming the space's current owner is refused, naming them.** Today
      `normalize_members` drops the owner silently, so the request succeeds having removed nobody and
      notified no one — and "remove the owner who left" is the single most likely thing an operator
      will write in this file. The refusal says to transfer the space first.
- [ ] `add_members` naming someone already a member stays an idempotent success rather than becoming a
      refusal. Replay-safety is worth more than the diagnostic here, and the reader's derived request
      ids depend on it.
- [ ] An operator `add_members` naming a username no user pool account matches keeps today's
      behaviour — the verb collects it and notifies the space's owner by name. A test pins that the
      operator's row does not change who is told.
- [ ] A test drives an operator request against a space whose owner is a real user and asserts it
      proceeds; a UI request for the same change from a non-owner is refused. Both halves are needed:
      the first alone passes with the owner check deleted, the second alone passes with the operator
      skip deleted.
- [ ] Every refusal above is a return value reaching `NotifyFailure`, and the recipient is the space's
      owner — for a forged or mistaken operator request they are the named party, and for an emptied
      space there is no owner and honestly nobody to tell.

### FR-005: The boundary, the prefix and the infrastructure

#### Description:

`OPERATOR_ACTIONS` widens to the three actions; the `SenderId` comparison is unchanged. The admin
bucket's prefix, its lifecycle rules and the reader's IAM move from `ownership-transfers/` to
`operator-requests/`.

#### Acceptance Criteria:

- [ ] `OPERATOR_ACTIONS` is `{transfer_ownership, add_members, remove_members}`, and a test enumerates
      `VALID_ACTIONS` and asserts every action outside that set — `create`, `delete`, `leave`,
      `forget`, `acknowledge_membership` — is refused on the operator origin, naming each. The test
      derives the refused set from `VALID_ACTIONS - OPERATOR_ACTIONS` so a ninth action added later is
      covered without an edit, and asserts that difference is non-empty so the loop cannot pass by
      iterating over nothing.
- [ ] The rest of `operator_refusal` is unchanged and its tests still pass: an unknown origin, a
      message carrying both an origin and an identity block, an unset role-id configuration and a
      `SenderId` from any other principal are each still refused, in that order.
- [ ] The reader's S3 grant — object actions on the prefix and a `s3:prefix`-conditioned `ListBucket`
      — is re-pointed at `operator-requests/*`, and a test asserts the reader's only S3 calls are
      against that prefix.
- [ ] Two lifecycle rules expire `operator-requests/processed/` and `operator-requests/rejected/`,
      one rule per prefix; `operator-requests/inbox/` gets **no** expiring rule, for SPEC-208's
      reason. The two `ownership-transfers/` rules are removed in the same change.
- [ ] The cutover requires `ownership-transfers/inbox/` to be **confirmed empty by a listing** before
      the prefix is retired, not assumed empty because the path has not been exercised. The listing is
      an operator action against the admin bucket; if it cannot be run from the building session it is
      recorded in `docs/testing/owed.md` with the exact command, and the retirement waits.
- [ ] No new resource family is provisioned, so no deploy-role expansion is expected. The build
      **confirms** that rather than assuming it, and if the re-pointed grant needs one it lands in its
      own PR ahead of this work.
- [ ] The reader's structured log names the action on every enqueued row, so the operator's only
      feedback channel distinguishes an add from a removal. The operator's continued lack of an inbox
      is re-recorded in `docs/testing/owed.md` against this spec, since a member-change refusal now
      goes to a space owner who may be exactly the person whose absence prompted the file.

---

## Data Model

```
# The operator CSV — <admin-bucket>/operator-requests/inbox/<anything>.csv
space,action,username
finance_reports,transfer_ownership,bcarter
finance_reports,remove_members,agriffith
project_atlas,add_members,dmehta
project_atlas,add_members,rsingh
```

`space` is the shared space's name. `action` is one of three, spelled exactly as the plane's own
action values so the operator's file and the plane's log line say the same word. `username` is the
member the row is about: the person taking the space for a transfer, and the person being added or
removed otherwise.

```python
# lambdas/shared-space-common/auth.py — the new predicate, beside transfer_refusal

def member_refusal(requester, space, action, target, registry) -> tuple[str, str] | None:
    """Decides one add_members or remove_members request. Pure — no AWS calls.

    `requester` is the verified username, or None for an operator-origin request, and None is what
    skips the owner check. It must not be the context's `actor`: for an operator request that field
    carries the space's own owner, so an owner check written against it passes without the skip and
    the skip could be deleted with every test green.
    """
```

```python
# lambdas/shared-space-common/config.py

OWNER_ONLY_ACTIONS = frozenset({"delete"})
OPERATOR_ACTIONS = frozenset({"transfer_ownership", "add_members", "remove_members"})
```

```jsonc
// One enqueued row. Flat, no identity block, exactly as SPEC-208 established.
{
  "schemaVersion": 1,
  "requestId": "…",
  "action": "remove_members",
  "origin": "operator",
  "space": "finance_reports",
  "payload": {"members": ["agriffith"]}
}
```

## File & Folder Structure

```
lambdas/
├── shared-space-transfer-reader/     # the header, the action column, the per-row checks, the cap
│   ├── transfer_reader.py
│   └── test_transfer_reader.py
├── shared-space-common/
│   ├── auth.py                       # member_refusal, and the owner check leaving authorize
│   ├── config.py                     # OWNER_ONLY_ACTIONS, OPERATOR_ACTIONS
│   └── messages.py                   # the new refusal wording
└── shared-space-validate/            # routing a member refusal to RefusedSeed

infra/modules/shared-spaces/policies/transfer-reader-permissions.json.tftpl
infra/modules/analytics/s3.tf         # the two lifecycle rules, re-pointed
```

## Implementation Phases

### Phase 1: The authorization change

- `auth.member_refusal`, its wording in `messages`, and the owner check leaving
  `OWNER_ONLY_ACTIONS` and `authorize`.
- The validator routing a member refusal to `RefusedSeed`, and the ASL walk asserting the arm
  notifies.
- The planted mutation of the owner check, run and reverted.

### Phase 2: The operator boundary

- `OPERATOR_ACTIONS` widened, and the enumerated refusal of the other five.
- The operator skip, and the paired tests that neither half passes alone.

### Phase 3: The CSV and the prefix

- The header, the action column, the per-row syntactic checks, the duplicate-row guard and the
  content-derived request id.
- The re-derived row cap, naming both budgets.
- The prefix move: the reader, its IAM, the two lifecycle rules, and the empty-inbox confirmation.
