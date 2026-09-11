# `observability` — the structured-logging pipe

A FIFO queue every service writes to, and a scheduled sweep that drains it into one NDJSON object
per service per day in the admin bucket under `logs/`.

| File | Holds |
|---|---|
| `sqs.tf` | the logs queue |
| `lambda.tf` | the sweep function, its log group, and the 10-minute schedule |
| `alarm.tf` | the backlog alarm, on the age of the queue's oldest message |
| `iam.tf` | the sweep's role, and the reusable **producer** policy document |
| `locals.tf` | names, and the `logs` prefix both the grant and the env read |
| `outputs.tf` | queue URL/ARN and the producer policy JSON |

Code: `lambdas/log-sweep/`. The client side is `cpcommon.observability`, the only way anything in
this repo logs.

## The queue is FIFO, and was Standard when it shipped

The original reason was concrete: log-foundry's `SQSSink` built its batch entries as `{"Id",
"MessageBody"}` and nothing else, and a **FIFO queue rejects a `SendMessageBatch` that omits
`MessageGroupId`** — every batch would have failed and the events would have been abandoned to
stderr. log-foundry later added FIFO support and removed that constraint.

`.fifo` is not decoration: AWS requires a FIFO queue's name to end in it, and the name is a
**ForceNew** attribute — so that rename was a **destroy-and-create**. The deploy role was granted
`DeleteQueue` on the old name alongside `CreateQueue` on the new one in its own prior PR, because
the single apply that performs the swap needs both.

**No `content_based_deduplication`**, and turning it on would be actively wrong: log-foundry mints a
fresh UUID `MessageDeduplicationId` per event, so every message is already unique — and two
identical events inside the 5-minute dedup window are a real thing for a retry-heavy control plane,
which SQS would then silently drop.

**One message group per event, set by the producer, not here.** A FIFO group gives up ten messages
until they are deleted, so the group is the sweep's ceiling: grouped by service, one session's API
traffic outran it for four hours on 2026-09-10. `cpcommon.observability` groups by each event's
`log_id`, so this queue's definition did not change. Sizing: `lambdas/info/planes/standalone.md`.

**No DLQ, deliberately.** The only failure the sweep can suffer on a message is a failed S3 write,
which is not the message's fault — a `maxReceiveCount` would move perfectly good events onto a
second queue that nothing reads. Every message is routable (an unparseable body goes to
`logs/service=_unrouted/`) and therefore deletable, so there is no poison message for a DLQ to
isolate.

## Three timings that must stay ordered

```
function timeout (300s)  <  queue visibility (360s)  <  schedule interval (600s)
```

- **Visibility must exceed the function timeout.** Shorter, and a slow sweep's in-flight messages
  become visible again to the *next* scheduled sweep while the first is still working on them —
  and both append them.
- **The timeout must stay below the schedule interval**, so a slow sweep cannot still be running
  when the next one fires.
- **Retention is 14 days**, which is headroom against a broken sweep, not the working buffer. Under
  normal operation a message lives for minutes; this is what gives a week and a half to notice.

The schedule is **10 minutes**, matching the DLQ drain (user decision, 2026-07-23; it replaced a
5-minute cadence). The trade is freshness for churn: a log is up to ten minutes behind the run that
produced it, which halves both the invocation count and the number of read-modify-write cycles over
each day's growing object. Not 1 minute — ~43k mostly-empty invocations a month would dominate this
function's own log group, which is itself something you have to read when the pipe misbehaves.

## The backlog alarm reads the queue's age, and tells nobody

`logs-backlog` fires when `ApproximateAgeOfOldestMessage` exceeds **1,800 s** for two consecutive
five-minute periods. Age rather than the sweep's stop reason, because age is the lag itself
whatever caused it — a wave cap, the time reserve, a blocked group, or a sweep not running — while
a caught-up sweep can still stop on its wave cap during an active session, chasing arrivals.
Healthy, the oldest message waits for the next tick and no longer (574–586 s measured across an
idle day), and each missed tick adds about 600 s, so two in a row stay just under the threshold
and three in a row cross it — about 40 minutes after the last good sweep. Missing data
reads as `INSUFFICIENT_DATA`, not as healthy: the sweep logs here every tick, so silence is itself
wrong.

**It has no action, by decision** (2026-09-10): its state is read in the console and by a session's
`aws cloudwatch describe-alarms --alarm-names dat-prod-logs-backlog`. Nothing enforces the
absence: the deploy role cannot create an SNS topic, but a Lambda is also a valid alarm action and
the role can already grant one an invoke permission — so adding an action is a decision to re-make,
not a gap to fill. Its name is a local, and the deploy grant names the same
`${project_name}-*-logs-backlog` pattern.

## The sweep reads back what it wrote, and that reversed a shipped property

It originally read nothing. One object per service per day means **read-modify-write**, because S3
has no append — the sweep must `GET` the day's object to extend it. What bounds the reversal is that
`s3:GetObject` is scoped to the **same `logs/*` prefix as the write**, so the role can read its own
output and nothing else in the admin bucket: not `fallback-results/`, not `shared-spaces/`, not
`table-share/`. It still cannot read a byte of user data anywhere.

Memory is **512 MB, not 256**, for the same reason: peak memory now tracks a day's log volume rather
than one batch. `LARGE_OBJECT_WARN_BYTES` in the handler warns long before that becomes binding.

**This role needs no user-space bucket-policy allowlist entry.** That Deny-all-but-allowlist resource
policy is on the *user-space* bucket, and this role touches neither user-data bucket. Stated
explicitly because "a new role got a 403 from the user-space bucket policy" has bitten this repo
three times — table-builder, table-share and data-quality, all fixed since.

## The portal role is granted nothing on this queue

Anywhere. The queue's contents are the operational record of what the control planes did, and a
browser that could enqueue could **forge log events attributing arbitrary activity to arbitrary
services**. Producers are execution roles only.

The sweep is itself a producer — it instruments itself through `cpcommon.observability`, which is
what proves the whole path end to end without instrumenting a control plane.

## The cpcommon required union

The sweep imports `cpcommon`, whose config requires `COGNITO_USER_POOL_ID`,
`COGNITO_APP_CLIENT_ID`, `USER_SPACE_BUCKET`, `SHARED_SPACE_BUCKET` and `ATHENA_WORKGROUP`. The sweep
reads none of them. That config once resolved **at import**, so a function missing one crashed at
cold start with an error naming neither the module nor the variable; it resolves on **first read**
now, so the failure lands on whichever branch reads it instead.

**Still set them.** The union is what any code path in `cpcommon` may demand, and "the function does
not use it" is not a reason to remove one.
