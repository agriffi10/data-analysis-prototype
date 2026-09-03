# Spec: Operator-Driven Shared-Space Membership

**ID:** SPEC-217
**Status:** Completed
**Last Updated:** 2026-09-02
**Depends On:** SPEC-208 (the operator CSV door, the `SenderId` boundary, refusals as return values, the verb's own refusal fence), SPEC-206 (the `SenderId` role-id comparison), SPEC-205 (a delete empties a space; `emptiedAt`, the cleared `owner`, and the inertness test this spec re-points), SPEC-051/053 (the shared-space plane, `add_members` and `remove_members`), SPEC-082 (registry CAS), SPEC-125 (`shared-space-common`), SPEC-152 (a pre-verb failure notifies), SPEC-201 (the API stamps the identity block the plane reads)

**Interacts with:** SPEC-203's membership index and the roster fan-out are written by the existing
verbs and are untouched — this spec changes who may ask for a membership change and how a request
arrives, never what a membership change *does*.

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
- The two member verbs gaining the refusal fence and the origin stamp `transfer_ownership` already
  carries, because a refusal that is a value is a refusal the verb can now be handed.
- An explicit refusal for removing a space's current owner, which today is silently dropped.
- The reader coalescing a file's rows into one request per `(space, action)`, the two caps that
  bounds, and the per-row syntactic checks.
- The admin bucket's lifecycle rules and the reader's IAM, re-pointed at the new prefix.

**The threat model widens, and that is the decision being taken.** Under SPEC-208 the operator door
could only move ownership *between people who were already members*: it granted access to nobody. A
row now grants a stranger live S3, Glue and Lake Formation access to a space's data, and what
stands in front of that is **who can write the inbox** — the `SenderId` comparison is not a second
fence against them, only against a forged message from somewhere else. That write set is wider than
"an operator": the deploy role holds `s3:*` on the admin bucket, and its trust policy admits
`pull_request`, so a PR-triggered job can place a file. That is pre-existing and this spec does not
widen it; what this spec must not do is describe it as narrower than it is, and the residual is
recorded in the register beside the decision. `shared-space-common/config.py`'s own docstring asks
that widening `OPERATOR_ACTIONS` "be a decision rather than an oversight"; this spec is that
decision.

### Out of Scope

- **`create`, `delete`, `leave`, `forget` and `acknowledge_membership` from a CSV.** The first two
  are the destructive pair, and an operator holding them turns this door into the admin surface
  CLAUDE.md forbids; the last three are self-scoped acts, and an operator performing one impersonates
  a user rather than administering a space. All five stay refused, and a test enumerates them.
- **An in-app admin surface.** Unmoved from SPEC-208: no admin group, no admin role, no admin route.
- **What a membership change does.** Slots, Lake Formation grants, the roster fan-out, the membership
  index and the notification wording are untouched. FR-006 is the one exception and it is not a
  change to the work: the two verbs gain the guard and the span stamp that `transfer_ownership`
  already has, which is bookkeeping about *whether they should have run at all*.
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
- **A backfill of files left under `ownership-transfers/`.** The cutover confirms that prefix empty
  before the reader stops looking at it.

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
- [ ] `action` must be one of **`add`, `remove`, `transfer`** — the operator's vocabulary, not the
      plane's. A row names one person, so `add_members` reads wrong on it, and an operator writing
      this file by hand should not have to know the wire.
- [ ] The three words are a **mapping to the plane's actions**, held as a module-level constant in
      the reader: `add → add_members`, `remove → remove_members`, `transfer → transfer_ownership`.
      The reader keeps it locally rather than importing the domain layer, which would buy a
      cold-start crash on `PORTAL_ROLE_ARN` — a variable the reader's environment does not set — and
      a test cross-checks it from the test's own `sys.path`, in the manner `SCHEMA_VERSION` and
      `MESSAGE_GROUP_ID` already are.
- [ ] **That cross-check asserts the mapping's VALUES set-equal `config.OPERATOR_ACTIONS`, and that
      the mapping is injective.** A second vocabulary is a thing that drifts, and this is what stops
      it: set equality alone forces a CSV word to exist for every action the plane admits and forces
      one to go when an action is withdrawn, but it collapses two words mapping to one action and
      agrees. Three keys, three distinct values, asserted separately from the set.
- [ ] A row naming any other action rejects the **whole file**, with a reason naming the line number
      and the three accepted words. Partial enqueueing is not an option this reader has: SPEC-208's rows
      are enqueued neither wholly nor partly, and mixing actions does not change that.
- [ ] **A file naming one space under more than one action is rejected**, naming the space and both
      lines. Two actions on one space in one file read as a sequence and are not one: their
      executions overlap, so a `transfer` row then a `remove` row on the same space can be validated
      in either order, and the losing order refuses with FR-004's "transfer the space first" —
      advice the previous line already took. The refusal is at the reader because it is the
      only place that can see the pair.
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
      usernames, in file order. One message per member is the mapping this criterion exists to
      forbid: the Pipe is `batch_size = 1` and `FIRE_AND_FORGET`, so N messages for one space are N
      overlapping executions, each a compare-and-swap against a single registry object whose
      `cpcommon.cas.MAX_ATTEMPTS` is 6 and whose docstring rests on contention being rare — and each
      dragging a full `write_roster_to_all`, so N single-member adds to one space cost O(N²) cache
      writes. The verbs already take a list, and one message is one CAS and one fan-out.
- [ ] A `transfer` row enqueues `action: "transfer_ownership"` with
      `payload: {"newOwner": <username>}`; `add` and `remove` enqueue `add_members` and
      `remove_members` with `payload: {"members": [...]}`. The message carries the **wire** action,
      never the CSV word — the validator's vocabulary is `VALID_ACTIONS` and a message naming `add`
      is refused as an unknown action. A test asserts each shape against the key the corresponding
      verb actually reads, rather than against a literal repeated in the test.
- [ ] A second `transfer` row for the same space naming a *different* target is refused,
      by the same one-action-one-space reasoning: two transfers of one space in one file are a race
      whichever way they are read. (A repeated target is already refused as a duplicate triple.)
- [ ] Every message carries `origin: "operator"`, no `identity` key, the queue's single message group
      and the schema version the validator accepts.
- [ ] The body's `requestId` is derived from the object key and the `(space, action)` pair, so one
      enqueued request is traceable to the line that asked for it. **Replay safety rests on the
      verbs' idempotency, not on deduplication**: the schedule is `rate(1 hour)` and the FIFO
      deduplication window is five minutes, so no two sweeps ever fall inside one window. A re-add
      of a current member is skipped, a re-removal of an absent member is skipped, and a re-transfer
      to the current owner is refused as a no-op.
- [ ] **The `MessageDeduplicationId` is NOT the derived request id.** *(Amended during the build:
      the criterion said "random", and random turned out to reintroduce a different fault. The
      sweep is invoked ASYNCHRONOUSLY by EventBridge with no `maximum_retry_attempts` set, so
      Lambda's own two retries fire about a minute and three minutes later — **inside** the
      five-minute deduplication window, unlike the hourly schedule this criterion reasons about.
      A random id therefore lets a crash between a send and the file move deliver the whole set
      twice, and a duplicate `transfer_ownership` refuses as `TransferTargetIsOwner` and tells the
      new owner it failed a minute after telling them it worked. The shipped id is salted with the
      source object's `ETag`: stable across a retry of the same bytes, so SQS collapses it, and
      not computable by the caller below, who can guess the object key but cannot read the
      bucket. The criterion's own reasoning is unchanged and is why the request id alone is not
      used.)* SPEC-208 passes
      the derived value as both, and that is safe only while the operator is the queue's only
      producer of these ids. The API's dedup id for this queue is `payload["requestId"]` — the
      *caller's own*, unaltered — on the same queue and the same single message group. So a derived
      dedup key is a value any signed-in user can compute from constants in this repository (the
      UUID namespace is a literal in the reader; the object key is a guess) and claim first on a
      harmless self-scoped action. SQS then accepts the operator's real row and **discards it as a
      duplicate**, `_send` does not read the response, the file moves to `processed/`, and the log
      reports the row as enqueued. A suppressed revocation, reported as success, to the one channel
      the operator has. Nothing is lost by randomising it, because the criterion above already says
      deduplication carries nothing.
- [ ] Two replay residuals are named, in both directions. A replayed `remove` an hour later removes
      a member who was legitimately re-added in between; a replayed `add` **re-grants** access to
      someone the owner removed in between, because the verb skips only names already on the freshly
      loaded roster. The second is the worse one and is the reason both are written down. Recorded,
      not solved — the fix is a request ledger the plane does not have.
- [ ] Files are processed in listing order, and the sweep still **stops** at a file it has no budget
      for rather than skipping past it.
- [ ] **The rows-per-invocation cap keeps its existing inputs and its existing value**, and the test
      asserting that is kept. Coalescing makes it conservative — a file's sends are now at most its
      distinct `(space, action)` pairs — and the conservatism is deliberate rather than an oversight
      to be re-derived away: the reader was never the expensive half, and a cap re-derived from a
      per-row *parse* cost would run to five figures, leave the over-cap rejection unreachable and
      bound nothing anyone cares about. What must change is the rejection's **wording**, which today
      says a file of N rows "could never be handled in one run" — no longer true when those rows are
      one send.
- [ ] **A second cap bounds members per message**, and it is the one that now matters. It is computed
      by a test from the `add_members` verb's **effective** timeout and a named per-member cost
      constant, in the manner `SEND_MILLISECONDS` already names the reader's. Two traps in reading
      that timeout, both of which ship green: the verb takes the module's `lookup(...)` **default**,
      because `local.shared_space_function_timeouts` carries one entry and `add-members` is not it —
      so a test parsing the map finds nothing and a test parsing the resource finds the `lookup`
      expression, not an integer. The test therefore reads the declared default **and asserts
      `add-members` has no override**, so it reddens the day one is added rather than sizing against
      a number that moved. The cost constant must cover the **fan-out too**, which is O(roster) and
      not per-member: a message adding M members to a space of R costs M lookups, slot assignments
      and index writes plus R+M cache writes, so a cost model that is R-independent is too permissive
      for exactly the large space the cap exists to protect.
- [ ] The justification for that cap is the **partial state**, not a lost notification: this machine
      declares no top-level `TimeoutSeconds` and `AddMembers` carries a `States.ALL` catch, so a verb
      that runs out of time is caught and reported. What it leaves behind is the problem — slots
      assigned, the registry unwritten, and `_release_slots` never reached.
- [ ] A `(space, action)` group larger than that cap **rejects the file**, with a reason naming the
      cap, on SPEC-208's reasoning that only the operator can split it.
- [ ] **Two per-file ceilings bound one mistake**: a cap on distinct spaces named in one file, and a
      cap on total `add` rows in one file. Neither is a resource budget and neither is computed —
      they are blast-radius controls, stated as such with the number chosen and argued in one line.
      Without them a single file is up to the row cap's worth of grants across as many spaces, with
      no dual control, no approval and no outcome ledger; the only ceiling on any one beneficiary is
      `MAX_SHARED_MEMBERSHIPS`, which is a per-user limit that happened to be there rather than a
      control this spec chose. A file over either ceiling is rejected with a reason naming it.
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
- [ ] **`test_the_emptied_record_is_inert_to_its_ORIGINAL_OWNER` is re-pointed, and keeps its
      discrimination.** That SPEC-205 test loops five actions asserting `authorize` raises on an
      emptied record; two of them are the actions this FR moves, so it reddens on a correct change
      and the cheapest repair is to delete those two names — losing the detection while production
      behaviour rests on FR-004 being wired. The two actions are asserted through `member_refusal`
      instead, **still driven as the original owner**. That alone is weaker than what it replaces:
      `authorize` refused because the `owner` field was cleared, which is what made the actor
      load-bearing, while the emptied branch copied from `transfer_refusal` fires on `emptiedAt`
      before any actor is consulted, so the assertion would pass as a stranger too. So it is paired
      with a live-record assertion — the original owner allowed, a non-owner refused by code — which
      is what actually pins the actor. This supersedes the mechanism half of the register's *emptied
      record is inert* entry, and the entry is amended in place rather than left to disagree.
- [ ] `delete` **stays** in `OWNER_ONLY_ACTIONS`, and a test asserts the set's exact contents, so
      removing the last member of it cannot pass as tidying.
- [ ] **The predicate takes `requester`, never the context's `actor`, and `requester is None` is what
      skips the owner check for an operator.** Written against `actor` the operator case would pass
      anyway — the validator records an operator request's `actor` as the space's own current owner,
      so it compares equal — and the skip could then be deleted with every test still green. This is
      the trap `transfer_refusal` already documents, one action over.
- [ ] `targets` is a **list**, because that is what the wire carries. The API's contract *does*
      refuse a browser's `members` that is not a list of strings (measured against
      `sharedSpace.enqueue`), so what the check covers is the **other producer**: the operator
      reader builds its own body and nothing validates that one. Two shapes reach the predicate
      from either side — a `payload` carrying no `members` key, and a list that normalises to
      nothing, such as `["  "]`. An absent, empty, or non-list `members` is refused with
      its own code rather than normalising to `[]` and succeeding as a no-op — `transfer_refusal` has
      exactly this in `TransferTargetMissing` and the member path is given none. It is reachable
      immediately: FR-005's enumeration drives every action through one operator envelope, so
      `member_refusal` is called with a `newOwner` payload and no `members` key.
- [ ] The predicate compares targets in the **same normalised form the verb will apply** —
      `normalize_members` lowercases, so a UI request naming `Alice` against owner `alice` must
      refuse rather than pass the predicate and be silently dropped by the verb. That silent drop is
      the behaviour FR-004 exists to end, and a verbatim comparison copied from `transfer_refusal`
      would leave it in place on the one path the CSV's syntactic check does not cover.
- [ ] Request-level conditions refuse the whole request; the one per-name condition, FR-004's removal
      naming the owner, also refuses the whole request rather than dropping that name, so the
      operator is told rather than partly served.
- [ ] Removing the owner check from `member_refusal` reddens the named tests and nothing unrelated;
      the mutation is planted, run and reverted, and the delivery doc says which tests caught it. The
      guard's failure would otherwise be silent, which is the class this project mutation-tests.
- [ ] `member_refusal` is pure: no AWS calls, and a test asserts the client fakes recorded none.
- [ ] The predicate is the **only** authority on these two actions. A test asserts `authorize` no
      longer decides them — an owner check written in both places is the complement that drifts.
- [ ] **`authorize` gains a terminal `raise`**, so an action that reaches the bottom is refused
      rather than allowed. Today the function ends by falling off the end and returning `None`,
      which means allowed; that is harmless only because every action in `VALID_ACTIONS` is caught
      by a branch above. After this FR the two member actions are deliberately allowed *there* and
      gated elsewhere, so the fall-through stops being unreachable and becomes the failure mode:
      losing the `member_refusal` call is then an open door rather than a refusal. An explicit
      `return` branch, on its own, is cosmetic — it has exactly the effect the fall-through already
      had.
- [ ] **`member_refusal` is called inside the same `if refusal is None:` guard `transfer_refusal`
      sits in.** The validator sets `requester = None` for **any** non-`None` `origin`, before
      `operator_refusal`'s verdict has been consulted — that is safe today only because the
      transfer predicate runs under that guard. Called outside it, or with its result overwriting
      the operator refusal, a message declaring any origin string at all skips the owner check. A
      test drives `origin: "anything"` with a member action and asserts the refusal that survives is
      the origin one.
- [ ] **Every code the predicate can return renders its own sentence.** The codes are a module-level
      frozenset in `auth`, `_refusal` refuses a code outside it, and a test asserts set equality with
      the message table's keys — enumerated from that constant rather than swept from call sites, so
      the guard needs no positive control. Key equality alone is not enough and the criterion says
      so: `refusal_message` consults one table and degrades an unregistered code to
      `'We couldn't transfer the shared workspace "{space}".'`, so a second table would satisfy set
      equality while every member refusal told the user their *transfer* failed. The test asserts the
      **rendered sentence** for each member code is not that fallback.

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
- [ ] **The refusal's CONTENT splits the same way, or the member path becomes an existence oracle.**
      The four request-level refusals discriminate unknown space, not-owner, not-active and emptied
      — delivered into the notification inbox of whoever asked, for any space name they care to
      try. That is the disclosure the project already declined when it refused to publish a
      shared-space directory. An operator refusal keeps the detail, because the owner is entitled to
      it; a **UI** refusal collapses those four into one sentence that distinguishes nothing. A test
      asserts the four produce byte-identical wording on the UI path. (Transfer carries the same
      oracle today; this spec does not inherit it into two more actions, and whether transfer's own
      is narrowed is recorded as a follow-up rather than smuggled in here.)
- [ ] **A removal does not revoke a live session, and the spec says so where an operator will read
      it.** The principal tag is stamped when credentials are vended, nothing in the fleet revokes a
      token, and the pool client sets no token validity — so the ID token's Cognito default of one
      hour is the window, plus the life of any presigned URL already minted. Revocation is this
      spec's motivating case, so an operator reading it must not believe Friday's row took effect on
      Friday. The verb's own docstring already records this; the spec repeats it rather than leaving
      the honest statement only in the code.

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
- [ ] `operator_refusal`'s **behaviour** is unchanged and its tests still pass: an unknown origin, a
      message carrying both an origin and an identity block, an unset role-id configuration and a
      `SenderId` from any other principal are each still refused, in that order. Its **wording** is
      not unchanged: `TransferOriginUntrusted`, `TransferOriginNotConfigured` and
      `TransferOriginBothCredentials` each render "That request **to transfer** …", so after this
      spec a forged operator `add_members` tells the space's owner that someone tried to transfer
      their workspace. The three sentences become action-neutral, or gain a per-action form; either
      is acceptable and silence is not.
- [ ] The reader's S3 grant — object actions on the prefix and an `s3:prefix`-conditioned
      `ListBucket` — is re-pointed at `operator-requests/*`, and a test asserts the reader's only S3
      calls are against that prefix.
- [ ] Two lifecycle rules expire `operator-requests/processed/` and `operator-requests/rejected/`,
      one rule per prefix; `operator-requests/inbox/` gets **no** expiring rule, for SPEC-208's
      reason.
- [ ] **A listing of `ownership-transfers/` — all three sub-prefixes, not just the inbox — confirms
      it empty before the reader and its IAM stop looking at it.** That confirmation gates the
      *prefix move*, not merely the lifecycle-rule removal: once the reader points at
      `operator-requests/*`, a file under the old inbox is unreadable by the only thing that could
      drain it, in a prefix that deliberately has no expiry. Two consequences ride with it —
      removing an expiring rule while objects sit under it leaves them with no expiry at all, and the
      old objects have no other reaper. If the listing is not empty the objects are deleted or the
      old rules kept until they age out; if the listing cannot be run from the building session it
      goes to `docs/testing/owed.md` with the exact command, and the move waits on it.
- [ ] `docs/testing/owed.md`'s two SPEC-208 operator rows are **rewritten**, not appended to: they
      are the instruction sheet for a check nobody has run, and they currently name
      `ownership-transfers/inbox/` and a `space,new_owner` file. Left as they are, the next operator
      writes a file this reader rejects.
- [ ] Every other site still stating the old shape is corrected in the same change: the plane page
      `lambdas/info/planes/shared-spaces.md`, the SPEC-208 entry in `docs/decisions/control-planes.md`
      (which describes the queue's second producer as reading "an operator's CSV of ownership
      transfers"), `shared-space-common/config.py`'s `OPERATOR_ACTIONS` docstring, and SPEC-208's own
      spec and delivery doc, marked in place rather than left to disagree.
- [ ] No new resource family is provisioned, so no deploy-role expansion is expected — **confirmed by
      a `git diff` over `infra/modules/base/policies/` being empty**, not by a plan, which shows
      resource diffs rather than directory ones and needs credentials the building session may not
      hold. If the re-pointed grant does need one, it lands in its own PR ahead of this work.

### FR-006: The two verbs refuse a refused request, and record who asked

#### Description:

`transfer_ownership` raises `TerminalError("unauthorized", …)` when handed a context carrying a
`refusal`, and re-stamps `origin` on its span. Both behaviours become necessary for `add_members`
and `remove_members` the moment their refusals stop being raises.

#### Acceptance Criteria:

- [ ] Each of `add_members` and `remove_members` raises `TerminalError("unauthorized", …)` naming the
      refusal code when its context carries a `refusal`, and a test drives one into each. Until this
      spec their refusals were raises in the validator and no verb could be reached by one; now the
      router's `Choice` is the only thing between a refused member change and the work, and the plane
      page records why that is not enough for transfer — *"without it, any failure of the routing
      completes a real transfer"*. The same sentence, one verb over, is a stranger gaining access.
- [ ] Each verb re-stamps `origin` on its span when the context carries one, because `@traced` clears
      baggage; a test asserts an operator-driven add is not recorded as the owner adding people to
      their own space. `remove_members` emits no actor at all today and gains one, or an
      operator-driven removal is attributable to nobody.
- [ ] No other verb behaviour changes: a test asserts the slot writes, the registry delta, the
      fan-out, the index writes and the notifications for a non-refused request are what they are
      today.

---

## Data Model

```
# The operator CSV — <admin-bucket>/operator-requests/inbox/<anything>.csv
space,action,username
finance_reports,add,bcarter
finance_reports,add,rsingh
project_atlas,transfer,dmehta
sales_archive,remove,agriffith
```

`space` is the shared space's name. `action` is `add`, `remove` or `transfer` — one word per row,
because a row names one person. `username` is the member the row is about: the person taking the
space for a transfer, and the person being added or removed otherwise. **One space appears under at
most one action per file** (FR-001), and the rows sharing a `(space, action)` become one request
(FR-002) — the two `finance_reports` rows above are one `add_members` naming both people.

The reader maps each word to the action the plane already knows, and a test holds the mapping to
`OPERATOR_ACTIONS` in both directions:

```python
# lambdas/shared-space-transfer-reader/transfer_reader.py
ACTIONS = {
    "add": "add_members",
    "remove": "remove_members",
    "transfer": "transfer_ownership",
}
```

```python
# lambdas/shared-space-common/auth.py — the new predicate, beside transfer_refusal

def member_refusal(requester, space, action, targets, registry) -> tuple[str, str] | None:
    """Decides one add_members or remove_members request. Pure — no AWS calls.

    `requester` is the verified username, or None for an operator-origin request, and None is what
    skips the owner check. It must not be the context's `actor`: for an operator request that field
    carries the space's own owner, so an owner check written against it passes without the skip and
    the skip could be deleted with every test green.

    `targets` is the list the wire carries, compared in the form the verb will normalise it to. An
    absent, empty or non-list `members` is refused rather than normalised to nothing and succeeding.
    A request-level condition refuses the whole request; so does the one per-name condition, a
    removal naming the owner, because partly serving an operator is worse than telling them.
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
│   ├── transfer_reader.py            # ACTIONS: the operator's three words
│   └── test_transfer_reader.py
├── shared-space-common/
│   ├── auth.py                       # member_refusal, the code constant, the owner check leaving authorize
│   ├── config.py                     # OWNER_ONLY_ACTIONS, OPERATOR_ACTIONS
│   └── messages.py                   # the new refusal wording, and the rendered-sentence test
├── shared-space-validate/            # routing a member refusal to RefusedSeed
├── shared-space-add-members/         # the refusal fence and the origin stamp
├── shared-space-remove-members/      # the same, plus an actor on its event
└── shared-space-delete/              # the SPEC-205 inertness test, re-pointed and re-paired

infra/modules/shared-spaces/policies/transfer-reader-permissions.json.tftpl
infra/modules/analytics/s3.tf         # the two lifecycle rules, re-pointed
```

## Implementation Phases

### Phase 1: The authorization change

- `auth.member_refusal`, its code constant, its wording in `messages`, the rendered-sentence test,
  and the owner check leaving `OWNER_ONLY_ACTIONS` and `authorize`.
- The validator routing a member refusal to `RefusedSeed`, and the ASL walk asserting the arm
  notifies.
- FR-006's refusal fence and origin stamp on both verbs — they are what makes the value-shaped
  refusal safe, so they land with it and not after it.
- SPEC-205's inertness test re-pointed and re-paired, and the register entry amended in place.
- The planted mutation of the owner check, run and reverted. Note that until Phase 2 admits the two
  actions on the operator origin, `operator_refusal` refuses them first — so this phase's
  operator-skip tests call the predicate directly, and the end-to-end pairing arrives with Phase 2.

### Phase 2: The operator boundary

- `OPERATOR_ACTIONS` widened, its exact-contents assertion, the enumerated refusal of the other
  five, and the three re-worded origin sentences.
- The operator skip end to end, and the paired tests that neither half passes alone.

### Phase 3: The CSV and the prefix

- The header, the action column, the per-row syntactic checks, the one-action-per-space rule, the
  duplicate-row rule and the coalescing.
- The members-per-message cap and its Terraform read; the rows-per-invocation cap kept, with its
  rejection re-worded.
- The prefix move, gated on the empty-prefix listing: the reader, its IAM, the two lifecycle rules,
  and the doc sites that still name the old shape.
