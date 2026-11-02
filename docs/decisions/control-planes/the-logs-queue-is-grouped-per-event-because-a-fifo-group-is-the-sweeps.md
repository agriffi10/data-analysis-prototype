---
type: Decision
title: "The logs queue is grouped per event, because a FIFO group is the sweep's ceiling (2026-09-11)"
description: "The logs queue has one message group per event (`log_id`), because each FIFO group drains only ten messages per wave; do not group by service or trace, and while a backlog exists the queue's age is the only completeness check."
---

**A FIFO message group gives up at most ten messages until they are deleted, and the sweep may
delete only once the append is durable — so each group drains ten per wave, whatever `MAX_WAVES`
says.** SPEC-129 grouped the logs queue by **service**, overriding `log-foundry`'s per-trace
default on the premise that "a single-consumer sweep cannot use [parallel delivery] anyway". The
premise was false: one receive batch spans groups, and the sweep's receive loop takes up to
`MAX_MESSAGES` a wave across them. So the real ceiling was ten per service per wave — 500 a tick,
3,000 an hour — and on 2026-09-10 one working session's `service=api` produced 10,371 events in its
busiest hour. The API partition fell four hours behind while every sweep stopped on its wave cap
having used 22–50 s of its 300 s timeout, and nothing alarmed.

**The sweep also fed its own backlog, and the convergence argument could not see it.** Each wave
put three events plus four per day-group into the `observability` group — measured 11.2 a wave
with two day-groups — against a drain of ten, so its own group grew whenever another was behind.
The recorded proof of convergence was a ratio of events to messages below one across the queue
(0.58), which guaranteed nothing, because the drain is per group. Grouping per event ends the
pile-up and not the volume, which ended when the emitters left the wave loop ([the SPEC-130/131
entry](structured-logging-narrative-primitives-and-the-one-door-rule.md)).

**Raising `MAX_WAVES` or the cadence could not fix it**, which is why neither was the change. A
day-object rewrite costs ~123 ms + 22 ms per MB, so a wave slows as the day grows: ~220 waves fit
in the timeout at that day's sizes and ~135 at 32 MB — 13,200 and 8,200 an hour per service, the
second below one session's peak. A faster schedule buys at most 1.5x, erodes the same way, and
reverses the 10-minute decision. **Grouped per event** (`log_id`, which is also the dedup id), no
group holds a second message, a wave takes up to 1,000 from any mix of services for about the same
rewrites as a wave of twenty, and the sweep's own output drains alongside everything else.
`MAX_WAVES = 50` stands. The first full wave in production took about 2.5 s for 1,000 messages,
so about 95 fit in the 240 s after the reserve. The wave cap binds first, at 50,000 a tick, against
a measured worst tick of 6,594 — a pre-deploy estimate of 5–7 s had put the cap where the reserve
binds, and the run corrected it. What is given up is delivery order, which no code
reads — the sweep partitions by each event's own timestamp — and one operator inference with it: a
partition's newest record no longer proves the older ones have landed, so while any backlog exists
the queue's age is the only completeness check.

**Do NOT group by trace**, `log-foundry`'s default: a large run's trace, and the sweep's own (one
per sweep), would still each be a ten-a-wave group. **A caught-up sweep finishes on the first wave
of arrivals alone**: during an active session each wave finds what arrived during the last, so a
sweep that waited for an empty receive would run to its wave cap over a drained queue for as long
as arrivals kept landing in every wave — reasoned, not observed: in its first two days grouped per
event every sweep finished in one to three waves with no stop reason (`docs/testing/sessions.md`,
2026-09-13), so the finish is a bound
rather than a response to anything seen. It reads each message's `SentTimestamp` and finishes, as
a normal sweep, after a wave whose every message was stamped at or after the sweep's start and
whose receive ended on an empty round rather than a cap. An undated message and a capped receive
both mean run on, because stopping early is the costly direction and SQS does not order messages
across groups. The backlog signal is still the `logs-backlog` alarm on the age of the queue's
oldest message, which has **no action by decision** — its state is read in the console and by a
session's `describe-alarms`. Sizing evidence: `lambdas/info/planes/standalone.md`.

## History

### 2026-09-11

- **Settled:** entered the register.
