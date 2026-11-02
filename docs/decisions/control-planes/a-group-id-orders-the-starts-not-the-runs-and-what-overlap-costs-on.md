---
type: Decision
title: "A group id orders the STARTS, not the runs, and what overlap costs on each plane (control-plane-wide)"
description: "**An `IF NOT EXISTS` create reports somebody's success, not necessarily yours.** It is what makes a retry a no-op, and a run that lost a race runs exactly the same no-op — so the statement succeeding is no evidence THIS run built the table, and a plane that reports on it alone is speaking for whoever won. Table-builder confirms instead: it reads the table back and refuses `table_exists` unless the catalog carries the LOCATION, the partition keys and the projection this run declared, compared through the parser and the renderer that built the statement rather than a second copy of either. Table-share's create is the same statement and still tells both runs they succeeded. **A `MessageGroupId` orders the STARTS, not the runs, on every Pipe-fed plane.** The Pipe starts a Standard machine `FIRE_AND_FORGET`, and the message leaves the queue when `StartExecution` returns, so the next one in its group starts while the first still runs. A plane whose runs must not overlap needs a guard of its own: a lock, a conditional write, or a key unique to the run. Notifications and feedback are the exception: an event-source mapping drains them, and that does hold a group to one invocation. What overlap costs, plane by plane."
---

Found 2026-09-15, auditing every plane's prose once the archive plane's claim that its group ids
serialize runs turned out false. Six more planes said the same thing of their own: shared spaces,
table builder, table share, file send, data quality and results conversion.

**The mechanism.** Every Pipe starts its Standard machine `FIRE_AND_FORGET`, the only mode AWS allows
a Standard workflow, and the message leaves the queue once `StartExecution` returns, after which
the Pipe sends the group's next message. So a `MessageGroupId` orders the starts, and a start that
fails holds the group's next one back until its retries run out; nothing stops a second run
beginning while the first is still going. File-ops' live check watched exactly that on 2026-09-10
(`docs/testing/owed.md`, *Two file operations in one space do not run at once*). The two queues a
Lambda event-source mapping drains, notifications and feedback, are the exception: a mapping runs
one invocation per FIFO group at a time, so their group ids do serialize their writers.

**What overlap does, plane by plane.** File-ops holds a per-space lock and the table-builder refresh
a per-table one, which is why neither appears below; the archive plane's arms are its own
[entry](../archive-and-restore/the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md).

- **Shared spaces: the name is unique without the queue.** `registry.reserve` creates the record
  with `If-None-Match: *`, so of two users submitting one name at once one is refused
  `name already taken` and the winner's record is untouched; the constant group id adds nothing to
  that. The registry's other writes, bar the final delete, the per-user cache and the membership
  index re-read and write under ETag CAS, which keeps each document whole. What CAS does not
  re-check is what the verb was authorized on — **and a CAS on one document orders nothing against
  a write to another, which is the second half of this arm.** **Repaired 2026-09-15 (Andrew), in
  the granting direction only:** `save_members` and `set_status` took an `expected_owner` and
  refused with `OwnerChanged`; `save_members` still does, and `set_status`'s check moved into
  `begin_delete` on 2026-09-26 (one on the emptying rewrite was tried and dropped, as below) —
  passed by the add, and only for a delta that
  actually ADDS somebody, since one that grants nothing needs no re-authorization and refusing it
  would turn an idempotent no-op into a failure. The delete carries it on the cascade's FIRST
  WRITE, the deleting status, rather than on a read: a read can only be re-checked by the write
  after it, and there a refusal has written nothing to a record it may not touch, and hands the
  space back rather than writing `failed` onto a record that is now somebody else's. **A transfer
  landing LATER, during the revocation loop, is not caught — and that is the decision, not the
  gap.** Three arrangements were tried and each was worse, which is the part worth keeping:
  refusing on the emptying rewrite arrives after every grant is gone, the new owner's included,
  and an owner's slot is one no ordinary verb can re-issue because the add normalises the owner
  out; emptying before revoking closes that but clears the owner and roster before anyone is
  revoked, so a Lambda killed mid-loop — a timeout is none of the four errors this fleet's
  machines retry — strands every unreached grant on a record naming nobody, unreachable even by a
  retry; and a repair that gave the revoked grants back wrote the new owner a MEMBER card, could
  re-grant over a delete the new owner had meanwhile started, and swallowed the one failure that
  mattered. Losing the space to a late delete is recoverable — the objects, the database and the
  name all survive an emptying, which is why emptying exists — and a grant nobody can see is not.
  **Revoking first is kept for a different reason than the refusal**: a FAULT in the main loop
  leaves the record untouched and the retry idempotent. It does not make a hard KILL safe, it
  only shrinks the stranded population to the latecomer pass, since the rewrite has blanked the
  roster by then and the replay reads it back empty.
  `set_owner` now also refuses a target who left the roster
  (`TransferTargetNoLongerMember`), which closes an owner who is not a member **when the removal
  lands first**: being the owner is itself the access. The other order, a transfer to the leaver
  or the removed member landing first, was open until 2026-09-26, when `save_members` began
  refusing a removal naming the record's current owner
  ([entry](a-delete-decides-its-route-on-the-record-it-claims-and-a-removal-cannot.md)). **`remove_members` is otherwise deliberately NOT repaired** — a
  late remove revokes rather than grants, and `MembershipRefused` already decides that refusing
  one strands a member who slipped through; `expected_owner` is a general parameter, so it is one
  line if that reading changes. The roster fan-out now runs under the owner the COMMIT carries, at all four sites that
  passed the validator's, and writes nothing at all when the commit carries none — which also
  stops a late leave or remove re-creating every member's cache card for a space a delete has just
  emptied. Those cards are the browser's affordances, re-authorized at the validator, so that half
  was cosmetic. **The membership index was not:** the add wrote it AFTER its registry commit, so a
  delete's revocation landing in between let the add re-create the entry — `status` active, which
  is what an emptied record deliberately keeps — and the API's index source stamps a principal tag
  for any active entry. Reproduced against the verbs, and repaired the same day by writing every
  GRANT before the commit and only revocations after it, with the add rolling back both grants on
  any failure of the commit: a delete emptying after the commit finds the member in the record
  `empty_space` hands back, and one emptying before it makes the commit refuse. Latent while
  `MEMBERSHIP_SOURCE` is `claims`, which is every environment — the slot is the grant there, and
  the delete clears it. **Still live, and recorded rather than repaired:** CAS on an absent record
  writes create-only from the caller's snapshot, so an owner verb landing after a teardown's final
  delete recreates the record — `save_members` and `set_status` are the two that fall back that
  way, and `save_members`' owner check evaluates against that snapshot, so it does not close this; member
  actions are refused on anything not active, so it reaches only a never-active space, such as an
  owner's retried create racing their own delete. `create-space` writes its own index entry AFTER
  `finalize`, and that one cannot take the ordering above: the record reads `provisioning` until
  `finalize`, so an entry written earlier would name a space no session may reach — its own
  docstring argues that, and it still holds. So the create has the add's old shape, and it needs
  no absent record to bite: a creator deleting their own space in the window after `finalize`
  has their entry re-created over an emptied record, permanently, because an emptied roster names
  them nowhere any verb will sweep. A self-grant over their own retained objects, which is what
  caps it. `finalize` used to widen this — it builds its record from a literal, so on a freed name
  it re-created the record rather than refusing — and since 2026-09-26 it refuses an absent,
  claimed or re-owned record ([entry](a-delete-decides-its-route-on-the-record-it-claims-and-a-removal-cannot.md)), which leaves the two above as the
  only create-only fallbacks. The add's rollback is best-effort by design and skips anyone on the roster it reads, so
  on the destroying route a read landing before the record is deleted keeps both grants over a
  name that is then freed. The narrowing second index write has a residual of its own, in the
  denying direction: a delete dropping the entry between the commit and that write re-creates it
  non-granting, and nothing sweeps it, so a member can be denied a space the roster later allows. And the Cognito membership slots are no document at all:
  `assign_or_find_slot` reads the user's attributes and writes one slot with no condition, so two
  spaces adding one user at once can pick the same free slot, and the user keeps only one of the
  two grants while both rosters list them — a denial rather than a grant, in every interleaving,
  which is why it is the one left alone.
- **Table builder: a create still holds no lock, and now says so when it loses.** Two same-name
  creates in one database both pass `check-table-absent`, a point-in-time `GetTable` with
  `InspectSource` and `InferSchema` between it and the DDL, and the second
  `CREATE EXTERNAL TABLE IF NOT EXISTS` is a no-op over the first one's table. What changed
  (2026-09-15) is what that no-op is reported as. `execute-ddl` now reads the table back and refuses
  `table_exists` unless the catalog carries the LOCATION, the partition keys and the per-key
  projection properties **this** run declared — the three facts the request states, compared through
  the parser and the renderer the DDL itself used — so the loser is told the name is taken instead of
  that its table is ready to query. A replay still succeeds, because a retry meets its own table,
  which is the property `IF NOT EXISTS` is there for. The fix is a post-condition, not a lock:
  nothing is serialized, both runs still pay the whole inspection and inference, and nothing is
  overwritten. **The residual is the DATA COLUMNS, and only them** — two creates over the same
  folder whose partition declarations also match to the property agree on all three facts and are
  both told created, and the columns are then whichever run's inference landed. That is a
  difference of sampling rather than of request: both inferred from the LOCATION they agree on, and
  a single create already reads one sample file. **Every field the request itself states is
  compared**, which is why the projection is matched per key by EQUALITY inside that key's own
  `projection.` namespace and not by containment: `digits`, `interval` and `interval.unit` are
  optional, so a declaration without one is a strict subset of a declaration with it, and
  containment told a run declaring `month` its table was ready over a table generating `month=1`
  where its own request asked for `month=01`. Outside a declared key's namespace nothing is
  compared, so `projection.enabled` and any property AWS writes of its own accord cannot refuse an
  ordinary create.
  **A confirmation a run cannot make is reported as a failure, decided 2026-09-15 (Andrew).** That
  is the one thing here a user sees beyond the loser's refusal: a deterministic Glue fault on the
  read-back reports `ddl_execution_failed` over a table that exists, and a table still invisible
  after `ExecuteDdl`'s Retry reports the generic sentence, because the absence is raised as
  `TransientError` so the machine looks again rather than failing a create that landed. Both are
  near-unreachable — the role holds `glue:GetTable` and is this plane's LF admin, and a missing
  `CREATE_TABLE` grant fails the Athena statement long before the read-back — and the alternative
  was reporting an unconfirmed success as a success, which is the class this whole entry is about.
- **Table share: one table, told twice.** `check-target-absent` reads the catalog and then the
  prefix, the copy is an unconditional `CopyObject` into `{recipient}/shared_tables/{table}/`, which
  no run owns alone, and the create is `IF NOT EXISTS`. Two shares of one source to one recipient
  under one name, the second guarded before the first has created the table or landed an object,
  both clear the guard, copy the same keys and succeed, and each notifies; a double-submit that
  straddles the 60-second dedup bucket is enough. Anything written at
  those keys between the first copy and the second is overwritten. If the source is rewritten
  between the two runs' listings, the two can copy different object sets into the one location —
  each builds its manifest from whatever plan is at its plan key when it gets there, and two
  members' shares do not even share that key, since it digests the actor — and the table then
  reads both snapshots.
- **File operations: the lock serialises the plane, not every writer.** `check-destinations`
  heads each planned key twice, the second immediately before the transfer, and the copy is then
  an unconditional `CopyObject`, for as long as the Map runs. The per-space lock orders one file
  operation against another, but not a browser upload, an API document write, a restore's
  copy-back or a delivery into the space — so a file landing at a planned key mid-transfer is
  overwritten and the run reports success, under the `refuse` answer as well as `overwrite`. Found
  by the control-plane data-loss audit on 2026-09-26.
- **File send: an overlapping send can overwrite what the recipient did with the first.** The guard
  lists the names already in `shared_files/{sender}/`, and the copy is an unconditional `CopyObject`.
  A second send of an item to one recipient, submitted before the first run's copy of that name
  lands, clears the guard beside the first; it re-copies what the first delivered, and a file the
  recipient edited in between is overwritten with versioning off. The window lasts as long as the
  first run's copy, up to the three-hour ceiling, not only while two sends are "submitted close
  together". Separately, the plan and the manifest are keyed by request id and this plane has no
  `request_id_reused` refusal, so a hand-built request reusing an id past the five-minute dedup
  window shares both keys with the first, and one run can copy the other's plan — names its own
  guard never checked — over a recipient's files. The browser mints an id per submit and cannot.
- **Data quality: the request id is claimed.** Every per-run key — the temp tables, the manifest,
  the report, the query results and the Athena tokens — is derived from the request id, and one
  execution claims the id before any of them exists, so a second execution sending it past the dedup
  window is refused before it lists a file ([the claim](a-data-quality-request-id-is-claimed-by-one-execution-before-anything.md)). Two
  checks of one location with different ids are independent, and the runs index is written under
  ETag CAS.
- **Results conversion: the write is the guard.** The one object is written with `If-None-Match: *`
  unless the request asked to overwrite, so the loser of two overlapping saves to one name is
  refused `destination_occupied`. Two overwrites of one key land in the order they finish rather
  than the order they were submitted.

**Decided 2026-09-15 (Andrew): record now, and repair file send and table share in the follow-up
spec [decided the same day](../archive-and-restore/the-group-id-orders-the-starts-not-the-runs-and-the-restore-guard-is.md)
for the archive restore's copy-back — and on 2026-09-26 he folded the file-operations arm into that
same spec, under the `refuse` answer.** All of them overwrite through the
one copy engine, `cpcommon.transfer`, and the repair chosen there — `If-None-Match: *` on
`CopyObject` and `CompleteMultipartUpload` — makes "never overwrites" true at every write on each
plane, which is the promise the Help page already makes for a send and for a share. It does not by
itself make the losing run report a conflict: the engine records a `412` as an ordinary per-item
failure, and both collectors turn any failed item into `copy_failed`, so the spec owes that mapping
too, and for table share an answer to two runs that each lose a key to the other and leave a
half-copied prefix with no table. The same spec adds a `request_id_reused` refusal to file send, as
archive and file-ops carry. Until it lands, the file-operations, file-send and table-share arms
above are live.
The table builder's misreported create is closed above, by a post-condition rather than a lock,
and its own residual is named there.

**The shared-space residuals were triaged separately on 2026-09-15 (Andrew), and the granting ones
repaired the same day.** The trigger was an audit claim that the add's membership-index write could
outlive a delete's revocation; it was reproduced against the verbs rather than taken on report, and
it is the only one of the six that grants under a source no environment runs yet. The rule that
came out of the triage, and that the arm above applies: **the direction decides the response.** A
residual that DENIES what the roster allows — the slot collision, a late remove — is recorded and
left, because refusing it strands somebody and the wrong choice costs a re-add. One that GRANTS
what the roster denies is repaired, and the repair is an ORDERING rather than a check wherever one
exists: a check across two documents has no atomicity to lean on, where writing the grant before
the commit makes a concurrent delete's own sweep the thing that catches it. What that ordering
costs is a member briefly holding a grant no roster shows, which is the shape the Cognito slot
already had and the reason a rollback sits beside it.

This audit corrected the sites it found claiming a group id serializes runs, and marked each one a
register, delivery doc or spec carried in place rather than rewriting it; the cancelled
file-converter spec, which never shipped, was left as it was. The fence clause is what should catch
the next one, at authoring.

## History

### 2026-09-26

- **Changed:** `save_members` began refusing a removal naming the current owner, `set_status`'s owner check moved into `begin_delete`, `finalize` refuses an absent, claimed or re-owned record, and the file-operations arm joined the copy-engine repair spec.

### 2026-09-15

- **Settled:** entered the register.
- **Changed:** Shared spaces' granting races were repaired with `expected_owner` and grants written before the commit, and table-builder's `execute-ddl` now reads the table back and refuses `table_exists`.
