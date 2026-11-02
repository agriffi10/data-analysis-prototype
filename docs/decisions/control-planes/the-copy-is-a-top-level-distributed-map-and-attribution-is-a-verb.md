---
type: Decision
title: "The copy is a top-level Distributed Map, and attribution is a verb (SPEC-160)"
description: "Table-share's copy is one top-level Distributed Map over a flat recipient-by-object manifest, and `collect-transfer-results` attributes by reading both the SUCCEEDED and the FAILED/PENDING exports; one failed item means that recipient gets no table."
---

Sharing a table used to copy every object for a recipient inside **one** `copy-objects` invocation,
inside a `Map` over recipients. The share caps followed from that: `SHARE_MAX_OBJECTS = 1000` and
`SHARE_MAX_TOTAL_BYTES = 20 GiB` were sized backwards from a 900-second Lambda timeout. A user with
several hundred Parquet part files did not get a slow share; they got a refusal that read like a
product decision and was really an implementation detail.

The copy is now a **top-level Step Functions Distributed Map** over a flat `(recipient × object)`
JSON Lines manifest in the admin bucket, batching items into the same copy code as before.

**Top level, NOT nested inside the recipient `Map`.** The nested version is the obvious one and it
buys nothing: it fans out per recipient, so the ceiling stays per-recipient work. One Map over pairs
covers every recipient at once and never raises the nesting question. It costs exactly one thing,
and that cost is this decision's other half: **per-recipient isolation stops being a property of a
Map item.**

**So attribution became a verb, and it reads BOTH result groups.** `collect-transfer-results` reads
the Map Run's `ResultWriter` export. Step Functions files a child by its **execution status, not by
what its payload says** — and the batch copier deliberately **succeeds** while reporting per-item
failures, so those land in `SUCCEEDED_n.json`. A collector reading only `FAILED_n.json` would report
universal success while a recipient received an incomplete dataset **and a table over it**. It
therefore reads `SUCCEEDED_n` (per-item `failures` from the output) **and** `FAILED_n`/`PENDING_n`
(whole-batch failures, attributed from the child's *input*). A record whose payload Step Functions
omitted (`Included: false`) is **unattributable and fails the whole request** — never "no failures
found". One failed item means that recipient gets **no table**: a partial copy under a table
definition is worse than no table at all.

**`ToleratedFailurePercentage: 100` and `STANDARD` children.** The Map Run must always finish, or
there is nothing for the collector to attribute. Children are STANDARD because a batch may hold a
multi-GiB object whose multipart copy exceeds EXPRESS's five-minute ceiling, and EXPRESS's
at-least-once semantics would re-run whole batches.

**A WHOLE-batch failure fails every recipient in that batch, and that is fail-closed on purpose.**
Items are batched in recipient-major order, so a batch spans several recipients only when a
recipient has fewer objects than the batch size — but when it does, a child execution that dies
outright (an exhausted `TransientError` retry, a Lambda timeout) takes all of them down with it. It
reported nothing per item, so which of its items landed is genuinely unknown, and the conservative
answer is the only honest one. Pre-160 each recipient had its own invocation and its own retry
budget, so this is a real narrowing of isolation, accepted deliberately: the alternative is trusting
a copy nobody observed. A Distributed Map cannot partition batches by key, so a per-recipient
guarantee would mean a Map per recipient — the nested design this decision rejects.

**Attribution keys on `(kind, name)`, never the name alone.** A destination is a pair, and nothing
in this system stops a shared space being named after a user (the archival arc records the same
hazard for its key layout). Keyed on the name, one failed object in space `acme` would deny user
`acme` a table they actually received, and send them a failure notification for it.

**The export is reconciled against the manifest, not merely parsed.** Every unrecognised shape
raises — an entry naming no object, a result file that is not a list of records, a record with no
item count — because a reader that skips what it does not understand reports a clean run over an
export it never read. Shape checks alone are not enough, though: a well-formed export can still
cover only some of the batches, so the collector requires the item count the export accounts for to
equal the count `build-transfer-manifest` wrote. Anything less is a whole-request failure.

**The raw `{Error, Cause}` is decoded at the collector and NOT carried onward.** This is a payload
decision. A Cause runs to hundreds of bytes with its stack; leaving `guardResults` on the state
*and* re-emitting the raw error in the outcomes would put three copies of every refusal on the state
by the time the finish Map merges its results — measured at **108% of the 256 KB limit** for 50
conflicting recipients, which is the *ordinary* case of re-sharing a table most recipients already
have, and a breach there lands **on a Map** and destroys every per-recipient outcome. So the
collector **consumes** `guardResults` and carries `cpcommon.errors.failure_reason`'s decoded code;
the raw object remains in the execution history at the state that produced it. The two peaks — the
guard Map's output and the finish Map's — are both modelled by
`test_the_whole_map_state_stays_under_the_payload_limit`, at 42% and 45%.

**A deterministic item failure never raises; a transient one always does.** The batch returns
per-item outcomes and succeeds, so one unreadable key never costs its 49 siblings their copy. A
throttle raises after every in-flight copy settles, and the Map retries the whole batch — safe
because copy is idempotent and the conflict guard has already run. The `CopyObjects` child state
carries **no `Catch`**: catching there would SUCCEED a failed child, filing it under `SUCCEEDED_n`
with no per-item failures, and every item in it would be reported as copied.

**The manifest key is execution-unique; the copy plan beside it is deliberately not.** A plan is a
pure function of the request, and two overlapping executions colliding on one plan key is harmless
because both plans describe the same object set — that argument is written out in `plan_key`'s
docstring and still holds **— superseded in part 2026-09-15: only while the source is unchanged
between the two listings, the residual that docstring itself names; if it changes, the two runs
copy different sets into one location ([the group id entry](a-group-id-orders-the-starts-not-the-runs-and-what-overlap-costs-on.md)) —**. It does **not** carry to the manifest: its lines depend on which
recipients the **guard accepted**, which is time- and destination-dependent, so a shared key would
let one execution's Map Run copy for a recipient the other's guard had just refused as `conflict`.
The execution name is stamped by a **Pass** state (SPEC-157's measured pattern: reading `$$` in a
task's own `Parameters` wraps the payload, and every notify path here reads the request at the top
level).

**The Distributed Map's permissions are the STATE MACHINE role's, not the Lambda execution role's.**
It is the state machine that calls `StartExecution` for each child and that reads the `ItemReader`
object and writes the `ResultWriter` export. Putting them on the execution role renders green,
applies green, passes a policy-render test, and fails on the first real share with `AccessDenied` at
the `ItemReader` — naming a role nobody was looking at. `StopExecution` is not granted;
`StartExecution` + `DescribeExecution` is the documented least-privilege pair. A test asserts the
`states:` actions appear in the SFN policy and **not** in the execution policy.

**The engine lives on `cpcommon.transfer`, not `tscommon`.** SPEC-164→167 (send files) is the second
caller and SPEC-168→172 (archive) the third; SPEC-156 already settled that `cpcommon` owns the
algorithm while a domain layer owns its wording and key layout. `tscommon.copy` was **deleted**, not
wrapped — a re-export shim is the deliberate twin that spec exists to prevent. Table-share keeps the
manifest **key layout** (`copy_plan.transfer_manifest_key`) and every user-facing sentence.

**S3 Batch Operations is rejected, not deferred** — see the amendment on the *Table Share* entry
above. The refusal is a property of the API (`TargetKeyPrefix` prepends to the full source key; 5 GB
per object; one destination bucket per job), not of the implementation it was proposed to replace.

**The caps did not move.** 160 changes the mechanism and nothing a user can see: same push, same
conflict rules, same notifications, same `SHARE_MAX_*`. That ordering is deliberate — a regression in
a new engine must not be able to hide behind a new limit. SPEC-161 raises the ceiling.

**Two numbers live in two places, and a test holds them together.** `MAX_ITEMS_PER_BATCH` and
`MAP_MAX_CONCURRENCY` (20) are read by the batch verb from `cpcommon/transfer/config.py` and by the
rendered ASL from `locals.tf`, because Terraform cannot import Python. The batch size is sized
against S3's *worst case* — two 1024-byte keys and two 63-byte bucket names put an item near 2.3 KB,
so even 50 items sat under half the 256 KB child-execution input limit — and that bound is
**computed in a test**, not asserted as a number.

> **Superseded (SPEC-161, 2026-08-10) — `MAX_ITEMS_PER_BATCH` is 8, and the PAYLOAD bound is no
> longer the binding one.** `ItemBatcher` batches by **count, never by bytes**, so the unit that
> must copy inside `copy-objects`' 900 seconds is a whole batch. That was implicit while
> table-share's total cap was 20 GiB — a batch could not exceed the whole table — and SPEC-161's
> 1 TiB removed it.
>
> **And a batch's cost is a MAKESPAN.** `copy_batch` hands one whole object to each of
> `COPY_CONCURRENCY` workers and `copy_one` part-copies serially, so the cost is
> `ceil(items / COPY_CONCURRENCY)` rounds of the slowest object — never total bytes over an
> aggregate rate. **8 = `COPY_CONCURRENCY` makes that ceiling one**, so a batch costs one object's
> time (429 s at `SHARE_MAX_OBJECT_BYTES` 10 GiB). At 10 items it was two rounds and 859 s against
> a 900 s timeout; the bytes-over-bandwidth reading called the same configuration 537 s and stayed
> green. `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the makespan and
> `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality. **The batch size,
> `COPY_CONCURRENCY` and table-share's per-object cap can no longer be changed independently.**

## History

### 2026-09-15

- **Changed:** Two overlapping runs colliding on one plan key is harmless only while the source is unchanged between the two listings.

### 2026-08-10

- **Settled:** SPEC-160.
- **Changed:** SPEC-161 set `MAX_ITEMS_PER_BATCH` to 8, because a batch's cost is a makespan and the payload bound no longer binds.
