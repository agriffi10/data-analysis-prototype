# Standalone functions

Not part of a control plane: no Step Function, no request queue, no domain layer. Each is triggered
directly — by Cognito, by a schedule, or by its own queue. They still use `cpcommon`.

| Function | Trigger | What it does |
|---|---|---|
| `pre-signup/` | Cognito pre-signup | username validation and a disposable-email blocklist |
| `post-confirmation/` | Cognito post-confirmation | provisions the new user's Glue database — creating it, granting the portal role on it and stamping the `portal-managed` tag. It does **not** create the S3 prefix; the browser does, on the first visit to `/files`. `backfill.py` runs the same sequence for an already-confirmed user |
| `notifications-writer/` | its own FIFO queue | the **single writer** to a user's notification feed |
| `control-plane-dlq-drain/` | schedule | drains every plane's request DLQ into the notification the user already reads |
| `log-sweep/` | schedule | sweeps the structured-logging queue into one NDJSON object per service per day |
| `user-directory-build/` | schedule | publishes the username directory from the user-space bucket |

## The fences

- **The notifications `create` boundary is IAM and the API first, a RUNTIME check behind the grant.**
  The portal role holds no grant on the queue, and the API's route accepts only `markRead` and
  `markAllRead`. The writer's check names only the portal role, so against the API's own role the
  route is the only fence; the check is runtime because no SQS condition key reaches a message body. It compares the
  **role-id half** of the `SenderId`, and a refusal **logs and drops, never raises** — dead-lettering
  per forged request would drown its undrained DLQ.
- **The DLQ drain notifies the API-stamped `identity.actor`, never anything the body asserts.** A
  body with no usable identity block notifies nobody. Two DLQs stay undrained, deliberately:
  notifications, because draining it is circular, and feedback, whose body carries no identity
  block.
- **The flat `actor` is never read, but the drain still blanks the two legacy token fields** before
  it logs a parsed body, because a message from before the cutover can still arrive carrying a raw
  token.
- **The username directory is built from S3, not Cognito.** Today Cognito is complete and S3 is not,
  and the client transition reverses exactly that. It is readable by every authenticated user,
  accepted deliberately: usernames only, never emails.
- **One string is four things** — username = S3 prefix = principal tag = Glue database name — so it
  is catalog-safe by construction (`^[a-z][a-z0-9_]{2,62}$`). `pre-signup` is where that is enforced.
- **Structured logging goes through `cpcommon.observability` only.** The logs queue is FIFO with
  **one message group per event** — a group gives up ten messages a wave, so the group is the
  sweep's ceiling — swept on a schedule, appended under ETag CAS, retained forever. Messages are
  literals.

Back to [`../INDEX.md`](../INDEX.md).

---

## Why the numbers are what they are

Long-form reasoning that outgrew a docstring: sizing evidence, rejected designs and the
traps. Read the entry for what you are changing.

### `log-sweep` — why a sweep is a loop of waves

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
Long-polling would also have reversed a recorded decision (`docs/decisions/control-planes.md` → *structured logging*,
#270/#271) while fixing nothing — a blocked group does not become unblocked by waiting for it.

**Why the receive, the write and the delete have to repeat together.** Deleting is what unblocks
a group, and a message may only be deleted once its events are durable in S3 (put-then-delete;
losing logs is worse than duplicating them). So the unit that can repeat is the whole cycle, not
the receive. That is the wave.

**Sizing — re-derived from one measured session, 2026-09-10.** `MAX_WAVES = 50` was first set at
22x a *daily average* (~3,300 records, ~23 a tick) for the worst case of one backlogged group at
ten a wave. Both halves were wrong, and one working session showed it. Arrival is bursty:
`service=api` alone produced **10,371 events in its busiest hour** and 3,935 in its busiest ten
minutes, about two per request (`span.start`, `span.end`). And the ceiling was the **message
group**, not the wave count: grouped by service, the API group drained ten a wave — 500 a tick,
3,000 an hour — so it fell four hours behind while every sweep stopped on its wave cap having
used **22–50 s of a 300 s timeout**. `dat-prod-logs.fifo` peaked at 19,051 visible messages, and
its oldest message had waited 15,880 s by 00:30Z the next morning.

**What the timeout allows is set by what a wave costs.** Rewriting a day object costs **~123 ms +
22 ms per MB** of it (fitted over that day's 5,482 appends); a receive round costs ~25 ms and a
delete batch ~20 ms at most, both derived from the per-wave spans rather than timed alone.
Grouped by service a wave took ten per backlogged service for two rewrites of objects that grow
all day: about 220 waves fit in the 240 s left after the reserve at that day's 16 MB, ~135 at
32 MB — **13,200 and 8,200 an hour per service**, the second below one session's peak. So no
`MAX_WAVES`, and no faster schedule (at most 1.5x from the timeout-to-interval ratio, eroding the
same way, and reversing a user decision), keeps up with two sessions a day. The per-wave spans
those costs came from are gone (*The emitter question*, below); a re-fit reads the summary's
`rounds`, `receive_ms`, `delete_ms` and `waves` and each destination's `append_ms`, `appends` and
`bytes` instead — a sum per sweep rather than a duration per call, which is enough to fit cost
against size across sweeps, and gives every sweep's whole-wave time as the three timers over
`waves`.

**The producers now put every event in its own group** (`cpcommon.observability._message_group`),
so a wave takes up to `MAX_MESSAGES` = 1,000 from any mix of services for about the same few
rewrites as a wave of twenty — the bytes moved per message fall by the same factor. **The first
full wave in production, measured (2026-09-12 01:24Z), took about 2.5 s for 1,000 messages**: 100
receive rounds at 10.7 ms each, which is faster than the 25 ms derived above and shows a round does
return about ten on a busy queue; about 9 ms a delete batch; and 0.33 s and 0.09 s for its two
rewrites. Before that run, the pre-deploy estimate here was 5–7 s. So about 95 full waves fit in
the budget, and **the wave cap binds first, at about half of it**: `MAX_WAVES = 50` stands, and the
ceiling is simply 50 × 1,000 = 50,000 a tick, against a measured worst tick of 6,594 (every service,
the sweep's own events included). Raising it would buy nothing the measured traffic needs, and the
cap stays a backstop behind the caught-up finish below. The day objects in that run were small, and
every MB of every object a wave rewrites adds ~22 ms — but with the API and observability objects
both at a heavy day's 16–17 MB a wave is about 3.2 s, and 50 of them still fit in 160 s of the 240.
`SWEEP_RESERVE_MS = 60_000` exists because `MAX_WAVES` bounds the wave count and not the duration: a wave rewrites each day object in full, that object grows all day, and the 300s
timeout is the real ceiling. Peak memory is one wave (`MAX_MESSAGES`), not the sweep.

**Stopping is three different things and they want opposite responses.** A sweep that stops with
the queue possibly still yielding reports *why*: `wave-cap` (every wave the sweep was allowed
stopped its receive at a cap, or held a message older than the sweep or one it could not date —
read the next paragraph before raising anything), `time-reserve`
(the day objects have grown enough that a wave no longer fits — raise the timeout, or look at
the growth), `group-blocked` (see below). The clock is checked before the wave cap, so when both
hold the harder constraint is the one reported, and either outranks `group-blocked`, which only
qualifies a sweep that finished on its own. One flag reporting `limit=MAX_WAVES` for all three
reads as "plenty of budget, the queue just kept yielding" when the cause was the clock. Note the
`wave-cap` reason cannot distinguish "the cap bound me" from "I drained the queue on exactly the
last allowed wave" — only one more receive could, and the event says the queue *may* still be
yielding rather than buying certainty with an API call on every capped sweep. Review caught that
the first version of that hedge reached only the CloudWatch line while the structured event —
the account that carries `reason` and gets filtered on — still asserted the claim it softened.

**A caught-up sweep finishes on the first wave of arrivals alone, so a session cannot run it to
the cap.** Each wave finds what arrived during the one before — the session's traffic — so a
sweep that waited for an empty receive would take every wave it was allowed for
as long as something arrived during each one, rewriting multi-MB day objects once a wave with no
backlog behind them and reporting `wave-cap` over a queue it had already drained. That is reasoned
from a session's arrival rate rather than observed: the only `wave-cap` stops on record were over a
real backlog, before the queue was grouped per event, and in its first two days grouped per event
every sweep finished in one to three waves with no stop reason (`docs/testing/sessions.md`,
2026-09-13). So the finish below is a bound —
it makes the end of a sweep independent of arrival timing — not a fix for a run anyone saw. The
receive now asks for each message's
`SentTimestamp`, and after writing and deleting a wave the sweep finishes as a normal sweep, with
no stop reason, when every message in the wave was stamped at or after the sweep's start and the
wave's receive ended on an empty round rather than a cap. Each qualifier leans toward running on,
because stopping early is the costly direction and running on is only the old behaviour:

- **A message it cannot date** — no attribute, or one that does not parse — counts as old.
- **A wave whose receive stopped at a cap** keeps it going, arrivals or not: SQS does not order
  messages across groups ([FIFO delivery logic][fifo]), so a full wave says nothing about what
  is queued behind it.
- **A legacy per-service backlog keeps it running until the backlog is gone or the cap or the
  clock stops it**: a group never yields a new message ahead of an older one of its own, so its
  waves hold old messages until then. A message redelivered from an earlier sweep keeps its
  original stamp, so it reads as old too.

The finish is also qualified exactly as an empty receive is: with a message left in flight it
reports `group-blocked`, since a group blocked behind an unwritten or undeleted message can hide
older messages from both. The start is the Lambda's clock and the stamp is SQS's, so a skew only
moves which wave ends the sweep; nothing is lost either way, because whatever a sweep does not
delete stays queued for the next tick. The stop is no stronger than the empty receive beside it —
a short poll can come back empty spuriously, end a wave early, and this can then finish on it —
and neither is the backlog signal. That is the `logs-backlog` alarm on the age of the queue's
oldest message (`infra/modules/observability/alarm.tf`): age is the lag itself, whatever stopped
the sweep, and it also sees a sweep that is not running at all. Healthy, the oldest message waits
for the next tick and no longer — 574–586 s all through 2026-09-10 until the session — so each
missed tick adds about 600 s to the peak: two in a row reach ~1,780 s and stay under the 1,800 s
threshold, and **three in a row fire it**, about 40 minutes after the last good sweep. It has no
action, by decision: its state is read in the console and by a session's `describe-alarms`.

**Per-event groups also end one inference: a partition's newest record no longer proves the older
ones have landed.** Grouped by service, a partition was written in send order, so once it "ran
past" a time everything before that time was in. Now delivery order is free, so while any backlog
exists the only honest completeness check is the queue's age — nothing else can say a partition
is complete, and a live check that reads "B's record after A's" orders by `timestamp`, not by line.

**A message left in flight re-creates the false-empty inference, and that is why `group-blocked`
exists.** It is the *condition* that is named, not either cause, because the two doors are
symmetric and the second is the more likely one. A failed append leaves its messages queued; a
failed **delete** does the same, and `DeleteMessageBatch` reports a partial failure as **HTTP 200
with a `Failed` array** — so the try/except around it saw nothing at all on the most realistic
fault, and the append-side guard could not cover it because `failed` was 0 for the whole sweep.
That is the shape SPEC-151 closed on `delete_objects`; this had it too. The reason token also
deliberately avoids `write-failed`, which a destination's account already carries for a
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

**The emitter question, and why "no change" was the wrong answer.** This function logs into the
queue it drains, so its own telemetry is a real cost. When the wave loop landed, the receive span
and the per-destination `appending`/`appended` events began firing once per wave, and aggregating
them was rejected on a ratio: emitters and drained messages both scale with `waves x groups`,
measured at 0.58 events per message drained, so aggregating would have cost FR-002's
entry-and-outcome-per-destination property for nothing.

**The ratio was the wrong property, and 2026-09-10 showed it twice.** It was taken across the
wrong population: the drain was per message group, and each wave put three events plus four per
day-group into the `observability` group — **11.2 a wave with two day-groups** — against the ten
that group gave up, so it grew whenever another group was behind. That day's
`service=observability` object passed 15 MB; the ordinary figure is 4–10 MB a day, and has been
since the wave loop landed on 2026-08-14 — under 1 MB a day before it, and 17.5 MB the day after
it. That afternoon, still grouped by service, the sweep's own records were 12,772 of the queue's
42,714 sends, **about 640 a sweep** across twenty sweeps, eighteen of them capped. Grouping per
event retired the per-group condition and not the volume, since the emitters still fired every
wave and a busy session still fills every wave. Nor was it clean where it converged: the
`receive` step sat on a function the loop calls once per wave, and the `append-day` step on one
it calls once per destination per wave, which the child-span fence forbids — and each closed step
handed its events to the library's sender mid-run, so a later wave of the same sweep could
receive the sweep's own output.

**So no emitter runs inside the loop.** Each destination's account is tallied across the waves
and emitted once after the last: events landed, with the writes and appends they took, the size
left behind and `append_ms`, on the success event; events left queued, on one failure event per
reason; lost races, with the worst attempt beside the count, on one contention warning; and the
largest size read, on one warning when it crosses the threshold. The summary carries `rounds`,
`receive_ms`, `append_ms` and `delete_ms`, and the undeleted messages are one sweep-wide warning.
A sweep emits **one event per destination plus three**, plus at most one for each condition it
reports once per sweep (a filled wave, a stop, undated or unrouted bodies, undeleted messages)
and a few for each destination that degraded — whatever its waves or messages. FR-002's *entry*
event went with the loop: the library releases a span's events when the span closes or on an
explicit flush, and with every event on the handler's span — whose only flush runs after it
closes — an entry would leave at the same moment as its outcome and say nothing the outcome does
not. The same fact means nothing the sweep emits reaches the queue before it returns, so it
cannot receive its own output mid-run; a flush inside the loop would undo that. The accounts are
emitted from a `finally`, so a receive fault on a later wave still reports what the earlier
waves wrote; a sweep killed by its timeout reports nothing structured, since its only span never
closed, and its CloudWatch lines are the record.

**The guard tests the property, not a ratio, and it drives every path.** A ratio test passes a
per-wave emitter for as long as waves stay full, which is the regression it exists to catch.
`test_a_sweep_emits_the_same_events_however_many_waves_it_takes` holds three things at once: **no
emitter is called between the sweep's first receive and its last** — counted at the library's
level functions, so it holds however rarely an emitter would fire and whatever name reaches it;
two waves and six over the same destinations emit the same events, message for message, which
also holds the child spans a call count cannot see; and nothing reaches the sink before the sweep
returns. Each pair of sweeps takes clean appends and deletes, lost races, exhaustion, a write
fault, large objects, rejected and raising deletes, and bodies that are not JSON, not an object,
badly named or undated; ends on a wave its receive finished on an empty round, holding a message
stamped after the sweep began and one it cannot date; and runs once with the receive stopping on
its message cap and once on its round cap. A runtime guard holds only the paths it drives, so it
also proves it drove them all: it records every line of the sweep that ran — read from the
compiled source, so properties and classmethods count — and fails on any it did not, bar the
handler's blocks that end the loop or the sweep without continuing it. A branch added to the
sweep therefore fails it until the guard drives that branch too, which is the point and the cost;
only compared pairs may be driven, or a sweep run just to reach a line would satisfy the check
while nothing held that line. That completeness check is a gate, with a corpus proving each thing
it reports and its silence. It replaced a check on where an emitter is *written*, which review
evaded five ordinary ways (a stored alias, a nested function, a `for` loop, the report called in
the loop, a local import): a guard over spellings guards a spelling. Planted and reddened: a
per-message emitter, a per-wave emitter, either step put back, a flush inside the loop, a
per-attempt, per-read, per-delete or per-body warning in the old shape, an emitter on the
round-cap path by each of those routes, a new branch no sweep takes, a heartbeat throttled by
time, an emitter chosen by whether the wave was capped, a `continue` inside a block that ends the
loop, and an emitter in a property nothing reads. The two guards before this — the strict `O(1)`
form on `FakeSQS`, which never produced a second wave, and a ratio test on `FifoSQS` — both left
the suite when it was cut to how a caller drives the code.

**The test that could not fail.** `FakeSQS` served rounds and then emptied — which quietly
asserts that an empty receive means an empty queue, the exact premise that is false. It ran out
of rounds at precisely the moment a real queue would have blocked, so every test agreed with the
bug. `FifoSQS` models the ordering rule (a group with an in-flight message yields nothing until
a delete), and `test_a_backlog_across_groups_drains_in_one_sweep` fails against the old shape at
**30 of 75** — 10 per group, three groups.

Review caught a second one of the same kind in the fix's own tests: an "it went back after
deleting" test asserted `receives > 1` and an empty in-flight set, and **both hold for the
single-wave code** — the inner round loop receives a second time to get the empty round that
ends it, and one wave still deletes what it wrote. It was rewritten to assert a receive after a
delete, the only thing that can unblock a group; that test left the suite when it was cut to how
a caller drives the code, and `test_a_backlog_across_groups_drains_in_one_sweep` holds the
property now, since three waves over blocked groups need a receive after each delete. Each guard
here was checked against its own mutation (`MAX_WAVES = 1`; the reserve forced to `False`; the
`group-blocked` reason removed), and each fails alone.

**The caught-up stop's tests move the clock rather than read it.** The fake sweep runs inside a
millisecond, so on a real clock every arrival is stamped at the sweep's start and "sent since the
sweep started" cannot be told from "sent since this wave started". Review planted the second,
which brings the chase back, and the suite stayed green. `FifoSQS` now moves a patched clock a
second on each delete call that lets a message arrive, and returns `SentTimestamp` only to a
receive that asks for it. Each part
of the stop was planted and fails alone: the stop removed, checked before the write, or checked
after the cap; the start re-taken per wave; the attribute not requested; an undated message read
as new; a full wave allowed to stop, or the sweep-long `capped` read for the wave's `truncated`;
the comparison inverted; `group-blocked` outranking the clock or the cap, or not qualifying the
caught-up finish. Review found the `capped`, cap-order and cap-precedence plants surviving the
first version of these tests.

[fifo]: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues-understanding-logic.html

### `user-directory-build` — why the source is S3, not Cognito

Settled 2026-08-03, after reading `docs/transition_plan.md`.

**Today** Cognito is the complete record and S3 is not: the personal prefix is created *by the
browser* on the first visit to `/files` (`ensurePrefixMarker`, SPEC-014 — a deliberate
no-backend decision), so a confirmed user who never opened the file browser has no prefix.

**The transition reverses it.** `transition_plan.md` §2 item 7 settles that sign-in provisions
nothing — *this paragraph used to say the sync pre-creates every space* — and §3.12 now settles what
creates them instead: a **portal-owned provisioner**, run over the client's known username list
ahead of any sign-in. `ensurePrefixMarker` is deleted outright (§6.3), its write moving to
that provisioner
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
