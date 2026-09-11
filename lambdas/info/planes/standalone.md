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

- **The notifications `create` boundary is a RUNTIME check**, because no SQS condition key reaches a
  message body. It compares the **role-id half** of the `SenderId`, and a refusal **logs and drops,
  never raises** — dead-lettering per forged request would drown the one undrained DLQ.
- **The DLQ drain notifies from the VERIFIED token, never the untrusted body.** The notifications
  DLQ itself stays undrained, deliberately: draining it is circular.
- **The request envelope is FLAT** — `actor` is the raw token at the top level — because the drain
  reads and **redacts** that field flatly. Nested, a dead-lettered request notifies nobody *and*
  writes the JWT to CloudWatch.
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
same way, and reversing a user decision), keeps up with two sessions a day.

**The producers now put every event in its own group** (`cpcommon.observability._message_group`),
so a wave takes up to `MAX_MESSAGES` = 1,000 from any mix of services for about the same few
rewrites as a wave of twenty — the bytes moved per message fall by the same factor. A full wave
is then its 100 receive and 100 delete calls plus a handful of rewrites, **~5–7 s derived from the
per-call costs above, not yet measured whole** — and it assumes a round returns about ten
messages, which SQS does not promise on a queue holding fewer than a thousand; a short round costs
waves, never data, and the re-run records messages per wave. On that estimate 35–48 fit in the
budget. `MAX_WAVES = 50` stands
at the top of that range, where the wave cap and the reserve meet, for a ceiling of roughly
35,000–48,000 a tick against a measured worst tick of 6,594 (every service, the sweep's own events
included). `SWEEP_RESERVE_MS = 60_000` exists because `MAX_WAVES` bounds the wave count and not
the duration: a wave rewrites each day object in full, that object grows all day, and the 300s
timeout is the real ceiling. Peak memory is one wave (`MAX_MESSAGES`), not the sweep.

**Stopping is three different things and they want opposite responses.** A sweep that stops with
the queue possibly still yielding reports *why*: `wave-cap` (the sweep took every wave it was
allowed — read the next paragraph before raising anything), `time-reserve`
(the day objects have grown enough that a wave no longer fits — raise the timeout, or look at
the growth), `group-blocked` (see below). The clock is checked before the wave cap, so when both
hold the harder constraint is the one reported. One flag reporting `limit=MAX_WAVES` for all three
reads as "plenty of budget, the queue just kept yielding" when the cause was the clock. Note the
`wave-cap` reason cannot distinguish "the cap bound me" from "I drained the queue on exactly the
last allowed wave" — only one more receive could, and the event says the queue *may* still be
yielding rather than buying certainty with an API call on every capped sweep. Review caught that
the first version of that hedge reached only the CloudWatch line while the structured event —
the account that carries `reason` and gets filtered on — still asserted the claim it softened.

**A `wave-cap` stop is not a backlog while a session is active, so the alarm reads the queue's
age instead.** Each wave finds what arrived during the one before — the session's traffic, and the
sweep's own events, which the library sends every ten finished spans or every second rather than
at the end — so a caught-up sweep can take every wave it is allowed, every tick, for as long as
the session lasts. The backlog signal is the `logs-backlog` alarm on the age of the queue's oldest
message (`infra/modules/observability/alarm.tf`): age is the lag itself, whatever stopped the
sweep, and it also sees a sweep that is not running at all. Healthy, the oldest message waits for
the next tick and no longer — 574–586 s all through 2026-09-10 until the session — so each missed
tick adds about 600 s to the peak: two in a row reach ~1,780 s and stay under the 1,800 s
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

**That ratio was taken across the wrong population, and 2026-09-10 showed it.** The drain is per
message group, so what had to stay below one was the sweep's output INTO its own group against the
ten that group gave up a wave. Each wave puts three events plus four per day-group into it —
measured **11.2 a wave with two day-groups** — so with a group per service the `observability`
group grew whenever any other group was behind, however low the queue-wide ratio. That day's
`service=observability` object passed 15 MB. The ordinary figure is 4–10 MB a day, and has been
since the wave loop landed on 2026-08-14 — under 1 MB a day before it, and 17.5 MB the day after
it. Grouping per
event is what retired the per-group condition, and it left the queue-wide ratio as the one that
governs; the emitters still need no change.

The old guard asserted the strict `O(1)` form and stayed green through all of this, because it
ran on `FakeSQS` — which never blocks, so it never produced a second wave and would have passed
at any wave count. It was scoped to the single wave it measured, and a ratio test was added on
`FifoSQS`; **neither survives** — both left the suite when it was cut to how a caller drives the
code — so nothing now holds the ratio, and a per-message emitter would ship green.

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
