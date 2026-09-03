# `control-plane-dlq-drain` — one drain for every plane's request DLQ

One Lambda, one 10-minute schedule. It sweeps every control plane's request DLQ and turns each
dead-lettered request into the notification the user already reads.

| File | Holds |
|---|---|
| `lambda.tf` | the function, its log group, the sweep rule and the invoke grant |
| `iam.tf` | the drain's execution role |
| `locals.tf` | constructed names and ARNs |
| `outputs.tf` | function name, role ARN, and the queue names it sweeps |
| `variables.tf` | the module interface |

Code: `lambdas/control-plane-dlq-drain/`.

## One function over four queues

The per-domain differences — the user-facing noun, the field the actor's token lives in — are a
**table inside the handler keyed off the queue's ARN**. A fifth control plane is one map entry and
one more ARN in `DLQ_ARNS`, not a fifth copy of this module.

The DLQ ARNs arrive as **constructed strings** from the root module, not as other modules' outputs:
known at plan time, no cycle, and IAM never validates that a queue exists. Same pattern as the
notifications queue ARN every producer already scopes to.

## The smallest role in the repo, deliberately

Four queue reads, one send, and logs. No S3, no Glue, no Athena, no Cognito API (token verification
is offline JWKS), and **no access to any request queue** — a drain that could enqueue into a control
plane would be a way to inject work, and it has no reason to.

## The log group is now the only copy of a dead-lettered body

Consuming a DLQ message deletes it. The 14-day queue retention the arcs kept "for inspection" is
traded for this group's 14-day retention — a deliberate cost, paid so the user hears about the
failure at all. **Shortening this retention shortens the forensic window.**

## A schedule, not four event-source mappings

One EventBridge rule invokes the drain every 10 minutes and the handler polls all four DLQs itself
(receive → notify → delete, until empty). This replaced four always-on SQS event-source mappings —
four managed poll loops on queues that are, by design, almost always empty — whose idle long-polling
was the bulk of the account's SQS request volume.

**Nothing re-drives a message.** There is still no DLQ on the drain, and the sweep deletes every
message it reads whether or not it could notify about it: a redelivery would only re-run a decision
already made about a terminal message.

The trade against the mappings is that a dead-lettered request now surfaces within one interval
(~10 min) instead of seconds. Nothing watches these queues in real time, so that is immaterial.

## The envelope must stay flat

`actor` is the raw token at the **top level** of the request envelope, because the drain reads and
**redacts** that field flatly. Nested, a dead-lettered request notifies nobody *and* writes the JWT
to CloudWatch. The drain notifies from the **verified token**, never the untrusted body.

The notifications DLQ itself is not swept, deliberately: draining it is circular.

## The cpcommon required union

`COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `NOTIFICATIONS_QUEUE_URL` and `DLQ_ARNS` are
genuinely used. The buckets and the workgroup are `cpcommon`'s required union — set because any
code path in it may demand them, and "the drain does not use it" is not a reason to prune one. `LOGS_QUEUE_URL` is the exception: `cpcommon.observability` reads it with
`os.environ.get`, so a drain that loses it logs to stdout and still drains.
