# `feedback` — the single-writer daily feedback document

A FIFO request queue that triggers one writer Lambda directly. The writer is the **only** thing
that appends to `feedback/YYYY/MM/DD.json` in the existing admin bucket. No new bucket, no
EventBridge Pipe, no Step Function — a one-task append does not get a state machine
(`lambdas/info/best-practices/lambdas/lambdas.md` §10), and there is one verb.

| File | Holds |
|---|---|
| `sqs.tf` | the FIFO request queue and its own DLQ |
| `lambda.tf` | the writer, its log group, and the SQS event-source mapping |
| `iam.tf` | the writer's role |
| `locals.tf` | constructed names and ARNs |
| `outputs.tf` | queue URL/ARN and the writer role ARN |
| `variables.tf` | the module interface |
| `policies/` | writer trust and permissions |

Code: `lambdas/feedback-writer/`. Route: `lambdas/api/routes/feedback.py`.

## The browser holds no grant on this queue, and that is the whole attribution story

Every other enqueue in this product was once a browser call to SQS with the caller's own scoped
credentials. This one never was: the browser posts to `POST /v1/feedback`, the API verifies the
bearer, and the API sends on **its own execution role**. The portal role has no statement naming
this queue.

That is what keeps a feedback record attributable. On the user plane the portal role would need
`sqs:SendMessage` here — a grant carried by every session the API mints for every user, for a
write this one route makes — and no SQS condition key reaches a field inside a message body, so IAM
could not tie a record's username to the session that sent it. On the API plane no user-scoped
identity can write the queue. The route takes the username from the verified `cognito:username`
claim, and the request type declares no username field, so there is nothing to ignore.

## FIFO is what makes single-writer true without a lock

`MessageGroupId` is the submission's **UTC date**, stamped by the API and derived from the same
`submittedAt` the writer builds the key from. FIFO then delivers one day's submissions strictly in
arrival order, one at a time — the next is not released until the prior is deleted — so the writer
never races itself on one day's document. Different days are different groups and may process
concurrently, because they are different files.

Batch size is **1**, and the handler *refuses* a batch rather than absorbing one: taking the first
record would drop every other submission silently, and a submission has no other copy anywhere.

`content_based_deduplication` is **off**. The API sets an explicit `MessageDeduplicationId` — the
event id — on every send. With the fallback available, a send that stopped setting one would still
mostly collapse double-submits, so the guard would be gone with nothing going red.

## This DLQ is deliberately undrained, for a different reason from notifications'

Every control plane's request DLQ is swept into a user notification
(`modules/control-plane-dlq-drain`). Two are not. The notifications one is circular — the drain's
only delivery channel is that very queue. **This one is different: the drain notifies from the
verified identity inside the message body, and this body carries none by design.** The API
verified the caller and the browser never touches this queue, so there is no identity block to
read. Draining it would mean notifying a recipient named by an untrusted body field, which is the
exact inversion the drain exists to prevent.

`dlq_drain.UNDRAINED_QUEUES` names it, and a test asserts every request DLQ Terraform declares is
either wired into `SOURCES` or named there — so a future queue cannot be silently undrained.

The user's guarantee is narrow and deliberate: **the 200 means the submission reached the queue.**
Nothing after that point is something a user could act on, which is why nothing after that point
tells them anything.

## The writer holds no `s3:ListBucket`, and it does not need one

A role that cannot list a bucket cannot be told an object is absent — S3 answers `NoSuchKey` only
to a caller holding `s3:ListBucket`, and answers `AccessDenied` otherwise. Normally that means an
`except NoSuchKey: return None` branch needs a covering grant.

This writer never claims absence. **Any** read failure is reported as "no object, no tag", which
makes the following write conditional on `If-None-Match: *` — so a transient fault or a denial
loses its precondition instead of overwriting a day that is really there, the loop re-reads, and
exhausting the attempts raises so the message dead-letters. That is why there is no list grant to
scope, and why `test_absence_is_answerable.py` dispositions the read as `fail-safe-cas` rather
than `list-grant`.

There is **no `s3:DeleteObject` anywhere**. The document is only ever read-modify-rewritten, and
an existing document that will not parse is raised over rather than replaced.

> The writer's own code lands in the next change, and with it the `fail-safe-cas` disposition in
> `lambdas/test_absence_is_answerable.py` that records this reasoning against the read site.
> Until then this section describes what the writer is specified to do, not what a test holds it
> to.

## What is not here

No alarm on DLQ depth — there is no CloudWatch alarm anywhere in `infra/` today, and it would be
the first, a new resource type with its own deploy-role IAM. Named so the gap is a decision rather
than an oversight. No read surface of any kind: the records are read with the AWS CLI by whoever
wants them, and that is the whole retrieval story.

**The admin bucket has versioning off**, in common with every bucket here. For a document appended
under compare-and-swap that matters, and the thing standing in for it is the refusal above: a
document this writer cannot parse is left exactly where it is.

## Related

- [`../../info/INDEX.md`](../../info/INDEX.md) — the module index
- [`../../info/deploy-role-iam.md`](../../info/deploy-role-iam.md) — the trap list for a new resource type
- [`../../../lambdas/info/deployment.md`](../../../lambdas/info/deployment.md) — the Lambda code/infra split
