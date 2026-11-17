---
type: Decision
title: "A name is one user's or one space's: the create refuses a user's name, writes no slot before its own database, and a teardown touches only its own (2026-09-26, rewritten 2026-11-17)"
description: "**A space's Glue database and a user's personal one share ONE namespace under the bare name**, and the session's permissions are written against that name. So the create asks the pool **after the reservation** and refuses a user's name in any status, **finishes the database step before the slot** (a slot written and rolled back has already been in any ID token issued between), and refuses a database it did not mark. All three taken-name refusals raise `NameTaken`: one sentence, `name already taken`, that never says which holder, and a card flagged `retryable: false`, so the browser drops Retry on the flag and never on the words. The revoke and the drop act only when `teardown.owns_database` is `True` — not on a missing database, which would race a user confirming under that name. Sign-up is NOT guarded: the target environment has none."
---

**Found by a data-loss audit of the control planes, and closed on the access side by SPEC-248.**
Post-confirmation makes a user's personal Glue database under the username, and create-space makes
a space's under the space name — one namespace. The permissions a session carries read "the
database called your username" and "the database called each of your spaces", so whoever holds a
name holds a catalog. The archive and table-share record the same hazard for their own keys.

**The data-loss half (2026-09-26).** The create treated `AlreadyExistsException` as a retry of
itself, so a space called `alice` adopted alice's personal database: tagged it and granted the
portal role on it, and if that create failed, or its owner deleted or forgot it while it was still
provisioning, the teardown dropped every table in alice's catalog. The create now **marks** its
database (`config.DATABASE_MARKER_KEY`, a Glue database parameter naming the space) and, on
`AlreadyExistsException`, reads it back: marked for this space is its own earlier attempt; anything
else refuses the name. **The revoke and the drop read the same test**, `teardown.owns_database`,
for the same reason `is_destroyable` is one predicate: complements written twice drift.
`teardown.carries_marker` is that rule over a record already in hand, which the name-collision
report reads instead of a second copy.

**The access half (SPEC-248).**
- **The pool check runs after the reservation, inside the guard, and before any prefix, database or
  slot.** `AdminGetUser` on the requested name: a user in any status, unconfirmed included, refuses
  it; `UserNotFoundException` lets it through; any other answer is a fault and never read as "no
  such user". After the reservation because the state machine retries the create verb: a retry
  refused before reserving would go through the reserve-collision branch, which writes no record,
  and leave the reservation `provisioning` for good. Refusing after it leaves a `failed` record the
  owner can forget. In the verb and not in the API's route, because the API plane holds no pool read.
- **The database step runs before the slot.** Under the `claims` membership source the API stamps
  whatever the ID token carries, so a slot written and then rolled back has already granted the
  name to any token issued in between, for that token's hour. A membership-limit refusal now
  arrives after the database exists; it carries the marker, so the failed record's teardown drops it.
- **One sentence, one type, one flag.** The reserve collision, the foreign database and the pool
  refusal all raise `registry.NameTaken`, a `ProvisioningError` whose message is
  `name already taken`, so no refusal tells a user from a space from an orphaned database. Each is
  refused again at the same step for as long as its holder exists, so both failure branches write
  `retryable: false` on the creator's card for a `NameTaken` and for nothing else — an S3 fault, an
  exhausted compare-and-swap and the membership limit keep Retry. The card drops Retry on the flag;
  matching the sentence would make the browser key on wording.
- **The revoke stops unless the database is the space's own.** It used to carry on when there was
  no database at all. A refused create leaves none, and forgetting it while a user of that name
  confirms would race post-confirmation and revoke the grant it had just made on that user's new
  database. A missing database has no grants of this space's to revoke.
- **What already existed is reported, not repaired.** `shared-space-name-collisions` is a one-shot,
  read-only function dispatched by `report-name-collisions.yml`: usernames that are real spaces,
  user databases marked as a space's, slots no roster backs, users whose database predates them,
  and, for information, refused reservations named for users, unmarked space databases, orphan
  databases and the Lake Formation opt-ins. A failed read makes its lists `null`, never empty, and
  fails the run. It runs under the orchestrator role, which can write, so "writes nothing" rests on
  its test recording every call; a dedicated read-only role for a one-shot was weighed and not built.

**Do NOT build:**
- A backfill that marks the databases of spaces created before the marker. Marking is what lets the
  teardown drop a database, so it is the one path that could bring back the data loss this closed,
  and its only evidence would be circumstantial. Leaving them unmarked costs residue, which the
  report's orphan list names.
- A check where credentials are minted (`apicommon/identity.py` reading Glue before it stamps a
  tag). Every credential, file transfers included, would depend on Glue being reachable.
- Space databases named so they cannot overlap usernames: users type these names in SQL, and
  existing spaces would need a migration (Andrew, 2026-09-26).
- A guard on sign-up in this account. The target environment has no self-sign-up and its database
  names are predetermined (Andrew, 2026-11-17), so a stranger signing up under a space's name
  still inherits that space's catalog here until the account is decommissioned, and the report
  names anyone who already has.

**The cost, accepted:** a space created before the marker is unmarked, so tearing one down leaves
its database behind, and a create that failed before the marker existed can never be retried or
reused under that name. With no users on the plane that is a name, not data.

## History

### 2026-11-17

- **Rewritten in place by SPEC-248:** the entry doors the 2026-09-26 entry left open are closed on
  the side of spaces — the pool check, the database before the slot, `NameTaken` and its flag, the
  revoke only on a database the space owns, and the report. The title no longer says a space may be
  named after a user. Sign-up stays open, by decision.

### 2026-09-26

- **Settled:** entered the register.
