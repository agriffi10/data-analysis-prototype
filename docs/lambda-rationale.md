# Lambda Rationale

Long-form reasoning that used to live as narrative module docstrings and inline comments in
`lambdas/`. Moved here when the Lambda tree adopted the Google-style docstring standard
(`lambdas/info/best-practices/python/python.md` §14): a docstring states the interface and the
short *why*, and anything longer than a paragraph belongs in a doc.

Read the entry for an area before changing it. Where a claim is already a settled project
decision, the authority is `docs/decisions.md` — this file records the working detail and
the evidence behind it, not the decision itself.

---

## `cpcommon/__init__.py` — the layer's import-free root

`cpcommon/__init__.py` must not import anything, and this is load-bearing rather than
tidiness (SPEC-137 FR-001).

Anything imported from the package root runs for every function that attaches the layer,
whether or not that function uses it. Three functions — `pre-signup`, `post-confirmation`
and `notifications-writer` — attach the layer for one or two modules and set almost none of
`cpcommon.config`'s environment.

**The original reason was a fail-fast, and it expired.** `cpcommon.config` used to call
`_require()` on six variables **at import time**, so a single import added to the root broke
all three at cold start — on `pre-signup` a Cognito trigger, so it broke sign-up itself. That
is not hypothetical: it shipped, and it broke sign-up for nine days. SPEC-156 FR-004 moved
that resolution to **first access**, because the eager version was also the reason
`notifications-writer` could not import `cpcommon.auth` and carried a second copy of the
fleet's JWKS verifier.

**The rule survives its original reason, on cold-start cost.** The root is imported by every
control-plane verb, so a submodule imported there is paid for fifteen times over —
`type_mapping` alone would pull polars, ~100 MB, onto functions that never read a Parquet
footer.

Pinned by `test_layer_import_safety.py`, which holds the property with **two** mechanisms
because neither covers the other: an AST scan of each singleton's whole file against a
per-function allowlist (it sees a `cpcommon` import in a **function body**, which runs on a
later branch rather than at cold start), and a **subprocess** import of each singleton with
the six variables withheld (it sees what a module actually *touches*, including through a
module it never names). An in-process test can do neither, because `conftest.py` stamps the
six variables before collection.

The package is a package (`python/cpcommon/`) rather than flat modules so its module names
(`config`, `auth`, …) cannot collide with the domain layers' or `shared-space-common`'s
under one pytest run.

## `cpcommon/ddl.py` — why the storage clause is injectable

Identifier quoting, the column body, `PARTITIONED BY`, the projection `TBLPROPERTIES` and
the statement assembly are shared across the arcs. The **storage clause** is deliberately
not (SPEC-111 FR-001/FR-002), because the two arcs disagree on purpose:

- table-builder writes JSON with the **OpenX** SerDe — its shipped behaviour, unchanged.
- data-quality writes it with the **Hive** SerDe, because AWS documents OpenX as
  potentially non-deterministic around nulls, and the whole data-quality JSON story is
  "a null means the key was missing".
- data-quality also builds a single-column raw-line table with `LazySimpleSerDe` that has
  no analogue in table-builder at all.

So `storage` is injectable: pass nothing and you get the table-builder defaults; pass a
`Storage` and you get exactly your clause plus your properties. A domain's SerDe choice
belongs in that domain's layer, next to the reason for it — not in a shared `if fmt ==`
ladder that reads as if one of the two arcs is wrong.

The consolidation itself (from `table-builder-infer-schema/ddl.py`, SPEC-069) was the same
move as `cpcommon.type_mapping`: the projection-props logic is fiddly, easy to get subtly
wrong, and must not exist twice.

## `cpcommon/type_mapping.py` — polars in a layer every verb attaches

This module imports **polars**, and `cpcommon` is attached to **every** control-plane verb.
Importing it from a verb that does not also attach a polars layer is an `ImportError` at
**cold start**. Only two functions carry polars today:

- `table-builder-infer-schema` (the `table-builder-polars` layer)
- `data-quality-inspect-source` (the `data-quality-polars` layer)

Every other verb — 15+ of them — attaches `cpcommon` without polars.

Living here is safe **only** because `cpcommon/__init__.py` imports no submodules, so this
file is loaded if and only if something explicitly imports it. Do **not** add
`from . import type_mapping` to that `__init__`: it would break every polars-free verb the
instant it deployed, which is the shape of the PR #196 outage — a shared layer's import-time
requirement that only some functions can satisfy.

Adding a polars-carrying verb? Give it `cpcommon: true` **and** a polars layer in
`deploy-lambdas.yml`'s matrix, and check the combined per-function size guard.

## `cpcommon/observability.py` — the field rule's edges

The field rule itself is a **Key Decision** and lives in `docs/decisions.md` (SPEC-130) —
read it before instrumenting any call site. Recorded here are the three things about it that
are working detail rather than decision.

**The stack-trace exemption, decided rather than overlooked (user decision, 2026-07-23).**
`log-foundry`'s `end_event` attaches `traceback.format_exception` to every failed span, and
that walks the `__cause__` chain — so an exception whose cause quotes a cell (a polars parse
error naming the value it could not convert) carries that text into `error.stack` no matter
what a call site does. Accepted, not stripped: `logs/` is admin-only, and a stack is
diagnostic metadata an admin debugging a failed run needs. The rule binds what a verb
*chooses to put in a field*; it does not bind an automatic traceback. **Do not read a stack
trace as licence to relax the field rule.** Pinned by
`test_ACCEPTED_the_span_error_stack_may_carry_file_contents`.

**The email hazard is mechanical, not hypothetical (SPEC-137 FR-005).** A Cognito trigger
event carries `request.userAttributes.email`, so a single `info("signup", event=event)` — the
most natural line anyone writes while debugging a trigger — publishes it. **Never log a raw
trigger event, an attributes map, or any dict you did not build field by field**: the leak
arrives nested, where a field-name check cannot see it. Usernames are a different case and
are *not* sensitive here — the username already is the S3 prefix, the principal tag and the
Glue database name (SPEC-033), so it is the primary key of every operator-facing record
already.

**One run is nine traces, not one.** A data-quality run is nine Lambda invocations and
`log-foundry`'s trace context is per-process, so `trace_id` never crosses a Lambda boundary
and `parent_span_id` is always null at a handler's root span. Correlate on
`fields.request_id` instead (SPEC-128 FR-002). The fix, when it is worth the cost, is
`lf.continue_trace(traceparent)` — shipped as of log-foundry 0.3.0 — plus threading the
traceparent through the Step Functions state payload on every state, exactly as `reportKey`
is threaded today. Deliberately sequenced after the pipe is proven live.

## `log-sweep` — why a sweep is a loop of waves

The sweep drained the queue at a fixed **20 messages per invocation** for weeks, reported itself
finished every time, and put the log store six days behind on a fourteen-day retention. Found
2026-08-14 while trying to read back a record for SPEC-186 FR-005; the queue held 15,164 messages
and `logs/service=observability/` was still writing the `day=08` partition on the 14th.

**The mechanism is FIFO ordering, not polling luck.** On a FIFO queue a message group stops
yielding once one of its messages is in flight, until that message is deleted or its visibility
lapses ([FIFO delivery logic][fifo]). The receive loop held everything it took for the duration
of the loop, so after one round per group every group it had touched was blocked *by the loop
itself*; the next round came back empty and the loop returned. The backlog sat in exactly two
groups (`observability`, `dlq-drain`), which is why the number was always exactly 20 — 10 per
group, never varying, which is the signature of a structural limit rather than a sampling one.

**Why `WaitTimeSeconds` was not the bug, and long-polling is not the fix.** A short poll does
return spurious empties, and that was the first theory. It does not survive the evidence: a
sampling artifact produces a varying count, and twelve consecutive sweeps returned exactly 20.
Long-polling would also have reversed a recorded decision (`decisions.md` → *structured logging*,
#270/#271) while fixing nothing — a blocked group does not become unblocked by waiting for it.

**Why the receive, the write and the delete have to repeat together.** Deleting is what unblocks
a group, and a message may only be deleted once its events are durable in S3 (put-then-delete;
losing logs is worse than duplicating them). So the unit that can repeat is the whole cycle, not
the receive. That is the wave.

**Sizing.** `MAX_WAVES = 50`. The bound that matters is the **arrival rate**, not the backlog
depth — a backlog is drained over several sweeps, and only the rate has to be beaten. Measured
arrival is ~3,300 records/day (~1.5 MB/day at a measured 454 bytes/record), or ~23 per
ten-minute tick. A wave yields at most `10 x unblocked groups`, so the worst case that still has
to converge is a single backlogged group: 10 per wave, 500 per sweep, 72,000/day — 22x arrival.
`SWEEP_RESERVE_MS = 60_000` exists because `MAX_WAVES` bounds the wave count and not the
duration: a wave rewrites each day object in full, that object grows all day, and the 300s
timeout is the real ceiling. Peak memory is one wave (`MAX_MESSAGES`), not the sweep.

**Stopping is three different things and they want opposite responses.** A sweep that stops with
the queue possibly still yielding reports *why*: `wave-cap` (raise `MAX_WAVES`), `time-reserve`
(the day objects have grown enough that a wave no longer fits — raise the timeout, or look at
the growth), `group-blocked` (see below). The clock is checked before the wave cap, so when both
hold the harder constraint is the one reported. One flag reporting `limit=MAX_WAVES` for all three
reads as "plenty of budget, the queue just kept yielding" when the cause was the clock. Note the
`wave-cap` reason cannot distinguish "the cap bound me" from "I drained the queue on exactly the
last allowed wave" — only one more receive could, and the event says the queue *may* still be
yielding rather than buying certainty with an API call on every capped sweep. Review caught that
the first version of that hedge reached only the CloudWatch line while the structured event —
the account that carries `reason` and gets filtered on — still asserted the claim it softened.

**A message left in flight re-creates the false-empty inference, and that is why `group-blocked`
exists.** It is the *condition* that is named, not either cause, because the two doors are
symmetric and the second is the more likely one. A failed append leaves its messages queued; a
failed **delete** does the same, and `DeleteMessageBatch` reports a partial failure as **HTTP 200
with a `Failed` array** — so the try/except around it saw nothing at all on the most realistic
fault, and the append-side guard could not cover it because `failed` was 0 for the whole sweep.
That is the shape SPEC-151 closed on `delete_objects`; this had it too. The reason token also
deliberately avoids `write-failed`, which `_append_day` already emits on its own event for a
different thing.

**A message not deleted is a message still in flight.** Messages that were not deleted —
because the append failed, or because the delete did — stay
*in flight*, so they block their own group for the rest of the sweep. Once the healthy groups
drain, the next receive returns empty, which is precisely the reading this design removes. Found
in review with a per-key S3 fault: 30 `data-quality` messages behind a failing key, 10
`observability` messages healthy — 20 of the 30 were never looked at, and the only signal was
`failed` on the summary, which reports a write fault rather than a backlog. Under a persistent
per-key fault that drains the group at ten messages per tick, which is the arithmetic this entry
opens with. A fault-specific event cannot stand in for the stop reason here: it reports its own
cause, not that the queue is behind.

**The emitter question, and why the answer is "no change".** This function logs into the queue it
drains, so its own telemetry is a real cost — the `observability` group is itself one of the two
that had backlogged. The receive span and the per-destination `appending`/`appended` events now
fire once per wave rather than once per sweep, and the first instinct was to aggregate them.
That is wrong: emitters and drained messages **both** scale with `waves x groups`, so what has to
hold is a **ratio below one**, not a constant — measured at **0.58 events per message drained**
(115 events for 200 messages over two groups). Aggregating would have cost the FR-002
entry-and-outcome-per-destination property for nothing. Only the sweep summary is aggregated,
because it is genuinely per sweep.

The old guard asserted the strict `O(1)` form and stayed green through all of this, because it
ran on `FakeSQS` — which never blocks, so it never produced a second wave and would have passed
at any wave count. It is now scoped to the single wave it actually measures, and the ratio is
pinned separately on `FifoSQS`.

**The test that could not fail.** `FakeSQS` served rounds and then emptied — which quietly
asserts that an empty receive means an empty queue, the exact premise that is false. It ran out
of rounds at precisely the moment a real queue would have blocked, so every test agreed with the
bug. `FifoSQS` models the ordering rule (a group with an in-flight message yields nothing until
a delete), and `test_a_backlog_across_groups_drains_in_one_sweep` fails against the old shape at
**30 of 75** — 10 per group, three groups.

Review caught a second one of the same kind in the fix's own tests: an "it went back after
deleting" test asserted `receives > 1` and an empty in-flight set, and **both hold for the
single-wave code** — the inner round loop receives a second time to get the empty round that
ends it, and one wave still deletes what it wrote. It now records the receive/delete order and
asserts a receive after a delete, which is the only thing that can unblock a group. Each guard
here was checked against its own mutation (`MAX_WAVES = 1`; the reserve forced to `False`; the
`group-blocked` reason removed), and each fails alone.

[fifo]: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues-understanding-logic.html

---

## `tbcommon/config.py` — sizing `REFRESH_MAX_DEFINITION_BYTES`

The refresh path's definition cap is **40 KiB**, and it is deliberately not tscommon's
`SHARE_MAX_DEFINITION_BYTES`. That 32 KiB was measured for table-share's 50-recipient Map,
where the definition is copied into every item; table-builder has no Map.

> **Note (SPEC-161).** The comparison above is now against a value that means something different:
> table-share's definition travels by pointer, so its 64 KiB bounds Athena's query string, not a
> state payload. The 40 KiB here is unaffected — table-builder's definition still rides on its own
> state, and this paragraph's reasoning about that is unchanged.

What rides on a refresh state instead is one definition plus what `infer-schema` then adds
to the **same** state — its own inferred columns and the generated DDL. **Columns therefore
ride three times** while table properties ride once, so the worst case is a definition spent
entirely on columns (an ordinary flat Parquet table), not a mixed one. Measured at that
composition by `test_load_table_definition.py`:

| cap | columns | whole state | % of 256 KB |
|---|---|---|---|
| 32 KiB | 713 | 92,331 | 35% |
| **40 KiB** | **891** | **115,293** | **44%** ← chosen |
| 48 KiB | 1,069 | 138,255 | 53% ← over half; rejected |

Breaching the 256 KB state-payload limit raises `States.DataLimitExceeded`, thrown **outside
every Catch** — no recorded outcome and no notification, on a request that already did all
its work. So an oversized table is refused up front as a whole-request terminal.

## `table-builder-apply-refresh` — what the in-place update does *not* retire

Stated rather than implied, because SPEC-144 FR-006 AC1 claimed a serialization guarantee
that did not exist.

The Pipe still invokes `StartExecution` as `FIRE_AND_FORGET`
(`infra/modules/table-builder/pipe.tf`), so two refreshes on one database still overlap, and
**Glue offers no compare-and-set to close it**: `UpdateTable`'s `VersionId` is documented only
as "the version ID at which to update the table contents", alongside `TransactionId` and
`ViewUpdateAction`, with no precondition-failure error.

What changes is the **severity**. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions, and `ConcurrentModificationException` — which Glue
raises on genuine simultaneity — is retried. SPEC-157 owns closing the rest.

## `user-directory-build` — why the source is S3, not Cognito

Settled 2026-08-03, after reading `docs/transition_plan.md`.

**Today** Cognito is the complete record and S3 is not: the personal prefix is created *by the
browser* on the first visit to `/files` (`ensurePrefixMarker`, SPEC-014 — a deliberate
no-backend decision), so a confirmed user who never opened the file browser has no prefix.

**The transition reverses it.** `transition_plan.md` §2 item 7 settles that sign-in provisions
nothing — the sync pre-creates every space and `ensurePrefixMarker` is deleted outright (§6.3)
— while federated login makes `cognito:username` a synthetic `identitycenter_<subject>` value
(§6.1) and users appear in the pool only after their first sign-in. So S3 becomes complete and
Cognito becomes both incomplete *and* wrong-keyed.

**Do not "fix" this back to `ListUsers`, and do not add it as a union "to be safe":** a second
source with different completeness properties is a second thing to reason about every time the
directory looks wrong. A test asserts the module never imports or clientises Cognito.

**The document is advisory. A name's presence in it grants nothing.** No control plane reads
it, no membership check consults it, and no browser field refuses a name missing from it.
Existence is still decided where it always was — `admin_get_user` against the user pool — and
an unknown name is still reported back to the user as a notification. The residual gap (a
confirmed user who has never opened the file browser is absent until the transition lands) is
bounded: they can still be added, just without a suggestion.

## `dqcommon/config.py` — sizing the byte-scan budget

**Why the budget is per REQUEST, never per file.** An earlier version bounded it per file:
256 MiB × up to 1000 files ≈ 276 GB through one 1024 MB Lambda in 300 s ≈ **920 MB/s
sustained**, against a real-world ~60–100 MB/s. It would have passed on a three-file fixture and
timed out in production — the exact error class this arc's re-architecture exists to eliminate.

**`DQ_SCAN_MIN_SAMPLE_BYTES` — the second disaster, which the byte budget does not prevent.**
Bytes are not the only cost; **requests** are. A flat 1 head + 20 ranged reads per file is
**21,000 sequential GetObjects** on a 1000-file manifest. At ~30 ms round-trip each that is
~630 s against the function's 300 s ceiling, while reading only the 2 GiB the byte budget
permits. It would have timed out on exactly the large folders the budget rewrite was meant to
save, for a completely different reason.

So a file's share only buys a ranged read when that read is worth a round trip. Measured across
the range (share = 2 GiB / fileCount, head = half of it):

| files | samples | GETs | time |
|---|---|---|---|
| 1 | 20 | 21 | ~36 s |
| 12 | 20 | 252 | ~43 s |
| 100 | 2 | 300 | ~44 s |
| 1000 | 0 | 1000 | ~65 s — 21,000 GETs / ~630 s without the floor |

Both costs are now bounded: never more than `DQ_SCAN_TOTAL_BYTES`, and never more than ~1000
requests. At 1000 files no sample clears the floor, so a file's 2 MiB share buys only its head
window — `head = int(share * DQ_SCAN_HEAD_FRACTION)` = **1 MiB**, and the 1 MiB remainder is
under `DQ_SCAN_MIN_SAMPLE_BYTES`, so it buys no ranged read at all. That is the right trade: one
contiguous 1 MiB read beats 21 scattered 100 KiB ones for finding a corrupt export, and the
report says the coverage is sampled either way.

## `shared-space-common/registry.py` — why a membership write is a delta

`save_members` takes **deltas** (`add=`, `remove=`, `acknowledge=`) and derives the new roster
inside its own compare-and-swap. It used to take the roster the caller had computed from
`event["registry"]` — a snapshot read before the request began — and assign it over the
freshly-read record. So the CAS re-read the record and then overwrote the one field it exists to
protect with a stale value: two overlapping requests on one space were **last-write-wins on the
roster**, and a concurrent remove reinstated a just-added member (SPEC-151 FR-004).

Nothing serializes those requests. `shared-spaces/pipe.tf` is `FIRE_AND_FORGET` and the FIFO
group id is one global constant, which `cpcommon.cas`'s module docstring says outright (it was
`casio`'s until SPEC-156 FR-001 moved the loop).

**Four callers, not three.** `acknowledge-membership` is one too, and it is the only one that
*adds* to `acknowledged`. Left out of the conversion, it would have kept passing a whole computed
list and kept the defect.

**`status` is no longer written by this path.** It used to be forced to `"active"`
unconditionally, which let a membership write racing a delete return a `deleting` space to
`active` — the cascade would then run against a record claiming to be healthy. Only a
`setdefault` remains, to heal a record written before the field existed.

## `tscommon/config.py` — sizing the three share caps

**`SHARE_MAX_RECIPIENTS = 50`.** The disaster this prevents is not the fan-out — it is the
Map's **result**. Each item contributes a summary entry to `$.recipientResults`, and a failed
entry carries the raw Step Functions `{Error, Cause}` (PR #252 — the ASL decode that used to
shrink it raised an uncatchable `States.Runtime`, so the raw object is what makes the reason
recoverable at all). Measured against a real Cause from execution history: **~570 bytes per
failed recipient, ~1.2 KB with a verbose Athena `StateChangeReason`**. Step Functions caps a
state payload at 256 KB, and breaching it raises `States.DataLimitExceeded` **on the Map** —
which routes to the whole-request failure state and destroys every per-recipient outcome the
Map exists to preserve, turning a partial success into a total failure.

Measured, not guessed: at the bounded worst case (a maximum-length detail plus a deep stack)
100 recipients reach ~154 KB — under the limit, but the request object rides in the *same*
payload, so that margin is thinner than it looks. 50 lands at ~68 KB, 26% of the limit.
`test_the_whole_map_state_stays_under_the_payload_limit`
(`lambdas/control-plane-common/test_state_machines_cpcommon.py`) computes this from the
constants, so changing either without re-checking the other fails the build. The other half of the bound is
`cpcommon.athena` truncating the raw Athena reason: a cap on **count** alone cannot bound a
32 KB Cause, which breaches at **seven** recipients. It is also a sane product limit in its own
right — 1000 objects × 50 recipients is 50,000 `CopyObject` calls, and there was previously no
cap at all.

> **Amended (SPEC-161).** The product is now bounded directly by `SHARE_MAX_TRANSFER_ITEMS`
> (20,000), so `SHARE_MAX_RECIPIENTS` no longer carries that second job by implication — its own
> two bounds, the inline Map's state and the per-item error detail, are untouched by the scale
> work and the value stays **50**.

**`SHARE_MAX_DEFINITION_BYTES = 32 KiB`.** The last unbounded term on the Map's state. Moving
the object list to a pointer removed the big one, but `tableDefinition` still rides inline —
and it is **user-controlled**: it clones the source's columns (name/type/comment) and its Glue
table properties verbatim, and a user can set both from the query workspace. Measured with the
plan already by pointer, 50 recipients all failing:

| definition | state | % of 256 KB |
|---|---|---|
| 300 columns, no comments | 89 KB | 34% |
| 1,000 columns, no comments | 123 KB | 47% |
| 1,000 columns, 255-char comments | 393 KB | **150% — breach, after the pointer** |

32 KiB is generous — roughly 600 plain columns — and lands the worst case near 41%.

> **Superseded (SPEC-161).** Every word above is now historical, and the reason is worth keeping:
> **32 KiB was generous for plain columns and tight for commented ones.** A 100-column table with
> a 255-character comment per column serialises to about 32 KiB — an ordinary thing to want to
> share, sitting exactly on the boundary. The cap was doing two incompatible jobs at once, and a
> cap cannot: protect the payload, or decide how wide a table a user may share. The definition
> **travels by pointer** now (`definitionKey`), so the term is a digest path and the choice is
> gone. Measured after the move: an at-cap definition put back inline takes the guard peak from
> ~29% to **~55%** of the limit, which
> `test_the_whole_map_state_stays_under_the_payload_limit` now asserts so the pointer is
> demonstrated load-bearing rather than assumed tidy. **`SHARE_MAX_DEFINITION_BYTES` survives at
> 64 KiB bounding something else entirely** — Athena's query-string quota, **262,144 bytes and
> not adjustable**, because the definition renders into one `CREATE EXTERNAL TABLE`. Do not read
> it as a state bound.

**`SHARE_MAX_OBJECTS` / `SHARE_MAX_TOTAL_BYTES`.** Sized so a recipient Map item's parallel
server-side copy finishes comfortably inside copy-objects' 900s timeout (architecture §12).

> **Amended (SPEC-160).** That sizing rationale is now historical: the copy is a Distributed Map
> over batches, so no single invocation carries a recipient's whole table and the timeout no longer
> sets the ceiling. **The two values are unchanged anyway** — 160 changed the mechanism only, so it
> is provably behaviour-neutral, and SPEC-161 is where the ceiling moves. The two caps that are
> still load-bearing on the *state* — `SHARE_MAX_RECIPIENTS` and `SHARE_MAX_DEFINITION_BYTES` — are
> untouched by the restructure: the per-recipient array is still exactly one entry per recipient.

> **Superseded (SPEC-161) — the ceiling moved, and each cap now names a DIFFERENT limit.** They
> used to share one rationale (the copy verb's timeout) because one verb was the whole bound.
>
> **`SHARE_MAX_OBJECTS` = 20,000. Bound: `inspect-source`'s listing time.** `list_data_objects`
> pages at 1000 keys, so 20,000 objects is 20 `ListObjectsV2` round trips — one to two seconds of
> a 120-second budget — and the copy plan it writes is ~3.4 MB at ordinary Hive keys, ~21 MB at
> S3's worst-case 1024-byte ones, which is what inspect-source's 1024 MB is sized for.
>
> **`SHARE_MAX_TOTAL_BYTES` = 1 TiB. Bound: one copy of the SOURCE, and nothing more.** It caps
> what inspect-source lists and what the copy plan describes. **It does NOT bound the transfer**,
> and reading it as though it did is how the machine's `TimeoutSeconds` shipped unsatisfiable
> through two review rounds — see the entry below.
>
> **`SHARE_MAX_TRANSFER_BYTES` = 3 TiB (NEW). Bound: the state machine's `TimeoutSeconds`.** The
> manifest carries one item per (recipient, object) pair and **every item is a full copy**, so the
> Map moves `total_bytes × recipients`. This is the byte-axis twin of `SHARE_MAX_TRANSFER_ITEMS`,
> and the argument is verbatim the one that cap already made.
>
> **Two wrong models were tried before this number, and both read as safe.** First, sizing the
> timeout against `SHARE_MAX_TOTAL_BYTES` alone — 50 recipients × a 1 TiB source is **50 TiB**,
> 3.8 h at the conservative rate against a 3 h ceiling, with break-even at 8 recipients. Second,
> dividing by an **aggregate bandwidth** of 160 concurrent copies (`MAP_MAX_CONCURRENCY` ×
> `COPY_CONCURRENCY` × 25 MB/s = 4.0 GB/s), under which 16 TiB looked like 4,400 s.
>
> **The rate is a makespan.** `copy_batch` hands one WHOLE object to one worker and `copy_one`
> part-copies serially, so a batch whose bytes sit in one large object runs at **one** stream
> while seven idle — an ordinary mixed-size Parquet table, not a corner. The pessimistic
> denominator is `MAP_MAX_CONCURRENCY × rate` = **500 MB/s**, at which 16 TiB is 35,000 s. 3 TiB
> is ~6,600 s, and adding the finish Map (3,000 s) and the serial verbs (~720 s) the worst run is
> ~10,300 s inside the 10,800 s ceiling. All three terms are in the test, because each time a
> term was left out it stayed out for a whole review round.
>
> **`SHARE_MAX_OBJECT_BYTES` = 10 GiB (NEW). Bound: the copy verb's timeout, via the BATCH** — and
> that qualifier is the whole of it, because the first version of this cap got the granularity
> wrong. `ItemBatcher` batches by **COUNT, never by bytes**, so the unit that has to copy inside
> `copy-objects`' 900 seconds is `MAX_ITEMS_PER_BATCH` objects, not one. While the TOTAL cap was
> 20 GiB that bound was implicit — a batch could not exceed the whole table — and **raising the
> total to 1 TiB removed it with nothing replacing it**. A per-object cap alone does not restore
> it: at 50 items x 20 GiB the worst batch is **1000 GiB**, over 900 s even at an optimistic
> 100 MB/s per stream, so the child dies on the Lambda timeout, lands in `FAILED_n.json`, and the
> recipient is failed for a reason they cannot act on.
>
> **So `MAX_ITEMS_PER_BATCH` moves alongside it — to 8, which is `COPY_CONCURRENCY`.** And the
> quantity it is held against is a **makespan, not the batch's bytes**: `copy_batch` gives one
> whole object to one worker and `copy_one` part-copies serially, so a batch costs
> `ceil(items / COPY_CONCURRENCY)` ROUNDS of its slowest object. Setting the two equal makes that
> ceiling one, so a batch costs one object's time — **429 s** for 10 GiB at the conservative rate,
> inside two thirds of the 900 s timeout. At 10 items it was two rounds and **859 s**, 41 seconds
> from a hard timeout, while the bytes-over-bandwidth reading of the same numbers said 537 s.
>
> 10 GiB is chosen over a smaller per-object cap because it stays above S3's 5 GiB single-copy
> limit, so the multipart part-copy path stays reachable rather than becoming dead code. The price
> is more child executions on a many-small-files share; state transitions and Lambda invocations
> are both cheap and `MAP_MAX_CONCURRENCY` still bounds in-flight work.
> `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the makespan and
> `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality, so moving any of the
> three constants alone fails the build.
>
> **`SHARE_MAX_TRANSFER_ITEMS` = 20,000 (NEW). Bound: the manifest write and the collector's
> read-back**, which are the same volume in both directions. At S3's worst-case 1024-byte keys an
> item is ~2.3 KB, so 20,000 items is a ~46 MB manifest, and the Map Run export
> `collect-transfer-results` reads carries every batch's input again. **This is the cap the other
> two cannot express** — 20,000 objects is fine and 50 recipients is fine, and together they are a
> million manifest lines. It is enforced in `inspect-source` on the **requested** recipient count,
> before the guard Map, so an identical request cannot succeed or fail depending on who already
> holds a table of that name.
>
> **`build-transfer-manifest` and `collect-transfer-results` went 60 s/512 MB → 300 s/2048 MB**,
> because they *are* that third bound. Memory is also the CPU dial and this is JSON work, so it
> buys the timeout as much as the headroom.
> `test_the_manifest_verbs_are_sized_for_the_transfer_item_cap`
> (`lambdas/table-share-common/test_state_machine_table_share.py`) **computes** the worst-case
> volume from the cap and the same worst-case item the batch sizing uses, so raising the constant
> without re-sizing the verbs fails the build.
>
> **The item cap equals the object cap, so the object cap is reachable only for a single-recipient
> share** — 500 objects can go to 40 recipients, and 500 to all 50 is refused at 25,000 items. A
> deliberate consequence of bounding the product; the refusal names both numbers.
>
> **Step Functions is nowhere near binding at any of this** (checked against the live quota pages,
> 2026-08-10): an `ItemReader` file may be **10 GB**, a Map Run **100,000,000** items, and a
> Standard execution runs a **year**. Our own Lambdas are the ceiling, which is why every bound
> above names one.

## `cpcommon/transfer/config.py` — sizing the Distributed Map

**`MAX_ITEMS_PER_BATCH` (50 until SPEC-161, now 8).** A batch IS a child execution's input, and Step Functions caps that
at **256 KB**. The bound is taken against S3's worst case rather than a typical key, because a key
is user-controlled and the failure it prevents is a whole batch refused at start time: a source key
and a destination key can each be 1024 bytes, and a bucket name 63, which puts one manifest item
near **2.3 KB**. At 50 items that was ~112 KB — under half the limit — and at 8 it is ~18.9 KB.
`test_a_worst_case_batch_stays_under_the_input_limit`
(`lambdas/control-plane-common/test_transfer_cpcommon.py`) **computes** that rather than asserting
the number, so raising the constant without re-checking it fails the build.

**The second bound is time, and SPEC-161 is where it stopped being slack** — it is now the binding
one, and it is why this constant is **8**. The sentence that used to sit here read "50 server-side
copies on the bounded pool finish far inside copy-objects' 900-second timeout even when several go
multipart", and that was true only because table-share's TOTAL cap was 20 GiB, so a batch could
never exceed a whole table. Raising the total to 1 TiB removed that implicit bound.

**The bound is a MAKESPAN, and `items x object-size` is NOT it** — that product was the first
replacement tried and it is wrong for the same reason the sentence before it was. `copy_batch`
hands one WHOLE object to each of `COPY_CONCURRENCY` workers and `copy_one` part-copies serially,
so a batch costs `ceil(items / COPY_CONCURRENCY)` **rounds of its slowest object**, not its total
bytes over an aggregate rate. **8 = `COPY_CONCURRENCY` makes that ceiling one**, so a batch costs
one object's time — 429 s at `SHARE_MAX_OBJECT_BYTES` 10 GiB, inside two thirds of the 900 s
timeout. At 10 items it was two rounds and 859 s; the product reading of the same configuration
said 537 s and stayed green. `test_a_worst_case_batch_copies_inside_the_verb_timeout` computes the
makespan and `test_a_batch_is_exactly_one_round_of_the_worker_pool` pins the equality.
**These constants can no longer be changed independently of each other or of table-share's
per-object cap.**

**`MAP_MAX_CONCURRENCY = 20`.** Deliberately not the **10,000** default. Each child execution
invokes a Lambda that opens up to `COPY_CONCURRENCY` (8) S3 connections, so the default would put
the account's entire Lambda concurrency and a very large S3 request rate behind one user's share —
and the throttles that follows would be attributed to whatever else was running. 20 gives up to 160
in-flight copies, which is throughput without a self-inflicted `SlowDown`.

**Both numbers exist twice** — here for the verb, and in `infra/modules/table-share/locals.tf` for
the rendered ASL, because Terraform cannot import Python. `test_the_maps_sizing_matches_the_constants_the_verb_reads`
(`lambdas/table-share-common/test_state_machine_table_share.py`) asserts the pair still agree. Two
homes for one number is how a batch grows past the limit it was sized against while its own test
still passes.

## `cpcommon/bounded_read.py` — why polars' cloud reader is not used

Every control plane that infers a schema wants the same thing: the first few bytes of an
object, never the whole object (a source file can be hundreds of GB and a Lambda has no disk
for it). The obvious way — point polars at an `s3://` URI and let its `object_store` cloud
reader fetch only the byte ranges the scan needs — **does not work in Lambda**. It fails
with `failed to allocate {filesize} bytes to download uri = s3://…`: object_store gives up
on ranged access and tries to download the entire object, even when the role's credentials
are handed to it explicitly via `storage_options`. boto3 in the very same invocation
authenticates and reads fine.

The working pattern, proven live for data-quality (PR #242) and ported after the identical
failure hit table-builder on a real user's 31 MiB CSV: fetch a **bounded head** with boto3
and hand polars an in-memory buffer, which polars reads without touching object_store. The
no-full-download property is kept — reading stops after `max_lines` newlines or `max_bytes`,
whichever comes first, and the rest of the body is abandoned.

That covers formats whose schema lives at the **start** of the file: a CSV header is line 1,
and JSON type inference samples the first N lines. **Parquet keeps its schema in a footer at
the end**, which a head read cannot reach — so it gets `S3RangeReader`, a file-like object
serving `read`/`seek` from boto3 ranged GETs. Handed to `polars.read_parquet_schema`, that
fetches only the footer region: measured at **64 KiB and 4 GETs** for both a 0.3 MB and a
25 MB file, i.e. bounded by metadata size, not object size.

It must be `read_parquet_schema`. Over a Python file object, `scan_parquet` slurps the
**whole** object in a single `read()` (measured on polars 1.12.0), so a lazy reader buys
nothing there.

**Nothing in this codebase uses object_store any more**, which is the point: the one reader
that does not work here is no longer on any path, and no call site depends on credentials
being threaded into it.

## `cpcommon/errors.py` — why `failure_reason` exists in Python

No ASL state may decode an error `Cause`, and trying anyway killed executions outright.
The three control planes used to decode it in a `Pass` state:

```
"cause.$": "States.StringToJson($.error.Cause)"
```

A `Pass` state cannot `Catch`, and `States.StringToJson` raises `States.Runtime` on anything
that is not a JSON string. Verified against the live service with TestState:

| Error shape | Result |
|---|---|
| Lambda `TerminalError` (JSON Cause) | SUCCEEDED |
| `States.Timeout` (no Cause key) | `States.Runtime` — "JsonPath … could not be found" |
| `States.DataLimitExceeded` (prose) | `States.Runtime` — "Cannot convert String to Json" |
| `Lambda.Unknown` (prose) | `States.Runtime` — "Cannot convert String to Json" |

Three of four realistic shapes killed the execution **before** the recorded-failure and
notify states — so on precisely the failures a user most needs to hear about (a timeout, an
oversized payload, a Lambda that died without a handled error) they were told nothing at
all. Python can do this safely, so the decode moved to `cpcommon.errors.failure_reason` and
the machines pass `$.error` through untouched. See the `decisions.md` entry (#252).

**Why the reason split is gated on `errorType`.** `TerminalError` composes its message as
`f"{reason}: {detail}"` from a registered, colon-free code, so splitting on the first colon
reverses exactly what the raise site did. Every other exception's message is prose, and
splitting it yields prose dressed up as a reason code. Both of these are routine:

```
ClientError    -> "An error occurred (AccessDeniedException) when calling the CreateTable operation"
TransientError -> "listing objects"
```

Neither is a registered code, so a resolver falls back to the generic anyway — but the value
is logged, recorded and handed onward, and raw engine prose must never travel as if it were
a code (SPEC-106 FR-008).
